import base64
import unittest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ws_connector import WsConnectorRaw
from main import parse_ws_rpc


class TestParseWsRpc(unittest.TestCase):
    """Конфиг ws_rpc_url поддерживает плоскую строку и dict с login/password"""

    def test_plain_string(self):
        url, login, password = parse_ws_rpc('ws://host:8550')
        self.assertEqual(url, 'ws://host:8550')
        self.assertIsNone(login)
        self.assertIsNone(password)

    def test_dict_with_auth(self):
        cfg = {'url': 'ws://host:8549', 'login': 'monadnode', 'password': 'secret'}
        url, login, password = parse_ws_rpc(cfg)
        self.assertEqual(url, 'ws://host:8549')
        self.assertEqual(login, 'monadnode')
        self.assertEqual(password, 'secret')

    def test_dict_without_auth(self):
        cfg = {'url': 'ws://host:8549'}
        url, login, password = parse_ws_rpc(cfg)
        self.assertEqual(url, 'ws://host:8549')
        self.assertIsNone(login)
        self.assertIsNone(password)

    def test_none(self):
        url, login, password = parse_ws_rpc(None)
        self.assertIsNone(url)
        self.assertIsNone(login)
        self.assertIsNone(password)

    def test_invalid_type(self):
        with self.assertRaises(ValueError):
            parse_ws_rpc(42)


class TestWsConnectorAuthHeaders(unittest.TestCase):
    """Basic-Auth заголовок собирается только при заданных login/password"""

    def test_no_auth_when_credentials_missing(self):
        c = WsConnectorRaw('ws://host:8549')
        self.assertIsNone(c._build_auth_headers())

    def test_no_auth_when_only_login(self):
        c = WsConnectorRaw('ws://host:8549', login='user')
        self.assertIsNone(c._build_auth_headers())

    def test_no_auth_when_only_password(self):
        c = WsConnectorRaw('ws://host:8549', password='pass')
        self.assertIsNone(c._build_auth_headers())

    def test_auth_header_is_basic_base64(self):
        c = WsConnectorRaw('ws://host:8549', login='monadnode', password='0yQikOz74jpC1T9d0kLD')
        headers = c._build_auth_headers()
        self.assertIsNotNone(headers)
        self.assertEqual(len(headers), 1)
        name, value = headers[0]
        self.assertEqual(name, 'Authorization')
        expected_token = base64.b64encode(b'monadnode:0yQikOz74jpC1T9d0kLD').decode('ascii')
        self.assertEqual(value, f'Basic {expected_token}')

    def test_auth_header_handles_unicode(self):
        c = WsConnectorRaw('ws://host:8549', login='пользователь', password='парольХ')
        headers = c._build_auth_headers()
        name, value = headers[0]
        self.assertEqual(name, 'Authorization')
        expected_token = base64.b64encode('пользователь:парольХ'.encode('utf-8')).decode('ascii')
        self.assertEqual(value, f'Basic {expected_token}')


class TestWsConnectorLogPrefix(unittest.TestCase):
    """Префикс с именем бота добавляется в логи, когда name задан"""

    def test_prefix_with_name(self):
        c = WsConnectorRaw('ws://host:8549', name='monad')
        self.assertEqual(c._log_prefix(), '[monad] ')

    def test_prefix_without_name(self):
        c = WsConnectorRaw('ws://host:8549')
        self.assertEqual(c._log_prefix(), '')

    def test_prefix_none_name(self):
        c = WsConnectorRaw('ws://host:8549', name=None)
        self.assertEqual(c._log_prefix(), '')


if __name__ == "__main__":
    unittest.main()
