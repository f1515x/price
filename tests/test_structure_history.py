import unittest

import pandas as pd

from history import DAY, prepare
from smc import pine_weak_strong, weak_strong_structure
from structure_history import Config, replay


def fixture():
    values = [10, 8, 6, 9, 12, 10, 8, 5, 9, 13, 15, 11, 7, 4, 8, 12, 16, 10, 6, 3, 2]
    raw = [dict(t=i*DAY, o=c, h=c+1, l=c-1, c=c, v=1) for i, c in enumerate(values)]
    return prepare(raw, "BTC", 0, len(raw)*DAY, len(raw)*DAY)[0]


class StructureHistoryTests(unittest.TestCase):
    def test_confirmation_delay_and_unset(self):
        result = replay(fixture(), Config(2))
        self.assertIsNone(result[5]["structure"])
        first = result[6]
        self.assertEqual(first["structure"]["swing_high_index"], 4*DAY)
        self.assertEqual(first["structure"]["swing_high_confirmed_at"], 7*DAY)
        self.assertEqual(first["structure"]["swing_low_confirmed_at"], 5*DAY)
        self.assertEqual(first["reasons"], ["TREND_UNSET"])
        self.assertIsNone(first["strong_price"])
        for row in result:
            self.assertEqual(row["signal_time"], row["timestamp"]+DAY)
            if row["structure"]:
                self.assertLessEqual(row["structure_confirmed_at"], row["signal_time"])

    def test_future_append_and_mutation_do_not_rewrite_history(self):
        rows = fixture()
        complete = replay(rows, Config(2))
        for end in (6, 7, 11, 14, 20):
            self.assertEqual(replay(rows[:end], Config(2)), complete[:end])
        for row in rows[14:]:
            for field in ("open", "high", "low", "close"):
                row[field] *= 10
        self.assertEqual(replay(rows, Config(2))[:14], complete[:14])

    def test_direction_prices_and_legacy_parity(self):
        rows = fixture()
        result = replay(rows, Config(2))
        self.assertEqual(result[13]["weak_type"], "high")
        self.assertEqual(result[13]["raw_weak_price"], 16)
        self.assertEqual(result[13]["strong_price"], 3)
        self.assertEqual(result[13]["ratio"], 13/4)
        self.assertEqual(result[20]["weak_type"], "low")
        self.assertLess(result[20]["ratio"], 0)
        for i, row in enumerate(result):
            if row["status"] != "OK":
                continue
            prefix = pd.DataFrame(rows[:i+1]).set_index("timestamp")
            old = weak_strong_structure(prefix, pine_weak_strong(prefix, 2))
            for key in ("weak_type", "adjusted_weak_price", "ratio"):
                if isinstance(old[key], float):
                    self.assertAlmostEqual(row[key], old[key])
                else:
                    self.assertEqual(row[key], old[key])
            self.assertAlmostEqual(row["swing_atr"], abs(row["raw_weak_price"]-row["strong_price"])/row["atr14"])

    def test_gap_resets_structure_and_atr(self):
        rows = fixture()
        after = [dict(row, timestamp=row["timestamp"]+30*DAY) for row in rows]
        actual = replay(rows+after, Config(2))[len(rows):]
        expected = replay(after, Config(2))
        self.assertTrue(actual[0]["gap_before"])
        actual[0]["gap_before"] = False
        self.assertEqual(actual, expected)
        self.assertIsNone(actual[0]["structure"])
        self.assertIsNone(actual[0]["atr14"])

    def test_invalid_inputs_and_empty(self):
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                Config(value)
        self.assertEqual(replay([]), [])
        with self.assertRaises(ValueError):
            replay(list(reversed(fixture())))
        rows = fixture()
        rows[1]["symbol"] = "ETH"
        with self.assertRaises(ValueError):
            replay(rows)

    def test_unclosed_and_invalid_bars_are_excluded(self):
        raw = [dict(t=i*DAY, o=10, h=11, l=9, c=10, v=1) for i in range(20)]
        raw[17]["v"] = -1
        rows, _ = prepare(raw, "BTC", 0, 20*DAY, 19*DAY+1)
        result = replay(rows, Config(2))
        self.assertEqual(len(result), 18)
        self.assertEqual(result[-1]["timestamp"], 18*DAY)
        self.assertTrue(result[-1]["gap_before"])
        self.assertIsNone(result[-1]["structure"])


if __name__ == "__main__":
    unittest.main()
