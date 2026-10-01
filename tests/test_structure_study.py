import math
import unittest
from unittest.mock import patch

from history import DAY
from indicators import Config as IC
from structure_history import Config as SC
from structure_study import Config, features, filter_signals, study
from test_history import bars
from test_indicators import rows


def structures(data, side="high"):
    return [dict(timestamp=r["timestamp"], status="OK", weak_type=side,
                 ratio=.2, swing_atr=2, trend="BULLISH") for r in data]


class StructureStudyTests(unittest.TestCase):
    def test_midrank_current_exclusion_and_direction_histories(self):
        data = rows(bars(6))
        states = structures(data)
        for s, value in zip(states, (1, 2, 3, 2, 100, -1)):
            s.update(ratio=value, swing_atr=abs(value))
        states[-1]["weak_type"] = "low"
        result = features(data, states, Config(window=3, er_period=2))
        self.assertIsNone(result[2]["ratio_percentile"])
        self.assertEqual(result[3]["ratio_percentile"], 50)
        self.assertEqual(result[4]["ratio_percentile"], 100)
        self.assertIsNone(result[5]["ratio_percentile"])
        self.assertEqual(result[5]["ratio_count"], 0)
        self.assertEqual(result[5]["swing_percentile"], 0)

    def test_er_trend_zigzag_flat_and_gap(self):
        data = rows(bars(6))
        for r, close in zip(data, (10, 11, 12, 11, 11, 11)):
            r["close"] = close
        config = Config(window=1, er_period=2)
        result = features(data, structures(data), config)
        self.assertEqual(result[2]["er"], 1)
        self.assertEqual(result[3]["er"], 0)
        self.assertIsNone(result[5]["er"])
        self.assertEqual(result[5]["reasons"]["er"], "ZERO_PRICE_PATH")
        data[-1]["timestamp"] += DAY
        last = features(data, structures(data), config)[-1]
        self.assertEqual(last["ratio_count"], 0)
        self.assertIsNone(last["er"])

    def test_filter_directions_and_missing(self):
        for d, p in ((1, 20), (-1, 80)):
            self.assertTrue(all(v == d for v in filter_signals(d, dict(ratio_percentile=p, swing_percentile=80, er=.5)).values()))
            result = filter_signals(d, dict(ratio_percentile=100-p, swing_percentile=79, er=.51))
            self.assertEqual(result, dict(baseline=d, ratio=0, swing=0, er=0))
        self.assertEqual(filter_signals(1, dict(ratio_percentile=None, swing_percentile=None, er=None)), dict(baseline=1, ratio=0, swing=0, er=0))

    def test_invalid_and_unavailable(self):
        for kwargs in (dict(window=0), dict(er_period=True), dict(er_max=float("nan")), dict(structure_tail=50)):
            with self.assertRaises(ValueError):
                Config(**kwargs)
        data = rows(bars(3))
        states = structures(data)
        states[0]["status"] = "UNAVAILABLE"
        result = features(data, states, Config(window=2))
        self.assertEqual(result[2]["ratio_count"], 1)
        with self.assertRaises(ValueError):
            features(data, states[:-1])
        result = study(data)
        self.assertEqual(result["eligible"], 0)
        self.assertTrue(all(s["status"] == "INSUFFICIENT_EVENTS" for s in result["summaries"]))

    def test_real_pipeline_prefix_invariance(self):
        data = rows(bars(100))
        for i, r in enumerate(data):
            c = 100+.2*i+10*math.sin(i/3)
            r.update(open=c, close=c, high=c+1, low=c-1)
        args = dict(config=Config(window=3, er_period=3), indicator_config=IC(window=3), structure_config=SC(3))
        short, full = study(data[:80], **args), study(data, **args)
        self.assertTrue(short["candidates"])
        self.assertEqual(short["features"], full["features"][:80])
        self.assertEqual(short["candidates"], [c for c in full["candidates"] if c["index"] < 80])

    def test_paired_ablation_dedup_purge_and_reproducibility(self):
        data = rows(bars(150))
        indicators = [dict(ret_30d=.2, return_percentile=95, signed_move=3,
                           stretch_atr=3, signal_time=r["timestamp"]+DAY) for r in data]
        values = [dict(ratio_percentile=90 if i % 60 < 30 else 50, swing_percentile=90, er=.2) for i in range(150)]
        with patch("structure_study.calculate", return_value=indicators), patch("structure_study.replay", return_value=structures(data)), patch("structure_study.features", return_value=values):
            result = study(data)
            self.assertEqual(result, study(data))
        for event in result["events"]:
            if event["partition"] == "train":
                self.assertLessEqual(event["exit_time"], result["split_time"])
            else:
                self.assertGreaterEqual(event["entry_time"], result["split_time"])
        baseline = [e for e in result["events"] if e["partition"] == "train" and e["horizon"] == 1]
        self.assertEqual([e["index"] for e in baseline], [0, 30, 60, 90])
        ratio = next(s for s in result["summaries"] if s["partition"] == "train" and s["horizon"] == 1 and s["rule"] == "ratio")
        self.assertEqual(ratio["retained"]["n"], 2)
        self.assertEqual(ratio["rejected"]["n"], 2)
        self.assertEqual(ratio["baseline"]["n"], 4)


if __name__ == "__main__":
    unittest.main()
