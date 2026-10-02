from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_joint_execution import fixture
from audit_notice_execution import fixture_notice
from contract_specs import digest
from history import DAY
from joint_execution import load, simulate_joint
from notice_execution import inspect, simulate_notice_joint, NoticePolicyError


class NoticeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rows, self.candidates, self.config, self.groups, self.inputs = fixture(self.root / "joint")
        self.archive = self.root / "notice"

    def notice(self, **kwargs):
        self.sha = fixture_notice(self.archive, **kwargs)

    def run_scenario(self):
        return simulate_notice_joint(self.rows, self.candidates, self.config, self.groups,
            notice_archive=self.archive, notice_sha256=self.sha, **self.inputs)

    def periods(self):
        return load(self.config.execution, self.rows, 0, 4*DAY, **self.inputs)[0]

    def test_midnight_change_checks_both_sides_and_preserves_accounting(self):
        self.notice()
        actual = self.run_scenario()
        baseline = simulate_joint(self.rows, self.candidates, self.config, self.groups, **self.inputs)
        self.assertEqual(actual["summary"], baseline["summary"])
        self.assertEqual(actual["equity_curve"], baseline["equity_curve"])
        self.assertEqual(actual["daily_notice_policy"]["policy_status"], "PASSED")
        self.assertTrue(all(t["notice_manifest_sha256"] == self.sha for t in actual["trades"]))

    def test_intraday_blocks_before_joint_loader_and_engine(self):
        self.notice(effective_at="1970-01-02T08:00:00Z")
        with patch("notice_execution.load") as loader, patch("notice_execution.simulate_joint") as engine:
            with self.assertRaises(NoticePolicyError) as ctx:
                self.run_scenario()
            self.assertEqual(ctx.exception.report["blockers"][0]["bar_start"], DAY)
            self.assertEqual(ctx.exception.report["checked_events"][0]["effective_timestamp"], DAY+28800)
        loader.assert_not_called()
        engine.assert_not_called()

    def test_each_side_conflict_blocks_engine(self):
        for side in ("before", "after"):
            archive = self.root / side
            sha = fixture_notice(archive, **{side: "3"})
            with patch("notice_execution.simulate_joint") as engine, self.assertRaises(NoticePolicyError) as ctx:
                simulate_notice_joint(self.rows, self.candidates, self.config, self.groups,
                    notice_archive=archive, notice_sha256=sha, **self.inputs)
            self.assertEqual(ctx.exception.report["blockers"][0]["side"], side)
            engine.assert_not_called()

    def test_start_boundary_checks_only_after(self):
        self.notice(effective_at="1970-01-01T00:00:00Z", before="9", after="2")
        self.assertEqual(self.run_scenario()["daily_notice_policy"]["policy_status"], "PASSED")

    def test_end_boundary_is_excluded(self):
        self.notice(effective_at="1970-01-05T00:00:00Z", before="9", after="10")
        r = self.run_scenario()["daily_notice_policy"]
        self.assertEqual(r["checked_events"], [])
        self.assertEqual(r["ignored_event_ids"], ["synthetic-change"])

    def test_outside_events_do_not_extend_validity(self):
        self.notice(effective_at="1970-01-06T08:00:00Z")
        r = self.run_scenario()["daily_notice_policy"]
        self.assertEqual(r["verified_coverage_seconds"], 0)
        self.assertFalse(r["historical_specs_verified"])
        self.assertEqual(r["acceptance_status"], "NOT_VALIDATED")

    def test_unrequested_asset_event_does_not_block(self):
        self.notice(effective_at="1970-01-02T08:00:00Z")
        r = inspect(self.archive, self.sha, ["BTC"], 0, 4*DAY)
        self.assertEqual(r["policy_status"], "PASSED")
        self.assertEqual(r["verified_coverage_seconds"], 0)

    def test_midnight_without_mapping_blocks(self):
        self.notice()
        r = inspect(self.archive, self.sha, ["ETH"], 0, 4*DAY)
        self.assertEqual(r["blockers"][0]["reason"], "DAILY_SPECIFICATION_MAPPING_REQUIRED")

    def test_invalid_windows_and_symbols(self):
        self.notice()
        for start, end, symbols in ((True, DAY, ["ETH"]), (1, DAY, ["ETH"]),
            (DAY, DAY, ["ETH"]), (0, DAY, []), (0, DAY, ["eth"]), (0, DAY, ["ETH", "ETH"])):
            with self.subTest(start=start, end=end, symbols=symbols), self.assertRaises(ValueError):
                inspect(self.archive, self.sha, symbols, start, end)

    def test_period_symbol_mismatch_and_gaps_rejected(self):
        self.notice()
        with self.assertRaises(ValueError):
            inspect(self.archive, self.sha, ["ETH"], 0, 4*DAY, self.periods())
        periods = self.periods()
        periods["ETH"].pop(0)
        with self.assertRaises(ValueError):
            inspect(self.archive, self.sha, self.rows, 0, 4*DAY, periods)

    def test_tampering_before_execution(self):
        self.notice()
        (self.archive / "fixture.txt").write_bytes(b"tampered")
        with patch("notice_execution.simulate_joint") as engine, self.assertRaises(ValueError):
            self.run_scenario()
        engine.assert_not_called()

    def test_evidence_rechecked_after_execution(self):
        self.notice()
        for filename in ("fixture.txt", "notices.json"):
            path = self.archive / filename
            original = path.read_bytes()
            def mutate(*args, **kwargs):
                result = simulate_joint(*args, **kwargs)
                path.write_bytes(original + b" ")
                return result
            with self.subTest(filename=filename), patch("notice_execution.simulate_joint", side_effect=mutate):
                with self.assertRaises(ValueError):
                    self.run_scenario()
            path.write_bytes(original)
        self.assertEqual(digest((self.archive / "notices.json").read_bytes()), self.sha)

    def test_empty_rows_rejected(self):
        self.notice()
        self.rows["ETH"] = []
        with self.assertRaises(ValueError):
            self.run_scenario()


if __name__ == "__main__":
    unittest.main()
