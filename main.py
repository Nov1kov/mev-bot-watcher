import logging
import asyncio
import yaml
import click
from typing import Dict, Optional

from tx_watcher import TxWatcher
from eth_client import EthClient
from coingecko_client import CoinGeckoClient
from log_progress import setup_logging
from telegram_notifier import BotInfo
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


def parse_ws_rpc(ws_rpc) -> tuple:
    """Разбирает ws_rpc_url как строку или dict с login/password.

    Returns (url, login, password). login/password = None если не заданы.
    """
    if ws_rpc is None:
        return None, None, None
    if isinstance(ws_rpc, str):
        return ws_rpc, None, None
    if isinstance(ws_rpc, dict):
        return ws_rpc.get('url'), ws_rpc.get('login'), ws_rpc.get('password')
    raise ValueError(f"ws_rpc_url must be string or dict, got {type(ws_rpc).__name__}")


@click.group()
def cli():
    """Утилита для анализа и мониторинга Ethereum транзакций WETH"""
    setup_logging()


@cli.command()
@click.option('--config', '-c', required=True, type=click.Path(exists=True), default='config.yaml', help='Путь к файлу конфигурации')
@click.option('--bot-name', '-b', required=True, type=str, help='Имя бота в конфигурации')
@click.option('--start-block', '-s', type=int, help='Номер блока, с которого начать анализ (до последнего блока)')
@click.option('--block', '-n', 'block', type=int, help='Номер одиночного блока для отладочного прогона')
def analyze(config: str, bot_name: str, start_block: Optional[int], block: Optional[int]):
    """Режим анализа: диапазон от start-block или одиночный блок через функции подсчёта"""

    if (start_block is None) == (block is None):
        raise click.UsageError("Specify exactly one of --start-block / --block")

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
    if start_block is not None:
        logging.info(f"Starting from block: {start_block}")
    else:
        logging.info(f"Single block: {block}")

    # Запускаем анализ
    async def run_analysis():
        async with EthClient(http_rpc_url) as eth_client, CoinGeckoClient() as cg_client:
            bot_info = await BotInfo.from_rpc(
                eth_client, cg_client, bot_name, watched_address, weth_contract)
            analyzer = TxAnalyzer(eth_client, weth_contract, watched_address,
                                  cg_client=cg_client,
                                  coingecko_id=bot_info.coingecko_id,
                                  token_symbol=bot_info.token_symbol)
            if start_block is not None:
                await analyzer.analyze_from_block(start_block)
            else:
                await analyzer.analyze_single_block(block)

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

    telegram_config = full_config.get('telegram')

    async def run_monitoring():
        cg_client = CoinGeckoClient()
        await cg_client.__aenter__()

        # Настройка Telegram уведомлений
        notifier = None
        if telegram_config and telegram_config.get('bot_token'):
            from telegram_notifier import TelegramNotifier
            schedule = telegram_config.get('notify_schedule', '0 * * * *')
            notifier = TelegramNotifier(
                bot_token=telegram_config['bot_token'],
                chat_id=str(telegram_config['chat_id']),
                notify_schedule=schedule,
                cg_client=cg_client,
            )
            logging.info(f"Telegram notifications enabled (schedule: {schedule})")

        tasks = []
        eth_clients = []
        ws_connectors = []

        for name, bot_cfg in bots_to_monitor.items():
            weth_contract = bot_cfg['token_contract_address'].lower()
            watched_address = bot_cfg['watched_address'].lower()
            ws_url, ws_login, ws_password = parse_ws_rpc(bot_cfg.get('ws_rpc_url'))
            http_rpc_url = bot_cfg.get('http_rpc_url')

            logging.info(f"Setting up monitoring for bot '{name}':")
            logging.info(f"Token contract: {weth_contract}")
            logging.info(f"Watched address: {watched_address}")

            ws = WsConnectorRaw(ws_url, login=ws_login, password=ws_password, name=name)
            ws_connectors.append(ws)
            eth_client = EthClient(http_rpc_url)
            await eth_client.__aenter__()
            eth_clients.append(eth_client)

            bot_info = await BotInfo.from_rpc(
                eth_client, cg_client, name, watched_address, weth_contract)

            if notifier:
                notifier.register_bot(bot_info)

            watcher = TxWatcher(eth_client, weth_contract, watched_address,
                                bot_name=name, notifier=notifier)
            await watcher.subscribe(ws)
            tasks.append(ws.run())

        if notifier:
            async def send_startup_after_connect():
                await asyncio.gather(*(ws.ready.wait() for ws in ws_connectors))
                await notifier.send_startup_message()

            tasks.append(send_startup_after_connect())
            tasks.append(notifier.run_periodic_flush())

        try:
            await asyncio.gather(*tasks)
        finally:
            if notifier:
                await notifier.force_flush()
            for client in eth_clients:
                await client.__aexit__(None, None, None)
            await cg_client.__aexit__(None, None, None)

    asyncio.run(run_monitoring())


if __name__ == "__main__":
    cli()
