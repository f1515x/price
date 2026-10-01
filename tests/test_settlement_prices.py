import copy
from pathlib import Path
import tempfile
import unittest

from contract_specs import digest, encoded
from funding_history import collect
from history import DAY
from portfolio_simulation import PortfolioConfig
from settlement_prices import VERSION, load, simulate_manifest
from test_trade_simulation import cfg, data, candidate


class SettlementPriceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "prices.json"
        self.source = self.root / "source.txt"
        self.source.write_bytes(b"Synthetic settlement prices, not certified exchange evidence.\n")
        self.manifest = dict(version=VERSION, scope="DECLARED_SCENARIO_ONLY",
            sources=dict(fixture=dict(file="source.txt", description="synthetic fixture",
                                     sha256=digest(self.source.read_bytes()))), assets={})
        self.add_asset("BTC")

    def add_asset(self, symbol):
        report = collect(symbol, 0, 4*DAY, self.root / symbol,
            fetch=lambda p: encoded([dict(t=t+1, r="0.001") for t in range(0, 4*DAY, 28800)]), clock=lambda: 4*DAY)
        self.manifest["assets"][symbol] = dict(funding_snapshot=symbol,
            funding_sha256=digest((self.root / symbol / "funding.json").read_bytes()),
            prices=[dict(timestamp=r["timestamp"], mark_price=str(70+10*i), sources=["fixture"])
                    for i, r in enumerate(report["records"])])

    def write(self):
        self.path.write_bytes(encoded(self.manifest))
        return digest(self.path.read_bytes())

    def load(self):
        return load(self.path, self.write(), self.manifest["assets"], 0, 4*DAY, allow_declared_scenario=True)

    def simulate(self, direction=1, **kwargs):
        rows = {s: [dict(r, symbol=s) for r in data([(100, 105, 95, 100)]*4)] for s in self.manifest["assets"]}
        return simulate_manifest(rows, {s: [candidate(direction=direction)] for s in rows},
            PortfolioConfig(cfg(max_quantity=2), .05, 2), {s: "crypto" for s in rows}, self.path,
            self.write(), allow_declared_scenario=True, **kwargs)

    def test_price_rate_join_and_reported_delay_retained(self):
        funding, evidence = self.load()
        self.assertEqual(funding["BTC"][DAY][1], dict(timestamp=DAY+28800,
            reported_timestamp=DAY+28801, rate=.001, mark_price=110))
        self.assertFalse(evidence["settlement_prices_verified"])
        self.assertEqual(evidence["assets"]["BTC"]["certified_settlements"], 0)
        self.assertEqual(evidence["acceptance_status"], "NOT_VALIDATED")

    def test_varying_settlement_prices_and_multiasset_cash(self):
        self.add_asset("ETH")
        result = self.simulate()
        self.assertEqual(len(result["trades"]), 2)
        for trade in result["trades"]:
            self.assertAlmostEqual(trade["funding"], 2.32)
            self.assertAlmostEqual(trade["net_pnl"], -2.32)
        self.assertAlmostEqual(result["summary"]["final_equity"], 9995.36)
        self.assertIn("declared_settlement_prices", result["funding_model"])
        self.assertFalse(result["settlement_price_evidence"]["exact_costs_verified"])

    def test_short_credits_conservative_entry_ownership(self):
        trade = self.simulate(direction=-1)["trades"][0]
        self.assertAlmostEqual(trade["funding"], -1.86)
        self.assertAlmostEqual(trade["net_pnl"], 1.86)

    def test_ambiguous_stop_day_withholds_credit(self):
        rows = data([(100, 105, 95, 100), (100, 105, 95, 100),
                     (100, 115, 95, 100), (100, 105, 95, 100)])
        result = simulate_manifest({"BTC": rows}, {"BTC": [candidate(direction=-1)]},
            PortfolioConfig(cfg(max_quantity=2), .05, 2), {"BTC": "crypto"}, self.path,
            self.write(), allow_declared_scenario=True)
        self.assertEqual(result["trades"][0]["reason"], "STOP")
        self.assertEqual(result["trades"][0]["funding"], 0)

    def test_negative_historical_rates_reverse_debits_and_credits(self):
        directory = self.root / "negative"
        collect("BTC", 0, 4*DAY, directory,
            fetch=lambda p: encoded([dict(t=t, r="-0.001") for t in range(0, 4*DAY, 28800)]))
        asset = self.manifest["assets"]["BTC"]
        asset.update(funding_snapshot="negative", funding_sha256=digest((directory / "funding.json").read_bytes()))
        self.assertAlmostEqual(self.simulate()["trades"][0]["funding"], -1.86)
        self.assertAlmostEqual(self.simulate(direction=-1)["trades"][0]["funding"], 2.32)

    def test_genuine_incomplete_archive_never_substitutes_zero(self):
        directory = self.root / "incomplete"
        collect("BTC", 0, 4*DAY, directory,
            fetch=lambda p: encoded([dict(t=t, r="0") for t in range(28800, 4*DAY, 28800)]))
        asset = self.manifest["assets"]["BTC"]
        asset.update(funding_snapshot="incomplete", funding_sha256=digest((directory / "funding.json").read_bytes()))
        with self.assertRaisesRegex(ValueError, "Complete matching"):
            self.load()

    def test_manifest_source_and_funding_hashes(self):
        sha = self.write()
        self.path.write_bytes(self.path.read_bytes()+b" ")
        with self.assertRaises(ValueError):
            load(self.path, sha, ["BTC"], 0, 4*DAY, allow_declared_scenario=True)
        self.source.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.load()
        self.manifest["sources"]["fixture"]["sha256"] = digest(self.source.read_bytes())
        archive = self.root / "BTC" / "funding.json"
        archive.write_bytes(archive.read_bytes()+b" ")
        with self.assertRaises(ValueError):
            self.load()

    def test_raw_funding_tamper(self):
        (self.root / "BTC" / "page-0000.json").write_bytes(b"[]")
        with self.assertRaises(ValueError):
            self.load()

    def test_missing_duplicate_reverse_offgrid_extra_prices(self):
        original = copy.deepcopy(self.manifest)
        for mutation in ("missing", "duplicate", "reverse", "offgrid", "bool", "extra"):
            self.manifest = copy.deepcopy(original)
            prices = self.manifest["assets"]["BTC"]["prices"]
            if mutation == "missing":
                prices.pop()
            elif mutation == "duplicate":
                prices[1] = copy.deepcopy(prices[0])
            elif mutation == "reverse":
                prices.reverse()
            elif mutation == "extra":
                prices.append(copy.deepcopy(prices[-1]))
            else:
                prices[0]["timestamp"] = True if mutation == "bool" else 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.load()

    def test_bad_prices_and_float_precision(self):
        for value in (True, 100, "0", "-1", "NaN", "Infinity", "1e999", "1e-999", "invalid"):
            self.manifest["assets"]["BTC"]["prices"][0]["mark_price"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load()

    def test_safe_paths_and_references(self):
        original = copy.deepcopy(self.manifest)
        for relative in ("../outside", "C:/outside", "source.txt:stream"):
            for field in ("source", "funding"):
                self.manifest = copy.deepcopy(original)
                if field == "source":
                    self.manifest["sources"]["fixture"]["file"] = relative
                else:
                    self.manifest["assets"]["BTC"]["funding_snapshot"] = relative
                with self.subTest(relative=relative, field=field), self.assertRaises(ValueError):
                    self.load()
        for refs in ([], ["unknown"], ["fixture", "fixture"], [True]):
            self.manifest = copy.deepcopy(original)
            self.manifest["assets"]["BTC"]["prices"][0]["sources"] = refs
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                self.load()

    def test_snapshot_identity_range_interval_and_completeness(self):
        from spec_evidence import _json
        archive = self.root / "BTC" / "funding.json"
        original = _json(archive.read_bytes())
        for key, value in (("symbol", "ETH"), ("market", "other"), ("start", DAY),
                           ("assumed_interval", 14400), ("status", "INCOMPLETE_DO_NOT_SIMULATE")):
            record = dict(original, **{key: value})
            archive.write_bytes(encoded(record))
            self.manifest["assets"]["BTC"]["funding_sha256"] = digest(archive.read_bytes())
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.load()

    def test_explicit_scope_assets_and_no_certification_or_bounds(self):
        with self.assertRaises(ValueError):
            load(self.path, self.write(), ["BTC"], 0, 4*DAY)
        for symbols in (["ETH"], ["BTC", "ETH"], ["BTC", "BTC"], ["btc"]):
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                load(self.path, self.write(), symbols, 0, 4*DAY, allow_declared_scenario=True)
        for target, key in ((self.manifest, "exact_costs_verified"),
                            (self.manifest["assets"]["BTC"]["prices"][0], "mark_high")):
            target[key] = True
            with self.assertRaises(ValueError):
                self.load()
            del target[key]

    def test_duplicate_json_keys_and_unused_sources(self):
        self.write()
        body = self.path.read_bytes().replace(b'"scope":', b'"version": "duplicate", "scope":')
        self.path.write_bytes(body)
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            load(self.path, digest(body), ["BTC"], 0, 4*DAY, allow_declared_scenario=True)
        self.manifest["sources"]["unused"] = dict(self.manifest["sources"]["fixture"])
        with self.assertRaises(ValueError):
            self.load()

    def test_invalid_window_and_empty_bars(self):
        for start, end in ((True, 4*DAY), (1, 4*DAY), (0, DAY+1), (DAY, DAY), (-DAY, DAY)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                load(self.path, self.write(), ["BTC"], start, end, allow_declared_scenario=True)
        with self.assertRaises(ValueError):
            simulate_manifest({"BTC": []}, {}, PortfolioConfig(cfg(), .05, 2), {}, self.path,
                              self.write(), allow_declared_scenario=True)


if __name__ == "__main__":
    unittest.main()
