import unittest

from history import DAY, prepare
from indicators import Config, calculate
from test_history import bars


def rows(raw):
    return prepare(raw, "BTC", 0, (len(raw) + 2) * DAY, (len(raw) + 2) * DAY)[0]


class IndicatorTests(unittest.TestCase):
    def test_default_boundary_and_no_future_leakage(self):
        data = rows(bars(430))
        result = calculate(data)
        self.assertIsNone(result[394]["return_percentile"])
        self.assertEqual(result[395]["history_count"], 365)
        self.assertEqual(result[395]["history_end"], 394 * DAY)
        self.assertEqual(result[395]["status"], "OK")
        self.assertEqual(calculate(data[:400]), result[:400])
        self.assertEqual(result[395]["signal_time"], 396 * DAY)

    def test_distribution_arithmetic_and_current_exclusion(self):
        raw = [{"t": i * DAY, "o": 100, "h": 150, "l": 90, "c": 100, "v": 1} for i in range(35)]
        for i, close in enumerate((110, 120, 130, 120, 140), 30):
            raw[i]["c"] = close
        result = calculate(rows(raw), Config(window=3))
        point = result[33]
        self.assertAlmostEqual(point["return_percentile"], 50)
        self.assertAlmostEqual(point["typical_move"], 0.2)
        self.assertAlmostEqual(point["signed_move"], 1)
        self.assertAlmostEqual(point["robust_z"], 0)
        self.assertEqual(result[34]["reasons"]["robust_z"], "ZERO_MAD")
        self.assertEqual(result[34]["return_percentile"], 100)
        raw[33]["c"] = 140
        self.assertAlmostEqual(calculate(rows(raw), Config(window=3))[33]["robust_z"], 0.2 / (1.4826 * 0.1))

    def test_ema_and_wilder_atr_hand_calculation(self):
        raw = [dict(t=i * DAY, o=c, h=c+1, l=c-1, c=c, v=1) for i, c in enumerate((10, 12, 11, 15))]
        result = calculate(rows(raw), Config(window=1, ema_period=3, atr_period=3))
        self.assertIsNone(result[1]["ema"])
        self.assertEqual(result[2]["ema"], 11)
        self.assertEqual(result[3]["ema"], 13)
        self.assertAlmostEqual(result[2]["atr"], 7/3)
        self.assertAlmostEqual(result[3]["atr"], 29/9)
        self.assertAlmostEqual(result[3]["stretch_atr"], 18/29)

    def test_zero_denominators_and_ties(self):
        raw = [dict(t=i*DAY, o=100, h=100, l=100, c=100, v=0) for i in range(400)]
        last = calculate(rows(raw))[-1]
        self.assertEqual(last["return_percentile"], 50)
        for field, reason in (("signed_move", "ZERO_TYPICAL_MOVE"), ("robust_z", "ZERO_MAD"), ("stretch_atr", "ZERO_ATR")):
            self.assertIsNone(last[field])
            self.assertEqual(last["reasons"][field], reason)

    def test_gap_rewarm_and_valid_return_history(self):
        raw = bars(470)
        raw[400]["c"] = float("nan")
        result = calculate(rows(raw))
        after = next(r for r in result if r["timestamp"] == 401 * DAY)
        self.assertTrue(after["gap_before"])
        self.assertIsNone(after["ema"])
        self.assertIsNone(after["ret_30d"])
        self.assertEqual(after["history_count"], 365)
        self.assertEqual(after["history_end"], 399 * DAY)
        self.assertEqual(result[-1]["status"], "OK")

    def test_quality_and_unclosed_bar_exclusion(self):
        raw = bars(400)
        data, _ = prepare(raw, "BTC", 0, 400*DAY, 399*DAY+1)
        self.assertEqual(len(calculate(data)), 399)
        raw[398]["v"] = -1
        data, _ = prepare(raw, "BTC", 0, 400*DAY, 400*DAY)
        self.assertIsNone(calculate(data)[-1]["ret_30d"])

    def test_bad_config_order_and_mixed_assets(self):
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                Config(window=value)
        data = rows(bars(3))
        with self.assertRaises(ValueError):
            calculate(list(reversed(data)))
        data[1]["symbol"] = "ETH"
        with self.assertRaises(ValueError):
            calculate(data)
        self.assertEqual(calculate([]), [])


if __name__ == "__main__":
    unittest.main()
