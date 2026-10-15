import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sizes_upload", ROOT / "supabase.py")
upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload)


def order(contract="BTC_USDT", side="Open Long", amount="348", value="142.42"):
    return f"""🚀 ====== Order Alert ======
✨  contract            : {contract}
💰  activation_price    : 4087.850000000000001 USDT
📈  side                : {side}
📦  amount              : {amount} Contracts
📦  value               : {value} U
   ======================
"""


class SizesUploadTests(unittest.TestCase):
    def test_multiple_orders_share_report_timestamp_and_preserve_precision(self):
        rows = upload.parse_sizes(order() + order("ETH_USDT", "Open Short", "-4", "-10.2")
                                  + "\nTimestamp: 1791169976034 \n")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["activation_price"], "4087.850000000000001")
        self.assertEqual(rows[1]["amount"], -4)
        self.assertEqual(rows[1]["value"], "-10.2")
        self.assertTrue(all(row["timestamp"] == 1791169976034 for row in rows))

    def test_optional_timestamp_and_no_signals(self):
        self.assertIsNone(upload.parse_sizes(order())[0]["timestamp"])
        for text in ("", "\n", "none\n"):
            with self.subTest(text=text):
                self.assertEqual(upload.parse_sizes(text), [])

    def test_timestamp_only_report_preserves_timestamp_with_null_order_fields(self):
        expected = [{"contract": None, "activation_price": None, "side": None,
                     "amount": None, "value": None, "timestamp": 1791569579832}]
        for text in ("Timestamp: 1791569579832", "none\n\nTimestamp: 1791569579832 \n"):
            with self.subTest(text=text):
                self.assertEqual(upload.parse_sizes(text), expected)

    def test_corrupt_report_never_partially_uploads(self):
        invalid = [order().replace("348 Contracts", "1.2 Contracts"),
                   order().replace("4087.850000000000001 USDT", "NaN USDT"),
                   order(side="Open Short"),
                   order().replace("   ======================", ""),
                   order().replace("📦  value               : 142.42 U\n", ""),
                   order() + "执行失败: timeout",
                   order() + "Timestamp: 1\n" + order(),
                   "Timestamp: invalid", "Timestamp: 1\nTimestamp: 2",
                   "Timestamp: 1\n执行失败: timeout"]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError):
                upload.parse_sizes(text)

    def test_cli_default_uploads_real_report_in_one_batch(self):
        with patch.object(upload, "supabase") as send, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(upload.main([]), 0)
        self.assertEqual(send.call_args.args[0], upload.parse_sizes(
            (ROOT / "reports" / "sizes.txt").read_text(encoding="utf-8-sig")))

    def test_dry_run_and_empty_report_do_not_connect(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sizes.txt"
            for text, options in ((order(), ["--dry-run"]),
                                  ("Timestamp: 1", ["--dry-run"]), ("", []), ("none", [])):
                path.write_text(text, encoding="utf-8-sig")
                with patch.object(upload, "supabase") as send, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(upload.main(["--sizes-file", str(path), *options]), 0)
                    send.assert_not_called()

    def test_cli_timestamp_only_report_clears_table_then_inserts_null_fields(self):
        rows = [{"contract": None, "activation_price": None, "side": None,
                 "amount": None, "value": None, "timestamp": 1791569579832}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sizes.txt"
            path.write_text("\nTimestamp: 1791569579832 \n", encoding="utf-8-sig")
            with patch.object(upload, "load_config", return_value={
                "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "sb_secret_mock",
            }), patch.object(upload, "request_json", side_effect=[(204, None), (201, None)]) as request, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(upload.main(["--sizes-file", str(path), "--minimal"]), 0)
        endpoint = "https://example.supabase.co/rest/v1/orders"
        self.assertEqual(request.call_args_list, [
            call(endpoint + "?or=(contract.is.null,contract.not.is.null)",
                 "sb_secret_mock", token=None, minimal=True, method="DELETE"),
            call(endpoint, "sb_secret_mock", data=[{**rows[0], "quanto_multiplier": None, "order_price_round": None}], token=None, minimal=True),
        ])

    @patch.object(upload, "attach_contract_parameters", side_effect=lambda data, *args: data)
    def test_bulk_write_clears_table_before_insert(self, enrich):
        rows = upload.parse_sizes(order())
        with patch.object(upload, "load_config", return_value={
            "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "sb_secret_mock",
        }), patch.object(upload, "request_json", return_value=(201, rows)) as request, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(upload.supabase(rows, minimal=True), rows)
        endpoint = "https://example.supabase.co/rest/v1/orders"
        self.assertEqual(request.call_args_list, [
            call(endpoint + "?or=(contract.is.null,contract.not.is.null)",
                 "sb_secret_mock", token=None, minimal=True, method="DELETE"),
            call(endpoint, "sb_secret_mock", data=rows, token=None, minimal=True),
        ])

    @patch.object(upload, "attach_contract_parameters", side_effect=lambda data, *args: data)
    def test_delete_failure_prevents_insert(self, enrich):
        with patch.object(upload, "load_config", return_value={
            "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "sb_secret_mock",
        }), patch.object(upload, "request_json", side_effect=RuntimeError("HTTP 403")) as request, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(upload.main(["--data", '{"contract": "BTC_USDT"}']), 1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["method"], "DELETE")

    def test_check_only_and_empty_data_never_delete(self):
        with patch.object(upload, "load_config", return_value={
            "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "sb_secret_mock",
        }), patch.object(upload, "request_json", return_value=(200, [])) as request, \
                contextlib.redirect_stdout(io.StringIO()):
            upload.supabase(check_only=True)
            request.assert_called_once_with(
                "https://example.supabase.co/rest/v1/orders?select=*&limit=0",
                "sb_secret_mock", token=None)
            request.reset_mock()
            self.assertEqual(upload.supabase([]), [])
            request.assert_not_called()
            with self.assertRaises(ValueError):
                upload.supabase(["invalid"])
            request.assert_not_called()

    @patch.object(upload, "attach_contract_parameters", side_effect=lambda data, *args: data)
    def test_custom_table_and_token_apply_to_both_requests(self, enrich):
        row = {"contract": "BTC_USDT"}
        with patch.object(upload, "load_config", return_value={
            "SUPABASE_URL": "https://example.supabase.co/rest/v1",
            "SUPABASE_KEY": "sb_publishable_mock", "SUPABASE_ACCESS_TOKEN": "user-jwt",
        }), patch.object(upload, "request_json", side_effect=[(204, None), (201, [row])]) as request, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(upload.supabase(row, table="custom_orders"), [row])
        endpoint = "https://example.supabase.co/rest/v1/custom_orders"
        self.assertEqual(request.call_args_list, [
            call(endpoint + "?or=(contract.is.null,contract.not.is.null)",
                 "sb_publishable_mock", token="user-jwt", minimal=True, method="DELETE"),
            call(endpoint, "sb_publishable_mock", data=row, token="user-jwt", minimal=False),
        ])

    def test_http_delete_has_no_body_and_uses_auth(self):
        with patch.object(upload, "urlopen") as open_url:
            response = open_url.return_value.__enter__.return_value
            response.status = 204
            response.read.return_value = b""
            self.assertEqual(upload.request_json(
                "https://example.supabase.co/rest/v1/orders?or=(contract.is.null,contract.not.is.null)",
                "sb_secret_mock", token="user-jwt", minimal=True, method="DELETE"), (204, None))
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_method(), "DELETE")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Prefer"), "return=minimal")
        self.assertEqual(request.get_header("Authorization"), "Bearer user-jwt")

    def test_http_request_serializes_bulk_payload(self):
        rows = upload.parse_sizes(order())
        with patch.object(upload, "urlopen") as open_url:
            response = open_url.return_value.__enter__.return_value
            response.status = 201
            response.read.return_value = b""
            upload.request_json("https://example.supabase.co/rest/v1/orders", "sb_secret_mock",
                                data=rows, minimal=True)
        request = open_url.call_args.args[0]
        self.assertEqual(json.loads(request.data), rows)
        self.assertEqual(request.get_header("Prefer"), "return=minimal")

    def test_network_failure_sets_cli_failure_exit_code(self):
        with patch.object(upload, "supabase", side_effect=RuntimeError("HTTP 403")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(upload.main([]), 1)


class ContractParameterUploadTests(unittest.TestCase):
    config = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "sb_secret_mock"}
    btc = {"contract": "BTC_USDT", "quanto_multiplier": "0.00010000", "order_price_round": "0.2500"}
    eth = {"contract": "ETH_USDT", "quanto_multiplier": "0.0100", "order_price_round": "0.05"}

    def test_parameters_are_read_before_delete_and_written_to_matching_orders(self):
        rows = [{"contract": "BTC_USDT", "quanto_multiplier": "wrong"},
                {"contract": "ETH_USDT"}, {"contract": "BTC_USDT"}]
        with patch.object(upload, "load_config", return_value=self.config), \
                patch.object(upload, "request_json", side_effect=[(200, [self.btc]), (200, [self.eth]), (204, None), (201, None)]) as send, \
                contextlib.redirect_stdout(io.StringIO()):
            upload.supabase(rows, table="custom_orders", minimal=True)
        calls = send.call_args_list
        self.assertIn("/contracts?", calls[0].args[0])
        self.assertTrue(calls[0].args[0].endswith("contract=eq.BTC_USDT"))
        self.assertTrue(calls[1].args[0].endswith("contract=eq.ETH_USDT"))
        self.assertEqual(calls[2].kwargs["method"], "DELETE")
        self.assertTrue(calls[3].args[0].endswith("/custom_orders"))
        self.assertEqual(calls[3].kwargs["data"], [self.btc, self.eth, self.btc])
        self.assertEqual(len(calls), 4)
        self.assertEqual(rows[0]["quanto_multiplier"], "wrong")

    def test_invalid_or_missing_parameters_never_delete_old_orders(self):
        invalid = [[], [self.btc, self.btc], [self.eth], {}, [None],
                   *([{**self.btc, field: value}] for field in ("quanto_multiplier", "order_price_round")
                     for value in (None, 0.25, "NaN", "Infinity", "0", "-1", "bad"))]
        for records in invalid:
            with self.subTest(records=records), patch.object(upload, "load_config", return_value=self.config), \
                    patch.object(upload, "request_json", return_value=(200, records)) as send:
                with self.assertRaises(ValueError):
                    upload.supabase([{"contract": "BTC_USDT"}])
                self.assertEqual(send.call_count, 1)
                self.assertNotIn("method", send.call_args.kwargs)

    def test_later_contract_read_failure_preserves_old_orders(self):
        with patch.object(upload, "load_config", return_value=self.config), \
                patch.object(upload, "request_json", side_effect=[(200, [self.btc]), RuntimeError("HTTP 403")]) as send:
            with self.assertRaises(RuntimeError):
                upload.supabase([{"contract": "BTC_USDT"}, {"contract": "ETH_USDT"}])
        self.assertEqual(send.call_count, 2)
        self.assertTrue(all("method" not in item.kwargs for item in send.call_args_list))

    def test_single_object_uses_database_parameters_and_user_token(self):
        with patch.object(upload, "request_json", return_value=(200, [self.btc])) as send:
            result = upload.attach_contract_parameters({"contract": "BTC_USDT"},
                "https://example.supabase.co/rest/v1", "key", "user-token")
        self.assertEqual(result, self.btc)
        self.assertEqual(send.call_args.kwargs["token"], "user-token")


if __name__ == "__main__":
    unittest.main()
