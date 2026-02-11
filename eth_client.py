from typing import Optional, List, Any, Dict

import aiohttp


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
    
    async def eth_getBlockReceipts(self, block_number: int | str) -> Dict:
        """Функция для получения receipt о блоке"""
        receipts = await self.eth_call('eth_getBlockReceipts', [hex(block_number) if isinstance(block_number, int) else block_number])
        return receipts
