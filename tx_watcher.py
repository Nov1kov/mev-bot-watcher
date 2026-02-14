import logging
from typing import Optional

from eth_client import EthClient
from tx_analyzer import TxAnalyzer
from telegram_notifier import TelegramNotifier, TxEvent


class TxWatcher:
    def __init__(self, eth_client: EthClient, weth_contract_address: str, watched_address: str,
                 bot_name: str = "", notifier: Optional[TelegramNotifier] = None):
        self.eth_client = eth_client
        self.weth_contract_address = weth_contract_address.lower()
        self.watched_address = watched_address.lower()
        self.bot_name = bot_name
        self.notifier = notifier
        self.analyzer = TxAnalyzer(eth_client, weth_contract_address, watched_address)

    async def subscribe(self, ws_connector):
        await ws_connector.subscribe(self.handle_event, subscription_type="newHeads")

    async def handle_event(self, event: dict):
        result = event['result']
        block_number = result['number']
        block = await self.eth_client.get_block_with_transactions(block_number)
        block_summary = await self.analyzer.analyze_block(block)

        if not block_summary:
            return

        log_fn = (logging.warning if block_summary['has_fails']
                  else logging.info if block_summary['net_wei_change'] > 0
                  else logging.error)
        log_fn(f"[{self.bot_name}] Block {block_summary['block_number']}: "
               f"Net {block_summary['net_weth_change']} WETH")

        if self.notifier:
            await self.notifier.add_event(TxEvent(
                bot_name=self.bot_name,
                block_number=block_summary['block_number'],
                tx_count=block_summary['tx_count'],
                fail_count=block_summary['fail_count'],
                net_wei_change=block_summary['net_wei_change'],
                gas_fee_wei=block_summary['total_gas_wei'],
            ))
