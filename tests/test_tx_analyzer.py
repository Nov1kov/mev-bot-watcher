import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tx_analyzer import TxAnalyzer, TokenInfo, normalize_address, compute_profit_usd_for

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DEPOSIT = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
WITHDRAWAL = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
# Произвольные не-Transfer сигнатуры (должны игнорироваться парсером)
APPROVAL = "0x" + "a0" * 32
OTHER_EVENT = "0x" + "9e" * 32

# Синтетические хэши транзакций
FAIL_TX_HASH = "0x" + "fa" * 32
SUCCESS_TX_HASH = "0x" + "5e" * 32
MULTITOKEN_TX_HASH = "0x" + "70" * 32
MONAD_TX_HASH = "0x" + "60" * 32

WATCHED_ADDRESS = "0x000000000000000000000000000000000000a11a"
WETH_CONTRACT = "0x1111111111111111111111111111111111111111"


def pad(addr: str) -> str:
    """Адрес в виде 32-байтового topic (left-padded до 64 hex)."""
    return "0x" + addr[2:].lower().zfill(64)


def weth_token(address: str = WETH_CONTRACT, symbol: str = "WETH",
               decimals: int = 18, coingecko_id="ethereum") -> TokenInfo:
    return TokenInfo(address=address, symbol=symbol, decimals=decimals,
                     coingecko_id=coingecko_id, is_wrapped=True)


def make_analyzer(tokens=None, watched=WATCHED_ADDRESS, eth_client=None,
                  cg_client=None) -> TxAnalyzer:
    """Создаёт TxAnalyzer (по умолчанию — один WETH-токен) для тестов."""
    if tokens is None:
        tokens = [weth_token()]
    return TxAnalyzer(eth_client=eth_client, tokens=tokens,
                      watched_address=watched, cg_client=cg_client)


def net(result, token_address):
    return result['net_by_token'][normalize_address(token_address)]


# Синтетический receipt: fail-транзакция (логов нет, убыток равен стоимости газа)
FAIL_RECEIPT = {
    "status": "0x0",
    "logs": [],
    "transactionHash": FAIL_TX_HASH,
    "from": "0x00000000000000000000000000000000000face0",
    "to": WATCHED_ADDRESS,
    "gasUsed": "0x462ad",
    "effectiveGasPrice": "0x139cff0",
}

# Синтетический receipt: успешная транзакция (spread по WETH положительный,
# но газ делает итог в wei отрицательным)
COUNTERPARTY_A = "0x2222222222222222222222222222222222222222"
COUNTERPARTY_B = "0x4444444444444444444444444444444444444444"
OTHER_TOKEN = "0x3333333333333333333333333333333333333333"
OTHER_POOL = "0x5555555555555555555555555555555555555555"

SUCCESS_RECEIPT = {
    "status": "0x1",
    "logs": [
        # WETH Transfer COUNTERPARTY_A -> watched (incoming)
        {
            "address": WETH_CONTRACT,
            "topics": [TRANSFER, pad(COUNTERPARTY_A), pad(WATCHED_ADDRESS)],
            "data": "0x000000000000000000000000000000000000000000000000008bc909c5707ec5",
        },
        # Transfer другого токена (не отслеживается) — игнор
        {
            "address": OTHER_TOKEN,
            "topics": [TRANSFER, pad("0x6666666666666666666666666666666666666666"),
                       pad(COUNTERPARTY_A)],
            "data": "0x0000000000000000000000000000000000000000000000000000000004d3ad0c",
        },
        # WETH Transfer watched -> COUNTERPARTY_B (outgoing)
        {
            "address": WETH_CONTRACT,
            "topics": [TRANSFER, pad(WATCHED_ADDRESS), pad(COUNTERPARTY_B)],
            "data": "0x000000000000000000000000000000000000000000000000008bc612a9452b98",
        },
        # Событие пула (не Transfer) — игнор
        {
            "address": OTHER_POOL,
            "topics": [OTHER_EVENT, pad(WATCHED_ADDRESS), pad(COUNTERPARTY_A)],
            "data": "0x00000000",
        },
    ],
    "transactionHash": SUCCESS_TX_HASH,
    "from": "0x00000000000000000000000000000000000face0",
    "to": WATCHED_ADDRESS,
    "gasUsed": "0x62bad",
    "effectiveGasPrice": "0x1312d00",
}


class TestParseReceiptFail(unittest.TestCase):
    """Тесты обработки fail-транзакции"""

    def setUp(self):
        self.analyzer = make_analyzer()
        self.result = self.analyzer.parse_receipt(FAIL_RECEIPT, FAIL_RECEIPT['transactionHash'])

    def test_status_is_zero(self):
        self.assertEqual(self.result['status'], 0)

    def test_net_zero(self):
        self.assertEqual(net(self.result, WETH_CONTRACT), 0)

    def test_gas_fee_calculated(self):
        expected_gas = int("0x462ad", 16) * int("0x139cff0", 16)
        self.assertEqual(self.result['gas_fee_wei'], expected_gas)
        self.assertGreater(self.result['gas_fee_wei'], 0)

    def test_tx_hash(self):
        self.assertEqual(self.result['tx_hash'], FAIL_RECEIPT['transactionHash'])


class TestParseReceiptSuccess(unittest.TestCase):
    """Тесты обработки успешной транзакции"""

    def setUp(self):
        self.analyzer = make_analyzer()
        self.result = self.analyzer.parse_receipt(SUCCESS_RECEIPT, SUCCESS_RECEIPT['transactionHash'])

    def test_status_is_one(self):
        self.assertEqual(self.result['status'], 1)

    def test_net_weth(self):
        """net WETH = incoming (log 0) - outgoing (log 2)"""
        incoming = int("0x008bc909c5707ec5", 16)
        outgoing = int("0x008bc612a9452b98", 16)
        self.assertEqual(net(self.result, WETH_CONTRACT), incoming - outgoing)

    def test_ignores_non_weth_logs(self):
        """Не-WETH логи (другие токены, pool events) не влияют на net WETH"""
        self.assertGreater(net(self.result, WETH_CONTRACT), 0)

    def test_gas_fee_calculated(self):
        expected_gas = int("0x62bad", 16) * int("0x1312d00", 16)
        self.assertEqual(self.result['gas_fee_wei'], expected_gas)

    def test_net_minus_gas_negative(self):
        """Spread положительный, но gas делает итог (в wei) отрицательным"""
        spread = net(self.result, WETH_CONTRACT)
        self.assertGreater(spread, 0)
        self.assertLess(spread - self.result['gas_fee_wei'], 0)


class TestParseReceiptIgnoresOtherTokens(unittest.TestCase):
    """Тест: логи токенов вне списка отслеживаемых не учитываются"""

    def test_only_tracked_transfers_counted(self):
        analyzer = make_analyzer()
        receipt = {
            "status": "0x1",
            "gasUsed": "0x5208",
            "effectiveGasPrice": "0x3b9aca00",
            "logs": [
                {
                    "address": "0x9999999999999999999999999999999999999999",
                    "topics": [TRANSFER, pad(WATCHED_ADDRESS),
                               pad("0x1212121212121212121212121212121212121212")],
                    "data": "0x0000000000000000000000000000000000000000000000000de0b6b3a7640000",
                },
            ],
        }
        result = analyzer.parse_receipt(receipt, "0xfake")
        self.assertEqual(result['status'], 1)
        self.assertEqual(result['tx_hash'], "0xfake")
        self.assertEqual(net(result, WETH_CONTRACT), 0)


# ────────────────────────────────────────────────────────────────────────────
# Мультитокенный сценарий: бот арбитражит стейблы. Профит сделан в USDC
# (+1.719842), USDe проходит транзитом (net 0), газ платится в ETH. Ни одного
# WETH-перевода в транзакции нет. Все адреса синтетические.
WETH_ETH = "0x1010101010101010101010101010101010101010"
USDC = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
USDE = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
USDT = "0xcccccccccccccccccccccccccccccccccccccccc"
DAI = "0xdddddddddddddddddddddddddddddddddddddddd"
ETH_WATCHED = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"

CP_POOL = "0x6666666666666666666666666666666666666666"
CP_ROUTER = "0x7777777777777777777777777777777777777777"
CP_PM = "0x8888888888888888888888888888888888888888"

MULTITOKEN_RECEIPT = {
    "status": "0x1",
    "gasUsed": "0x51e39",
    "effectiveGasPrice": "0xbbda2bd4",
    "transactionHash": MULTITOKEN_TX_HASH,
    "from": "0x0000000000000000000000000000000000005ea6",
    "to": ETH_WATCHED,
    "logs": [
        # USDC Transfer CP_POOL -> watched (incoming)
        {"address": USDC, "topics": [TRANSFER, pad(CP_POOL), pad(ETH_WATCHED)],
            "data": "0x00000000000000000000000000000000000000000000000000000000e3c5a166"},
        # USDC Approval (watched, spender) — не Transfer, игнор
        {"address": USDC, "topics": [APPROVAL, pad(ETH_WATCHED), pad(CP_ROUTER)],
            "data": "0x00000000000000000000000000000000000000000000000000000000e3ab6344"},
        # USDC Transfer watched -> CP_ROUTER (outgoing)
        {"address": USDC, "topics": [TRANSFER, pad(ETH_WATCHED), pad(CP_ROUTER)],
            "data": "0x00000000000000000000000000000000000000000000000000000000e3ab6344"},
        # USDe Transfer CP_ROUTER -> watched (incoming)
        {"address": USDE, "topics": [TRANSFER, pad(CP_ROUTER), pad(ETH_WATCHED)],
            "data": "0x0000000000000000000000000000000000000000000000cf120c398b85715ecc"},
        # USDT Transfer CP_PM -> CP_POOL (не watched, игнор для net)
        {"address": USDT, "topics": [TRANSFER, pad(CP_PM), pad(CP_POOL)],
            "data": "0x00000000000000000000000000000000000000000000000000000000e3cdb955"},
        # USDe Transfer watched -> CP_PM (outgoing) — обнуляет USDe net
        {"address": USDE, "topics": [TRANSFER, pad(ETH_WATCHED), pad(CP_PM)],
            "data": "0x0000000000000000000000000000000000000000000000cf120c398b85715ecc"},
    ],
}


def eth_tokens():
    return [
        TokenInfo(WETH_ETH, "WETH", 18, "ethereum", is_wrapped=True),
        TokenInfo(USDC, "USDC", 6, "usd-coin"),
        TokenInfo(USDE, "USDe", 18, "ethena-usde"),
        TokenInfo(USDT, "USDT", 6, "tether"),
        TokenInfo(DAI, "DAI", 18, "dai"),
    ]


class TestMultitokenReceipt(unittest.TestCase):
    """Мультитокенный профит (синтетические адреса)"""

    def setUp(self):
        self.analyzer = make_analyzer(tokens=eth_tokens(), watched=ETH_WATCHED)
        self.result = self.analyzer.parse_receipt(
            MULTITOKEN_RECEIPT, MULTITOKEN_RECEIPT['transactionHash'])

    def test_usdc_net_profit(self):
        # 0xe3c5a166 - 0xe3ab6344 = 1_719_842 (raw, 6 знаков → +1.719842 USDC)
        self.assertEqual(net(self.result, USDC), 1_719_842)

    def test_usde_net_zero(self):
        """USDe пришёл и ушёл поровну — net 0"""
        self.assertEqual(net(self.result, USDE), 0)

    def test_usdt_not_touching_watched_ignored(self):
        """USDT перевод не затрагивает watched — net 0"""
        self.assertEqual(net(self.result, USDT), 0)

    def test_weth_untouched(self):
        self.assertEqual(net(self.result, WETH_ETH), 0)

    def test_gas(self):
        self.assertEqual(self.result['gas_fee_wei'], 0x51e39 * 0xbbda2bd4)

    def test_profit_usd(self):
        """profit = 1.719842 USDC − gas_eth × ETH (с замоканными ценами)"""
        prices = {"usd-coin": 1.0, "ethena-usde": 1.0, "tether": 1.0,
                  "dai": 1.0, "ethereum": 2400.0}
        gas_eth = (0x51e39 * 0xbbda2bd4) / 1e18
        expected = 1.719842 * 1.0 - gas_eth * 2400.0
        profit = self.analyzer.compute_profit_usd(
            self.result['net_by_token'], self.result['gas_fee_wei'], prices)
        self.assertAlmostEqual(profit, expected, places=6)

    def test_profit_usd_none_without_prices(self):
        profit = self.analyzer.compute_profit_usd(
            self.result['net_by_token'], self.result['gas_fee_wei'], {})
        self.assertIsNone(profit)


class TestComputeProfitUsdHelper(unittest.TestCase):
    """Модульная функция compute_profit_usd_for"""

    def test_only_gas_when_no_token_change(self):
        tokens = eth_tokens()
        net_by_token = {t.address: 0 for t in tokens}
        gas_wei = 10 ** 15  # 0.001 ETH
        profit = compute_profit_usd_for(tokens, "ethereum", net_by_token, gas_wei,
                                        {"ethereum": 2000.0})
        self.assertAlmostEqual(profit, -0.001 * 2000.0, places=9)

    def test_missing_token_price_skipped(self):
        tokens = eth_tokens()
        net_by_token = {t.address: 0 for t in tokens}
        net_by_token[normalize_address(USDC)] = 5_000_000  # +5 USDC
        # нет цены USDC, но есть нативная — USDC пропускается, газ учитывается
        profit = compute_profit_usd_for(tokens, "ethereum", net_by_token, 0,
                                        {"ethereum": 2000.0})
        self.assertEqual(profit, 0.0)


# Синтетический блок с тремя транзакциями: две нерелевантные и одна с to=watched
SAMPLE_BLOCK_NUMBER = 0x100
SAMPLE_BLOCK = {
    "number": hex(SAMPLE_BLOCK_NUMBER),
    "transactions": [
        {
            "from": "0x0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a",
            "to": "0x0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a",
            "hash": "0x" + "ab" * 32,
        },
        {
            "from": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "to": None,
            "hash": "0x" + "cd" * 32,
        },
        {
            "from": "0x00000000000000000000000000000000000face0",
            "to": WATCHED_ADDRESS,
            "hash": FAIL_TX_HASH,
        },
    ],
}


class TestAnalyzeBlockMatching(unittest.TestCase):
    """analyze_block находит транзакцию по from/to == watched_address"""

    def test_finds_matching_tx_by_to(self):
        mock_client = MagicMock()
        mock_client.get_transaction_receipt = AsyncMock(return_value=FAIL_RECEIPT)

        analyzer = make_analyzer(eth_client=mock_client)
        result = asyncio.run(analyzer.analyze_block(SAMPLE_BLOCK))

        mock_client.get_transaction_receipt.assert_called_once_with(FAIL_TX_HASH)
        self.assertIsNotNone(result)
        self.assertEqual(result['tx_count'], 1)
        self.assertEqual(result['fail_count'], 1)
        self.assertTrue(result['has_fails'])
        self.assertEqual(result['block_number'], SAMPLE_BLOCK_NUMBER)
        expected_gas = int("0x462ad", 16) * int("0x139cff0", 16)
        self.assertEqual(result['total_gas_wei'], expected_gas)
        self.assertEqual(result['net_by_token'][normalize_address(WETH_CONTRACT)], 0)

    def test_skips_non_matching_txs(self):
        mock_client = MagicMock()
        mock_client.get_transaction_receipt = AsyncMock()

        block_no_match = {
            "number": "0x100",
            "transactions": [
                {
                    "from": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "to": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "hash": "0x" + "11" * 32,
                },
            ],
        }
        analyzer = make_analyzer(eth_client=mock_client)
        result = asyncio.run(analyzer.analyze_block(block_no_match))

        mock_client.get_transaction_receipt.assert_not_called()
        self.assertIsNone(result)

    def test_matches_checksummed_address(self):
        mock_client = MagicMock()
        mock_client.get_transaction_receipt = AsyncMock(return_value=FAIL_RECEIPT)
        analyzer = make_analyzer(eth_client=mock_client)

        block = {
            "number": "0x1",
            "transactions": [
                {
                    "from": "0x000000000000000000000000000000000000dead",
                    "to": WATCHED_ADDRESS.upper().replace("0X", "0x"),
                    "hash": "0x" + "01" * 32,
                },
            ],
        }
        result = asyncio.run(analyzer.analyze_block(block))
        self.assertIsNotNone(result)
        mock_client.get_transaction_receipt.assert_called_once()

    def test_matches_by_from(self):
        mock_client = MagicMock()
        mock_client.get_transaction_receipt = AsyncMock(return_value=FAIL_RECEIPT)
        analyzer = make_analyzer(eth_client=mock_client)

        block = {
            "number": "0x1",
            "transactions": [
                {
                    "from": WATCHED_ADDRESS,
                    "to": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "hash": "0x" + "02" * 32,
                },
            ],
        }
        result = asyncio.run(analyzer.analyze_block(block))
        self.assertIsNotNone(result)
        mock_client.get_transaction_receipt.assert_called_once_with("0x" + "02" * 32)


class TestNormalizeAddress(unittest.TestCase):
    """Тест нормализации адресов"""

    def test_already_normal(self):
        self.assertEqual(
            normalize_address("0x0000000000deadbeef00112233445566778899aa"),
            "0x0000000000deadbeef00112233445566778899aa")

    def test_checksummed(self):
        self.assertEqual(
            normalize_address("0x0000000000DeAdBeEf00112233445566778899aA"),
            "0x0000000000deadbeef00112233445566778899aa")

    def test_short_address_without_padding(self):
        self.assertEqual(
            normalize_address("0xdeadbeef00112233445566778899aa"),
            "0x0000000000deadbeef00112233445566778899aa")

    def test_no_prefix(self):
        self.assertEqual(
            normalize_address("0000000000deadbeef00112233445566778899aa"),
            "0x0000000000deadbeef00112233445566778899aa")

    def test_whitespace(self):
        self.assertEqual(
            normalize_address("  0x0000000000deadbeef00112233445566778899aa  "),
            "0x0000000000deadbeef00112233445566778899aa")


# Синтетический receipt: бот оборачивает/разворачивает нативный токен через
# WMON.deposit()/withdraw() — эти события не эмитят ERC20 Transfer.
WMON_CONTRACT = "0x2020202020202020202020202020202020202020"
MONAD_WATCHED = "0xabababababababababababababababababababab"
MONAD_OTHER_TOKEN = "0x3030303030303030303030303030303030303030"
MONAD_POOL = "0x4040404040404040404040404040404040404040"


def wmon_token():
    return TokenInfo(WMON_CONTRACT, "WMON", 18, "monad", is_wrapped=True)


MONAD_DEPOSIT_WITHDRAW_RECEIPT = {
    "status": "0x1",
    "gasUsed": "0x688b7",
    "effectiveGasPrice": "0x199c82cc00",
    "transactionHash": MONAD_TX_HASH,
    "logs": [
        # Событие пула (не Transfer) — игнор
        {
            "address": MONAD_POOL,
            "topics": [OTHER_EVENT,
                       pad("0x5151515151515151515151515151515151515151"),
                       pad(MONAD_WATCHED)],
            "data": "0x00",
        },
        # Transfer другого токена TO watched — игнор (не WMON)
        {
            "address": MONAD_OTHER_TOKEN,
            "topics": [TRANSFER, pad(MONAD_POOL), pad(MONAD_WATCHED)],
            "data": "0x0000000000000000000000000000000000000000000000000000000010924f98",
        },
        # Transfer другого токена FROM watched — игнор (не WMON)
        {
            "address": MONAD_OTHER_TOKEN,
            "topics": [TRANSFER, pad(MONAD_WATCHED), pad(MONAD_POOL)],
            "data": "0x0000000000000000000000000000000000000000000000000000000010924f98",
        },
        # WMON Deposit(dst=watched) — incoming
        {
            "address": WMON_CONTRACT,
            "topics": [DEPOSIT, pad(MONAD_WATCHED)],
            "data": "0x0000000000000000000000000000000000000000000000001dd86d1937567255",
        },
        # WMON Withdrawal(src=watched) — outgoing
        {
            "address": WMON_CONTRACT,
            "topics": [WITHDRAWAL, pad(MONAD_WATCHED)],
            "data": "0x0000000000000000000000000000000000000000000000001c9f9d48ccc0409b",
        },
    ],
}


class TestParseReceiptDepositWithdrawal(unittest.TestCase):
    """Учёт WMON/WETH Deposit + Withdrawal на watched (native wrap/unwrap)"""

    DEPOSIT_AMOUNT = 0x1dd86d1937567255
    WITHDRAW_AMOUNT = 0x1c9f9d48ccc0409b

    def setUp(self):
        self.analyzer = make_analyzer(tokens=[wmon_token()], watched=MONAD_WATCHED)
        self.result = self.analyzer.parse_receipt(
            MONAD_DEPOSIT_WITHDRAW_RECEIPT,
            MONAD_DEPOSIT_WITHDRAW_RECEIPT['transactionHash'])

    def test_net_is_deposit_minus_withdraw(self):
        self.assertEqual(net(self.result, WMON_CONTRACT),
                         self.DEPOSIT_AMOUNT - self.WITHDRAW_AMOUNT)

    def test_net_is_profit_after_gas(self):
        n = net(self.result, WMON_CONTRACT)
        self.assertGreater(n - self.result['gas_fee_wei'], 0)


class TestParseReceiptIgnoresDepositsOfOthers(unittest.TestCase):
    """Deposit/Withdrawal других адресов на WETH-контракте игнорируются."""

    def test_other_dst_deposit_ignored(self):
        analyzer = make_analyzer(tokens=[wmon_token()], watched=MONAD_WATCHED)
        receipt = {
            "status": "0x1",
            "gasUsed": "0x5208",
            "effectiveGasPrice": "0x3b9aca00",
            "logs": [
                {
                    "address": WMON_CONTRACT,
                    "topics": [DEPOSIT, pad("0x1111111111111111111111111111111111111111")],
                    "data": "0x0000000000000000000000000000000000000000000000000de0b6b3a7640000",
                },
                {
                    "address": WMON_CONTRACT,
                    "topics": [WITHDRAWAL, pad("0x2222222222222222222222222222222222222222")],
                    "data": "0x0000000000000000000000000000000000000000000000000de0b6b3a7640000",
                },
            ],
        }
        result = analyzer.parse_receipt(receipt, "0xfake")
        self.assertEqual(net(result, WMON_CONTRACT), 0)


class TestBaseTokenDoesNotCountDepositWithdrawal(unittest.TestCase):
    """Deposit/Withdrawal учитываются только для wrapped, не для base_tokens."""

    def test_base_token_deposit_ignored(self):
        tokens = [
            TokenInfo(WETH_ETH, "WETH", 18, "ethereum", is_wrapped=True),
            TokenInfo(USDC, "USDC", 6, "usd-coin"),
        ]
        analyzer = make_analyzer(tokens=tokens, watched=ETH_WATCHED)
        receipt = {
            "status": "0x1",
            "gasUsed": "0x5208",
            "effectiveGasPrice": "0x3b9aca00",
            "logs": [
                # Deposit topic на base-токене (USDC) — не должен учитываться
                {
                    "address": USDC,
                    "topics": [DEPOSIT, pad(ETH_WATCHED)],
                    "data": "0x00000000000000000000000000000000000000000000000000000000000f4240",
                },
            ],
        }
        result = analyzer.parse_receipt(receipt, "0xfake")
        self.assertEqual(net(result, USDC), 0)


class TestAnalyzeBlockShortAddress(unittest.TestCase):
    """Адрес без ведущих нулей из RPC должен совпадать"""

    def test_matches_short_to_address(self):
        mock_client = MagicMock()
        mock_client.get_transaction_receipt = AsyncMock(return_value=FAIL_RECEIPT)
        # watched с ведущими нулями; в блоке тот же адрес придёт без них
        analyzer = make_analyzer(eth_client=mock_client,
                                 watched="0x0000000000deadbeef00112233445566778899aa")

        block = {
            "number": "0x1",
            "transactions": [
                {
                    "from": "0x000000000000000000000000000000000000dead",
                    "to": "0xDeAdBeEf00112233445566778899aA",
                    "hash": "0x" + "5a" * 32,
                },
            ],
        }
        result = asyncio.run(analyzer.analyze_block(block))
        self.assertIsNotNone(result)
        mock_client.get_transaction_receipt.assert_called_once_with("0x" + "5a" * 32)


if __name__ == "__main__":
    unittest.main()
