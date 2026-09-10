"""E2E на сырых данных BSC: профит бота приходит нативным BNB на EOA,
часть дохода при этом уходит билдеру.

Контракт бота анмаппит WBNB (87025944163963 wei) и раздаёт нативный BNB
двумя переводами: 35680637107224 wei билдеру и 51345307056739 wei обратно
на EOA. Логов с адресом EOA в receipt нет — доход виден только в
callTracer-трейсе.

Профит EOA = 51345307056739 − газ 30277354036085 = 21067953020654 wei
(≈ +$0.02 при BNB ~$718). Без трейса остаётся один газ — как раз тот
ложный «−$0.02», ради которого этот тест и написан.

Фикстуры в tests/fixtures — ответы RPC; в блоке оставлена только эта
транзакция, остальные 128 отброшены. Адреса, хеши и подпись заменены на
синтетические (EOA 0x…0e0a, контракт 0x…0b07, билдер 0x…0b1d).
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

TX = '0x7e577e577e577e577e577e577e577e577e577e577e577e577e577e577e577e57'
EOA = '0x0000000000000000000000000000000000000e0a'
BOT_CONTRACT = '0x0000000000000000000000000000000000000b07'
WBNB = '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'
USDT = '0x55d398326f99059fF775485246999027B3197955'
USDC = '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d'
BNB_USD = 718.0

PAYOUT_WEI = 51345307056739
GAS_WEI = 30277354036085


def load(name):
    with open(os.path.join(FIXTURES, f'bsc_eoa_payout_{name}.json')) as f:
        return json.load(f)


class TestEoaPayoutE2E(unittest.TestCase):
    def setUp(self):
        self.block = load('block')
        wrapped = TokenInfo(WBNB, 'WBNB', 18, 'binancecoin', is_wrapped=True)
        self.tokens = [
            wrapped,
            native_token_info(wrapped),
            TokenInfo(USDT, 'USDT', 18, 'tether'),
            TokenInfo(USDC, 'USDC', 18, 'usd-coin'),
        ]
        self.prices = {'binancecoin': BNB_USD, 'tether': 1.0, 'usd-coin': 1.0}
        self.eth_client = AsyncMock()
        self.eth_client.get_transaction_receipt.return_value = load('receipt')
        self.eth_client.trace_transaction.return_value = load('trace')
        self.analyzer = TxAnalyzer(self.eth_client, self.tokens, EOA)

    def test_profit_is_payout_minus_gas(self):
        summary = asyncio.run(self.analyzer.analyze_block(self.block))

        self.assertEqual(self.block['transactions'][0]['to'], BOT_CONTRACT)
        self.assertEqual(summary['tx_hashes'], [TX])
        self.assertEqual(summary['fail_count'], 0)
        self.assertFalse(summary['native_unknown'])
        # у EOA ни одного ERC20/WETH события — весь доход нативный, из трейса
        for token in self.tokens[:1] + self.tokens[2:]:
            self.assertEqual(summary['net_by_token'][token.address], 0, token.symbol)
        # доля билдера (35680637107224 wei) в профит EOA не входит
        self.assertEqual(summary['net_by_token'][self.tokens[1].address], PAYOUT_WEI)
        self.assertEqual(summary['total_gas_wei'], GAS_WEI)

        profit = self.analyzer.compute_profit_usd(
            summary['net_by_token'], summary['total_gas_wei'], self.prices,
            summary['native_unknown'])
        self.assertAlmostEqual(profit, (PAYOUT_WEI - GAS_WEI) / 1e18 * BNB_USD)
        self.assertEqual(f"{profit:+,.2f}", "+0.02")

    def test_trace_unavailable_reports_unknown_not_loss(self):
        """Регрессия: узел без архивного стейта не должен превращать доход в убыток."""
        self.eth_client.trace_transaction.side_effect = Exception(
            'required historical state unavailable (reexec=128)')
        summary = asyncio.run(self.analyzer.analyze_block(self.block))

        self.assertTrue(summary['native_unknown'])
        profit = self.analyzer.compute_profit_usd(
            summary['net_by_token'], summary['total_gas_wei'], self.prices,
            summary['native_unknown'])
        self.assertIsNone(profit)
        # без флага получился бы тот самый ложный «−$0.02»
        naive = self.analyzer.compute_profit_usd(
            summary['net_by_token'], summary['total_gas_wei'], self.prices)
        self.assertEqual(f"{naive:+,.2f}", "-0.02")


if __name__ == '__main__':
    unittest.main()
