import logging
from typing import List, Optional

from eth_client import EthClient
from tx_analyzer import TxAnalyzer, TokenInfo, normalize_address
from telegram_notifier import TelegramNotifier, TxEvent


class TxWatcher:
    def __init__(self, eth_client: EthClient, tokens: List[TokenInfo], watched_address: str,
                 bot_name: str = "", notifier: Optional[TelegramNotifier] = None):
        self.eth_client = eth_client
        self.tokens = tokens
        self.watched_address = normalize_address(watched_address)
        self.bot_name = bot_name
        self.notifier = notifier
        self.analyzer = TxAnalyzer(eth_client, tokens, watched_address)

    async def subscribe(self, ws_connector):
        await ws_connector.subscribe(self.handle_event, subscription_type="newHeads")

    async def handle_event(self, event: dict):
        result = event['result']
        block_number = result['number']
        block = await self.eth_client.get_block_with_transactions(block_number)
        block_summary = await self.analyzer.analyze_block(block)

        if not block_summary:
            return

        log_fn = logging.warning if block_summary['has_fails'] else logging.info
        net_parts = [
            f"{t.symbol} {self.analyzer.prettify(block_summary['net_by_token'].get(t.address, 0), t.decimals)}"
            for t in self.tokens
            if block_summary['net_by_token'].get(t.address, 0) != 0
        ]
        net_str = ", ".join(net_parts) if net_parts else "no token change"
        log_fn(f"[{self.bot_name}] Block {block_summary['block_number']}: {net_str}")

        if self.notifier:
            await self.notifier.add_event(TxEvent(
                bot_name=self.bot_name,
                watched_address=self.watched_address,
                block_number=block_summary['block_number'],
                tx_count=block_summary['tx_count'],
                fail_count=block_summary['fail_count'],
                net_by_token=block_summary['net_by_token'],
                gas_fee_wei=block_summary['total_gas_wei'],
                tx_hashes=block_summary['tx_hashes'],
            ))
