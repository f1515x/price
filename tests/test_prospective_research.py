import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from history import DAY, prepare, save_snapshot
from m6_research import aggregate, sha
from prospective_research import load_registration, partition, run, validate_data
import test_research_registration as registration_tests


class ProspectiveTests(unittest.TestCase):
    def setUp(self):
        self.fixture = registration_tests.RegistrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.record = self.fixture.register()
        self.root = self.fixture.root
        self.output = self.root / "result.json"
        self.now = datetime(2026, 10, 1, 20, tzinfo=timezone.utc)

    def load(self):
        return load_registration(self.fixture.output, self.fixture.path,
                                 self.fixture.fixture.protocol_path, sha(self.fixture.output))

    def rewrite(self):
        self.fixture.output.write_text(json.dumps(self.record), encoding="utf-8")

    def execute(self, root=None, expected=None):
        return run(root or self.root / "missing-data", self.fixture.output, self.fixture.path,
                   self.fixture.fixture.protocol_path, expected or sha(self.fixture.output),
                   self.output, now=self.now)

    def synthetic(self):
        bounds = self.record["folds"]
        left, right = bounds[0]["test_start"] - 400 * DAY, bounds[-1]["test_end"]
        self.now = datetime.fromtimestamp(right, timezone.utc)
        rows, quality = {}, {}
        for s in self.record["protocol"]["assets"]:
            raw = []
            for i, t in enumerate(range(left, right, DAY)):
                price = 100 * math.exp(.25 * math.sin(i / 31) + .04 * math.sin(i / 7))
                raw.append(dict(t=t, o=price, h=price * 1.05, l=price * .95, c=price, v=1))
            rows[s], quality[s] = prepare(raw, s, left, right, right)
            save_snapshot(self.root / (s + "-daily"), raw, rows[s], quality[s])
        return rows, quality

    def test_waiting_never_reads_snapshots_or_produces_outcomes(self):
        with patch("prospective_research.load_snapshot", side_effect=AssertionError("No data read")):
            result = self.execute()
        self.assertEqual(result["status"], "AWAITING_FUTURE_DATA")
        self.assertEqual(result["complete_folds"], 0)
        self.assertEqual(result["experiments"], [])
        self.assertEqual(result["acceptance"]["status"], "NOT_VALIDATED")
        self.assertTrue(result["no_orders"])

    def test_interim_profitable_folds_cannot_trigger_early_evaluation(self):
        self.now = datetime.fromtimestamp(self.record["folds"][3]["test_end"], timezone.utc)
        with patch("prospective_research.evaluate", side_effect=AssertionError("No interim test")):
            result = self.execute()
        self.assertEqual(result["complete_folds"], 4)
        self.assertEqual(result["aggregates"], [])

    def test_final_fold_close_is_required_and_naive_or_backdated_clock_rejected(self):
        for clock in (datetime(2026, 10, 1), datetime(2026, 9, 30, tzinfo=timezone.utc)):
            self.now = clock
            with self.assertRaises(ValueError):
                self.execute()
        self.now = datetime.fromtimestamp(self.record["folds"][-1]["test_end"] - 1, timezone.utc)
        self.assertEqual(self.execute()["status"], "AWAITING_FUTURE_DATA")

    def test_reviewed_registration_hash_is_mandatory(self):
        with self.assertRaisesRegex(ValueError, "Registration SHA-256"):
            self.execute(expected="0" * 64)
        self.assertFalse(self.output.exists())

    def test_changed_candidate_or_original_protocol_is_rejected(self):
        original = self.fixture.path.read_bytes()
        self.fixture.path.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "Candidate differs"):
            self.load()
        self.fixture.path.write_bytes(original)
        self.fixture.fixture.protocol_path.write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "Original terminated protocol"):
            self.load()

    def test_changed_fold_variant_or_policy_is_rejected(self):
        original = copy.deepcopy(self.record)
        for section in ("folds", "variants", "evaluation_policy"):
            self.record = copy.deepcopy(original)
            if section == "folds":
                self.record[section][0]["test_start"] -= DAY
            elif section == "variants":
                self.record[section][0]["execution"]["entry_atr"] = 1
            else:
                self.record[section]["early_promotion"] = True
            self.rewrite()
            with self.assertRaisesRegex(ValueError, "Frozen"):
                self.load()

    def test_frozen_code_change_or_missing_manifest_is_rejected(self):
        self.record["source_sha256"]["trade_simulation.py"] = "0" * 64
        self.rewrite()
        with self.assertRaisesRegex(ValueError, "Frozen source differs"):
            self.load()
        del self.record["source_sha256"]["trade_simulation.py"]
        self.rewrite()
        with self.assertRaisesRegex(ValueError, "manifest is incomplete"):
            self.load()

    def test_existing_result_is_never_overwritten(self):
        self.execute()
        original = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual(self.output.read_bytes(), original)

    def test_prefold_close_and_fixed_44_day_tail_are_excluded(self):
        rows = [dict(timestamp=i * DAY) for i in range(500)]
        cs = [dict(index=i, signal_time=(i + 1) * DAY) for i in range(500)]
        fold = dict(test_start=100 * DAY, test_end=465 * DAY)
        bars, candidates, _ = partition(rows, cs, list(range(500)), fold, 44)
        self.assertEqual(candidates[0]["signal_time"], 101 * DAY)
        self.assertEqual(candidates[-1]["signal_time"], 420 * DAY)
        self.assertEqual(bars[0]["timestamp"], 100 * DAY)
        self.assertTrue(all(c["signal_time"] == bars[c["index"]]["timestamp"] + DAY for c in candidates))

    def test_truncated_exposed_history_cannot_be_substituted_for_future_folds(self):
        rows, quality = self.synthetic()
        rows["BTC"] = rows["BTC"][:-1]
        with self.assertRaisesRegex(ValueError, "Complete future folds"):
            validate_data(rows, quality, self.record["protocol"], self.record["folds"], self.now)

    def test_data_gaps_quality_identity_and_unclosed_bars_fail_closed(self):
        rows, quality = self.synthetic()
        original = copy.deepcopy(quality)
        quality["BTC"]["issues"] = [dict(reason="CONFLICTING_DUPLICATE")]
        with self.assertRaisesRegex(ValueError, "quality issues"):
            validate_data(rows, quality, self.record["protocol"], self.record["folds"], self.now)
        quality = original
        quality["BTC"]["symbol"] = "SOL"
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_data(rows, quality, self.record["protocol"], self.record["folds"], self.now)
        quality["BTC"]["symbol"] = "BTC"
        with self.assertRaisesRegex(ValueError, "future or unclosed"):
            validate_data(rows, quality, self.record["protocol"], self.record["folds"],
                          datetime.fromtimestamp(self.now.timestamp() - 1, timezone.utc))
        rows["BTC"].pop(500)
        with self.assertRaisesRegex(ValueError, "Complete future folds"):
            validate_data(rows, quality, self.record["protocol"], self.record["folds"], self.now)

    def test_insufficient_warmup_and_different_asset_grids_are_rejected(self):
        rows, quality = self.synthetic()
        rows["BTC"] = rows["BTC"][6:]
        with self.assertRaisesRegex(ValueError, "causal warmup"):
            validate_data(rows, quality, self.record["protocol"], self.record["folds"], self.now)
        rows, quality = self.synthetic_in_memory()
        rows["BTC"] = rows["BTC"][1:]
        with self.assertRaisesRegex(ValueError, "Identical verified"):
            validate_data(rows, quality, self.record["protocol"], self.record["folds"], self.now)

    def synthetic_in_memory(self):
        from history import load_snapshot
        pairs = {s: load_snapshot(self.root / (s + "-daily")) for s in ("BTC", "ETH")}
        return {s: p[0] for s, p in pairs.items()}, {s: p[1] for s, p in pairs.items()}

    def test_all_five_folds_run_frozen_variants_and_both_rules_with_accounting(self):
        rows, quality = self.synthetic()
        left, right = self.record["folds"][0]["test_start"], self.record["folds"][-1]["test_end"]
        reports = {s: dict(symbol=s, start=left, end_exclusive=right,
                           status="COMPLETE_ASSUMED_GRID",
                           records=[dict(timestamp=t, rate=.0001) for t in range(left, right, 28800)])
                   for s in rows}
        marks = {s: dict(symbol=s, start=left, end_exclusive=right, interval="1d",
                         bars=[dict(t=t, o=100, h=105, l=95) for t in range(left, right, DAY)]) for s in rows}

        def replay_fixture(bars, config):
            # Deterministic confirmed structures isolate orchestration. Existing
            # structure replay tests exercise actual pivot causality separately.
            return [dict(status="OK", weak_type="low", ratio=-.2,
                         raw_weak_price=100, strong_price=120) for _ in bars]

        def periods(root, names, cfg, start, end):
            return {s: [dict(start=start, end=end, config=cfg, source="synthetic", verified_fields=[])] for s in names}

        with patch("prospective_research.replay", side_effect=replay_fixture), \
                patch("prospective_research.load_funding", side_effect=lambda p: reports[p.name.split("-")[0]]), \
                patch("prospective_research.load_marks", side_effect=lambda p: marks[p.name.split("-")[0]]), \
                patch("prospective_research.periods_for", side_effect=periods):
            result = self.execute(root=self.root)
        self.assertEqual(result["status"], "COMPLETED_RESEARCH_ONLY")
        self.assertEqual(len(result["experiments"]), 240)
        self.assertEqual(len(result["aggregates"]), 48)
        self.assertEqual({e["rule"] for e in result["experiments"]}, {"percentile_move", "legacy_proxy"})
        self.assertIn("exact_cost_evidence", result["acceptance"]["failed"])
        self.assertIn("verified_historical_specs", result["acceptance"]["failed"])
        self.assertEqual(result["acceptance"]["status"], "NOT_VALIDATED")
        self.assertGreater(sum(len(e["result"]["trades"]) for e in result["experiments"]), 0)
        for e in result["experiments"]:
            account = e["result"]
            self.assertAlmostEqual(account["summary"]["final_equity"],
                                   10000 + sum(t["net_pnl"] for t in account["trades"]))
            self.assertEqual(account["equity_curve"][0]["timestamp"], e["start"] + DAY)
            self.assertTrue(all(e["start"] + DAY <= t["signal_time"] < e["end"] - 44 * DAY
                                for t in account["trades"]))
        for a in result["aggregates"]:
            accounts = [e["result"] for e in result["experiments"]
                        if (e["variant"], e["rule"], e["cost_mode"]) ==
                        (a["variant"], a["rule"], a["cost_mode"])]
            self.assertEqual(a["summary"], aggregate(accounts, ("BTC", "ETH")))


if __name__ == "__main__":
    unittest.main()
