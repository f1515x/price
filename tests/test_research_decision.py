import copy
import json
from pathlib import Path
import tempfile
import unittest

from m6_research import acceptance, aggregate
from research_decision import close_hypothesis, digest


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.protocol = dict(version="test-protocol", assets=["BTC", "ETH"], acceptance=dict(
            min_trades=30, min_independent_blocks=30, min_mean_net_r=0, max_drawdown=.15,
            min_positive_fold_fraction=.5, min_trades_per_asset=10, min_positive_neighbor_fraction=.5))
        self.protocol_path = self.root / "protocol.json"
        self.protocol_path.write_text(json.dumps(self.protocol), encoding="utf-8")
        self.report_path = self.root / "report.json"
        self.report = dict(version="m6-rolling-preregistered-v1",
                           protocol=dict(self.protocol, preregistered_file_sha256=digest(self.protocol_path.read_bytes())),
                           folds=[dict(test_start=0, test_end=86400)], aggregates=[], experiments=[],
                           input_quality={"BTC": dict(end_exclusive=86400), "ETH": dict(end_exclusive=86400)},
                           limitations=["Historical specs unverified"])
        for variant, rule, cost, net_r in (
                ("base", "percentile_structure", "historical_funding", -.1),
                ("base", "legacy_proxy", "historical_funding", -.5),
                ("entry_atr=1", "percentile_structure", "historical_funding", .3),
                ("base", "percentile_structure", "proxy", 10)):
            run = dict(trades=[dict(symbol="BTC", signal_time=0, net_pnl=net_r * 50,
                                   net_r=net_r, holding_days=1)],
                       summary=dict(admitted=1, outcomes={"FILLED": 1}, max_drawdown=.01, net_pnl=net_r * 50))
            self.report["experiments"].append(dict(variant=variant, rule=rule, cost_mode=cost,
                                                   partition="test", fold=0, start=0, end=86400, result=run))
            self.report["aggregates"].append(dict(variant=variant, rule=rule, cost_mode=cost,
                                                 summary=aggregate([run], self.protocol["assets"])))
        self.recompute_acceptance()

    def recompute_acceptance(self):
        summaries = [a["summary"] for a in self.report["aggregates"]]
        self.report["acceptance"] = acceptance(summaries[0], summaries[1], [summaries[2]],
                                              self.protocol["acceptance"],
                                              dict(historical_funding=True, historical_specs=False))

    def close(self):
        self.report_path.write_text(json.dumps(self.report), encoding="utf-8")
        return close_hypothesis(self.report_path, self.protocol_path, digest(self.report_path.read_bytes()), "2026-10-01")

    def test_negative_base_is_closed_without_selecting_profitable_proxy_or_neighbor(self):
        decision = self.close()
        self.assertEqual(decision["decision"], "TERMINATED")
        self.assertEqual(decision["base_oos"]["mean_net_r"], -.1)
        self.assertEqual(decision["neighbors"], dict(count=1, positive=1))
        self.assertEqual(decision["preserved_acceptance_thresholds"], self.protocol["acceptance"])
        self.assertTrue(decision["retrospective"])

    def test_wrong_reviewed_report_hash_is_rejected(self):
        self.close()
        with self.assertRaisesRegex(ValueError, "Report SHA-256"):
            close_hypothesis(self.report_path, self.protocol_path, "0" * 64, "2026-10-01")

    def test_changed_protocol_is_rejected(self):
        self.protocol_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Protocol differs"):
            self.close()

    def test_fabricated_summary_is_rejected_even_with_new_report_hash(self):
        self.report["aggregates"][0]["summary"]["mean_net_r"] = -.2
        with self.assertRaisesRegex(ValueError, "Aggregate differs"):
            self.close()

    def test_changed_acceptance_is_rejected(self):
        self.report["acceptance"]["checks"]["positive_expectancy"] = True
        with self.assertRaisesRegex(ValueError, "Acceptance differs"):
            self.close()

    def test_missing_or_duplicate_test_folds_are_rejected(self):
        original = copy.deepcopy(self.report)
        self.report["experiments"].pop(0)
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            self.close()
        self.report = original
        self.report["experiments"].append(copy.deepcopy(self.report["experiments"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.close()

    def test_wrong_partition_boundary_is_rejected(self):
        self.report["experiments"][0]["start"] = 1
        with self.assertRaisesRegex(ValueError, "partition differs"):
            self.close()

    def test_nonnegative_base_cannot_be_closed_as_negative_expectancy(self):
        run = self.report["experiments"][0]["result"]
        run["trades"][0].update(net_r=.1, net_pnl=5)
        run["summary"]["net_pnl"] = 5
        self.report["aggregates"][0]["summary"] = aggregate([run], self.protocol["assets"])
        self.recompute_acceptance()
        with self.assertRaisesRegex(ValueError, "Termination requires"):
            self.close()


if __name__ == "__main__":
    unittest.main()
