import copy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contract_specs import digest, encoded
from dated_specifications import FIELDS
from execution_history import at_time
from history import DAY
from portfolio_simulation import PortfolioConfig
from reviewed_specifications import load, simulate_review
from spec_field_review import MARKET, VERSION
from test_trade_simulation import cfg, data, candidate


class ReviewedSpecificationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "review.json"
        self.body = b"SYNTHETIC assertions only; not historical issuer evidence.\n"
        self.path.with_name("fixture.txt").write_bytes(self.body)
        self.ledger = dict(version=VERSION, scope="REVIEW_ASSERTIONS_ONLY", market=MARKET,
            documents=dict(fixture=dict(file="fixture.txt", sha256=digest(self.body),
                origin="synthetic fixture", kind="effective_notice")), claims=[])
        specs = (dict(multiplier="1", quantity_step="1", min_quantity="1", max_quantity="2", price_tick="0.1"),
                 dict(multiplier="1", quantity_step="0.1", min_quantity="0.1", max_quantity="2.5", price_tick="0.1"))
        for i, (start, end) in enumerate(((0, DAY), (DAY, 3*DAY))):
            for field in FIELDS:
                self.ledger["claims"].append(dict(id=f"BTC-{i}-{field}", symbol="BTC", field=field,
                    value=specs[i][field], start=start, end=end, document="fixture", excerpt_start=0,
                    excerpt_end=len(self.body), excerpt=self.body.decode(), reviewer="fixture",
                    rationale="Synthetic execution arithmetic"))

    def write(self):
        self.path.write_bytes(encoded(self.ledger))
        return digest(self.path.read_bytes())

    def load(self, symbols=("BTC",), start=0, end=3*DAY):
        return load(self.path, self.write(), cfg(), symbols, start, end, allow_reviewed_scenario=True)

    def run_simulation(self, names=("BTC",)):
        rows = {s: [dict(r, symbol=s) for r in data([(100,105,95,100)]*3)] for s in names}
        return simulate_review(rows, {s: [candidate()] for s in names}, PortfolioConfig(cfg(), .05, 2),
            {s: "crypto" for s in names}, self.path, self.write(), allow_reviewed_scenario=True)

    def test_boundary_resolution_and_preserved_risk_costs(self):
        periods, report = self.load()
        self.assertEqual(at_time(periods["BTC"], DAY-1).max_quantity, 2)
        self.assertEqual(at_time(periods["BTC"], DAY).max_quantity, 2.5)
        for p in periods["BTC"]:
            self.assertFalse(p["verified_fields"])
            self.assertEqual({k:v for k,v in asdict(p["config"]).items() if k not in FIELDS},
                             {k:v for k,v in asdict(cfg()).items() if k not in FIELDS})
        self.assertFalse(report["historical_specs_verified"])
        self.assertFalse(report["exact_costs_verified"])
        self.assertFalse(report["used_for_execution_parameters"])

    def test_fill_time_provenance_and_cash(self):
        result = self.run_simulation()
        trade = result["trades"][0]
        self.assertEqual(trade["quantity"], 2.5)
        self.assertEqual(trade["entry_time"], DAY)
        ref = trade["entry_specification_review"]
        self.assertEqual(ref["claim_ids_by_field"]["max_quantity"], ["BTC-1-max_quantity"])
        self.assertEqual(ref["ledger_sha256"], digest(self.path.read_bytes()))
        self.assertEqual(result["summary"]["final_equity"], 10000 + sum(t["net_pnl"] for t in result["trades"]))
        self.assertTrue(result["reviewed_specification_evidence"]["used_for_execution_parameters"])
        self.assertEqual(result["reviewed_specification_evidence"]["acceptance_status"], "NOT_VALIDATED")

    def test_multiasset_isolation(self):
        for c in list(self.ledger["claims"]):
            self.ledger["claims"].append(dict(c, id=c["id"].replace("BTC", "ETH"), symbol="ETH",
                value="0.01" if c["field"] == "multiplier" else c["value"]))
        result = self.run_simulation(("BTC", "ETH"))
        self.assertEqual({t["symbol"] for t in result["trades"]}, {"BTC", "ETH"})
        for trade in result["trades"]:
            ids = trade["entry_specification_review"]["claim_ids_by_field"]
            self.assertTrue(all(i.startswith(trade["symbol"]) for refs in ids.values() for i in refs))

    def test_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, "Explicit"):
            load(self.path, self.write(), cfg(), ["BTC"], 0, 3*DAY)

    def test_missing_field_blocks_execution(self):
        self.ledger["claims"].pop()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            self.run_simulation()

    def test_conflict_blocks_execution(self):
        self.ledger["claims"].append(dict(self.ledger["claims"][-1], id="conflict", value="0.2"))
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.run_simulation()

    def test_same_value_overlap_keeps_both_claims(self):
        self.ledger["claims"].append(dict(self.ledger["claims"][-1], id="equivalent", value="0.100"))
        _, report = self.load()
        self.assertEqual(report["provenance"]["BTC"][1]["claim_ids_by_field"]["price_tick"],
                         ["BTC-1-price_tick", "equivalent"])

    def test_empty_and_observations_not_executable(self):
        for kind in ("observation", "synthetic"):
            self.ledger["documents"]["fixture"]["kind"] = kind
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "Incomplete"):
                self.load()
        self.ledger["documents"], self.ledger["claims"] = {}, []
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            self.load()

    def test_joint_quantity_validation(self):
        for c in self.ledger["claims"]:
            if c["field"] == "quantity_step":
                c["value"] = "0.3"
        with self.assertRaisesRegex(ValueError, "align"):
            self.load()

    def test_joint_quantity_bounds_validation(self):
        for c in self.ledger["claims"]:
            if c["field"] == "max_quantity":
                c["value"] = "0.1"
        with self.assertRaisesRegex(ValueError, "align|below minimum"):
            self.load()

    def test_independent_field_boundaries_are_combined(self):
        for c in self.ledger["claims"]:
            if c["field"] == "price_tick":
                if c["start"] == 0:
                    c["end"] = 2*DAY
                else:
                    c.update(start=2*DAY, value="0.2")
        periods, report = self.load()
        self.assertEqual([(p["start"], p["end"]) for p in periods["BTC"]],
                         [(0, DAY), (DAY, 2*DAY), (2*DAY, 3*DAY)])
        self.assertEqual(at_time(periods["BTC"], DAY).max_quantity, 2.5)
        self.assertEqual(at_time(periods["BTC"], DAY).price_tick, .1)
        self.assertEqual(at_time(periods["BTC"], 2*DAY).price_tick, .2)
        self.assertEqual(report["provenance"]["BTC"][1]["claim_ids_by_field"]["price_tick"],
                         ["BTC-0-price_tick"])

    def test_multiplier_conversion_unsupported(self):
        for c in self.ledger["claims"]:
            if c["field"] == "multiplier" and c["start"] == DAY:
                c["value"] = "2"
        with self.assertRaisesRegex(ValueError, "Multiplier changes"):
            self.load()

    def test_intraday_boundary_rejected_even_equal_value(self):
        self.ledger["claims"].append(dict(self.ledger["claims"][-1], id="intraday", start=DAY+1))
        with self.assertRaisesRegex(ValueError, "Intraday"):
            self.load()

    def test_nonrepresentable_values_rejected(self):
        original = copy.deepcopy(self.ledger)
        for value in ("1e999", "1e-999", "0.10000000000000000001"):
            self.ledger = copy.deepcopy(original)
            self.ledger["claims"][-1]["value"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "precision"):
                self.load()

    def test_clipping_and_daily_window(self):
        periods, _ = self.load(start=DAY, end=2*DAY)
        self.assertEqual([(p["start"], p["end"]) for p in periods["BTC"]], [(DAY, 2*DAY)])
        with self.assertRaisesRegex(ValueError, "daily boundaries"):
            self.load(start=1)

    def test_hash_document_and_forged_authentication(self):
        sha = self.write()
        with self.assertRaisesRegex(ValueError, "ledger differs"):
            load(self.path, "0"*64, cfg(), ["BTC"], 0, 3*DAY, allow_reviewed_scenario=True)
        self.path.with_name("fixture.txt").write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "Document hash"):
            self.load()
        self.path.with_name("fixture.txt").write_bytes(self.body)
        self.ledger["claims"][0]["verified"] = True
        with self.assertRaises(ValueError):
            self.load()

    def test_evidence_mutation_during_simulation_fails_closed(self):
        from portfolio_simulation import simulate
        def mutate(*args, **kwargs):
            result = simulate(*args, **kwargs)
            self.path.with_name("fixture.txt").write_bytes(b"changed during run")
            return result
        with patch("reviewed_specifications.simulate", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "Document hash"):
                self.run_simulation()


if __name__ == "__main__":
    unittest.main()
