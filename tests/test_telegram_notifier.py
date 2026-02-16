import asyncio
import time
import unittest
from unittest.mock import AsyncMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_notifier import TelegramNotifier, TxEvent, format_report


class TestFormatReport(unittest.TestCase):
    """Тесты форматирования отчёта"""

    def test_single_profitable_event(self):
        events = [TxEvent(
            bot_name="ethereum",
            block_number=18000000,
            tx_count=1,
            fail_count=0,
            net_wei_change=1_000_000_000_000_000,  # +0.001 ETH
            gas_fee_wei=500_000_000_000_000,
        )]
        msg = format_report(events)
        self.assertIn("ETHEREUM", msg)
        self.assertIn("\u2705", msg)  # profit emoji
        self.assertIn("+0.001000", msg)
        self.assertIn("Транзакций: 1", msg)
        self.assertNotIn("Неудачных", msg)

    def test_single_losing_event(self):
        events = [TxEvent(
            bot_name="ethereum",
            block_number=18000000,
            tx_count=1,
            fail_count=1,
            net_wei_change=-500_000_000_000_000,
            gas_fee_wei=500_000_000_000_000,
        )]
        msg = format_report(events)
        self.assertIn("\u274c", msg)  # loss emoji
        self.assertIn("Неудачных: 1", msg)
        self.assertIn("-0.000500", msg)

    def test_zero_profit(self):
        events = [TxEvent("ethereum", 100, 1, 0, 0, 0)]
        msg = format_report(events)
        self.assertIn("\u2796", msg)  # neutral emoji

    def test_multiple_bots(self):
        events = [
            TxEvent("ethereum", 100, 2, 0, 1_000_000_000_000_000, 200_000_000_000_000),
            TxEvent("arbitrum", 200, 3, 1, -500_000_000_000_000, 300_000_000_000_000),
        ]
        msg = format_report(events)
        self.assertIn("ETHEREUM", msg)
        self.assertIn("ARBITRUM", msg)
        # ethereum profitable, arbitrum loss
        eth_pos = msg.index("ETHEREUM")
        arb_pos = msg.index("ARBITRUM")
        eth_section = msg[eth_pos:arb_pos]
        arb_section = msg[arb_pos:]
        self.assertIn("\u2705", eth_section)
        self.assertIn("\u274c", arb_section)

    def test_aggregation_same_bot(self):
        events = [
            TxEvent("ethereum", 100, 1, 0, 1_000_000_000_000_000, 100_000_000_000_000),
            TxEvent("ethereum", 101, 2, 1, 2_000_000_000_000_000, 200_000_000_000_000),
        ]
        msg = format_report(events)
        self.assertIn("Транзакций: 3", msg)
        self.assertIn("Блоков: 2", msg)
        self.assertIn("Неудачных: 1", msg)
        self.assertIn("+0.003000", msg)
        self.assertIn("0.000300", msg)  # gas

    def test_no_fails_line_when_zero(self):
        events = [TxEvent("ethereum", 100, 3, 0, 1_000_000_000_000_000, 100_000_000_000_000)]
        msg = format_report(events)
        self.assertNotIn("Неудачных", msg)

    def test_gas_display(self):
        events = [TxEvent("ethereum", 100, 1, 0, 0, 3_500_000_000_000_000)]
        msg = format_report(events)
        self.assertIn("0.003500", msg)


class TestTelegramNotifierBatching(unittest.TestCase):
    """Тесты логики батчинга уведомлений"""

    def _make_event(self, bot="ethereum", net=1_000_000_000_000_000, gas=100_000_000_000_000):
        return TxEvent(bot, 100, 1, 0, net, gas)

    def test_flushes_when_interval_passed(self):
        notifier = TelegramNotifier("token", "chat", notify_interval_minutes=1)
        notifier._last_sent = time.time() - 120  # 2 min ago
        notifier._send = AsyncMock()

        asyncio.run(notifier.add_event(self._make_event()))

        notifier._send.assert_called_once()
        self.assertEqual(len(notifier._pending), 0)

    def test_batches_when_interval_not_passed(self):
        notifier = TelegramNotifier("token", "chat", notify_interval_minutes=60)
        notifier._last_sent = time.time()
        notifier._send = AsyncMock()

        asyncio.run(notifier.add_event(self._make_event()))

        notifier._send.assert_not_called()
        self.assertEqual(len(notifier._pending), 1)

    def test_multiple_events_batched(self):
        notifier = TelegramNotifier("token", "chat", notify_interval_minutes=60)
        notifier._last_sent = time.time()
        notifier._send = AsyncMock()

        async def add_three():
            await notifier.add_event(self._make_event())
            await notifier.add_event(self._make_event())
            await notifier.add_event(self._make_event())

        asyncio.run(add_three())

        notifier._send.assert_not_called()
        self.assertEqual(len(notifier._pending), 3)

    def test_force_flush_sends(self):
        notifier = TelegramNotifier("token", "chat", notify_interval_minutes=60)
        notifier._send = AsyncMock()
        notifier._pending = [self._make_event(), self._make_event()]

        asyncio.run(notifier.force_flush())

        notifier._send.assert_called_once()
        self.assertEqual(len(notifier._pending), 0)

    def test_force_flush_empty_does_nothing(self):
        notifier = TelegramNotifier("token", "chat", notify_interval_minutes=60)
        notifier._send = AsyncMock()

        asyncio.run(notifier.force_flush())

        notifier._send.assert_not_called()

    def test_flush_updates_last_sent(self):
        notifier = TelegramNotifier("token", "chat", notify_interval_minutes=1)
        notifier._last_sent = 0  # long ago
        notifier._send = AsyncMock()

        before = time.time()
        asyncio.run(notifier.add_event(self._make_event()))
        after = time.time()

        self.assertGreaterEqual(notifier._last_sent, before)
        self.assertLessEqual(notifier._last_sent, after)

    def test_first_event_sends_immediately(self):
        """Первое событие должно отправиться сразу (_last_sent == 0)"""
        notifier = TelegramNotifier("token", "chat", notify_interval_minutes=60)
        notifier._send = AsyncMock()

        asyncio.run(notifier.add_event(self._make_event()))

        notifier._send.assert_called_once()

    def test_startup_message(self):
        notifier = TelegramNotifier("token", "chat", notify_interval_minutes=30)
        notifier._send = AsyncMock()

        bots = {
            "ethereum": {
                "blockchain": "ethereum",
                "watched_address": "0xc0c9c680a96cf92604a94cff927c0ad674450191",
            },
            "arbitrum": {
                "blockchain": "arbitrum",
                "watched_address": "0x0000000000DeAdBeEf00112233445566778899aA",
            },
        }
        asyncio.run(notifier.send_startup_message(bots))

        notifier._send.assert_called_once()
        msg = notifier._send.call_args[0][0]
        self.assertIn("Monitor Started", msg)
        self.assertIn("ethereum", msg)
        self.assertIn("arbitrum", msg)
        self.assertIn("Ethereum", msg)
        self.assertIn("Arbitrum", msg)
        self.assertIn("30 мин", msg)
        self.assertIn("0xc0c9c680a96cf92604a94cff927c0ad674450191", msg)


class TestTxEvent(unittest.TestCase):
    """Тесты TxEvent"""

    def test_default_timestamp(self):
        before = time.time()
        event = TxEvent("ethereum", 100, 1, 0, 1000, 500)
        after = time.time()
        self.assertGreaterEqual(event.timestamp, before)
        self.assertLessEqual(event.timestamp, after)

    def test_fields(self):
        event = TxEvent("arbitrum", 200, 3, 1, -500, 300)
        self.assertEqual(event.bot_name, "arbitrum")
        self.assertEqual(event.block_number, 200)
        self.assertEqual(event.tx_count, 3)
        self.assertEqual(event.fail_count, 1)
        self.assertEqual(event.net_wei_change, -500)
        self.assertEqual(event.gas_fee_wei, 300)


if __name__ == "__main__":
    unittest.main()
