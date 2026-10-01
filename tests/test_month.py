import argparse
import os
import unittest
from unittest.mock import MagicMock, patch

import requests

import month


class MonthTests(unittest.TestCase):
    def session(self, payload):
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value.json.return_value = payload
        return session

    def test_anonymous_query_preserves_interface(self):
        session = self.session({"Perf.1M": "21.21"})
        with patch.dict(os.environ, {}, clear=True), patch.object(month.requests, "Session", return_value=session):
            self.assertEqual(month.get_month_performance(" btc "), 21.21)
        session.cookies.set.assert_not_called()
        session.get.assert_called_once_with(month.url, params=dict(month.params, symbol="GATE:BTCUSDT.P"), timeout=15)
        session.get.return_value.raise_for_status.assert_called_once()

    def test_runtime_config_read_on_each_call_and_scoped(self):
        session = self.session({"Perf.1M": -2})
        with patch.dict(os.environ, {"TRADINGVIEW_COOKIES_JSON": '{"sessionid":"test-value"}'}, clear=True):
            with patch.object(month.requests, "Session", return_value=session):
                self.assertEqual(month.get_month_performance("ETH"), -2)
            self.assertEqual(month.load_cookies(), {"sessionid": "test-value"})
            os.environ["TRADINGVIEW_COOKIES_JSON"] = ""
            self.assertEqual(month.load_cookies(), {})
        session.cookies.set.assert_called_once_with("sessionid", "test-value", domain="scanner.tradingview.com", path="/", secure=True)

    def test_invalid_config_rejected_before_network_without_secret(self):
        cases = ['private-secret', '[]', 'null', '{"sessionid":123}',
                 '{"bad name":"private-secret"}', '{"sessionid":""}',
                 '{"sessionid":"private-secret\\n"}']
        for raw in cases:
            with self.subTest(raw=raw), patch.dict(os.environ, {"TRADINGVIEW_COOKIES_JSON": raw}, clear=True):
                with patch.object(month.requests, "Session") as factory:
                    with self.assertRaises(ValueError) as error:
                        month.get_month_performance("BTC")
                    self.assertNotIn("private-secret", str(error.exception))
                    factory.assert_not_called()

    def test_missing_performance_remains_error(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(month.requests, "Session", return_value=self.session({})):
            with self.assertRaisesRegex(ValueError, "Perf.1M"):
                month.get_month_performance("BTC")

    def test_http_error_propagates(self):
        session = self.session({})
        session.get.return_value.raise_for_status.side_effect = requests.HTTPError("401")
        with patch.dict(os.environ, {}, clear=True), patch.object(month.requests, "Session", return_value=session):
            with self.assertRaises(requests.HTTPError):
                month.get_month_performance("BTC")

    def test_invalid_symbol_rejected_before_network(self):
        with patch.object(month.requests, "Session") as factory:
            with self.assertRaises(argparse.ArgumentTypeError):
                month.get_month_performance("BTC/USDT")
            factory.assert_not_called()

    def test_main_retains_threshold_output(self):
        with patch.object(month, "get_month_performance", return_value=16), patch("builtins.print") as output:
            self.assertEqual(month.main("BTC"), 16)
            self.assertTrue(any("open short" in str(call) for call in output.call_args_list))


if __name__ == "__main__":
    unittest.main()
