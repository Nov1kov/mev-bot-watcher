"""E2E на сырых данных BSC: профит бота приходит нативным BNB на EOA.

Контракт бота анмаппит WBNB и шлёт нативный BNB на EOA — ни одного лога с
адресом EOA в receipt нет, поэтому профит виден только через callTracer-трейс.

Фикстуры в tests/fixtures — ответы RPC (block, receipt, callTracer); в блоке
оставлены только транзакции с участием EOA, остальные 151 отброшены.
"""
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mev_bot_watcher.tx_analyzer import TxAnalyzer, TokenInfo, native_token_info

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

EOA = '0x0000000000000000000000000000000000000e0a'
BOT_CONTRACT = '0x0000000000000000000000000000000000000b07'
WBNB = '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'
BNB_USD = 729.48  # цена BNB на момент блока


def load(name):
    with open(os.path.join(FIXTURES, f'bsc_native_profit_{name}.json')) as f:
        return json.load(f)


class TestNativeProfitE2E(unittest.TestCase):
    def setUp(self):
        self.block = load('block')
        wrapped = TokenInfo(address=WBNB, symbol='WBNB', decimals=18,
                            coingecko_id='binancecoin', is_wrapped=True)
        self.tokens = [wrapped, native_token_info(wrapped)]
        eth_client = AsyncMock()
        eth_client.get_transaction_receipt.return_value = load('receipt')
        eth_client.trace_transaction.return_value = load('trace')
        self.analyzer = TxAnalyzer(eth_client, self.tokens, EOA)

    def test_profit_from_native_transfer_to_eoa(self):
        summary = asyncio.run(self.analyzer.analyze_block(self.block))

        self.assertEqual(self.block['transactions'][0]['to'], BOT_CONTRACT)
        self.assertEqual(summary['tx_count'], 1)
        self.assertEqual(summary['fail_count'], 0)
        # у EOA нет ни одного ERC20/WETH события — весь профит нативный
        self.assertEqual(summary['net_by_token'][self.tokens[0].address], 0)
        self.assertEqual(summary['net_by_token'][self.tokens[1].address], 106198935910867)
        self.assertEqual(summary['total_gas_wei'], 37727045238672)

        profit = self.analyzer.compute_profit_usd(
            summary['net_by_token'], summary['total_gas_wei'], {'binancecoin': BNB_USD})
        self.assertAlmostEqual(profit, 0.05, places=2)

    def test_without_native_token_profit_is_only_gas_loss(self):
        """Регрессия: без нативного псевдо-токена виден лишь убыток на газ."""
        analyzer = TxAnalyzer(self.analyzer.eth_client, self.tokens[:1], EOA)
        summary = asyncio.run(analyzer.analyze_block(self.block))
        profit = analyzer.compute_profit_usd(
            summary['net_by_token'], summary['total_gas_wei'], {'binancecoin': BNB_USD})
        self.assertLess(profit, 0)


if __name__ == '__main__':
    unittest.main()
