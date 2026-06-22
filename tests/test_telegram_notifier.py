import asyncio
import time
import unittest
from unittest.mock import AsyncMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_notifier import TelegramNotifier, TxEvent, BotInfo, format_report
from tx_analyzer import TokenInfo, normalize_address

WETH = "0x1010101010101010101010101010101010101010"
USDC = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
ARB_WETH = "0x2020202020202020202020202020202020202020"
ADDR = "0x1234567890abcdef1234567890abcdef12345678"


def weth_token(address=WETH, symbol="WETH", coingecko_id="ethereum"):
    return TokenInfo(address, symbol, 18, coingecko_id, is_wrapped=True)


def usdc_token():
    return TokenInfo(USDC, "USDC", 6, "usd-coin")


def make_bot(name="ethereum", tokens=None, native_balance=None, balances=None,
             watched=ADDR, scanner_url=None):
    if tokens is None:
        tokens = [weth_token()]
    return BotInfo(name=name, watched_address=watched, tokens=tokens,
                   native_balance_wei=native_balance, balances=balances or {},
                   scanner_url=scanner_url)


def event(bot="ethereum", net_by_token=None, gas=0, tx_count=1, fail_count=0,
          watched=ADDR, block=100):
    if net_by_token is None:
        net_by_token = {normalize_address(WETH): 0}
    return TxEvent(bot_name=bot, watched_address=watched, block_number=block,
                   tx_count=tx_count, fail_count=fail_count,
                   net_by_token=net_by_token, gas_fee_wei=gas)


class TestFormatReport(unittest.TestCase):
    """Форматирование отчёта (профит в USD + балансы по токенам)"""

    def test_profit_usd_positive(self):
        bots = {"ethereum": make_bot(tokens=[weth_token(), usdc_token()])}
        events = [event(net_by_token={normalize_address(USDC): 5_000_000}, gas=0)]
        msg = format_report(events, bots_info=bots, prices={"usd-coin": 1.0, "ethereum": 2500.0})
        self.assertIn("ETHEREUM", msg)
        self.assertIn("0x1234...5678", msg)
        self.assertIn("✅", msg)
        self.assertIn("$+5.00", msg)
        self.assertIn("Successful txs: 1/1", msg)

    def test_profit_usd_negative_from_gas(self):
        bots = {"ethereum": make_bot(tokens=[weth_token(), usdc_token()])}
        # +1 USDC, но газ 0.01 ETH × $2500 = $25 → убыток
        events = [event(net_by_token={normalize_address(USDC): 1_000_000},
                        gas=10 ** 16, fail_count=0)]
        msg = format_report(events, bots_info=bots, prices={"usd-coin": 1.0, "ethereum": 2500.0})
        self.assertIn("❌", msg)
        self.assertIn("$-24.00", msg)

    def test_no_bots_info_shows_na(self):
        events = [event()]
        msg = format_report(events)
        self.assertIn("n/a", msg)
        self.assertIn("➖", msg)

    def test_balances_block_with_usd(self):
        bots = {"ethereum": make_bot(
            tokens=[weth_token(), usdc_token()],
            native_balance=1_500_000_000_000_000_000,  # 1.5 ETH
            balances={normalize_address(WETH): 2_000_000_000_000_000_000,  # 2 WETH
                      normalize_address(USDC): 1_000_000_000},  # 1000 USDC
        )}
        events = [event(net_by_token={normalize_address(USDC): 1_000_000})]
        msg = format_report(events, bots_info=bots,
                            prices={"usd-coin": 1.0, "ethereum": 2000.0})
        self.assertIn("Balance", msg)
        self.assertIn("ETH: 1.5000", msg)
        self.assertIn("WETH: 2.0000", msg)
        self.assertIn("USDC: 1000.0000", msg)
        self.assertIn("$3,000.00", msg)  # 1.5 ETH × 2000

    def test_balances_hide_zero(self):
        """Строки с балансом, округляемым до 0.0000, не выводятся."""
        dai = TokenInfo("0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "DAI", 18, "dai")
        bots = {"ethereum": make_bot(
            tokens=[weth_token(), usdc_token(), dai],
            native_balance=0,  # ETH 0.0000 → скрыть
            balances={normalize_address(WETH): 73_900_000_000_000_000,  # 0.0739 WETH
                      normalize_address(USDC): 9_310_000,               # 9.31 USDC
                      normalize_address(dai.address): 0},               # DAI 0.0000 → скрыть
        )}
        events = [event(net_by_token={normalize_address(USDC): 1_000_000})]
        msg = format_report(events, bots_info=bots,
                            prices={"usd-coin": 1.0, "ethereum": 2000.0, "dai": 1.0})
        self.assertIn("WETH: 0.0739", msg)
        self.assertIn("USDC: 9.3100", msg)
        self.assertNotIn("ETH: 0.0000", msg)
        self.assertNotIn("DAI:", msg)

    def test_aggregation_same_bot(self):
        bots = {"ethereum": make_bot(tokens=[weth_token(), usdc_token()])}
        events = [
            event(net_by_token={normalize_address(USDC): 1_000_000}, tx_count=1, fail_count=0),
            event(net_by_token={normalize_address(USDC): 2_000_000}, tx_count=2, fail_count=1),
        ]
        msg = format_report(events, bots_info=bots, prices={"usd-coin": 1.0, "ethereum": 2000.0})
        self.assertIn("Successful txs: 2/3", msg)
        self.assertIn("$+3.00", msg)

    def test_multiple_bots_sorted(self):
        bots = {
            "ethereum": make_bot("ethereum", tokens=[weth_token(), usdc_token()]),
            "arbitrum": make_bot("arbitrum", tokens=[weth_token(ARB_WETH)]),
        }
        events = [
            event("ethereum", net_by_token={normalize_address(USDC): 5_000_000}),
            event("arbitrum", net_by_token={normalize_address(ARB_WETH): -10 ** 16}),
        ]
        msg = format_report(events, bots_info=bots,
                            prices={"usd-coin": 1.0, "ethereum": 2000.0})
        pos_arb = msg.find("ARBITRUM")
        pos_eth = msg.find("ETHEREUM")
        self.assertTrue(0 <= pos_arb < pos_eth)


class TestAddressLink(unittest.TestCase):
    """Кликабельная ссылка на сканер для адреса бота"""

    def test_address_link_with_trailing_slash(self):
        bot = make_bot(scanner_url="https://etherscan.io/")
        link = bot.address_link("0x1234...5678")
        self.assertEqual(link, f"[0x1234...5678](https://etherscan.io/address/{bot.watched_address})")

    def test_address_link_without_trailing_slash(self):
        bot = make_bot(scanner_url="https://arbiscan.io")
        link = bot.address_link("0x1234...5678")
        self.assertEqual(link, f"[0x1234...5678](https://arbiscan.io/address/{bot.watched_address})")

    def test_address_link_slash_variants_match(self):
        """С '/' на конце и без него результат должен совпадать."""
        addr = "0xcccccccccccccccccccccccccccccccccccccccc"
        with_slash = make_bot(scanner_url="https://etherscan.io/", watched=addr)
        without_slash = make_bot(scanner_url="https://etherscan.io", watched=addr)
        self.assertEqual(with_slash.address_link("x"), without_slash.address_link("x"))

    def test_address_link_preserves_path_prefix(self):
        bot = make_bot(scanner_url="https://explorer.example.com/eth")
        self.assertIn("https://explorer.example.com/eth/address/", bot.address_link("addr"))

    def test_address_link_without_scanner_falls_back_to_backticks(self):
        bot = make_bot(scanner_url=None)
        self.assertEqual(bot.address_link("0x1234...5678"), "`0x1234...5678`")

    def test_report_uses_scanner_link(self):
        bots = {"ethereum": make_bot(tokens=[weth_token(), usdc_token()],
                                     scanner_url="https://etherscan.io/")}
        events = [event(net_by_token={normalize_address(USDC): 5_000_000})]
        msg = format_report(events, bots_info=bots, prices={"usd-coin": 1.0, "ethereum": 2500.0})
        self.assertIn(f"[0x1234...5678](https://etherscan.io/address/{normalize_address(ADDR)})", msg)

    def test_startup_uses_scanner_link(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._send = AsyncMock()
        bot = make_bot("ethereum", watched="0xcccccccccccccccccccccccccccccccccccccccc",
                       scanner_url="https://etherscan.io/")
        notifier.register_bot(bot)
        asyncio.run(notifier.send_startup_message())
        msg = notifier._send.call_args[0][0]
        self.assertIn(f"https://etherscan.io/address/{bot.watched_address}", msg)


class TestBotInfo(unittest.TestCase):
    def test_native_symbol(self):
        self.assertEqual(make_bot(tokens=[weth_token(symbol="WETH")]).native_symbol, "ETH")
        self.assertEqual(make_bot(tokens=[weth_token(symbol="WMON")]).native_symbol, "MON")
        self.assertEqual(make_bot(tokens=[weth_token(symbol="ETH")]).native_symbol, "ETH")

    def test_native_coingecko_id(self):
        self.assertEqual(make_bot(tokens=[weth_token(coingecko_id="ethereum")]).native_coingecko_id,
                         "ethereum")

    def test_coingecko_ids_collects_all(self):
        bot = make_bot(tokens=[weth_token(), usdc_token()])
        self.assertEqual(set(bot.coingecko_ids), {"ethereum", "usd-coin"})

    def test_refresh_balances(self):
        eth_client = AsyncMock()
        eth_client.get_balance = AsyncMock(return_value=10 ** 18)
        eth_client.get_erc20_balance = AsyncMock(side_effect=[2 * 10 ** 18, 5_000_000])
        bot = BotInfo(name="ethereum", watched_address=ADDR,
                      tokens=[weth_token(), usdc_token()], eth_client=eth_client)
        asyncio.run(bot.refresh_balances())
        self.assertEqual(bot.native_balance_wei, 10 ** 18)
        self.assertEqual(bot.balances[normalize_address(WETH)], 2 * 10 ** 18)
        self.assertEqual(bot.balances[normalize_address(USDC)], 5_000_000)


class TestStartupMessage(unittest.TestCase):
    def test_startup_basic(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="*/30 * * * *")
        notifier._send = AsyncMock()
        notifier.register_bot(make_bot("ethereum", watched="0xcccccccccccccccccccccccccccccccccccccccc"))
        notifier.register_bot(make_bot("arbitrum", tokens=[weth_token(ARB_WETH)],
                                       watched="0x0000000000DeAdBeEf00112233445566778899aA"))
        asyncio.run(notifier.send_startup_message())

        notifier._send.assert_called_once()
        msg = notifier._send.call_args[0][0]
        self.assertIn("Monitor Started", msg)
        self.assertIn("ethereum", msg)
        self.assertIn("arbitrum", msg)
        self.assertIn("*/30 * * * *", msg)
        self.assertIn("WETH", msg)

    def test_startup_balances_with_usd(self):
        cg_client = AsyncMock()
        cg_client.get_prices_usd = AsyncMock(return_value={"ethereum": 2000.0, "usd-coin": 1.0})
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *", cg_client=cg_client)
        notifier._send = AsyncMock()
        notifier.register_bot(make_bot(
            "ethereum",
            tokens=[weth_token(), usdc_token()],
            native_balance=1_500_000_000_000_000_000,
            balances={normalize_address(WETH): 0, normalize_address(USDC): 1_000_000_000},
            watched="0xcccccccccccccccccccccccccccccccccccccccc",
        ))
        asyncio.run(notifier.send_startup_message())
        msg = notifier._send.call_args[0][0]
        self.assertIn("ETH: 1.5000", msg)
        self.assertIn("$3,000.00", msg)
        self.assertIn("USDC: 1000.0000", msg)
        self.assertIn("$2,000.00", msg)  # WETH header price

    def test_startup_alphabetical_order(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._send = AsyncMock()
        for name in ["z_bot", "a_bot", "m_bot"]:
            notifier.register_bot(make_bot(name, watched="0x1"))
        asyncio.run(notifier.send_startup_message())
        msg = notifier._send.call_args[0][0]
        pos_a = msg.find("*a_bot*")
        pos_m = msg.find("*m_bot*")
        pos_z = msg.find("*z_bot*")
        self.assertTrue(pos_a < pos_m < pos_z)


class TestTelegramNotifierBatching(unittest.TestCase):
    """Логика батчинга уведомлений (поведение не изменилось)"""

    def test_first_event_sends_immediately(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._send = AsyncMock()
        asyncio.run(notifier.add_event(event()))
        notifier._send.assert_called_once()

    def test_second_event_batched(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._last_sent = time.time()
        notifier._send = AsyncMock()
        asyncio.run(notifier.add_event(event()))
        notifier._send.assert_not_called()
        self.assertEqual(len(notifier._pending), 1)

    def test_force_flush_sends(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="0 * * * *")
        notifier._send = AsyncMock()
        notifier._pending = [event(), event()]
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
        asyncio.run(notifier.add_event(event()))
        after = time.time()
        self.assertGreaterEqual(notifier._last_sent, before)
        self.assertLessEqual(notifier._last_sent, after)

    def test_seconds_until_next(self):
        notifier = TelegramNotifier("token", "chat", notify_schedule="* * * * *")
        delay = notifier._seconds_until_next()
        self.assertGreaterEqual(delay, 0)
        self.assertLessEqual(delay, 60)


class TestTxEvent(unittest.TestCase):
    def test_default_timestamp(self):
        before = time.time()
        e = event()
        after = time.time()
        self.assertGreaterEqual(e.timestamp, before)
        self.assertLessEqual(e.timestamp, after)

    def test_fields(self):
        net = {normalize_address(USDC): -500}
        e = TxEvent("arbitrum", "0xabc", 200, 3, 1, net, 300)
        self.assertEqual(e.bot_name, "arbitrum")
        self.assertEqual(e.tx_count, 3)
        self.assertEqual(e.fail_count, 1)
        self.assertEqual(e.net_by_token, net)
        self.assertEqual(e.gas_fee_wei, 300)


if __name__ == "__main__":
    unittest.main()
