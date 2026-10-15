"""Offline regressions for issue #6; run only in remote CI."""
import contextlib
from decimal import Decimal
import hashlib
import hmac
import io
import unittest
from unittest.mock import Mock, patch

import requests

from price_monitor import settings
from price_monitor.clients import gate, supabase as db
from price_monitor.market import precision
from price_monitor.risk import sizing


BTC = {"contract": "BTC_USDT", "quanto_multiplier": "0.00010000",
       "order_price_round": "0.2500", "leverage_max": "100"}
ETH = {"contract": "ETH_USDT", "quanto_multiplier": "0.0100",
       "order_price_round": "0.05", "leverage_max": "50"}


class StorageTests(unittest.TestCase):
    def test_database_credentials_are_used_for_signature_even_with_env_credentials(self):
        with patch.object(settings, "load_env", return_value={"API_KEY": "ignored", "API_SECRET": "ignored"}), \
                patch.object(db, "request", return_value=[{"API_KEY=": ' "db-key" ', "API_SECRET=": "'db-secret'"}]), \
                patch.object(gate.time, "time", return_value=123):
            headers = gate.gen_sign("GET", "/api/v4/unified/accounts", "")
        message = "GET\n/api/v4/unified/accounts\n\n" + hashlib.sha512(b"").hexdigest() + "\n123"
        self.assertEqual(headers["KEY"], "db-key")
        self.assertEqual(headers["SIGN"], hmac.new(b"db-secret", message.encode(), hashlib.sha512).hexdigest())

    def test_credentials_fail_closed_without_exposing_values(self):
        for rows in ([], [{}, {}], {}, [{"API_KEY=": "key"}],
                     [{"API_KEY=": "key", "API_SECRET=": "sensitive\nvalue"}],
                     [{"API_KEY=": "key", "API_SECRET=": 123}]):
            with self.subTest(rows=rows), patch.object(db, "request", return_value=rows):
                with self.assertRaises(RuntimeError) as error:
                    settings.credentials()
                self.assertNotIn("sensitive", str(error.exception))

    def test_transport_auth_upsert_and_no_response_body_leak(self):
        for key in ("sb_secret_fake", "legacy.jwt.key"):
            with self.subTest(key=key), patch.object(db, "load_env", return_value={"SUPABASE_URL": "https://example.supabase.co/", "SUPABASE_KEY": key}), \
                    patch.object(db.requests, "request", return_value=Mock(ok=True, content=b"")) as send:
                db.save_contract("btc", BTC)
                args, kwargs = send.call_args
                self.assertEqual(args, ("POST", "https://example.supabase.co/rest/v1/contracts"))
                self.assertEqual(kwargs["params"], {"on_conflict": "contract"})
                self.assertEqual(kwargs["json"], BTC)
                self.assertEqual(kwargs["headers"]["Prefer"], "resolution=merge-duplicates,return=minimal")
                self.assertEqual("Authorization" in kwargs["headers"], key == "legacy.jwt.key")
                send.return_value = Mock(ok=False, status_code=403, text="sensitive")
                with self.assertRaisesRegex(RuntimeError, "HTTP 403") as error:
                    db.load_credentials()
                self.assertNotIn("sensitive", str(error.exception))
                send.side_effect = requests.ConnectionError("sensitive")
                with self.assertRaises(RuntimeError) as error:
                    db.load_credentials()
                self.assertNotIn("sensitive", str(error.exception))

    def test_user_token_and_orders3_config_alias(self):
        with patch.object(db, "load_env", return_value={"SUPABASE_URL": "https://example.supabase.co/rest/v1", "SUPABASE_ANON_KEY": "sb_publishable_fake", "SUPABASE_ACCESS_TOKEN": "user-token"}), \
                patch.object(db.requests, "request", return_value=Mock(ok=True, content=b"[]", json=lambda: [])) as send:
            db.request("GET", "secret")
            self.assertEqual(send.call_args.kwargs["headers"]["Authorization"], "Bearer user-token")
            self.assertEqual(send.call_args.args[1], "https://example.supabase.co/rest/v1/secret")

    def test_refresh_overwrites_only_matching_contract_with_exact_strings(self):
        records = {"ETH_USDT": ETH.copy()}
        def transport(method, table, *, params=None, data=None):
            if method == "POST":
                records[data["contract"]] = dict(data)
            else:
                return [records[params["contract"].removeprefix("eq.")]]
        with patch.object(db, "request", side_effect=transport):
            db.save_contract("BTC", BTC)
            db.save_contract("BTC", {**BTC, "quanto_multiplier": "0.000000000000000000000000000123400"})
            self.assertEqual(db.load_contract("BTC")["quanto_multiplier"], "0.000000000000000000000000000123400")
            self.assertEqual(sizing.getquanto_multiplier("ETH"), "0.0100")
            self.assertEqual(sizing.get_price_step("BTC"), Decimal("0.2500"))
            self.assertEqual(gate.get_max_leverage(Mock(), "ETH"), 50)
        self.assertEqual(records["ETH_USDT"], ETH)

    def test_invalid_contract_records_do_not_write(self):
        for row in ({**BTC, "contract": "ETH_USDT"},
                    *({**BTC, field: value} for field in ("quanto_multiplier", "order_price_round", "leverage_max")
                      for value in (None, 0.25, "NaN", "Infinity", "0", "-1"))):
            with self.subTest(row=row), patch.object(db, "request") as send:
                with self.assertRaises(RuntimeError):
                    db.save_contract("BTC", row)
                send.assert_not_called()
        for rows in ([], [BTC, BTC], [ETH]):
            with patch.object(db, "request", return_value=rows), self.assertRaises(RuntimeError):
                db.load_contract("BTC")

    def test_precision_storage_failure_stops_command(self):
        response = Mock()
        response.json.return_value = {"name": "BTC_USDT", "last_price": "10", "mark_price": "10", "index_price": "10", **BTC}
        with patch.object(precision.requests.Session, "get", return_value=response), \
                patch.object(db, "request", side_effect=RuntimeError("write failed")):
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                precision.get_price_precision("BTC")

    def test_real_tick_rounding_and_quantity_use_same_price(self):
        for action, count in (("Open Long", 10), ("Open Short", -10)):
            with patch.object(db, "load_contract", return_value=BTC), \
                    patch.object(sizing, "load_contract", return_value={**BTC, "quanto_multiplier": "1"}), \
                    patch.object(sizing, "_get_price_and_action", return_value=(10.24, action)), \
                    patch.object(sizing, "amount", return_value=100), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(sizing.size("BTC"), count)
                self.assertIn("10.0000 USDT", output.getvalue())
