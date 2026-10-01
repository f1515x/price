import copy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from contract_specs import digest, encoded
from dated_costs import VERSION, load, simulate_manifest
from dated_specifications import VERSION as SPEC_VERSION, FIELDS as SPEC_FIELDS
from execution_history import at_time
from history import DAY
from portfolio_simulation import PortfolioConfig, simulate
from test_trade_simulation import cfg, data, candidate


class DatedCostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "costs.json"
        self.path.with_name("source.txt").write_bytes(b"Synthetic costs, not account evidence.\n")
        self.manifest = dict(version=VERSION, scope="DECLARED_SCENARIO_ONLY",
            sources=dict(fixture=dict(file="source.txt", description="synthetic fixture",
                sha256=digest(self.path.with_name("source.txt").read_bytes()))),
            assets=dict(BTC=[dict(start=0, end=2*DAY, costs=dict(fee_rate="0.001", slippage="0"), sources=["fixture"]),
                            dict(start=2*DAY, end=4*DAY, costs=dict(fee_rate="0.002", slippage="0.01"), sources=["fixture"])]))
        self.base = cfg(max_quantity=2, quantity_step=1, min_quantity=1)

    def write(self):
        self.path.write_bytes(encoded(self.manifest))
        return digest(self.path.read_bytes())

    def load(self):
        return load(self.path, self.write(), self.base, ["BTC"], 0, 4*DAY, allow_declared_scenario=True)

    def run_scenario(self, direction=1, **kwargs):
        rows = {s: [dict(r, symbol=s) for r in data([(100,105,95,100)]*4)] for s in self.manifest["assets"]}
        c = candidate(direction=direction)
        return simulate_manifest(rows, {s: [c] for s in rows}, PortfolioConfig(self.base, .05, 2),
                                 {s: "crypto" for s in rows}, self.path, self.write(),
                                 allow_declared_scenario=True, **kwargs)

    def test_cross_day_entry_exit_and_cash(self):
        result = self.run_scenario()
        trade = result["trades"][0]
        self.assertEqual(trade["entry_time"], DAY)
        self.assertEqual(trade["exit_time"], 4*DAY)
        self.assertEqual(trade["entry_fee"], .2)
        self.assertEqual(trade["exit_price"], 99)
        self.assertEqual(trade["exit_fee"], .396)
        self.assertAlmostEqual(trade["net_pnl"], -2.596)
        self.assertAlmostEqual(result["summary"]["final_equity"], 10000-2.596)
        self.assertEqual(trade["cost_application"]["exit_day"], 3*DAY)
        self.assertFalse(result["dated_cost_evidence"]["exact_costs_verified"])

    def test_short_adverse_slippage(self):
        trade = self.run_scenario(direction=-1)["trades"][0]
        self.assertEqual(trade["exit_price"], 101)
        self.assertAlmostEqual(trade["net_pnl"], -2.604)

    def test_exit_at_boundary_uses_exiting_bar_cost(self):
        rows = data([(100,105,95,100), (100,105,85,100), (100,105,95,100), (100,105,95,100)])
        result = simulate_manifest({"BTC": rows}, {"BTC": [candidate()]}, PortfolioConfig(self.base, .05, 2),
            {"BTC": "crypto"}, self.path, self.write(), allow_declared_scenario=True)
        trade = result["trades"][0]
        self.assertEqual(trade["exit_time"], 2*DAY)
        self.assertEqual(trade["exit_price"], 90)
        self.assertEqual(trade["cost_application"]["exit_fee_rate"], .001)
        self.assertEqual(trade["exit_fee"], .18)

    def test_historical_funding_preserved_and_incomplete_rejected(self):
        funding = {"BTC": {day*DAY: [dict(timestamp=day*DAY+hour*3600, rate=.001, mark_price=100)
                                     for hour in (0, 8, 16)] for day in range(4)}}
        result = self.run_scenario(funding=funding)
        self.assertAlmostEqual(result["trades"][0]["funding"], 1.6)
        self.assertAlmostEqual(result["trades"][0]["net_pnl"], -4.196)
        self.assertFalse(result["dated_cost_evidence"]["exact_costs_verified"])
        del funding["BTC"][DAY][0]
        with self.assertRaises(ValueError):
            self.run_scenario(funding=funding)

    def test_boundaries_only_cost_fields_change(self):
        periods, report = self.load()
        self.assertEqual(at_time(periods["BTC"], 2*DAY).fee_rate, .002)
        for period in periods["BTC"]:
            for key, value in asdict(self.base).items():
                if key not in ("fee_rate", "slippage"):
                    self.assertEqual(getattr(period["config"], key), value)
            self.assertEqual(period["verified_fields"], [])
        self.assertEqual(report["acceptance_status"], "NOT_VALIDATED")

    def test_zero_cost_static_equivalence(self):
        for p in self.manifest["assets"]["BTC"]:
            p["costs"] = dict(fee_rate="0", slippage="0")
        rows = data([(100,105,95,100)]*4)
        reference = simulate({"BTC": rows}, {"BTC": [candidate()]}, PortfolioConfig(self.base, .05, 2), {"BTC": "crypto"})
        result = self.run_scenario()
        self.assertEqual(result["summary"], reference["summary"])
        self.assertEqual(result["equity_curve"], reference["equity_curve"])

    def test_combines_independent_specification_boundaries(self):
        spec = {k: str(getattr(self.base, k)) for k in SPEC_FIELDS}
        spec["price_tick"] = "0.1"
        manifest = dict(version=SPEC_VERSION, scope="DECLARED_SCENARIO_ONLY", sources=self.manifest["sources"],
            assets=dict(BTC=[dict(start=0, end=DAY, specification=spec, sources=["fixture"]),
                dict(start=DAY, end=4*DAY, specification=dict(spec, max_quantity="3"), sources=["fixture"])]))
        path = self.path.with_name("specs.json")
        path.write_bytes(encoded(manifest))
        result = self.run_scenario(specification_path=path, specification_sha256=digest(path.read_bytes()))
        self.assertEqual(result["trades"][0]["quantity"], 3)
        self.assertEqual([(p["start"], p["end"]) for p in result["execution_periods"]["BTC"]],
                         [(0, DAY), (DAY, 2*DAY), (2*DAY, 4*DAY)])
        self.assertAlmostEqual(result["summary"]["final_equity"], 10000-3.894)
        self.assertFalse(result["dated_specification_evidence"]["historical_specs_verified"])

    def test_multiasset_cash(self):
        self.manifest["assets"]["ETH"] = copy.deepcopy(self.manifest["assets"]["BTC"])
        result = self.run_scenario()
        self.assertEqual({t["symbol"] for t in result["trades"]}, {"BTC", "ETH"})
        self.assertAlmostEqual(result["summary"]["final_equity"], 10000+sum(t["net_pnl"] for t in result["trades"]))

    def test_explicit_scenario_and_spec_hash_pair(self):
        with self.assertRaises(ValueError):
            load(self.path, self.write(), self.base, ["BTC"], 0, 4*DAY)
        with self.assertRaises(ValueError):
            self.run_scenario(specification_path="unused")

    def test_hash_and_source_tampering(self):
        sha = self.write()
        self.path.write_bytes(self.path.read_bytes()+b" ")
        with self.assertRaises(ValueError):
            load(self.path, sha, self.base, ["BTC"], 0, 4*DAY, allow_declared_scenario=True)
        self.path.with_name("source.txt").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.load()

    def test_invalid_costs_and_precision(self):
        for value in (True, 0, "-0.01", "1", "NaN", "Infinity", "invalid", "1e-999", "0."+"9"*100):
            self.manifest["assets"]["BTC"][0]["costs"]["fee_rate"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load()

    def test_gaps_overlaps_intraday_and_reverse(self):
        original = copy.deepcopy(self.manifest)
        for key, value in (("start", DAY), ("start", 3*DAY), ("start", True), ("start", 2*DAY+1), ("end", 3*DAY)):
            self.manifest = copy.deepcopy(original)
            self.manifest["assets"]["BTC"][1][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.load()
        self.manifest = copy.deepcopy(original)
        self.manifest["assets"]["BTC"].reverse()
        with self.assertRaises(ValueError):
            self.load()

    def test_paths_sources_and_assets(self):
        original = copy.deepcopy(self.manifest)
        for file in ("../outside", "C:/outside", "source.txt:stream"):
            self.manifest = copy.deepcopy(original)
            self.manifest["sources"]["fixture"]["file"] = file
            with self.subTest(file=file), self.assertRaises(ValueError):
                self.load()
        self.manifest = copy.deepcopy(original)
        self.manifest["assets"]["BTC"][0]["sources"] = ["missing"]
        with self.assertRaises(ValueError):
            self.load()
        self.manifest = copy.deepcopy(original)
        for symbols in (["ETH"], ["BTC", "ETH"], ["BTC", "BTC"], ["btc"]):
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                load(self.path, self.write(), self.base, symbols, 0, 4*DAY, allow_declared_scenario=True)

    def test_no_certification_risk_or_funding_override(self):
        for place, key, value in ((self.manifest, "exact_costs_verified", True),
                (self.manifest["assets"]["BTC"][0]["costs"], "risk_fraction", "1"),
                (self.manifest["assets"]["BTC"][0]["costs"], "funding_daily", "0")):
            place[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.load()
            del place[key]

    def test_duplicate_json_keys(self):
        self.write()
        body = self.path.read_bytes().replace(b'"scope":', b'"version": "duplicate", "scope":')
        self.path.write_bytes(body)
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            load(self.path, digest(body), self.base, ["BTC"], 0, 4*DAY, allow_declared_scenario=True)


if __name__ == "__main__":
    unittest.main()
