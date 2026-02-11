import logging
import asyncio
import yaml
import click
from typing import Dict, Optional

from tx_watcher import TxWatcher
from eth_client import EthClient
from log_progress import setup_logging
from tx_analyzer import TxAnalyzer
from ws_connector import WsConnectorRaw


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
    
    logging.info(f"Starting analysis for bot '{bot_name}':")
    logging.info(f"Token contract: {weth_contract}")
    logging.info(f"Watched address: {watched_address}")
    logging.info(f"Starting from block: {start_block}")
    
    # Запускаем анализ
    async def run_analysis():
        async with EthClient(http_rpc_url) as eth_client:
            analyzer = TxAnalyzer(eth_client, weth_contract, watched_address)
            await analyzer.analyze_from_block(start_block)
    
    asyncio.run(run_analysis())



@cli.command()
@click.option('--config', '-c', required=True, type=click.Path(exists=True), default='config.yaml', help='Путь к файлу конфигурации')
@click.option('--bot-name', '-b', type=str, help='Имя конкретного бота (если не указано, мониторятся все боты)')
def monitor(config: str, bot_name: Optional[str] = None):
    """Режим мониторинга: постоянно отслеживать новые транзакции для всех или указанного бота"""

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
            ws_rpc_url = bot_config.get('ws_rpc_url')
            http_rpc_url = bot_config.get('http_rpc_url')

            logging.info(f"Setting up monitoring for bot '{name}':")
            logging.info(f"Token contract: {weth_contract}")
            logging.info(f"Watched address: {watched_address}")

            async with WsConnectorRaw(ws_rpc_url) as ws:
                async with EthClient(http_rpc_url) as eth_client:
                    blocks_watcher = TxWatcher(eth_client, weth_contract, watched_address)
                    await blocks_watcher.subscribe(ws)
                    tasks.append(ws.run())

        # Запускаем все задачи параллельно
        await asyncio.gather(*tasks)

    asyncio.run(run_monitoring())


if __name__ == "__main__":
    cli()
