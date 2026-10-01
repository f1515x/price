import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from m6_research import run
from research_decision import digest
from research_registration import register, read_json
import test_research_decision as decision_tests


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = decision_tests.DecisionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        source = Path(__file__).resolve().parents[1]
        self.previous = json.loads((source / "research/m6_protocol.json").read_bytes())
        self.fixture.protocol = self.previous
        self.fixture.protocol_path.write_text(json.dumps(self.previous), encoding="utf-8")
        self.fixture.report["protocol"] = dict(self.previous, preregistered_file_sha256=digest(self.fixture.protocol_path.read_bytes()))
        self.fixture.recompute_acceptance()
        self.fixture.close()
        self.candidate = json.loads((source / "research/m6_restart_protocol.json").read_bytes())
        self.path = self.root / "candidate.json"
        self.output = self.root / "registration.json"
        self.now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)

    def register(self):
        self.path.write_text(json.dumps(self.candidate), encoding="utf-8")
        return register(self.path, self.fixture.report_path, self.fixture.protocol_path,
                        digest(self.fixture.report_path.read_bytes()), self.output, now=self.now)

    def test_registration_preserves_gates_and_freezes_future_folds(self):
        result = self.register()
        self.assertEqual(result["status"], "REGISTERED_AWAITING_FUTURE_DATA")
        self.assertEqual(result["protocol"]["acceptance"], self.previous["acceptance"])
        self.assertEqual(result["predecessor"]["decision"], "TERMINATED")
        self.assertEqual(len(result["folds"]), 5)
        self.assertEqual(len(result["variants"]), 12)
        self.assertEqual(result["candidate_sha256"], digest(self.path.read_bytes()))
        self.assertTrue(result["evaluation_policy"]["exact_cost_evidence_required"])
        for left, right in zip(result["folds"], result["folds"][1:]):
            self.assertEqual(left["test_end"], right["test_start"])

    def test_reusing_exposed_data_or_registration_day_is_rejected(self):
        for day in ("2020-01-01", "2026-10-01", "2026-11-14"):
            with self.subTest(day=day):
                self.candidate["test_start"] = day
                with self.assertRaisesRegex(ValueError, "future, unexposed"):
                    self.register()
                self.assertFalse(self.output.exists())

    def test_late_registration_cannot_backdate_frozen_test(self):
        self.now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "future, unexposed"):
            self.register()

    def test_lowered_gates_and_profitable_parameter_selection_are_rejected(self):
        original = copy.deepcopy(self.candidate)
        for section, key, value in (("acceptance", "min_trades", 1),
                                    ("execution", "entry_atr", 1),
                                    ("execution", "risk_fraction", .01)):
            with self.subTest(key=key):
                self.candidate = copy.deepcopy(original)
                self.candidate[section][key] = value
                with self.assertRaisesRegex(ValueError, "preserved"):
                    self.register()

    def test_old_hypothesis_equivalent_rule_and_optional_stopping_are_rejected(self):
        original = copy.deepcopy(self.candidate)
        for key, value in (("hypothesis_id", self.previous["version"] + ":percentile_structure:base"),
                           ("primary_rule", "percentile"), ("test_folds", True), ("test_folds", 1),
                           ("unknown", 1)):
            with self.subTest(key=key):
                self.candidate = dict(original, **{key: value})
                with self.assertRaises(ValueError):
                    self.register()

    def test_existing_registration_is_not_overwritten(self):
        self.register()
        original = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            self.register()
        self.assertEqual(self.output.read_bytes(), original)

    def test_duplicate_keys_and_nonfinite_parameters_are_rejected(self):
        for text in ('{"version":1,"version":2}', '{"value":NaN}'):
            self.path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                read_json(self.path)

    def test_changed_reviewed_evidence_blocks_registration(self):
        self.path.write_text(json.dumps(self.candidate), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Report SHA-256"):
            register(self.path, self.fixture.report_path, self.fixture.protocol_path,
                     "0" * 64, self.output, now=self.now)

    def test_changed_feature_defaults_are_rejected(self):
        self.candidate["events"]["move"] = 1
        with self.assertRaisesRegex(ValueError, "feature defaults"):
            self.register()

    def test_old_runner_cannot_silently_ignore_new_hypothesis(self):
        with self.assertRaisesRegex(ValueError, "separate runner"):
            run(self.root / "missing-data", self.candidate, self.output)


if __name__ == "__main__":
    unittest.main()
