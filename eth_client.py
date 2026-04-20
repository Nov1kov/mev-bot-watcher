from typing import Optional, List, Any, Dict

import aiohttp


def _decode_abi_string(hex_result: str) -> str:
    """Декодирование строки из результата eth_call.

    Поддерживает стандартные ABI dynamic string (offset+length+data),
    а также контракты со старым ABI, возвращающие bytes32 (как MKR).
    """
    if hex_result.startswith('0x'):
        hex_result = hex_result[2:]
    if not hex_result:
        return ''
    # bytes32 fallback: длина данных ≤ 64 hex (32 байта)
    if len(hex_result) < 128:
        return bytes.fromhex(hex_result).rstrip(b'\x00').decode('utf-8', errors='replace')
    length = int(hex_result[64:128], 16)
    data = hex_result[128:128 + length * 2]
    return bytes.fromhex(data).decode('utf-8', errors='replace')


class EthClient:
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

    async def get_balance(self, address: str) -> int:
        """Нативный баланс адреса в wei через eth_getBalance"""
        result = await self.eth_call('eth_getBalance', [address, 'latest'])
        return int(result, 16)

    async def get_erc20_balance(self, token_address: str, holder_address: str) -> int:
        """Баланс ERC20 токена на адресе через вызов balanceOf(address)"""
        # function selector: keccak256("balanceOf(address)")[:4] = 0x70a08231
        padded = holder_address.lower().removeprefix('0x').zfill(64)
        data = '0x70a08231' + padded
        result = await self.eth_call('eth_call', [{'to': token_address, 'data': data}, 'latest'])
        if not result or result == '0x':
            return 0
        return int(result, 16)

    async def get_block_with_transactions(self, block_number: int | str) -> Dict:
        """Функция для получения блока с полными транзакциями"""
        block = await self.eth_call('eth_getBlockByNumber',
                                    [hex(block_number) if isinstance(block_number, int) else block_number, True])
        return block

    async def get_transaction_receipt(self, tx_hash: str) -> Dict:
        """Функция для получения receipt о транзакции"""
        receipt = await self.eth_call('eth_getTransactionReceipt', [tx_hash])
        return receipt

    async def get_transaction_by_hash(self, tx_hash: str) -> Dict:
        """Функция для получения транзакции по хешу"""
        transaction = await self.eth_call('eth_getTransactionByHash', [tx_hash])
        return transaction
    
    async def get_logs(self, from_block: int, to_block: int, address: str, topics: list) -> list:
        """Получение логов по фильтру"""
        params = {
            'fromBlock': hex(from_block),
            'toBlock': hex(to_block),
            'address': address,
            'topics': topics,
        }
        return await self.eth_call('eth_getLogs', [params])

    async def get_token_symbol(self, address: str) -> str:
        """Получение символа ERC20 токена через RPC вызов symbol()"""
        # function selector: keccak256("symbol()")[:4] = 0x95d89b41
        result = await self.eth_call('eth_call', [{'to': address, 'data': '0x95d89b41'}, 'latest'])
        return _decode_abi_string(result)

    async def eth_getBlockReceipts(self, block_number: int | str) -> Dict:
        """Функция для получения receipt о блоке"""
        receipts = await self.eth_call('eth_getBlockReceipts', [hex(block_number) if isinstance(block_number, int) else block_number])
        return receipts
