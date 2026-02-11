import json
import logging
from typing import List

from eth_client import EthClient

ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class TxWatcher:
    def __init__(self, eth_client: EthClient, weth_contract_address: str, watched_address: str):
        self.eth_client = eth_client
        self.weth_contract_address = weth_contract_address.lower()
        self.watched_address = watched_address.lower()

    async def subscribe(self, ws_connector):
        await ws_connector.subscribe(self.handle_event, subscription_type="newHeads")
        # await ws_connector.subscribe(self.handle_event, subscription_type="logs",
        #                              subscription_arg={
        #                                  'address': self.weth_contract_address,
        #                                  'topics': [[ERC20_TRANSFER_TOPIC]]})

    async def handle_event(self, event: dict):
        result = event['result']
        block = await self.eth_client.get_block_with_transactions(result['number'])
        from_address, to_address, amount = parse_transfer_event(result['topics'], result['data'])
        if from_address == self.watched_address or to_address == self.watched_address:
            logging.info(f"New transfer: {from_address} -> {to_address} {amount}")


def parse_transfer_event(topics: List[str], data: str) -> tuple:
    # Transfer(address,address,uint256)
    from_address = "0x" + topics[1][-40:].lower()
    to_address = "0x" + topics[2][-40:].lower()
    amount = int(data, 16)
    return from_address, to_address, amount