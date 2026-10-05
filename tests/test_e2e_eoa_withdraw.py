"""E2E на сырых данных Ethereum: вывод средств с контракта бота на EOA.

EOA вызывает контракт бота (watched_address), тот анврапит WETH
(Withdrawal, 29999999999999936 wei) и переводит нативный ETH на EOA
(30000000000000000 wei — на 64 wei больше, из своего баланса).
Это внутренний перевод бота: убыток — только газ.

Подводные камни трейса:
- WETH возвращает ETH в receive() контракта, а тот проксирует его через
  DELEGATECALL с тем же value — это не перевод, а унаследованный msg.value;
- перевод контракт -> EOA (отправитель транзакции) не отток.

Фикстуры в tests/fixtures — ответы RPC; адреса (EOA 0x…0e0a, контракт
0x…0b07, имплементация 0x…0b08), хеши, номер блока и подпись заменены
на синтетические.
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
WETH = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
ETH_USD = 4000.0

UNWRAPPED_WEI = 29999999999999936
GAS_WEI = 0xc766 * 0x816eedd


def load(name):
    with open(os.path.join(FIXTURES, f'eth_eoa_withdraw_{name}.json')) as f:
        return json.load(f)


class TestEoaWithdrawE2E(unittest.TestCase):
    def setUp(self):
        self.block = load('block')
        wrapped = TokenInfo(WETH, 'WETH', 18, 'ethereum', is_wrapped=True)
        self.tokens = [wrapped, native_token_info(wrapped)]
        self.eth_client = AsyncMock()
        self.eth_client.get_transaction_receipt.return_value = load('receipt')
        self.eth_client.trace_transaction.return_value = load('trace')
        self.analyzer = TxAnalyzer(self.eth_client, self.tokens, BOT_CONTRACT)

    def profit_with(self, eoa_addresses):
        analyzer = TxAnalyzer(self.eth_client, self.tokens, BOT_CONTRACT,
                              eoa_addresses=eoa_addresses)
        summary = asyncio.run(analyzer.analyze_block(self.block))
        return analyzer.compute_profit_usd(
            summary['net_by_token'], summary['total_gas_wei'], {'ethereum': ETH_USD})

    def test_withdraw_to_eoa_costs_only_gas(self):
        summary = asyncio.run(self.analyzer.analyze_block(self.block))

        self.assertEqual(self.block['transactions'][0]['from'], EOA)
        self.assertEqual(summary['tx_count'], 1)
        self.assertFalse(summary['native_unknown'])
        # WETH анврапнут, ETH ушёл на EOA — свой адрес, поэтому не отток
        self.assertEqual(summary['net_by_token'][self.tokens[0].address], -UNWRAPPED_WEI)
        self.assertEqual(summary['net_by_token'][self.tokens[1].address], UNWRAPPED_WEI)
        self.assertEqual(summary['total_gas_wei'], GAS_WEI)

        profit = self.analyzer.compute_profit_usd(
            summary['net_by_token'], summary['total_gas_wei'], {'ethereum': ETH_USD})
        self.assertAlmostEqual(profit, -GAS_WEI / 1e18 * ETH_USD)


    def test_eoa_in_configured_list_costs_only_gas(self):
        self.assertAlmostEqual(self.profit_with([EOA.upper().replace('0X', '0x')]),
                               -GAS_WEI / 1e18 * ETH_USD)

    def test_eoa_not_in_configured_list_is_outflow(self):
        """Заданный список строгий: вывод на чужой адрес — отток."""
        other = '0x' + '0' * 36 + 'dead'
        self.assertAlmostEqual(self.profit_with([other]),
                               -(30000000000000000 + GAS_WEI) / 1e18 * ETH_USD)


if __name__ == '__main__':
    unittest.main()
