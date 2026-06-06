import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Union, List

from log_progress import print_progress
from eth_client import EthClient
from coingecko_client import CoinGeckoClient

ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
WETH_DEPOSIT_TOPIC = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
WETH_WITHDRAWAL_TOPIC = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"


def parse_transfer_event(topics: List[str], data: str) -> tuple:
    """Разбор ERC20 Transfer события из логов"""
    # Transfer(address,address,uint256)
    from_address = "0x" + topics[1][-40:].lower()
    to_address = "0x" + topics[2][-40:].lower()
    amount = int(data, 16)
    return from_address, to_address, amount


def parse_single_address_event(topics: List[str], data: str) -> tuple:
    """Разбор события с одним индексированным адресом и uint256: Deposit / Withdrawal."""
    address = "0x" + topics[1][-40:].lower()
    amount = int(data, 16)
    return address, amount


def normalize_address(addr: str) -> str:
    """Нормализация Ethereum адреса: 0x + 40 hex символов, lowercase"""
    addr = addr.strip().lower()
    if addr.startswith('0x'):
        addr = addr[2:]
    return '0x' + addr.zfill(40)


def native_symbol_of(symbol: str) -> str:
    """Тикер нативного токена по символу обёртки: WETH -> ETH, WMON -> MON."""
    if len(symbol) > 1 and symbol[0].upper() == "W":
        return symbol[1:]
    return symbol


def compute_profit_usd_for(tokens: List["TokenInfo"], native_coingecko_id: Optional[str],
                           net_by_token: Dict[str, int], gas_wei: int,
                           prices_by_id: Dict[str, float]) -> Optional[float]:
    """Свести мультитокенный профит и газ в USD.

    profit = Σ(net_token / 10^decimals × price) − gas_eth × native_price.
    Возвращает None, если нет ни одной известной цены (USD неопределён).
    """
    if not prices_by_id:
        return None
    profit = 0.0
    used_any = False
    for token in tokens:
        net = net_by_token.get(token.address, 0)
        if net == 0 or not token.coingecko_id:
            continue
        price = prices_by_id.get(token.coingecko_id)
        if price is None:
            logging.warning(f"no price for {token.symbol}, skipped in USD profit")
            continue
        profit += net / 10 ** token.decimals * price
        used_any = True

    native_price = prices_by_id.get(native_coingecko_id) if native_coingecko_id else None
    if native_price is not None:
        profit -= gas_wei / 1e18 * native_price
        used_any = True

    return profit if used_any else None


@dataclass
class TokenInfo:
    """Метаданные отслеживаемого токена.

    is_wrapped=True помечает обёртку нативного токена (WETH/WMON): только для
    неё учитываются события Deposit/Withdrawal, и её цена используется для
    оценки газа (нативный токен равен обёртке по цене 1:1).
    """
    address: str
    symbol: str
    decimals: int = 18
    coingecko_id: Optional[str] = None
    is_wrapped: bool = False

    def __post_init__(self):
        self.address = normalize_address(self.address)

    @property
    def native_symbol(self) -> str:
        return native_symbol_of(self.symbol)

    @classmethod
    async def from_rpc(cls, eth_client, cg_client, address: str,
                       is_wrapped: bool = False) -> "TokenInfo":
        """Собирает TokenInfo по RPC: symbol + decimals, coingecko_id — через CoinGecko."""
        symbol = "?"
        try:
            symbol = await eth_client.get_token_symbol(address)
        except Exception:
            logging.exception(f"failed to fetch symbol for {address}")

        decimals = 18
        try:
            decimals = await eth_client.get_decimals(address)
        except Exception:
            logging.exception(f"failed to fetch decimals for {address}, fallback to 18")

        coingecko_id: Optional[str] = None
        if cg_client is not None:
            try:
                # для обёртки резолвим по нативному тикеру (WETH -> ETH),
                # т.к. цены wrapped и нативного равны 1:1
                lookup_symbol = native_symbol_of(symbol) if is_wrapped else symbol
                coingecko_id = await cg_client.resolve_id_by_symbol(lookup_symbol)
            except Exception:
                logging.exception(f"failed to resolve coingecko_id for {symbol}")

        return cls(address=address, symbol=symbol, decimals=decimals,
                   coingecko_id=coingecko_id, is_wrapped=is_wrapped)


class TxAnalyzer:
    """Класс для анализа транзакций по набору отслеживаемых токенов"""

    def __init__(self, eth_client: EthClient, tokens: List[TokenInfo], watched_address: str,
                 cg_client: Optional[CoinGeckoClient] = None):
        self.eth_client = eth_client
        self.tokens = tokens
        self.tokens_by_address = {t.address: t for t in tokens}
        self.watched_address = normalize_address(watched_address)
        self.cg_client = cg_client
        self.wrapped = next((t for t in tokens if t.is_wrapped),
                            tokens[0] if tokens else None)
        self.native_coingecko_id = self.wrapped.coingecko_id if self.wrapped else None
        self.native_symbol = self.wrapped.native_symbol if self.wrapped else "ETH"

    def parse_receipt(self, receipt: Dict, tx_hash: str) -> Dict:
        """Разбор receipt: gas, статус и net-изменение баланса по каждому токену.

        Учитываются события на адресах отслеживаемых токенов: ERC20 Transfer
        (в обе стороны) для всех токенов, а также WETH Deposit(dst, wad) и
        WETH Withdrawal(src, wad) — только для wrapped-токена (обёртки нативного).
        """
        net_by_token: Dict[str, int] = {t.address: 0 for t in self.tokens}
        gas_fee_wei = int(receipt['gasUsed'], 16) * int(receipt['effectiveGasPrice'], 16)
        status = int(receipt['status'], 16)

        for log in receipt['logs']:
            addr = normalize_address(log['address'])
            token = self.tokens_by_address.get(addr)
            if token is None:
                continue
            topic0 = log['topics'][0].lower()
            if topic0 == ERC20_TRANSFER_TOPIC:
                from_address, to_address, amount = parse_transfer_event(log['topics'], log['data'])
                if from_address == self.watched_address:
                    net_by_token[addr] -= amount
                if to_address == self.watched_address:
                    net_by_token[addr] += amount
            elif token.is_wrapped and topic0 == WETH_DEPOSIT_TOPIC:
                dst, amount = parse_single_address_event(log['topics'], log['data'])
                if dst == self.watched_address:
                    net_by_token[addr] += amount
            elif token.is_wrapped and topic0 == WETH_WITHDRAWAL_TOPIC:
                src, amount = parse_single_address_event(log['topics'], log['data'])
                if src == self.watched_address:
                    net_by_token[addr] -= amount

        return {
            "status": status,
            "tx_hash": tx_hash,
            "net_by_token": net_by_token,
            "gas_fee_wei": gas_fee_wei,
        }

    async def analyze_block(self, block: Dict) -> Optional[Dict]:
        """Функция анализа транзакций внутри блока"""
        transactions_details = []

        for tx in block['transactions']:
            tx_from = normalize_address(tx['from'])
            tx_to = normalize_address(tx['to']) if tx['to'] else None
            if tx_from == self.watched_address or (tx_to and tx_to == self.watched_address):
                receipt = await self.eth_client.get_transaction_receipt(tx['hash'])
                transactions_details.append(self.parse_receipt(receipt, tx['hash']))

        if transactions_details:
            return self.create_block_summary(block, transactions_details)
        return None

    @staticmethod
    def prettify(amount_raw: Union[int, float], decimals: int) -> str:
        """Форматирование raw-значения токена в человекочитаемое с учётом decimals"""
        return f"{amount_raw / 10 ** decimals:.6f}"

    @staticmethod
    def prettify_weth(number: Union[int, float]) -> str:
        """Форматирование значения wei (18 знаков) — для газа/нативного токена"""
        return f"{number / 1e18:.6f}"

    def create_block_summary(self, block: Dict, transactions_details: List[Dict]) -> Dict:
        """Создает сводку по блоку на основе деталей транзакций"""
        net_by_token: Dict[str, int] = {t.address: 0 for t in self.tokens}
        for tx in transactions_details:
            for addr, value in tx['net_by_token'].items():
                net_by_token[addr] = net_by_token.get(addr, 0) + value

        total_gas_wei = sum(tx['gas_fee_wei'] for tx in transactions_details)
        has_fails = any(tx['status'] == 0 for tx in transactions_details)

        return {
            "has_fails": has_fails,
            "block_number": int(block['number'], 16),
            "tx_hashes": [tx['tx_hash'] for tx in transactions_details],
            "net_by_token": net_by_token,
            "total_gas_wei": total_gas_wei,
            "tx_count": len(transactions_details),
            "fail_count": sum(1 for tx in transactions_details if tx['status'] == 0),
        }

    def compute_profit_usd(self, net_by_token: Dict[str, int], gas_wei: int,
                           prices_by_id: Dict[str, float]) -> Optional[float]:
        """Свести мультитокенный профит и газ в USD (см. compute_profit_usd_for)."""
        return compute_profit_usd_for(self.tokens, self.native_coingecko_id,
                                      net_by_token, gas_wei, prices_by_id)

    async def _fetch_prices(self) -> Dict[str, float]:
        """USD-цены для всех токенов + нативного, одним запросом к CoinGecko."""
        if not self.cg_client:
            return {}
        ids = {t.coingecko_id for t in self.tokens if t.coingecko_id}
        if self.native_coingecko_id:
            ids.add(self.native_coingecko_id)
        if not ids:
            return {}
        try:
            return await self.cg_client.get_prices_usd(ids)
        except Exception:
            logging.exception("Failed to fetch prices from CoinGecko")
            return {}

    async def get_relevant_blocks(self, start_block: int, end_block: int, chunk_size: int = 10000) -> set:
        """Поиск блоков, затрагивающих баланс watched_address по любому из токенов.

        Для каждого токена: ERC20 Transfer (в обе стороны); для wrapped-токена
        дополнительно WETH Deposit(dst=watched) и Withdrawal(src=watched).
        """
        padded_address = "0x" + self.watched_address[2:].zfill(64)
        block_numbers = set()

        for from_block in range(start_block, end_block + 1, chunk_size):
            to_block = min(from_block + chunk_size - 1, end_block)

            for token in self.tokens:
                # Transfer.from, Deposit.dst, Withdrawal.src — индексированы в topics[1]
                topic1_events = [ERC20_TRANSFER_TOPIC]
                if token.is_wrapped:
                    topic1_events += [WETH_DEPOSIT_TOPIC, WETH_WITHDRAWAL_TOPIC]

                logs_topic1 = await self.eth_client.get_logs(
                    from_block, to_block, token.address,
                    [topic1_events, padded_address],
                )
                logs_transfer_to = await self.eth_client.get_logs(
                    from_block, to_block, token.address,
                    [ERC20_TRANSFER_TOPIC, None, padded_address],
                )

                for log in logs_topic1 + logs_transfer_to:
                    block_numbers.add(int(log['blockNumber'], 16))

        return block_numbers

    def _log_block_summary(self, block_summary: Dict) -> None:
        net_by_token = block_summary['net_by_token']
        log_fn = (logging.warning if block_summary['has_fails'] else logging.info)
        log_fn(f"Block Number: {block_summary['block_number']}")
        for tx_hash in block_summary['tx_hashes']:
            log_fn(f"    Tx: {tx_hash}")
        for token in self.tokens:
            net = net_by_token.get(token.address, 0)
            if net != 0:
                log_fn(f"    Net {token.symbol}: {self.prettify(net, token.decimals)}")
        log_fn(f"    Gas: {self.prettify_weth(block_summary['total_gas_wei'])} {self.native_symbol}")
        log_fn('-' * 50)

    async def _log_total_profit(self, totals: Dict[str, int], total_gas_wei: int) -> None:
        prices = await self._fetch_prices()

        for token in self.tokens:
            net = totals.get(token.address, 0)
            if net != 0:
                logging.info(f"Total {token.symbol}: {self.prettify(net, token.decimals)}")
        logging.info(f"Total gas: {self.prettify_weth(total_gas_wei)} {self.native_symbol}")

        profit_usd = self.compute_profit_usd(totals, total_gas_wei, prices)
        if profit_usd is not None:
            logging.info(f"Total profit: ${profit_usd:+,.2f}")
        else:
            logging.warning("Total profit in USD unavailable (no prices)")

    async def analyze_from_block(self, start_block_number: int):
        """Функция для анализа блоков начиная с указанного"""
        latest_block = await self.eth_client.get_latest_block()

        logging.info(
            f"Scanning events from block {start_block_number} to {latest_block} ({latest_block - start_block_number} blocks)")

        relevant_blocks = await self.get_relevant_blocks(start_block_number, latest_block)
        logging.info(f"Found {len(relevant_blocks)} blocks with relevant transfers")

        totals: Dict[str, int] = {t.address: 0 for t in self.tokens}
        total_gas_wei = 0
        for block_number in print_progress(sorted(relevant_blocks), total_tasks=len(relevant_blocks)):
            block = await self.eth_client.get_block_with_transactions(block_number)
            block_summary = await self.analyze_block(block)

            if block_summary:
                self._log_block_summary(block_summary)
                for addr, value in block_summary['net_by_token'].items():
                    totals[addr] = totals.get(addr, 0) + value
                total_gas_wei += block_summary['total_gas_wei']

        await self._log_total_profit(totals, total_gas_wei)

    async def analyze_single_block(self, block_number: int):
        """Отладочный прогон одного блока через analyze_block"""
        block = await self.eth_client.get_block_with_transactions(block_number)
        block_summary = await self.analyze_block(block)

        if block_summary is None:
            logging.info(f"Block {block_number}: no relevant transactions")
            return

        self._log_block_summary(block_summary)
        await self._log_total_profit(block_summary['net_by_token'], block_summary['total_gas_wei'])
