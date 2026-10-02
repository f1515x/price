"""月度指标的离线计算及 HTTP 边界测试。"""

import argparse
import contextlib
from datetime import datetime, timezone
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import requests

from price_monitor.market import quarterly as q


class MonthlyTests(unittest.TestCase):
    START = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
    END = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())

    def candles(self):
        return [
            {"t": timestamp,
             "h": "120", "l": "80", "c": "100" if i == 0 else "110"}
            for i, timestamp in enumerate(range(self.START - q.DAY_SECONDS, self.END, q.DAY_SECONDS))
        ]

    def test_previous_close_sorted_and_current_day_excluded(self):
        candles = self.candles()
        # 前一日及当前自然月的极值都不能进入一个月高低价。
        candles[0].update(h="1000", l="1")
        # 区间最高价与最低价出现在不同日期，须取整个区间的极值。
        candles[1]["h"] = "150"
        candles[-1]["l"] = "60"
        candles.append({"t": self.END, "h": "999", "l": "1", "c": "5"})
        expected = (150 - 60) / 100 * 100
        self.assertAlmostEqual(
            q.calculate_month_amplitude(
                list(reversed(candles)), start_timestamp=self.START, end_timestamp=self.END,
            ),
            expected,
        )

    def test_calendar_window_crosses_year_and_includes_leap_day(self):
        for current, start, end in (
            ((2026, 10, 2), (2026, 9, 1), (2026, 10, 1)),
            ((2026, 1, 15), (2025, 12, 1), (2026, 1, 1)),
            ((2024, 3, 31), (2024, 2, 1), (2024, 3, 1)),
        ):
            timestamp = lambda parts: int(datetime(*parts, tzinfo=timezone.utc).timestamp())
            with self.subTest(current=current):
                self.assertEqual(q.get_month_window(timestamp(current)),
                                 (timestamp(start), timestamp(end)))

    def test_rejects_missing_duplicate_and_invalid_prices(self):
        cases = [self.candles()[:-1], self.candles() + [self.candles()[0]], {}]
        for field, value in (("c", "0"), ("h", "NaN"), ("l", "121"),
                             ("c", None), ("h", True), ("t", 1.5)):
            candles = self.candles()
            candles[1][field] = value
            cases.append(candles)
        for candles in cases:
            with self.subTest(candles=candles), self.assertRaises(ValueError):
                q.calculate_month_amplitude(
                    candles, start_timestamp=self.START, end_timestamp=self.END,
                )

    def test_symbols_and_cli_defaults(self):
        self.assertEqual(q.parse_args([]).base_asset, "BTC")
        self.assertEqual(q.parse_args([" eth "]).base_asset, "ETH")
        self.assertEqual(q.parse_base_asset("1000pepe"), "1000PEPE")
        for symbol in ("", "中文", "BTC_USDT", "éth", "ß", "ＢＴＣ", None):
            with self.subTest(symbol=symbol), self.assertRaises(argparse.ArgumentTypeError):
                q.parse_base_asset(symbol)

    def test_tradingview_response_and_http_errors(self):
        session = Mock()
        response = session.get.return_value
        response.json.return_value = {"Perf.1M": "-21.21"}
        self.assertEqual(q.get_month_performance("eth", session=session), -21.21)
        kwargs = session.get.call_args.kwargs
        self.assertEqual(kwargs["params"]["symbol"], "GATE:ETHUSDT.P")
        self.assertEqual(kwargs["params"]["fields"], "Perf.1M")
        self.assertEqual(kwargs["timeout"], 15)
        for data in ({}, [], {"Perf.1M": "inf"}, {"Perf.1M": True}):
            response.json.return_value = data
            with self.subTest(data=data), self.assertRaises(ValueError):
                q.get_month_performance("BTC", session=session)
        response.raise_for_status.side_effect = requests.HTTPError("503")
        with self.assertRaises(requests.HTTPError):
            q.get_month_performance("BTC", session=session)

    def test_gate_request_window(self):
        session = Mock()
        session.get.return_value.json.return_value = self.candles()
        q.get_month_amplitude("eth", session=session, now=self.END + 1234)
        kwargs = session.get.call_args.kwargs
        self.assertEqual(kwargs["params"], {
            "contract": "ETH_USDT", "interval": "1d", "timezone": "utc0",
            "from": self.START - q.DAY_SECONDS, "to": self.END - 1,
        })
        self.assertEqual(kwargs["timeout"], 15)
        session.get.return_value.raise_for_status.assert_called_once()

    def test_shared_session_and_combined_value(self):
        with patch.object(q.requests, "Session") as factory:
            session = factory.return_value.__enter__.return_value
            session.get.return_value.json.side_effect = [{"Perf.1M": -20}, self.candles()]
            with patch.object(q.time, "time", return_value=self.END + 1):
                result = q.get_monthly_metrics("btc")
            self.assertEqual(result.base_asset, "BTC")
            self.assertEqual(result.amplitude_1m, 40)
            self.assertAlmostEqual(result.combined_average, 10)
            self.assertEqual(session.get.call_count, 2)
            factory.return_value.__exit__.assert_called_once()

    def test_cli_output_and_failure_status(self):
        with patch.object(q, "get_monthly_metrics", return_value=q.MonthlyMetrics("ETH", -20, 40)):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(q.main(["ETH"]), 0)
            self.assertIn("+10.00%", output.getvalue())
            self.assertIn("1 个月振幅", output.getvalue())
            self.assertIn("1 个月综合均值", output.getvalue())
            self.assertNotIn("3 个月", output.getvalue())
        for error in (requests.Timeout("timeout"), ValueError("missing candles")):
            with patch.object(q, "get_monthly_metrics", side_effect=error):
                with contextlib.redirect_stderr(io.StringIO()) as output:
                    self.assertEqual(q.main([]), 1)
                self.assertIn(str(error), output.getvalue())

    def test_legacy_import_does_not_request_network(self):
        spec = importlib.util.spec_from_file_location("quarterly_legacy", Path(__file__).with_name("1.py"))
        with patch.object(q.requests.Session, "get") as get:
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
