import logging
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


class TxAnalyzer:
    """Класс для анализа транзакций"""

    def __init__(self, eth_client: EthClient, weth_contract_address: str, watched_address: str,
                 cg_client: Optional[CoinGeckoClient] = None,
                 coingecko_id: Optional[str] = None,
                 token_symbol: str = "ETH"):
        self.eth_client = eth_client
        self.weth_contract_address = normalize_address(weth_contract_address)
        self.watched_address = normalize_address(watched_address)
        self.ERC20_TRANSFER_TOPIC = ERC20_TRANSFER_TOPIC
        self.cg_client = cg_client
        self.coingecko_id = coingecko_id
        self.token_symbol = token_symbol

    def parse_receipt(self, receipt: Dict, tx_hash: str) -> Dict:
        """Разбор receipt транзакции: gas, статус, входящие/исходящие трансферы.

        Учитываются события только на WETH-контракте: ERC20 Transfer,
        WETH Deposit(dst, wad) и WETH Withdrawal(src, wad). Последние два
        не эмитят Transfer, но изменяют баланс WETH отслеживаемого адреса.
        """
        incoming_wei = []
        outgoing_wei = []
        gas_fee_wei = int(receipt['gasUsed'], 16) * int(receipt['effectiveGasPrice'], 16)
        status = int(receipt['status'], 16)

        for log in receipt['logs']:
            if normalize_address(log['address']) != self.weth_contract_address:
                continue
            topic0 = log['topics'][0].lower()
            if topic0 == self.ERC20_TRANSFER_TOPIC:
                from_address, to_address, amount = parse_transfer_event(log['topics'], log['data'])
                if from_address == self.watched_address:
                    outgoing_wei.append(amount)
                if to_address == self.watched_address:
                    incoming_wei.append(amount)
            elif topic0 == WETH_DEPOSIT_TOPIC:
                dst, amount = parse_single_address_event(log['topics'], log['data'])
                if dst == self.watched_address:
                    incoming_wei.append(amount)
            elif topic0 == WETH_WITHDRAWAL_TOPIC:
                src, amount = parse_single_address_event(log['topics'], log['data'])
                if src == self.watched_address:
                    outgoing_wei.append(amount)

        return {
            "status": status,
            "tx_hash": tx_hash,
            "incoming_wei": incoming_wei,
            "outgoing_wei": outgoing_wei,
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
    def prettify_weth(number: Union[int, float]) -> str:
        """Форматирование значения wei в WETH"""
        return f"{number / 1e18:.6f}"

    def create_block_summary(self, block: Dict, transactions_details: List[Dict]) -> Dict:
        """Создает сводку по блоку на основе деталей транзакций"""
        tx_hashes = [f"\t\n{tx['tx_hash']}" for tx in transactions_details]
        incoming_details_weth = ", ".join(
            [self.prettify_weth(amount) for tx in transactions_details for amount in tx['incoming_wei']]
        )
        incoming_summary_weth = self.prettify_weth(
            sum([amount for tx in transactions_details for amount in tx['incoming_wei']]))
        outgoing_details_weth = ", ".join(
            [self.prettify_weth(amount) for tx in transactions_details for amount in tx['outgoing_wei']]
        )
        outgoing_summary_weth = self.prettify_weth(
            sum([amount for tx in transactions_details for amount in tx['outgoing_wei']]))
        gas_fee_details_eth = ", ".join([self.prettify_weth(tx['gas_fee_wei']) for tx in transactions_details])
        gas_fee_summary_eth = self.prettify_weth(sum([tx['gas_fee_wei'] for tx in transactions_details]))
        net_weth_details = f" ({incoming_summary_weth} - {outgoing_summary_weth} - {gas_fee_summary_eth})"
        net_wei_change = sum(
            [sum(tx['incoming_wei']) - sum(tx['outgoing_wei']) - tx['gas_fee_wei'] for tx in transactions_details])
        net_weth_change = self.prettify_weth(net_wei_change)
        has_fails = any(tx['status'] == 0 for tx in transactions_details)

        block_summary = {
            "has_fails": has_fails,
            "block_number": int(block['number'], 16),
            "txs": "".join(tx_hashes),
            "incoming_weth": f"{incoming_summary_weth} ({incoming_details_weth})",
            "outgoing_weth": f"{outgoing_summary_weth} ({outgoing_details_weth})",
            "gas_fee_eth": f"{gas_fee_summary_eth} ({gas_fee_details_eth})",
            "net_weth_change": net_weth_change + net_weth_details,
            "net_wei_change": net_wei_change,
            "tx_count": len(transactions_details),
            "fail_count": sum(1 for tx in transactions_details if tx['status'] == 0),
            "total_gas_wei": sum(tx['gas_fee_wei'] for tx in transactions_details),
        }
        return block_summary

    async def get_relevant_blocks(self, start_block: int, end_block: int, chunk_size: int = 10000) -> set:
        """Поиск блоков, затрагивающих баланс WETH watched_address, через eth_getLogs.

        Покрывает те же события, что и parse_receipt: ERC20 Transfer (в обе стороны),
        WETH Deposit(dst=watched) и WETH Withdrawal(src=watched).
        """
        padded_address = "0x" + self.watched_address[2:].zfill(64)
        # Transfer.from, Deposit.dst, Withdrawal.src — индексированы в topics[1]
        topic1_events = [self.ERC20_TRANSFER_TOPIC, WETH_DEPOSIT_TOPIC, WETH_WITHDRAWAL_TOPIC]
        block_numbers = set()

        for from_block in range(start_block, end_block + 1, chunk_size):
            to_block = min(from_block + chunk_size - 1, end_block)

            logs_topic1 = await self.eth_client.get_logs(
                from_block, to_block,
                self.weth_contract_address,
                [topic1_events, padded_address],
            )
            logs_transfer_to = await self.eth_client.get_logs(
                from_block, to_block,
                self.weth_contract_address,
                [self.ERC20_TRANSFER_TOPIC, None, padded_address],
            )

            for log in logs_topic1 + logs_transfer_to:
                block_numbers.add(int(log['blockNumber'], 16))

        return block_numbers

    def _log_block_summary(self, block_summary: Dict) -> None:
        log_fn = (logging.warning if block_summary['has_fails']
                  else logging.info if block_summary['net_wei_change'] > 0
                  else logging.error)
        log_fn(f"Block Number: {block_summary['block_number']}")
        log_fn(f"    Transaction Hash:{block_summary['txs']}")
        log_fn(f"    Incoming WETH: {block_summary['incoming_weth']} WETH")
        log_fn(f"    Outgoing WETH: {block_summary['outgoing_weth']} WETH")
        log_fn(f"    Gas Fee: {block_summary['gas_fee_eth']} ETH")
        log_fn(f"    Net WETH Change: {block_summary['net_weth_change']} WETH")
        log_fn('-' * 50)

    async def _log_total_profit(self, summary_profit_wei: int) -> None:
        profit_tokens = summary_profit_wei / 1e18
        usd_suffix = ""
        if self.cg_client and self.coingecko_id:
            try:
                price = await self.cg_client.get_price_usd(self.coingecko_id)
                if price is not None:
                    usd_suffix = f" (${profit_tokens * price:.2f} @ {self.token_symbol}=${price:.2f})"
            except Exception:
                logging.exception("Failed to fetch token price for analyze summary")
        logging.info(f"Total profit: {self.prettify_weth(summary_profit_wei)} {self.token_symbol}{usd_suffix}")

    async def analyze_from_block(self, start_block_number: int):
        """Функция для анализа блоков начиная с указанного"""
        latest_block = await self.eth_client.get_latest_block()

        logging.info(
            f"Scanning events from block {start_block_number} to {latest_block} ({latest_block - start_block_number} blocks)")

        relevant_blocks = await self.get_relevant_blocks(start_block_number, latest_block)
        logging.info(f"Found {len(relevant_blocks)} blocks with WETH transfers")

        summary_profit = 0
        for block_number in print_progress(sorted(relevant_blocks), total_tasks=len(relevant_blocks)):
            block = await self.eth_client.get_block_with_transactions(block_number)
            block_summary = await self.analyze_block(block)

            if block_summary:
                self._log_block_summary(block_summary)
                summary_profit += block_summary['net_wei_change']

        await self._log_total_profit(summary_profit)

    async def analyze_single_block(self, block_number: int):
        """Отладочный прогон одного блока через analyze_block"""
        block = await self.eth_client.get_block_with_transactions(block_number)
        block_summary = await self.analyze_block(block)

        if block_summary is None:
            logging.info(f"Block {block_number}: no relevant transactions")
            return

        self._log_block_summary(block_summary)
        await self._log_total_profit(block_summary['net_wei_change'])
