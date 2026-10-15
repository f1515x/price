"""Gate public metadata regressions; run only in remote CI."""
import contextlib
from decimal import Decimal
import io
import unittest
from unittest.mock import Mock, patch

import requests

from price_monitor.clients import gate, supabase as storage
from price_monitor.market import precision
from price_monitor.risk import sizing


BTC = {"name": "BTC_USDT", "quanto_multiplier": "0.00010000",
       "order_price_round": "0.2500", "leverage_max": "100"}


class GateContractTests(unittest.TestCase):
    def test_metadata_uses_public_gate_without_database_or_signature(self):
        session = Mock()
        session.get.return_value.json.return_value = BTC
        with patch.object(storage, "request", side_effect=AssertionError("unexpected database access")), \
                patch.object(gate, "credentials", side_effect=AssertionError("unexpected credentials")):
            self.assertEqual(gate.get_contract_info("btc", session), BTC)
            self.assertEqual(gate.get_max_leverage(session, "BTC_USDT"), 100)
        session.get.assert_called_with(
            "https://api.gateio.ws/api/v4/futures/usdt/contracts/BTC_USDT",
            headers={"Accept": "application/json"}, timeout=15,
        )
        session.close.assert_not_called()

    def test_invalid_metadata_is_rejected(self):
        invalid = [None, [], {**BTC, "name": "ETH_USDT"},
                   *({**BTC, field: value}
                     for field in ("quanto_multiplier", "order_price_round", "leverage_max")
                     for value in (None, 0.25, "NaN", "Infinity", "0", "-1", "bad")),
                   {**BTC, "leverage_max": "1.5"}]
        session = Mock()
        for data in invalid:
            with self.subTest(data=data):
                session.get.return_value.json.return_value = data
                with self.assertRaises(RuntimeError):
                    gate.get_contract_info("BTC", session)

    def test_owned_session_closes_on_network_or_json_failure(self):
        for error in (requests.ConnectionError("offline"), ValueError("invalid JSON")):
            with self.subTest(error=error), patch.object(gate.requests, "Session") as factory:
                if isinstance(error, requests.RequestException):
                    factory.return_value.get.side_effect = error
                else:
                    factory.return_value.get.return_value.json.side_effect = error
                with self.assertRaises(RuntimeError):
                    gate.get_contract_info("BTC")
                factory.return_value.close.assert_called_once_with()

    def test_real_tick_rounding_and_quantity_use_same_price(self):
        response = Mock()
        response.json.return_value = {**BTC, "quanto_multiplier": "1"}
        with patch.object(storage, "request", side_effect=AssertionError("unexpected database access")), \
                patch.object(gate.requests.Session, "get", return_value=response):
            self.assertEqual(sizing.get_price_step("BTC"), Decimal("0.2500"))
            self.assertEqual(sizing.getquanto_multiplier("BTC"), "1")
            for action, count in (("Open Long", 10), ("Open Short", -10)):
                with patch.object(sizing, "_get_price_and_action", return_value=(10.24, action)), \
                        patch.object(sizing, "amount", return_value=100), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(sizing.size("BTC"), count)
                    self.assertIn("10.0000 USDT", output.getvalue())

    def test_price_precision_does_not_write_to_database(self):
        session = Mock()
        session.get.return_value.json.return_value = {
            "last_price": "1.2300", "mark_price": "1.23", "index_price": "1.230",
        }
        with patch.object(storage, "request", side_effect=AssertionError("unexpected database access")):
            result = precision.get_price_precision("BTC", session)
        self.assertEqual(result["last_price"]["step"], Decimal("0.0001"))


if __name__ == "__main__":
    unittest.main()
