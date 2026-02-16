import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tx_analyzer import TxAnalyzer

WATCHED_ADDRESS = "0x0000000000deadbeef00112233445566778899aa"
WETH_CONTRACT = "0x82af49447d8a07e3bd95bd0d56f35241523fbab1"

# Реальный receipt: fail транзакция на Arbitrum
# https://arbiscan.io/tx/0x3b9b86db4a1a8b999c8c933310a67a28488a7d5d4aea22d74c190843b83a6c17
FAIL_RECEIPT = {
    "status": "0x0",
    "logs": [],
    "transactionHash": "0x3b9b86db4a1a8b999c8c933310a67a28488a7d5d4aea22d74c190843b83a6c17",
    "from": "0x0000000000face00000000000000000000cafe00",
    "to": "0x0000000000deadbeef00112233445566778899aa",
    "gasUsed": "0x462ad",
    "effectiveGasPrice": "0x139cff0",
}

# Реальный receipt: успешная транзакция на Arbitrum
# https://arbiscan.io/tx/0xbefc153d4cf017b1579a17af23bb27d543c58cbd37b3b3dd196dc044292f6336
SUCCESS_RECEIPT = {
    "status": "0x1",
    "logs": [
        {
            "address": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
            "topics": [
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                "0x000000000000000000000000389938cf14be379217570d8e4619e51fbdafaa21",
                "0x0000000000000000000000000000000000deadbeef00112233445566778899aa"
            ],
            "data": "0x000000000000000000000000000000000000000000000000008bc909c5707ec5",
        },
        {
            "address": "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9",
            "topics": [
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                "0x000000000000000000000000aa89ba37d1975ae294974ebb33db9d4b5324f2f2",
                "0x000000000000000000000000389938cf14be379217570d8e4619e51fbdafaa21"
            ],
            "data": "0x0000000000000000000000000000000000000000000000000000000004d3ad0c",
        },
        {
            "address": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
            "topics": [
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                "0x0000000000000000000000000000000000deadbeef00112233445566778899aa",
                "0x0000000000000000000000004bfc22a4da7f31f8a912a79a7e44a822398b4390"
            ],
            "data": "0x000000000000000000000000000000000000000000000000008bc612a9452b98",
        },
        {
            "address": "0x4bfc22a4da7f31f8a912a79a7e44a822398b4390",
            "topics": [
                "0x19b47279256b2a23a1665c810c8d55a1758940ee09377d4f8d26497a3577dc83",
                "0x0000000000000000000000000000000000deadbeef00112233445566778899aa",
                "0x000000000000000000000000aa89ba37d1975ae294974ebb33db9d4b5324f2f2"
            ],
            "data": "0x00000000",
        },
    ],
    "transactionHash": "0xbefc153d4cf017b1579a17af23bb27d543c58cbd37b3b3dd196dc044292f6336",
    "from": "0x0000000000face00000000000000000000cafe00",
    "to": "0x0000000000deadbeef00112233445566778899aa",
    "gasUsed": "0x62bad",
    "effectiveGasPrice": "0x1312d00",
}


def make_analyzer() -> TxAnalyzer:
    """Создаёт TxAnalyzer без реального eth_client (для тестов parse_receipt)"""
    return TxAnalyzer(eth_client=None, weth_contract_address=WETH_CONTRACT, watched_address=WATCHED_ADDRESS)


class TestParseReceiptFail(unittest.TestCase):
    """Тесты обработки fail-транзакции (реальные данные Arbitrum)"""

    def setUp(self):
        self.analyzer = make_analyzer()
        self.result = self.analyzer.parse_receipt(FAIL_RECEIPT, FAIL_RECEIPT['transactionHash'])

    def test_status_is_zero(self):
        self.assertEqual(self.result['status'], 0)

    def test_no_incoming(self):
        self.assertEqual(self.result['incoming_wei'], [])

    def test_no_outgoing(self):
        self.assertEqual(self.result['outgoing_wei'], [])

    def test_gas_fee_calculated(self):
        expected_gas = int("0x462ad", 16) * int("0x139cff0", 16)
        self.assertEqual(self.result['gas_fee_wei'], expected_gas)
        self.assertGreater(self.result['gas_fee_wei'], 0)

    def test_tx_hash(self):
        self.assertEqual(self.result['tx_hash'], FAIL_RECEIPT['transactionHash'])

    def test_net_loss_equals_gas(self):
        """Для fail-транзакции убыток = стоимость gas"""
        net = sum(self.result['incoming_wei']) - sum(self.result['outgoing_wei']) - self.result['gas_fee_wei']
        self.assertEqual(net, -self.result['gas_fee_wei'])


class TestParseReceiptSuccess(unittest.TestCase):
    """Тесты обработки успешной транзакции (реальные данные Arbitrum)"""

    def setUp(self):
        self.analyzer = make_analyzer()
        self.result = self.analyzer.parse_receipt(SUCCESS_RECEIPT, SUCCESS_RECEIPT['transactionHash'])

    def test_status_is_one(self):
        self.assertEqual(self.result['status'], 1)

    def test_incoming_weth(self):
        """WETH Transfer TO watched address (log 0)"""
        expected = int("0x008bc909c5707ec5", 16)
        self.assertEqual(self.result['incoming_wei'], [expected])

    def test_outgoing_weth(self):
        """WETH Transfer FROM watched address (log 2)"""
        expected = int("0x008bc612a9452b98", 16)
        self.assertEqual(self.result['outgoing_wei'], [expected])

    def test_ignores_non_weth_logs(self):
        """Не-WETH логи (USDT, pool events) должны быть проигнорированы"""
        total_transfers = len(self.result['incoming_wei']) + len(self.result['outgoing_wei'])
        self.assertEqual(total_transfers, 2)  # только 2 WETH Transfer-а

    def test_gas_fee_calculated(self):
        expected_gas = int("0x62bad", 16) * int("0x1312d00", 16)
        self.assertEqual(self.result['gas_fee_wei'], expected_gas)

    def test_net_change(self):
        """Spread положительный, но gas делает итог отрицательным"""
        incoming = sum(self.result['incoming_wei'])
        outgoing = sum(self.result['outgoing_wei'])
        spread = incoming - outgoing
        self.assertGreater(spread, 0)  # spread положительный
        net = spread - self.result['gas_fee_wei']
        self.assertLess(net, 0)  # но gas съедает прибыль

    def test_tx_hash(self):
        self.assertEqual(self.result['tx_hash'], SUCCESS_RECEIPT['transactionHash'])


class TestParseReceiptIgnoresOtherTokens(unittest.TestCase):
    """Тест: логи других контрактов не учитываются"""

    def test_only_weth_transfers_counted(self):
        analyzer = make_analyzer()
        receipt = {
            "status": "0x1",
            "gasUsed": "0x5208",
            "effectiveGasPrice": "0x3b9aca00",
            "logs": [
                {
                    "address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "topics": [
                        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                        "0x0000000000000000000000000000000000deadbeef00112233445566778899aa",
                        "0x0000000000000000000000001111111111111111111111111111111111111111"
                    ],
                    "data": "0x0000000000000000000000000000000000000000000000000de0b6b3a7640000",
                },
            ],
        }
        result = analyzer.parse_receipt(receipt, "0xfake")
        self.assertEqual(result['status'], 1)
        self.assertEqual(result['tx_hash'], "0xfake")
        self.assertEqual(result['incoming_wei'], [])
        self.assertEqual(result['outgoing_wei'], [])


# Реальный блок 432537070 (0x19c7fdee) на Arbitrum
# Содержит fail-транзакцию 0x3b9b86... с to=watched_address
BLOCK_432537070 = {
    "number": "0x19c7fdee",
    "transactions": [
        # TX[0] — не наша, должна быть пропущена
        {
            "from": "0x00000000000000000000000000000000000a4b05",
            "to": "0x00000000000000000000000000000000000a4b05",
            "hash": "0x4d645eec5e866d53a3758e0c20a35f615c1788c4b94db134d3f7847ee1aea880",
        },
        # TX[1] — не наша, to=None (contract creation)
        {
            "from": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "to": None,
            "hash": "0x1111111111111111111111111111111111111111111111111111111111111111",
        },
        # TX[2] — наша fail-транзакция (to == watched_address)
        {
            "from": "0x0000000000face00000000000000000000cafe00",
            "to": "0x0000000000DeAdBeEf00112233445566778899aA",  # checksummed, как в реальном блоке
            "hash": "0x3b9b86db4a1a8b999c8c933310a67a28488a7d5d4aea22d74c190843b83a6c17",
        },
    ],
}


class TestAnalyzeBlockMatching(unittest.TestCase):
    """Тест: analyze_block находит транзакцию по условию from/to == watched_address"""

    def test_finds_matching_tx_by_to(self):
        """Транзакция с to=watched_address должна быть обработана"""
        mock_client = MagicMock()
        mock_client.get_transaction_receipt = AsyncMock(return_value=FAIL_RECEIPT)

        analyzer = TxAnalyzer(mock_client, WETH_CONTRACT, WATCHED_ADDRESS)
        result = asyncio.run(analyzer.analyze_block(BLOCK_432537070))

        # receipt запрошен ровно 1 раз — только для matching транзакции
        mock_client.get_transaction_receipt.assert_called_once_with(
            "0x3b9b86db4a1a8b999c8c933310a67a28488a7d5d4aea22d74c190843b83a6c17"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['tx_count'], 1)
        self.assertEqual(result['fail_count'], 1)
        self.assertTrue(result['has_fails'])
        self.assertEqual(result['block_number'], 432537070)
        # Убыток = газ, т.к. fail-транзакция: incoming=0, outgoing=0
        expected_gas = int("0x462ad", 16) * int("0x139cff0", 16)  # 5_921_252_487_120 wei
        self.assertEqual(result['total_gas_wei'], expected_gas)
        self.assertEqual(result['net_wei_change'], -expected_gas)

    def test_skips_non_matching_txs(self):
        """Транзакции без watched_address в from/to не вызывают get_transaction_receipt"""
        mock_client = MagicMock()
        mock_client.get_transaction_receipt = AsyncMock()

        block_no_match = {
            "number": "0x19c7fdee",
            "transactions": [
                {
                    "from": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "to": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "hash": "0x1111",
                },
            ],
        }
        analyzer = TxAnalyzer(mock_client, WETH_CONTRACT, WATCHED_ADDRESS)
        result = asyncio.run(analyzer.analyze_block(block_no_match))

        mock_client.get_transaction_receipt.assert_not_called()
        self.assertIsNone(result)

    def test_matches_checksummed_address(self):
        """Адрес в checksummed формате (mixed case) должен совпадать"""
        mock_client = MagicMock()
        mock_client.get_transaction_receipt = AsyncMock(return_value=FAIL_RECEIPT)

        # watched_address в lowercase, в блоке — checksummed
        analyzer = TxAnalyzer(mock_client, WETH_CONTRACT, WATCHED_ADDRESS)

        block = {
            "number": "0x1",
            "transactions": [
                {
                    "from": "0xdeadbeef",
                    "to": "0x0000000000DeAdBeEf00112233445566778899aA",  # checksummed
                    "hash": "0xabc",
                },
            ],
        }
        result = asyncio.run(analyzer.analyze_block(block))
        self.assertIsNotNone(result)
        mock_client.get_transaction_receipt.assert_called_once()

    def test_matches_by_from(self):
        """Транзакция с from=watched_address тоже должна обрабатываться"""
        mock_client = MagicMock()
        mock_client.get_transaction_receipt = AsyncMock(return_value=FAIL_RECEIPT)

        analyzer = TxAnalyzer(mock_client, WETH_CONTRACT, WATCHED_ADDRESS)

        block = {
            "number": "0x1",
            "transactions": [
                {
                    "from": "0x0000000000DeAdBeEf00112233445566778899aA",
                    "to": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "hash": "0xdef",
                },
            ],
        }
        result = asyncio.run(analyzer.analyze_block(block))
        self.assertIsNotNone(result)
        mock_client.get_transaction_receipt.assert_called_once_with("0xdef")


if __name__ == "__main__":
    unittest.main()
