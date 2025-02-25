import logging
import aiohttp
import asyncio
import yaml
import click
from typing import Dict, List, Optional, Any, Union

from log_progress import print_progress, setup_logging


class EthereumClient:
    """Класс для работы с Ethereum JSON-RPC API"""

    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def eth_call(self, method: str, params: Optional[List[Any]] = None) -> Any:
        """Асинхронная функция для отправки запросов JSON-RPC"""
        if params is None:
            params = []

        async with self.session.post(
                self.rpc_url, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
        ) as response:
            result = await response.json()
            return result['result']

    async def get_latest_block(self) -> int:
        """Функция для получения последнего блока"""
        block_number = await self.eth_call('eth_blockNumber')
        return int(block_number, 16)

    async def get_block_with_transactions(self, block_number: int) -> Dict:
        """Функция для получения блока с полными транзакциями"""
        block = await self.eth_call('eth_getBlockByNumber', [hex(block_number), True])
        return block

    async def get_transaction_receipt(self, tx_hash: str) -> Dict:
        """Функция для получения квитанции о транзакции"""
        receipt = await self.eth_call('eth_getTransactionReceipt', [tx_hash])
        return receipt


class TransactionAnalyzer:
    """Класс для анализа транзакций"""

    def __init__(self, eth_client: EthereumClient, weth_contract_address: str, watched_address: str):
        self.eth_client = eth_client
        self.weth_contract_address = weth_contract_address.lower()
        self.watched_address = watched_address.lower()
        self.ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

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
                        from_address = '0x' + log['topics'][1][26:]
                        to_address = '0x' + log['topics'][2][26:]
                        amount = int(log['data'], 16)

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
            "net_wei_change": net_wei_change
        }
        return block_summary

    async def analyze_from_block(self, start_block_number: int):
        """Функция для анализа блоков начиная с указанного"""
        latest_block = await self.eth_client.get_latest_block()

        logging.info(
            f"Monitoring from block: {start_block_number} to {latest_block} ({latest_block - start_block_number} blocks left)")

        summary_profit = 0
        for block_number in print_progress(range(start_block_number, latest_block + 1)):
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

        logging.info(f"Total profit: {self.prettify_weth(summary_profit)} WETH")

    async def monitor_new_blocks(self):
        """Функция для мониторинга новых блоков"""
        # Здесь будет реализация мониторинга новых блоков
        # Пока оставим заглушку для будущей реализации
        logging.info(f"Starting monitoring for address: {self.watched_address}")
        logging.info(f"WETH contract: {self.weth_contract_address}")
        logging.info("Monitoring function will be implemented later...")


def load_config(config_path: str) -> Dict:
    """Загрузка конфигурации из YAML файла"""
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)
    

def get_bot_config_by_name(config: Dict, bot_name: str) -> Optional[Dict]:
    """Получение конфигурации бота по имени"""
    if 'bots' not in config:
        return None
    
    for name, bot_config in config['bots'].items():
        if name == bot_name:
            return bot_config
    
    return None


@click.group()
def cli():
    """Утилита для анализа и мониторинга Ethereum транзакций WETH"""
    setup_logging()


@cli.command()
@click.option('--config', '-c', required=True, type=click.Path(exists=True), default='config.yaml', help='Путь к файлу конфигурации')
@click.option('--bot-name', '-b', required=True, type=str, help='Имя бота в конфигурации')
@click.option('--start-block', '-s', required=True, type=int, help='Номер блока, с которого начать анализ')
def analyze(config: str, bot_name: str, start_block: int):
    """Режим анализа: проанализировать транзакции начиная с указанного блока"""

    # Загружаем конфигурацию
    full_config = load_config(config)
    
    # Получаем конфигурацию указанного бота
    bot_config = get_bot_config_by_name(full_config, bot_name)
    
    if not bot_config:
        available_bots = ", ".join(full_config['bots'].keys())
        logging.error(f"Bot '{bot_name}' not found in config. Available bots: {available_bots}")
        return
    
    # Извлекаем настройки для указанного бота
    weth_contract = bot_config['token_contract_address'].lower()
    watched_address = bot_config['watched_address'].lower()
    http_rpc_url = bot_config['http_rpc_url']
    ws_rpc_url = bot_config.get('ws_rpc_url')  # Опционально
    
    logging.info(f"Starting analysis for bot '{bot_name}':")
    logging.info(f"Token contract: {weth_contract}")
    logging.info(f"Watched address: {watched_address}")
    logging.info(f"HTTP RPC URL: {http_rpc_url}")
    if ws_rpc_url:
        logging.info(f"WebSocket RPC URL: {ws_rpc_url}")
    logging.info(f"Starting from block: {start_block}")
    
    # Запускаем анализ
    async def run_analysis():
        async with EthereumClient(http_rpc_url) as eth_client:
            analyzer = TransactionAnalyzer(eth_client, weth_contract, watched_address)
            await analyzer.analyze_from_block(start_block)
    
    asyncio.run(run_analysis())



@cli.command()
@click.option('--config', '-c', required=True, type=click.Path(exists=True), default='config.yaml', help='Путь к файлу конфигурации')
@click.option('--bot-name', '-b', type=str, help='Имя конкретного бота (если не указано, мониторятся все боты)')
def monitor(config: str, bot_name: Optional[str] = None):
    """Режим мониторинга: постоянно отслеживать новые транзакции для всех или указанного бота"""
    try:
        # Загружаем конфигурацию
        full_config = load_config(config)
        
        if bot_name:
            # Мониторинг только одного бота
            bot_config = get_bot_config_by_name(full_config, bot_name)
            if not bot_config:
                available_bots = ", ".join(full_config['bots'].keys())
                logging.error(f"Bot '{bot_name}' not found in config. Available bots: {available_bots}")
                return
            bots_to_monitor = {bot_name: bot_config}
        else:
            # Мониторинг всех ботов
            bots_to_monitor = full_config['bots']
        
        logging.info(f"Starting monitoring for {len(bots_to_monitor)} bots")
        
        # Здесь будет реализация мониторинга для всех ботов
        async def run_monitoring():
            tasks = []
            
            for name, bot_config in bots_to_monitor.items():
                weth_contract = bot_config['token_contract_address'].lower()
                watched_address = bot_config['watched_address'].lower()
                http_rpc_url = bot_config['http_rpc_url']
                ws_rpc_url = bot_config.get('ws_rpc_url')  # Опционально
                
                logging.info(f"Setting up monitoring for bot '{name}':")
                logging.info(f"Token contract: {weth_contract}")
                logging.info(f"Watched address: {watched_address}")
                
                async with EthereumClient(http_rpc_url) as eth_client:
                    analyzer = TransactionAnalyzer(eth_client, weth_contract, watched_address)
                    # Добавляем задачу для мониторинга
                    tasks.append(analyzer.monitor_new_blocks())
            
            # Запускаем все задачи параллельно
            await asyncio.gather(*tasks)
        
        asyncio.run(run_monitoring())
        
    except Exception as e:
        logging.error(f"Error during monitoring: {e}")


if __name__ == "__main__":
    cli()
