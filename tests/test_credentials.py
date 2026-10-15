"""Offline regressions for issue #6; run only in remote CI."""
import hashlib
import hmac
import unittest
from unittest.mock import Mock, patch

import requests

from price_monitor import settings
from price_monitor.clients import gate, supabase as db


class CredentialTests(unittest.TestCase):
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

    def test_transport_auth_and_no_response_body_leak(self):
        for key in ("sb_secret_fake", "legacy.jwt.key"):
            with self.subTest(key=key), patch.object(db, "load_env", return_value={"SUPABASE_URL": "https://example.supabase.co/", "SUPABASE_KEY": key}), \
                    patch.object(db.requests, "request", return_value=Mock(ok=True, content=b"[]", json=lambda: [])) as send:
                db.request("GET", "secret", params={"select": "*"})
                args, kwargs = send.call_args
                self.assertEqual(args, ("GET", "https://example.supabase.co/rest/v1/secret"))
                self.assertEqual(kwargs["params"], {"select": "*"})
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
