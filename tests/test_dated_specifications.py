import copy
import json
from pathlib import Path
import tempfile
import unittest

from contract_specs import digest, encoded
from dated_specifications import VERSION, load, simulate_manifest
from execution_history import at_time
from history import DAY
from portfolio_simulation import PortfolioConfig
from test_trade_simulation import cfg, data, candidate


def specification(**changes):
    return dict(multiplier="1", quantity_step="1", min_quantity="1",
                max_quantity="2", price_tick="0.1", **changes)


class DatedSpecificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "manifest.json"
        source = self.path.with_name("fixture.txt")
        source.write_bytes(b"Synthetic declaration, not exchange evidence.\n")
        self.manifest = dict(version=VERSION, scope="DECLARED_SCENARIO_ONLY",
                             sources=dict(fixture=dict(file=source.name, sha256=digest(source.read_bytes()),
                                                       description="synthetic declaration")),
                             assets=dict(BTC=[dict(start=0, end=DAY, specification=specification(), sources=["fixture"]),
                                              dict(start=DAY, end=3*DAY,
                                                   specification=dict(specification(), quantity_step="0.1", min_quantity="0.1", max_quantity="2.5"),
                                                   sources=["fixture"])]))

    def write(self):
        self.path.write_bytes(encoded(self.manifest))
        return digest(self.path.read_bytes())

    def load(self):
        return load(self.path, self.write(), cfg(), ["BTC"], 0, 3*DAY, allow_declared_scenario=True)

    def test_boundaries_preserve_risk_costs_and_unverified_status(self):
        periods, report = self.load()
        periods = periods["BTC"]
        self.assertEqual(at_time(periods, DAY-1).quantity_step, 1)
        self.assertEqual(at_time(periods, DAY).quantity_step, .1)
        with self.assertRaises(ValueError):
            at_time(periods, 3*DAY)
        for p in periods:
            self.assertEqual(p["verified_fields"], [])
            for key in ("fee_rate", "slippage", "funding_daily", "risk_fraction", "entry_atr", "stop_atr"):
                self.assertEqual(getattr(p["config"], key), getattr(cfg(), key))
        self.assertFalse(report["historical_specs_verified"])
        self.assertFalse(report["exact_costs_verified"])
        self.assertEqual(report["acceptance_status"], "NOT_VALIDATED")

    def test_fill_time_quantity_and_cash_reconcile(self):
        sha = self.write()
        result = simulate_manifest({"BTC": data([(100,105,95,100)]*3)}, {"BTC": [candidate()]},
                                   PortfolioConfig(cfg(), .05, 2), {"BTC": "crypto"}, self.path, sha,
                                   allow_declared_scenario=True)
        self.assertEqual(result["trades"][0]["quantity"], 2.5)
        self.assertEqual(result["trades"][0]["entry_time"], DAY)
        self.assertEqual(result["summary"]["final_equity"],
                         10000 + sum(t["net_pnl"] for t in result["trades"]))
        self.assertEqual(result["dated_specification_evidence"]["manifest_sha256"], sha)
        self.assertTrue(result["dated_specification_evidence"]["used_for_execution_parameters"])

    def test_explicit_scenario_required(self):
        with self.assertRaises(ValueError):
            load(self.path, self.write(), cfg(), ["BTC"], 0, 3*DAY)

    def test_multiasset_contract_units(self):
        self.manifest["assets"]["ETH"] = copy.deepcopy(self.manifest["assets"]["BTC"])
        for period in self.manifest["assets"]["ETH"]:
            period["specification"]["multiplier"] = "0.01"
        rows = {s: [dict(r, symbol=s) for r in data([(100,105,95,100)]*3)] for s in ("BTC", "ETH")}
        result = simulate_manifest(rows, {s: [candidate()] for s in rows}, PortfolioConfig(cfg(), .05, 2),
                                   {s: "crypto" for s in rows}, self.path, self.write(),
                                   allow_declared_scenario=True)
        self.assertEqual({t["symbol"] for t in result["trades"]}, {"BTC", "ETH"})
        self.assertEqual(result["summary"]["final_equity"],
                         10000 + sum(t["net_pnl"] for t in result["trades"]))

    def test_pending_order_cancelled_after_tick_change(self):
        self.manifest["assets"]["BTC"][0]["end"] = 2*DAY
        self.manifest["assets"]["BTC"][1]["start"] = 2*DAY
        self.manifest["assets"]["BTC"][1]["specification"]["price_tick"] = "3"
        result = simulate_manifest({"BTC": data([(110,115,105,110)]*3)}, {"BTC": [candidate()]},
                                   PortfolioConfig(cfg(), .05, 2), {"BTC": "crypto"}, self.path, self.write(),
                                   allow_declared_scenario=True)
        self.assertEqual(result["orders"][0]["status"], "EXECUTION_SPEC_CHANGED")
        self.assertFalse(result["trades"])

    def test_hash_and_source_corruption(self):
        sha = self.write()
        self.path.write_bytes(self.path.read_bytes()+b" ")
        with self.assertRaises(ValueError):
            load(self.path, sha, cfg(), ["BTC"], 0, 3*DAY, allow_declared_scenario=True)
        self.path.with_name("fixture.txt").write_bytes(b"corrupted")
        with self.assertRaises(ValueError):
            self.load()

    def test_gaps_overlaps_order_and_coverage(self):
        original = copy.deepcopy(self.manifest)
        for key, value in (("start", DAY+DAY), ("start", 0), ("end", 2*DAY)):
            self.manifest = copy.deepcopy(original)
            self.manifest["assets"]["BTC"][1][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.load()
        self.manifest = copy.deepcopy(original)
        self.manifest["assets"]["BTC"].reverse()
        with self.assertRaises(ValueError):
            self.load()

    def test_intraday_bool_negative_boundaries(self):
        for value in (True, -DAY, DAY+1):
            self.manifest["assets"]["BTC"][1]["start"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load()

    def test_multiplier_change_rejected(self):
        self.manifest["assets"]["BTC"][1]["specification"]["multiplier"] = "2"
        with self.assertRaisesRegex(ValueError, "Multiplier changes"):
            self.load()

    def test_precision_and_invalid_numeric_values(self):
        original = copy.deepcopy(self.manifest)
        for key, value in (("quantity_step", "0.3"), ("price_tick", "NaN"), ("multiplier", "1e999"),
                           ("min_quantity", "0"), ("max_quantity", "0.5"), ("price_tick", True),
                           ("multiplier", "oops")):
            self.manifest = copy.deepcopy(original)
            self.manifest["assets"]["BTC"][0]["specification"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.load()

    def test_asset_identity_missing_and_extra(self):
        for names in (["ETH"], ["BTC", "ETH"], ["btc"], ["BTC", "BTC"]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                load(self.path, self.write(), cfg(), names, 0, 3*DAY, allow_declared_scenario=True)

    def test_paths_and_unknown_sources(self):
        original = copy.deepcopy(self.manifest)
        for file in ("../outside", "C:/outside", "fixture.txt:stream"):
            self.manifest = copy.deepcopy(original)
            self.manifest["sources"]["fixture"]["file"] = file
            with self.subTest(file=file), self.assertRaises(ValueError):
                self.load()
        self.manifest = copy.deepcopy(original)
        self.manifest["assets"]["BTC"][0]["sources"] = ["missing"]
        with self.assertRaises(ValueError):
            self.load()

    def test_cannot_claim_verified_status_or_modify_costs(self):
        for place, key, value in ((self.manifest, "historical_specs_verified", True),
                                  (self.manifest["assets"]["BTC"][0]["specification"], "fee_rate", "0"),
                                  (self.manifest["assets"]["BTC"][0], "verified_fields", ["multiplier"])):
            place[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.load()
            del place[key]

    def test_duplicate_json_keys_rejected(self):
        self.write()
        body = self.path.read_bytes().replace(b'"scope":', b'"version": "duplicate", "scope":')
        self.path.write_bytes(body)
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            load(self.path, digest(body), cfg(), ["BTC"], 0, 3*DAY, allow_declared_scenario=True)


if __name__ == "__main__":
    unittest.main()
