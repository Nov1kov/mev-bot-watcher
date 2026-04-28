import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_notifier import TelegramNotifier, TxEvent, BotInfo, format_report


class TestFormatReport(unittest.TestCase):
    """Тесты форматирования отчёта"""

    def test_single_profitable_event(self):
        events = [TxEvent(
            bot_name="ethereum",
            watched_address="0x1234567890abcdef1234567890abcdef12345678",
            block_number=18000000,
            tx_count=1,
            fail_count=0,
            net_wei_change=1_000_000_000_000_000,  # +0.001 ETH
            gas_fee_wei=500_000_000_000_000,
        )]
        msg = format_report(events)
        self.assertIn("ETHEREUM", msg)
        self.assertIn("0x1234...5678", msg)  # short address
        self.assertIn("\u2705", msg)  # profit emoji
        self.assertIn("+0.001000", msg)
        self.assertIn("Successful txs: 1/1", msg)

    def test_single_losing_event(self):
        events = [TxEvent(
            bot_name="ethereum",
            watched_address="0x1234567890abcdef1234567890abcdef12345678",
            block_number=18000000,
            tx_count=1,
            fail_count=1,
            net_wei_change=-500_000_000_000_000,
            gas_fee_wei=500_000_000_000_000,
        )]
        msg = format_report(events)
        self.assertIn("\u274c", msg)  # loss emoji
        self.assertIn("Successful txs: 0/1", msg)
        self.assertIn("-0.000500", msg)

    def test_zero_profit(self):
        events = [TxEvent("ethereum", "0x1234567890abcdef1234567890abcdef12345678", 100, 1, 0, 0, 0)]
        msg = format_report(events)
        self.assertIn("\u2796", msg)  # neutral emoji

    def test_multiple_bots(self):
        events = [
            TxEvent("ethereum", "0x1234567890abcdef1234567890abcdef12345678", 100, 2, 0, 1_000_000_000_000_000, 200_000_000_000_000),
            TxEvent("arbitrum", "0xabcdef1234567890abcdef1234567890abcdef12", 200, 3, 1, -500_000_000_000_000, 300_000_000_000_000),
        ]
        msg = format_report(events)
        self.assertIn("ETHEREUM", msg)
        self.assertIn("ARBITRUM", msg)
        lines = msg.split("\n")
        eth_line = next(l for l in lines if "ETHEREUM" in l)
        arb_line = next(l for l in lines if "ARBITRUM" in l)
        self.assertIn("\u2705", eth_line)
        self.assertIn("\u274c", arb_line)

    def test_aggregation_same_bot(self):
        events = [
            TxEvent("ethereum", "0x1234567890abcdef1234567890abcdef12345678", 100, 1, 0, 1_000_000_000_000_000, 100_000_000_000_000),
            TxEvent("ethereum", "0x1234567890abcdef1234567890abcdef12345678", 101, 2, 1, 2_000_000_000_000_000, 200_000_000_000_000),
        ]
        msg = format_report(events)
        self.assertIn("Successful txs: 2/3", msg)
        self.assertIn("+0.003000", msg)

    def test_all_successful(self):
        events = [TxEvent("ethereum", "0x1234567890abcdef1234567890abcdef12345678", 100, 3, 0, 1_000_000_000_000_000, 100_000_000_000_000)]
        msg = format_report(events)
        self.assertIn("Successful txs: 3/3", msg)

    def test_no_gas_line(self):
        events = [TxEvent("ethereum", "0x1234567890abcdef1234567890abcdef12345678", 100, 1, 0, 0, 3_500_000_000_000_000)]
        msg = format_report(events)
        self.assertNotIn("Gas:", msg)

    def test_usd_price_shown(self):
        events = [TxEvent(
            bot_name="ethereum",
            watched_address="0x1234567890abcdef1234567890abcdef12345678",
            block_number=100,
            tx_count=1,
            fail_count=0,
            net_wei_change=1_000_000_000_000_000_000,  # +1 ETH
            gas_fee_wei=0,
        )]
        msg = format_report(events, prices={"ethereum": 2500.0})
        self.assertIn("+1.000000 ETH", msg)
        self.assertIn("$+2500.00", msg)

    def test_no_usd_when_price_none(self):
        events = [TxEvent("ethereum", "0x1234567890abcdef1234567890abcdef12345678", 100, 1, 0, 1_000_000_000_000_000, 0)]
        msg = format_report(events)
        self.assertNotIn("$", msg)

    def test_alphabetical_order(self):
        events = [
            TxEvent("z_bot", "0x1", 100, 1, 0, 1000, 100),
            TxEvent("a_bot", "0x2", 100, 1, 0, 1000, 100),
            TxEvent("m_bot", "0x3", 100, 1, 0, 1000, 100),
        ]
        msg = format_report(events)
        # Check order of appearances
        pos_a = msg.find("A_BOT")
        pos_m = msg.find("M_BOT")
        pos_z = msg.find("Z_BOT")
        self.assertTrue(pos_a < pos_m < pos_z, f"Order is wrong: A:{pos_a}, M:{pos_m}, Z:{pos_z}")


class TestTelegramNotifierBatching(unittest.TestCase):
    """Тесты логики батчинга уведомлений"""

    def _make_event(self, bot="ethereum", net=1_000_000_000_000_000, gas=100_000_000_000_000):
        return TxEvent(bot, "0x1234567890abcdef1234567890abcdef12345678", 100, 1, 0, net, gas)

    def test_first_event_sends_immediately(self):
        """Первое событие должно отправиться сразу (_last_sent == 0)"""
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._send = AsyncMock()

        asyncio.run(notifier.add_event(self._make_event()))

        notifier._send.assert_called_once()

    def test_second_event_batched(self):
        """После первой отправки события накапливаются до следующего cron-тика"""
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._last_sent = time.time()
        notifier._send = AsyncMock()

        asyncio.run(notifier.add_event(self._make_event()))

        notifier._send.assert_not_called()
        self.assertEqual(len(notifier._pending), 1)

    def test_multiple_events_batched(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
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
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._send = AsyncMock()
        notifier._pending = [self._make_event(), self._make_event()]

        asyncio.run(notifier.force_flush())

        notifier._send.assert_called_once()
        self.assertEqual(len(notifier._pending), 0)

    def test_force_flush_empty_does_nothing(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._send = AsyncMock()

        asyncio.run(notifier.force_flush())

        notifier._send.assert_not_called()

    def test_flush_updates_last_sent(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._send = AsyncMock()

        before = time.time()
        asyncio.run(notifier.add_event(self._make_event()))
        after = time.time()

        self.assertGreaterEqual(notifier._last_sent, before)
        self.assertLessEqual(notifier._last_sent, after)

    def test_startup_message(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="*/30 * * * *")
        notifier._send = AsyncMock()

        notifier.register_bot(BotInfo(
            name="ethereum",
            watched_address="0xc0c9c680a96cf92604a94cff927c0ad674450191",
            token_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            token_symbol="WETH",
        ))
        notifier.register_bot(BotInfo(
            name="arbitrum",
            watched_address="0x0000000000DeAdBeEf00112233445566778899aA",
            token_address="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            token_symbol="WETH",
        ))
        asyncio.run(notifier.send_startup_message())

        notifier._send.assert_called_once()
        msg = notifier._send.call_args[0][0]
        self.assertIn("Monitor Started", msg)
        self.assertIn("ethereum", msg)
        self.assertIn("arbitrum", msg)
        self.assertIn("*/30 * * * *", msg)
        self.assertIn("0xc0c9c680a96cf92604a94cff927c0ad674450191", msg)
        self.assertIn("WETH", msg)

    def test_startup_message_with_balance(self):
        """Выводит суммарный баланс (native + wrapped) в нативном тикере"""
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._send = AsyncMock()

        notifier.register_bot(BotInfo(
            name="ethereum",
            watched_address="0xc0c9c680a96cf92604a94cff927c0ad674450191",
            token_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            token_symbol="WETH",
            total_balance_wei=1_234_500_000_000_000_000,  # 1.2345 ETH
        ))
        asyncio.run(notifier.send_startup_message())

        msg = notifier._send.call_args[0][0]
        self.assertIn("1.2345 ETH", msg)
        self.assertIn("Balance", msg)
        # Без цены USD-части быть не должно
        self.assertNotIn("$", msg.split("Balance")[1].split("\n")[0])

    def test_startup_message_balance_with_usd(self):
        """Если есть coingecko_id и cg_client, рядом с балансом показывается USD"""
        cg_client = AsyncMock()
        cg_client.get_prices_usd = AsyncMock(return_value={"ethereum": 2000.0})

        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *",
                                    cg_client=cg_client)
        notifier._send = AsyncMock()
        notifier.register_bot(BotInfo(
            name="ethereum",
            watched_address="0xc0c9c680a96cf92604a94cff927c0ad674450191",
            token_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            token_symbol="WETH",
            coingecko_id="ethereum",
            total_balance_wei=1_500_000_000_000_000_000,  # 1.5 ETH
        ))
        asyncio.run(notifier.send_startup_message())

        msg = notifier._send.call_args[0][0]
        self.assertIn("1.5000 ETH", msg)
        self.assertIn("$3,000.00", msg)

    def test_native_symbol_strips_w_prefix(self):
        self.assertEqual(BotInfo("b", "a", "t", token_symbol="WETH").native_symbol, "ETH")
        self.assertEqual(BotInfo("b", "a", "t", token_symbol="WMON").native_symbol, "MON")
        self.assertEqual(BotInfo("b", "a", "t", token_symbol="ETH").native_symbol, "ETH")
        self.assertEqual(BotInfo("b", "a", "t", token_symbol="W").native_symbol, "W")

    def test_startup_message_with_price(self):
        """Если для бота задан coingecko_id и CoinGecko клиент, в приветствии будет цена"""
        cg_client = AsyncMock()
        cg_client.get_prices_usd = AsyncMock(return_value={"ethereum": 3210.5})

        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *",
                                    cg_client=cg_client)
        notifier._send = AsyncMock()

        notifier.register_bot(BotInfo(
            name="ethereum",
            watched_address="0xc0c9c680a96cf92604a94cff927c0ad674450191",
            token_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            token_symbol="WETH",
            coingecko_id="ethereum",
        ))
        asyncio.run(notifier.send_startup_message())

        msg = notifier._send.call_args[0][0]
        self.assertIn("WETH", msg)
        self.assertIn("$3,210.50", msg)
        cg_client.get_prices_usd.assert_awaited_once()

    def test_startup_message_alphabetical_order(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._send = AsyncMock()

        names = ["z_bot", "a_bot", "m_bot"]
        for name in names:
            notifier.register_bot(BotInfo(
                name=name,
                watched_address="0x1",
                token_address="0x2",
                token_symbol="ETH",
            ))

        asyncio.run(notifier.send_startup_message())
        msg = notifier._send.call_args[0][0]
        pos_a = msg.find("*a_bot*")
        pos_m = msg.find("*m_bot*")
        pos_z = msg.find("*z_bot*")
        self.assertTrue(pos_a < pos_m < pos_z, f"Order is wrong in startup: A:{pos_a}, M:{pos_m}, Z:{pos_z}")

    def test_seconds_until_next(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="* * * * *")
        delay = notifier._seconds_until_next()
        self.assertGreaterEqual(delay, 0)
        self.assertLessEqual(delay, 60)


class TestTxEvent(unittest.TestCase):
    """Тесты TxEvent"""

    def test_default_timestamp(self):
        before = time.time()
        event = TxEvent("ethereum", "0x1234567890abcdef1234567890abcdef12345678", 100, 1, 0, 1000, 500)
        after = time.time()
        self.assertGreaterEqual(event.timestamp, before)
        self.assertLessEqual(event.timestamp, after)

    def test_fields(self):
        event = TxEvent("arbitrum", "0xabcdef1234567890abcdef1234567890abcdef12", 200, 3, 1, -500, 300)
        self.assertEqual(event.bot_name, "arbitrum")
        self.assertEqual(event.watched_address, "0xabcdef1234567890abcdef1234567890abcdef12")
        self.assertEqual(event.block_number, 200)
        self.assertEqual(event.tx_count, 3)
        self.assertEqual(event.fail_count, 1)
        self.assertEqual(event.net_wei_change, -500)
        self.assertEqual(event.gas_fee_wei, 300)


if __name__ == "__main__":
    unittest.main()
