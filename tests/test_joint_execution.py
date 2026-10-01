from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_joint_execution import fixture
from contract_specs import digest, encoded
from execution_history import at_time
from history import DAY
from joint_execution import load, simulate_joint
from portfolio_simulation import simulate
from spec_evidence import _json


class JointExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "inputs"
        self.rows, self.candidates, self.config, self.groups, self.inputs = fixture(self.root)

    def run_scenario(self, **overrides):
        return simulate_joint(self.rows, self.candidates, self.config, self.groups,
                              **dict(self.inputs, **overrides))

    def load(self):
        return load(self.config.execution, self.rows, 0, 4*DAY, **self.inputs)

    def rewrite(self, key, mutate):
        path = self.inputs[key + "_path"]
        value = _json(path.read_bytes())
        mutate(value)
        path.write_bytes(encoded(value))
        self.inputs[key + "_sha256"] = digest(path.read_bytes())

    def test_joint_boundaries_and_unchanged_risk(self):
        periods, funding, report = self.load()
        for symbol, ps in periods.items():
            self.assertEqual([(p["start"],p["end"]) for p in ps], [(0,DAY),(DAY,2*DAY),(2*DAY,4*DAY)])
            self.assertEqual(at_time(ps, DAY).max_quantity, 2.5)
            self.assertEqual(at_time(ps, 2*DAY).fee_rate, .002)
            self.assertEqual(len(funding[symbol]), 4)
            for p in ps:
                for key in ("risk_fraction", "max_exposure", "max_drawdown", "initial_equity", "stop_atr"):
                    self.assertEqual(getattr(p["config"],key), getattr(self.config.execution,key))
                self.assertEqual(p["verified_fields"], [])
        self.assertFalse(report["used_for_execution_parameters"])

    def test_long_short_independent_accounting_and_provenance(self):
        result = self.run_scenario()
        trades = {t["symbol"]: t for t in result["trades"]}
        self.assertEqual(set(trades), {"BTC", "ETH"})
        # Long: gross -2.5, fees .25+.495, eight debits at marks 110..180.
        # Short: gross -.025, fees .0025+.00505, credits only on full held days.
        for symbol, pnl, funding in (("BTC", -6.145, 2.9), ("ETH", -.0093, -.02325)):
            trade = trades[symbol]
            self.assertAlmostEqual(trade["net_pnl"], pnl)
            self.assertAlmostEqual(trade["funding"], funding)
            self.assertEqual(trade["quantity"], 2.5)
            self.assertEqual(trade["entry_specification_review"]["ledger_sha256"], self.inputs["review_sha256"])
            self.assertEqual(trade["entry_specification_review"]["claim_ids_by_field"]["max_quantity"],
                             [f"{symbol}-1-max_quantity"])
            self.assertEqual(trade["cost_application"]["manifest_sha256"], self.inputs["cost_sha256"])
            self.assertEqual(trade["settlement_price_manifest_sha256"], self.inputs["price_sha256"])
        self.assertAlmostEqual(result["summary"]["final_equity"], 9993.8457)
        self.assertIn("declared_settlement_prices", result["funding_model"])

    def test_exit_boundary_uses_exiting_bar_costs(self):
        self.rows["BTC"][1]["low"] = 85
        trade = next(t for t in self.run_scenario()["trades"] if t["symbol"] == "BTC")
        self.assertEqual(trade["exit_time"], 2*DAY)
        self.assertEqual(trade["exit_price"], 90)
        self.assertEqual(trade["cost_application"]["exit_day"], DAY)
        self.assertEqual(trade["cost_application"]["exit_fee_rate"], .001)
        self.assertAlmostEqual(trade["exit_fee"], .225)

    def test_equivalent_to_direct_engine(self):
        periods, funding, _ = self.load()
        reference = simulate(self.rows, self.candidates, self.config, self.groups,
                             execution_periods=periods, funding=funding)
        actual = self.run_scenario()
        self.assertEqual(actual["summary"], reference["summary"])
        self.assertEqual(actual["equity_curve"], reference["equity_curve"])

    def test_explicit_scenario_permission(self):
        for value in (False, None, 1, "true"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_scenario(allow_scenario=value)

    def test_missing_review_coverage_blocks_engine(self):
        self.rewrite("review", lambda v: v["claims"].pop())
        with patch("joint_execution.simulate") as engine, self.assertRaises(ValueError):
            self.run_scenario()
        engine.assert_not_called()

    def test_conflicting_review_blocks_engine(self):
        def mutate(v):
            claim = dict(v["claims"][0], id="conflict", value="2")
            v["claims"].append(claim)
        self.rewrite("review", mutate)
        with self.assertRaises(ValueError):
            self.run_scenario()

    def test_cost_gap_rejected(self):
        self.rewrite("cost", lambda v: v["assets"]["BTC"][0].update(end=DAY))
        with self.assertRaises(ValueError):
            self.run_scenario()

    def test_missing_settlement_rejected(self):
        self.rewrite("price", lambda v: v["assets"]["ETH"]["prices"].pop())
        with self.assertRaises(ValueError):
            self.run_scenario()

    def test_each_manifest_hash_rechecked(self):
        for key in ("review", "cost", "price"):
            path = self.inputs[key + "_path"]
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_scenario()
            path.write_bytes(original)

    def test_source_and_funding_archive_rechecked_after_simulation(self):
        for relative in ("fixture.txt", "BTC/page-0000.json", "ETH/funding.json", "review.json", "cost.json", "price.json"):
            path = self.root / relative
            original = path.read_bytes()
            def mutate(*args, **kwargs):
                result = simulate(*args, **kwargs)
                path.write_bytes(original + b" ")
                return result
            with self.subTest(relative=relative), patch("joint_execution.simulate", side_effect=mutate), self.assertRaises(ValueError):
                self.run_scenario()
            path.write_bytes(original)

    def test_mismatched_asset_grids_rejected(self):
        self.rows["ETH"].pop()
        with self.assertRaises(ValueError):
            self.run_scenario()

    def test_empty_bars_rejected(self):
        self.rows["BTC"] = []
        with self.assertRaises(ValueError):
            self.run_scenario()

    def test_all_evidence_remains_uncertified(self):
        report = self.run_scenario()["joint_execution_evidence"]
        self.assertEqual(report["scope"], "JOINT_SCENARIO_ONLY")
        self.assertEqual(report["acceptance_status"], "NOT_VALIDATED")
        for field in ("historical_specs_verified", "exact_costs_verified", "settlement_prices_verified"):
            self.assertFalse(report[field])
        for key in ("specification_review", "cost_evidence", "settlement_price_evidence"):
            self.assertTrue(report[key]["used_for_execution_parameters"])
            self.assertEqual(report[key]["acceptance_status"], "NOT_VALIDATED")


if __name__ == "__main__":
    unittest.main()
