import json
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from contract_specs import collect, digest, encoded
from prospective_evidence import assess
from prospective_research import run
from spec_evidence import build
from test_contract_specs import raw
import test_prospective_research as executor_tests


class ProspectiveEvidenceTests(unittest.TestCase):
    # Use setup helpers without rerunning inherited executor tests.
    setUp = executor_tests.ProspectiveTests.setUp

    def ledger(self, symbols=("BTC", "ETH"), requested=None, stamp=None):
        path = self.root / "specs"
        collect(list(symbols), path, fetch=lambda s: json.dumps(raw(s)).encode(),
                clock=lambda: int(self.now.timestamp()) if stamp is None else stamp)
        target = self.root / "ledger"
        build([path], target, list(requested or symbols), 0, 3000)
        return target, digest((target / "ledger.json").read_bytes())

    def with_evidence(self, path=None, pin=None):
        return run(self.root / "missing-data", self.fixture.output, self.fixture.path,
                   self.fixture.fixture.protocol_path, digest(self.fixture.output.read_bytes()),
                   self.output, now=self.now, evidence_ledger=path, expected_evidence_sha256=pin)

    def test_integration_recomputes_registered_windows_and_preserves_input(self):
        path, pin = self.ledger()
        before = {str(p): p.read_bytes() for p in path.rglob("*") if p.is_file()}
        with patch("prospective_research.load_snapshot", side_effect=AssertionError("No market data")):
            report = self.with_evidence(path, pin)
        evidence = report["specification_evidence"]
        self.assertEqual(evidence["status"], "VERIFIED_OBSERVATIONS_ONLY")
        self.assertEqual(evidence["ledger_sha256"], pin)
        self.assertEqual(evidence["ledger_required_window"]["end"], 3000)
        self.assertEqual(len(evidence["folds"]), 5)
        for fold, bounds in zip(evidence["folds"], self.record["folds"]):
            self.assertEqual(fold["required_window"]["start"], bounds["test_start"])
            self.assertEqual(fold["required_window"]["end"], bounds["test_end"])
            for asset in fold["assets"]:
                self.assertEqual(asset["observation_count"], 1)
                self.assertEqual(asset["observations_in_window"], 0)
                self.assertEqual(asset["uncovered_intervals"],
                                 [dict(start=bounds["test_start"], end=bounds["test_end"])])
        self.assertEqual(report["status"], "AWAITING_FUTURE_DATA")
        self.assertEqual(report["experiments"], [])
        self.assertFalse(evidence["used_for_execution_parameters"])
        self.assertEqual(before, {str(p): p.read_bytes() for p in path.rglob("*") if p.is_file()})

    def test_no_ledger_explicitly_reports_all_asset_and_fold_gaps(self):
        result = self.with_evidence()
        evidence = result["specification_evidence"]
        self.assertEqual(evidence["status"], "NO_LEDGER_PROVIDED")
        self.assertIsNone(evidence["ledger_sha256"])
        for fold in evidence["folds"]:
            self.assertEqual([a["symbol"] for a in fold["assets"]], ["BTC", "ETH"])
            self.assertTrue(all("NO_SPEC_OBSERVATIONS" in a["reasons"] for a in fold["assets"]))
        self.assertFalse(result["acceptance"]["checks"]["verified_historical_specs"])
        self.assertFalse(result["acceptance"]["checks"]["exact_cost_evidence"])

    def test_directory_and_pin_must_be_paired_before_output(self):
        for path, pin in ((self.root, None), (None, "0" * 64)):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "required together"):
                self.with_evidence(path, pin)
            self.assertFalse(self.output.exists())

    def test_bad_pin_or_corrupt_archive_rejects_before_output(self):
        path, pin = self.ledger()
        with self.assertRaisesRegex(ValueError, "reviewed"):
            self.with_evidence(path, "0" * 64)
        next((path / "snapshots").rglob("BTC-raw.json")).write_bytes(b"{}")
        with self.assertRaises(ValueError):
            self.with_evidence(path, pin)
        self.assertFalse(self.output.exists())

    def test_missing_registered_asset_stays_visible(self):
        path, pin = self.ledger(symbols=("BTC",))
        evidence = assess(self.record, path, pin, now=self.now)
        for fold in evidence["folds"]:
            btc, eth = fold["assets"]
            self.assertEqual(btc["observation_count"], 1)
            self.assertEqual(eth["observation_count"], 0)
            self.assertIn("NO_SPEC_OBSERVATIONS", eth["reasons"])

    def test_archived_asset_not_in_original_ledger_is_recomputed(self):
        path, pin = self.ledger(requested=("BTC",))
        evidence = assess(self.record, path, pin, now=self.now)
        self.assertEqual(evidence["folds"][0]["assets"][1]["observation_count"], 1)

    def test_forged_verified_findings_rejected_even_with_repin(self):
        path, pin = self.ledger()
        ledger = json.loads((path / "ledger.json").read_bytes())
        ledger["assets"][0]["historical_specs_verified"] = True
        (path / "ledger.json").write_bytes(encoded(ledger))
        with self.assertRaisesRegex(ValueError, "recomputation"):
            self.with_evidence(path, digest((path / "ledger.json").read_bytes()))
        self.assertFalse(self.output.exists())

    def test_future_dated_evidence_rejected(self):
        path, pin = self.ledger(stamp=int(self.now.timestamp()) + 1)
        with self.assertRaisesRegex(ValueError, "postdates"):
            self.with_evidence(path, pin)
        self.assertFalse(self.output.exists())

    def test_completed_branch_keeps_evidence_gates_and_no_parameters_changed(self):
        path, pin = self.ledger()
        self.now = datetime.fromtimestamp(self.record["folds"][-1]["test_end"], timezone.utc)
        outcome = dict(status="COMPLETED_RESEARCH_ONLY", experiments=[], aggregates=[],
                       acceptance=dict(status="VALIDATED", checks={}, failed=[]))
        with patch("prospective_research.evaluate", return_value=outcome) as evaluate:
            result = self.with_evidence(path, pin)
        self.assertEqual(evaluate.call_args.args[1], self.record)
        self.assertEqual(result["acceptance"]["status"], "NOT_VALIDATED")
        self.assertEqual(result["acceptance"]["failed"], ["verified_historical_specs", "exact_cost_evidence"])
