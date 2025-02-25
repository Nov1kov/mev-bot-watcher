import logging
import aiohttp
import asyncio
import yaml

from log_progress import print_progress, setup_logging  # Импортируем библиотеку для работы с YAML


with open('config.yaml', 'r') as file:
    config = yaml.safe_load(file)

# Извлекаем настройки для первого бота
bot_config = config['bots'][1]
WETH_CONTRACT_ADDRESS = bot_config['WETH_CONTRACT_ADDRESS'].lower()
WATCHED_ADDRESS = bot_config['WATCHED_ADDRESS'].lower()
RPC_URL = bot_config['RPC_URL']
ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"  # Хеш события Transfer


# Асинхронная функция для отправки запросов JSON-RPC
async def eth_call(method, params=None):
    if params is None:
        params = []

    async with aiohttp.ClientSession() as session:
        async with session.post(
            RPC_URL, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
        ) as response:
            result = await response.json()
            return result['result']


# Функция для получения последнего блока
async def get_latest_block():
    block_number = await eth_call('eth_blockNumber')
    return int(block_number, 16)


# Функция для получения блока с полными транзакциями
async def get_block_with_transactions(block_number):
    block = await eth_call('eth_getBlockByNumber', [hex(block_number), True])
    return block


async def get_transaction_receipt(tx_hash):
    receipt = await eth_call('eth_getTransactionReceipt', [tx_hash])
    return receipt


# Функция анализа транзакций внутри блока
async def analyze_block(block):
    transactions_details = []

    for tx in block['transactions']:
        if tx['from'].lower() == WATCHED_ADDRESS.lower() or (tx['to'] and tx['to'].lower() == WATCHED_ADDRESS.lower()):

            # Получаем квитанцию о транзакции для данных о логах
            receipt = await get_transaction_receipt(tx['hash'])
            incoming_wei = []
            outgoing_wei = []
            gas_fee_wei = int(receipt['gasUsed'], 16) * int(receipt['effectiveGasPrice'], 16)  # Расчет затрат на газ в wei
            status = int(receipt['status'], 16)

            # Анализируем логи на предмет Transfer событий
            for log in receipt['logs']:
                if log['topics'][0].lower() == ERC20_TRANSFER_TOPIC and log['address'].lower() == WETH_CONTRACT_ADDRESS:
                    from_address = '0x' + log['topics'][1][26:]
                    to_address = '0x' + log['topics'][2][26:]
                    amount = int(log['data'], 16)

                    if from_address.lower() == WATCHED_ADDRESS.lower():
                        outgoing_wei.append(amount)
                    if to_address.lower() == WATCHED_ADDRESS.lower():
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
        return create_block_summary(block, transactions_details)


def prettify_weth(number):
    return f"{number / 1e18:4f}"
    

def create_block_summary(block, transactions_details):
    tx_hashes = [f"\t\n{tx['tx_hash']}" for tx in transactions_details]
    incoming_details_weth = ", ".join(
        [prettify_weth(amount) for tx in transactions_details for amount in tx['incoming_wei']]
    )
    incoming_summary_weth = prettify_weth(sum([amount for tx in transactions_details for amount in tx['incoming_wei']]))
    outgoing_details_weth = ", ".join(
        [prettify_weth(amount) for tx in transactions_details for amount in tx['outgoing_wei']]
    )
    outgoing_summary_weth = prettify_weth(sum([amount for tx in transactions_details for amount in tx['outgoing_wei']]))
    gas_fee_detauls_eth = ", ".join([prettify_weth(tx['gas_fee_wei']) for tx in transactions_details])
    gas_fee_summary_eth = prettify_weth(sum([tx['gas_fee_wei'] for tx in transactions_details]))
    net_weth_details = f" ({incoming_summary_weth} - {outgoing_summary_weth} - {gas_fee_summary_eth})"
    net_wei_change = sum([sum(tx['incoming_wei']) - sum(tx['outgoing_wei']) - tx['gas_fee_wei'] for tx in transactions_details])
    net_weth_change = prettify_weth(net_wei_change)
    has_fails = any(tx['status'] == 0 for tx in transactions_details)
    block_summary = {
        "has_fails": has_fails,
        "block_number": int(block['number'], 16),
        "txs": "".join(tx_hashes),
        "incoming_weth": f"{incoming_summary_weth} ({incoming_details_weth})",
        "outgoing_weth": f"{outgoing_summary_weth} ({outgoing_details_weth})",
        "gas_fee_eth": f"{gas_fee_summary_eth} ({gas_fee_detauls_eth})",
        "net_weth_change": net_weth_change + net_weth_details,
        "net_wei_change": net_wei_change
    }
    return block_summary


# Функция для фильтрации транзакций по адресам и взаимодействиям с WETH
async def analyze_from_block(block_number):
    latest_block = await get_latest_block()

    logging.info(f"Monitoring from block: {block_number} to {latest_block} ({latest_block - block_number} blocks left)")

    summary_profit = 0
    for block_number in print_progress(range(block_number, latest_block)):
        block = await get_block_with_transactions(block_number)
        block_summary = await analyze_block(block)
        if block_summary:
            logging_color = logging.warning if block_summary['has_fails'] else logging.info if block_summary['net_wei_change'] > 0 else logging.error
            logging_color(f"Block Number: {block_summary['block_number']}")
            logging_color(f"    Transaction Hash:{block_summary['txs']}")
            logging_color(f"    Incoming WETH: {block_summary['incoming_weth']} WETH")
            logging_color(f"    Outgoing WETH: {block_summary['outgoing_weth']} WETH")
            logging_color(f"    Gas Fee: {block_summary['gas_fee_eth']} ETH")
            logging_color(f"    Net WETH Change: {block_summary['net_weth_change']} WETH")
            logging_color('-' * 50)
            summary_profit += block_summary['net_wei_change']

    logging.info(f"Total profit: {prettify_weth(summary_profit)} WETH")


def settings():
    pass


if __name__ == "__main__":
    setup_logging()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(analyze_from_block(309832303))