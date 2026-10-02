"""Offline migration and calculation regression checks."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from price_monitor import settings
from price_monitor.analysis.indicators import atr14
from price_monitor.analysis import structure
from price_monitor.clients import telegram
from price_monitor.market import candles, precision
from price_monitor.market.quarterly import MonthlyMetrics
from price_monitor.risk import allocation, sizing
from price_monitor.strategy import signals


class MonitorTests(unittest.TestCase):
    def test_imports_and_help_without_credentials(self):
        env = {k: v for k, v in os.environ.items() if k not in ("API_KEY", "API_SECRET")}
        with tempfile.TemporaryDirectory() as directory:
            env["PRICE_MONITOR_ROOT"] = directory
            result = subprocess.run(
                [sys.executable, "-c", "import amount, size; from price_monitor.clients import gate"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for command in ("allocation", "sizes", "precision", "signals", "structure", "candles", "performance"):
                result = subprocess.run(
                    [sys.executable, "-m", "price_monitor", command, "--help"],
                    env=env, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_environment_overrides_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text('API_KEY=file-key\nAPI_SECRET="file-secret"\n')
            with patch.object(settings, "ROOT_DIR", Path(directory)), patch.dict(os.environ, {"API_KEY": "env-key"}, clear=True):
                self.assertEqual(settings.credentials(), ("env-key", "file-secret"))

    def test_missing_credentials_raise_only_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(settings, "ROOT_DIR", Path(directory)), patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RuntimeError):
                    settings.credentials()

    def test_signal_boundaries_and_directions(self):
        for threshold in (5, 20, 35):
            for direction, weak_type, expected in ((1, "high", 101), (-1, "low", 99)):
                with self.subTest(threshold=threshold, weak_type=weak_type):
                    perf = direction * (threshold + 1)
                    structure = {"ratio": direction * (threshold + 1) / 100,
                                 "weak_type": weak_type, "adjusted_weak_price": 100}
                    self.assertEqual(signals.price(perf, structure, threshold), expected)
                    self.assertIsNone(signals.price(direction * threshold, structure, threshold))
                    self.assertIsNone(signals.price(
                        perf, {**structure, "ratio": direction * threshold / 100}, threshold,
                    ))
                    self.assertIsNone(signals.price(
                        perf, {**structure, "weak_type": "low" if direction == 1 else "high"}, threshold,
                    ))

    def test_signal_threshold_preserves_sign_and_precision(self):
        high = {"ratio": 0.20003, "weak_type": "high", "adjusted_weak_price": 100}
        self.assertIsNone(signals.price(20.003, high, 20.004))
        self.assertEqual(signals.price(20.003, high, 20.002), 101)
        self.assertEqual(signals.price(-4, {**high, "ratio": -0.04}, -5), 101)
        low = {**high, "ratio": 0.04, "weak_type": "low"}
        self.assertEqual(signals.price(4, low, -5), 99)
        self.assertIsNone(signals.price(0, {**high, "ratio": 0}, 0))
        for threshold in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                signals.price(30, high, threshold)

    def test_monthly_threshold_used_by_analysis_and_sizing(self):
        structure = {"ratio": 0.25, "weak_type": "high", "adjusted_weak_price": 100}
        for amplitude, expected in ((10, 101), (40, None)):
            with self.subTest(amplitude=amplitude):
                metrics = MonthlyMetrics("BTC", 30, amplitude)
                with patch.object(signals, "get_monthly_metrics", return_value=metrics) as get_metrics, \
                        patch.object(signals, "get_structure", return_value=structure) as get_structure, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(signals.analyze("btc", 7), expected)
                    get_metrics.assert_called_once_with("BTC")
                    get_structure.assert_called_once_with("BTC", 7)
                    self.assertIn(f"{metrics.combined_average:+.2f}%", output.getvalue())
                    get_metrics.reset_mock()
                    self.assertEqual(sizing._get_price_and_action("BTC_USDT"),
                                     (expected, "Open Short" if expected else None))
                    get_metrics.assert_called_once_with("BTC")

    def test_monthly_metrics_failure_propagates(self):
        with patch.object(signals, "get_monthly_metrics", side_effect=ValueError("missing candles")), \
                patch.object(signals, "get_structure") as get_structure:
            with self.assertRaisesRegex(ValueError, "missing candles"):
                signals.analyze("BTC")
            with self.assertRaisesRegex(ValueError, "missing candles"):
                sizing._get_price_and_action("BTC_USDT")
            get_structure.assert_not_called()

    def test_allocation_formula(self):
        maximum = allocation.compute_max_open(196.63528496, 100, 0.00075)
        self.assertAlmostEqual(maximum, 17098.720431304347)
        self.assertEqual(allocation.amount(maximum), 170.99)

    def test_wilder_atr(self):
        data = pd.DataFrame({"high": [12.] * 15, "low": [8.] * 15, "close": [10.] * 15})
        result = atr14(data)
        self.assertTrue(result.iloc[:13].isna().all())
        self.assertEqual(result.iloc[13], 4)
        self.assertEqual(result.iloc[14], 4)

    def test_structure_matches_pre_migration_baseline(self):
        close = [100 + (i % 40 if i % 40 < 20 else 40 - i % 40) + i / 50 for i in range(200)]
        data = pd.DataFrame({"open": close, "high": [v + 2 for v in close], "low": [v - 2 for v in close], "close": close})
        expected = json.loads((Path(__file__).parent / "fixtures/structure_expected.json").read_text(encoding="utf-8"))
        result = structure.pine_weak_strong(data, 5)
        self.assertEqual(structure.serializable(result), expected["structure"])
        self.assertEqual(structure.weak_strong_structure(data, result), expected["signal_inputs"])

    def test_precision_preserves_trailing_zeros(self):
        self.assertEqual(str(precision.decimal_step("1.2300")), "0.0001")
        self.assertEqual(str(precision.decimal_step("100")), "1")

    def test_symbol_file_comments_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "symbols.txt")
            path.write_text("# heading\nbtc\nBTC_USDT\nETH # comment\n")
            self.assertEqual(precision.read_symbols(path), ["BTC_USDT", "ETH_USDT"])

    def test_mocked_precision_then_sizing(self):
        response = unittest.mock.Mock()
        response.json.return_value = {"last_price": "10.10", "mark_price": "10.1", "index_price": "10.100"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "nested/price_steps.json")
            with patch.object(precision.requests.Session, "get", return_value=response), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(precision.main(["BTC", "--output", str(path)]), 0)
            self.assertEqual(json.loads(path.read_text())[0]["step"], "0.1")
            step = sizing.get_price_step("BTC", path)
            for action, expected in (("Open Long", 9), ("Open Short", -9)):
                with patch.object(sizing, "_get_price_and_action", return_value=(10.19, action)), patch.object(sizing, "amount", return_value=100), patch.object(sizing, "getquanto_multiplier", return_value="1"):
                    # Inject the generated mapping through the existing reader.
                    with patch.object(sizing, "get_price_step", return_value=step), contextlib.redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(sizing.size("BTC"), expected)
                    self.assertIn("10.1 USDT", output.getvalue())

    def test_no_signal_skips_account_requests(self):
        with patch.object(sizing, "_get_price_and_action", return_value=(None, None)), patch.object(sizing, "amount") as account:
            self.assertIsNone(sizing.size("BTC"))
            account.assert_not_called()

    def test_candle_cache_update_is_sorted_and_unique(self):
        old = [{"t": t, "c": "old"} for t in range(1, 12)]
        new = [{"t": t, "c": "new"} for t in range(4, 12)]
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(list(reversed(new))).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "BTC.json")
            path.write_text(json.dumps(old))
            with patch.object(candles, "urlopen", return_value=response):
                self.assertEqual(candles.db(path, "contract=BTC_USDT"), (11, 8))
            result = json.loads(path.read_text())
            self.assertEqual([row["t"] for row in result], list(range(1, 12)))
            self.assertEqual(result[-1]["c"], "new")

    def test_telegram_chunk_limit_without_sending(self):
        chunks = list(telegram._message_chunks("a" * 9000))
        self.assertEqual("".join(chunks), "a" * 9000)
        self.assertTrue(all(len(chunk) <= 4096 for chunk in chunks))

    def test_legacy_imports_use_package_implementations(self):
        self.assertIs(importlib.import_module("size"), sizing)
        self.assertIs(importlib.import_module("price"), signals)


if __name__ == "__main__":
    unittest.main()
