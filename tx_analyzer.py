import logging
from typing import Dict, Optional, Union, List

from log_progress import print_progress
from eth_client import EthClient

ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def parse_transfer_event(topics: List[str], data: str) -> tuple:
    """Разбор ERC20 Transfer события из логов"""
    # Transfer(address,address,uint256)
    from_address = "0x" + topics[1][-40:].lower()
    to_address = "0x" + topics[2][-40:].lower()
    amount = int(data, 16)
    return from_address, to_address, amount


class TxAnalyzer:
    """Класс для анализа транзакций"""

    def __init__(self, eth_client: EthClient, weth_contract_address: str, watched_address: str):
        self.eth_client = eth_client
        self.weth_contract_address = weth_contract_address.lower()
        self.watched_address = watched_address.lower()
        self.ERC20_TRANSFER_TOPIC = ERC20_TRANSFER_TOPIC

    async def analyze_block(self, block: Dict) -> Optional[Dict]:
        """Функция анализа транзакций внутри блока"""
        transactions_details = []

        for tx in block['transactions']:
            if tx['from'].lower() == self.watched_address or (tx['to'] and tx['to'].lower() == self.watched_address):

                # Получаем квитанцию о транзакции для данных о логах
                receipt = await self.eth_client.get_transaction_receipt(tx['hash'])
                incoming_wei = []
                outgoing_wei = []
                gas_fee_wei = int(receipt['gasUsed'], 16) * int(receipt['effectiveGasPrice'], 16)
                status = int(receipt['status'], 16)

                # Анализируем логи на предмет Transfer событий
                for log in receipt['logs']:
                    if log['topics'][0].lower() == self.ERC20_TRANSFER_TOPIC and log[
                        'address'].lower() == self.weth_contract_address:
                        from_address, to_address, amount = parse_transfer_event(log['topics'], log['data'])
                        if from_address.lower() == self.watched_address:
                            outgoing_wei.append(amount)
                        if to_address.lower() == self.watched_address:
                            incoming_wei.append(amount)

                # Собираем детальную информацию по транзакции
                transactions_details.append(
                    {
                        "status": status,
                        "tx_hash": tx['hash'],
                        "incoming_wei": incoming_wei,
                        "outgoing_wei": outgoing_wei,
                        "gas_fee_wei": gas_fee_wei,
                    }
                )

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
        """Поиск блоков с WETH-трансферами watched_address через eth_getLogs"""
        padded_address = "0x" + self.watched_address[2:].zfill(64)
        block_numbers = set()

        for from_block in range(start_block, end_block + 1, chunk_size):
            to_block = min(from_block + chunk_size - 1, end_block)

            logs_from = await self.eth_client.get_logs(
                from_block, to_block,
                self.weth_contract_address,
                [self.ERC20_TRANSFER_TOPIC, padded_address],
            )
            logs_to = await self.eth_client.get_logs(
                from_block, to_block,
                self.weth_contract_address,
                [self.ERC20_TRANSFER_TOPIC, None, padded_address],
            )

            for log in logs_from + logs_to:
                block_numbers.add(int(log['blockNumber'], 16))

        return block_numbers

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
                logging_color = logging.warning if block_summary['has_fails'] else logging.info if block_summary[
                                                                                                       'net_wei_change'] > 0 else logging.error
                logging_color(f"Block Number: {block_summary['block_number']}")
                logging_color(f"    Transaction Hash:{block_summary['txs']}")
                logging_color(f"    Incoming WETH: {block_summary['incoming_weth']} WETH")
                logging_color(f"    Outgoing WETH: {block_summary['outgoing_weth']} WETH")
                logging_color(f"    Gas Fee: {block_summary['gas_fee_eth']} ETH")
                logging_color(f"    Net WETH Change: {block_summary['net_weth_change']} WETH")
                logging_color('-' * 50)
                summary_profit += block_summary['net_wei_change']

        eth_price = await self.eth_client.get_eth_price_usd()
        profit_eth = summary_profit / 1e18
        profit_usd = profit_eth * eth_price
        logging.info(f"Total profit: {self.prettify_weth(summary_profit)} WETH (${profit_usd:.2f} @ ETH=${eth_price:.0f})")
