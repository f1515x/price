"""Offline credential migration regressions; run only in remote CI."""
import hashlib
import hmac
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from price_monitor import settings
from price_monitor.clients import gate, infisical, supabase as db


CONFIG = {
    "INFISICAL_CLIENT_ID": "client-id", "INFISICAL_CLIENT_SECRET": "client-secret",
    "INFISICAL_PROJECT_ID": "project-id", "INFISICAL_ENV": "prod",
}


def response(data, status=200):
    return Mock(status_code=status, json=Mock(return_value=data), text="sensitive-response")


def success():
    return [response({"accessToken": "test-token"}),
            response({"secret": {"secretValue": ' "remote-key" '}}),
            response({"secret": {"secretValue": "'remote-secret'"}})]


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = patch.object(settings, "ROOT_DIR", Path(self.directory.name))
        root.start()
        self.addCleanup(root.stop)
        env = patch.dict(os.environ, CONFIG, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_infisical_credentials_used_for_unchanged_gate_signature(self):
        Path(self.directory.name, ".env").write_text("API_KEY=old-key\nAPI_SECRET=old-secret\n")
        with patch.object(infisical.requests, "request", side_effect=success()) as send, \
                patch.object(db, "request", side_effect=AssertionError("old database called")), \
                patch.object(gate.time, "time", return_value=123):
            headers = gate.gen_sign("GET", "/api/v4/unified/accounts", "")
        message = "GET\n/api/v4/unified/accounts\n\n" + hashlib.sha512(b"").hexdigest() + "\n123"
        self.assertEqual(headers["KEY"], "remote-key")
        self.assertEqual(headers["SIGN"], hmac.new(b"remote-secret", message.encode(), hashlib.sha512).hexdigest())
        self.assertEqual(send.call_count, 3)
        calls = send.call_args_list
        self.assertEqual(calls[0].args, ("POST", "https://us.infisical.com/api/v1/auth/universal-auth/login"))
        self.assertEqual(calls[0].kwargs["json"], {"clientId": "client-id", "clientSecret": "client-secret"})
        for call, name in zip(calls[1:], ("GATE_API_KEY", "GATE_API_SECRET")):
            self.assertEqual(call.args, ("GET", "https://us.infisical.com/api/v4/secrets/" + name))
            self.assertEqual(call.kwargs["headers"], {"Authorization": "Bearer test-token"})
            self.assertEqual(call.kwargs["params"], {"projectId": "project-id", "environment": "prod", "secretPath": "/", "type": "shared"})
        for call in calls:
            self.assertEqual(call.kwargs["timeout"], 20)
            self.assertIs(call.kwargs["allow_redirects"], False)

    def test_missing_or_empty_configuration_fails_before_network(self):
        for name in CONFIG:
            for value in (None, " "):
                env = dict(CONFIG)
                if value is None:
                    del env[name]
                else:
                    env[name] = value
                with self.subTest(name=name, value=value), patch.dict(os.environ, env, clear=True), \
                        patch.object(infisical.requests, "request") as send:
                    with self.assertRaisesRegex(RuntimeError, name):
                        settings.credentials()
                    send.assert_not_called()

    def test_dotenv_aliases_and_process_precedence(self):
        config = "\n".join(f"{k}={v}" for k, v in CONFIG.items() if k != "INFISICAL_ENV")
        Path(self.directory.name, ".env").write_text(config + "\nINFISICAL_ENVIRONMENT=file-env\nINFISICAL_URL=https://vault.example\nINFISICAL_SECRET_PATH=/gate\nAPI_KEY=ignored\n")
        for overrides, expected in (({}, "file-env"), ({"INFISICAL_ENV": "env-prod"}, "env-prod"),
                                    ({"INFISICAL_ENVIRONMENT": "env-alias"}, "env-alias"),
                                    ({"INFISICAL_ENV": "canonical", "INFISICAL_ENVIRONMENT": "alias"}, "canonical")):
            with self.subTest(overrides=overrides), patch.dict(os.environ, overrides, clear=True), \
                    patch.object(infisical.requests, "request", side_effect=success()) as send:
                self.assertEqual(settings.credentials(), ("remote-key", "remote-secret"))
                self.assertTrue(send.call_args.args[1].startswith("https://vault.example/api/"))
                self.assertEqual(send.call_args.kwargs["params"]["environment"], expected)
                self.assertEqual(send.call_args.kwargs["params"]["secretPath"], "/gate")
                self.assertNotIn("API_KEY", settings.load_env(keys=infisical.CONFIG_KEYS))
        # An environment alias also overrides a canonical name in the file.
        with Path(self.directory.name, ".env").open("a") as file:
            file.write("INFISICAL_ENV=file-canonical\n")
        with patch.dict(os.environ, {"INFISICAL_ENVIRONMENT": "env-alias"}, clear=True), \
                patch.object(infisical.requests, "request", side_effect=success()) as send:
            settings.credentials()
            self.assertEqual(send.call_args.kwargs["params"]["environment"], "env-alias")

    def test_invalid_endpoint_or_path_is_rejected_without_echo(self):
        for overrides in ({"INFISICAL_URL": "https://user:sensitive@vault.example"},
                          {"INFISICAL_URL": "https://vault.example?token=sensitive"},
                          {"INFISICAL_URL": "invalid-sensitive"},
                          {"INFISICAL_SECRET_PATH": "sensitive"}):
            with self.subTest(overrides=overrides), patch.dict(os.environ, overrides), \
                    patch.object(infisical.requests, "request") as send:
                with self.assertRaises(RuntimeError) as error:
                    settings.credentials()
                self.assertNotIn("sensitive", str(error.exception))
                send.assert_not_called()

    def test_failures_never_fallback_or_expose_sensitive_values(self):
        Path(self.directory.name, ".env").write_text("API_KEY=old-key\nAPI_SECRET=old-secret\nSUPABASE_URL=https://old.example\nSUPABASE_KEY=old-db\n")
        os.environ.update({"API_KEY": "old-env-key", "API_SECRET": "old-env-secret"})
        failures = [response({}, status) for status in (302, 401, 403, 404, 500)]
        failures += [requests.Timeout("sensitive-timeout"), requests.ConnectionError("sensitive-connection"),
                     response({}), response([]), response({"accessToken": 123}),
                     response({"accessToken": " "}), response({"accessToken": "sensitive\nvalue"}),
                     Mock(status_code=200, json=Mock(side_effect=ValueError("sensitive-json")))]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(infisical.requests, "request", side_effect=[failure]), \
                    patch.object(db, "request", side_effect=AssertionError("old database called")):
                with self.assertRaises(RuntimeError) as error:
                    settings.credentials()
                self.assertNotIn("sensitive", str(error.exception))
                self.assertTrue(error.exception.__suppress_context__ or error.exception.__context__ is None)

    def test_secret_responses_and_values_are_validated_for_both_secrets(self):
        malformed = [[], {}, {"secret": []}, {"secret": {"secretValueHidden": True, "secretValue": "masked"}}]
        malformed += [{"secret": {"secretValue": v}} for v in (None, 123, "", " ", "''", '" "', "x" * 4097, "sensitive\nvalue", "sensitive\rvalue", "sensitive\0value")]
        failures = [response(data) for data in malformed]
        failures += [response({}, status) for status in (401, 403, 404, 500)]
        failures += [requests.Timeout("sensitive"), requests.ConnectionError("sensitive"),
                     Mock(status_code=200, json=Mock(side_effect=ValueError("sensitive-json")))]
        for index in (1, 2):
            for failure in failures:
                replies = success()[:index] + [failure]
                with self.subTest(index=index, failure=type(failure).__name__), \
                        patch.object(infisical.requests, "request", side_effect=replies):
                    with self.assertRaises(RuntimeError) as error:
                        settings.credentials()
                    self.assertNotIn("sensitive", str(error.exception))

    def test_new_authentication_each_call_without_persistent_token(self):
        with patch.object(infisical.requests, "request", side_effect=success() + success()) as send:
            settings.credentials()
            settings.credentials()
            self.assertEqual([c.args[0] for c in send.call_args_list], ["POST", "GET", "GET"] * 2)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])


class SupabaseTransportTests(unittest.TestCase):
    def test_existing_supabase_rest_helper_is_preserved(self):
        for key in ("sb_secret_fake", "legacy.jwt.key"):
            with self.subTest(key=key), patch.object(db, "load_env", return_value={"SUPABASE_URL": "https://example.supabase.co/", "SUPABASE_KEY": key}), \
                    patch.object(db.requests, "request", return_value=Mock(ok=True, content=b"[]", json=lambda: [])) as send:
                self.assertEqual(db.request("GET", "orders", params={"select": "*"}), [])
                self.assertEqual(send.call_args.args, ("GET", "https://example.supabase.co/rest/v1/orders"))
                self.assertEqual("Authorization" in send.call_args.kwargs["headers"], key == "legacy.jwt.key")
                send.return_value = Mock(ok=False, status_code=403, text="sensitive")
                with self.assertRaisesRegex(RuntimeError, "HTTP 403") as error:
                    db.request("GET", "orders")
                self.assertNotIn("sensitive", str(error.exception))
                send.side_effect = requests.ConnectionError("sensitive")
                with self.assertRaises(RuntimeError) as error:
                    db.request("GET", "orders")
                self.assertNotIn("sensitive", str(error.exception))

    def test_user_token_and_orders3_config_alias(self):
        with patch.object(db, "load_env", return_value={"SUPABASE_URL": "https://example.supabase.co/rest/v1", "SUPABASE_ANON_KEY": "sb_publishable_fake", "SUPABASE_ACCESS_TOKEN": "user-token"}), \
                patch.object(db.requests, "request", return_value=Mock(ok=True, content=b"[]", json=lambda: [])) as send:
            db.request("GET", "orders")
            self.assertEqual(send.call_args.kwargs["headers"]["Authorization"], "Bearer user-token")
            self.assertEqual(send.call_args.args[1], "https://example.supabase.co/rest/v1/orders")
