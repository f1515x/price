import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


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
        self.assertEqual(upload.parse_sizes("none\n\nTimestamp: 1791169976034"), [])

    def test_corrupt_report_never_partially_uploads(self):
        invalid = [order().replace("348 Contracts", "1.2 Contracts"),
                   order().replace("4087.850000000000001 USDT", "NaN USDT"),
                   order(side="Open Short"),
                   order().replace("   ======================", ""),
                   order().replace("📦  value               : 142.42 U\n", ""),
                   order() + "执行失败: timeout",
                   order() + "Timestamp: 1\n" + order()]
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
            for text, options in ((order(), ["--dry-run"]), ("Timestamp: 1", [])):
                path.write_text(text, encoding="utf-8-sig")
                with patch.object(upload, "supabase") as send, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(upload.main(["--sizes-file", str(path), *options]), 0)
                    send.assert_not_called()

    def test_bulk_write_does_not_require_select(self):
        rows = upload.parse_sizes(order())
        with patch.object(upload, "load_config", return_value={
            "SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "sb_secret_mock",
        }), patch.object(upload, "request_json", return_value=(201, rows)) as request, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(upload.supabase(rows, minimal=True), rows)
        request.assert_called_once_with("https://example.supabase.co/rest/v1/orders",
                                        "sb_secret_mock", data=rows, token=None, minimal=True)

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


if __name__ == "__main__":
    unittest.main()
