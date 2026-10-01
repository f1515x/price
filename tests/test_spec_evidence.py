import json
from pathlib import Path
import tempfile
import unittest

from contract_specs import collect, digest, encoded
from spec_evidence import build, verify
from test_contract_specs import raw


class SpecEvidenceTests(unittest.TestCase):
    def snapshot(self, root, name, stamp=1000, **changes):
        path = Path(root) / name
        collect(["BTC"], path, fetch=lambda s: json.dumps(dict(raw(s), **changes)).encode(),
                clock=lambda: stamp)
        return path

    def ledger(self, root, paths, symbols=None, start=0, end=3000):
        path = Path(root) / "ledger"
        report = build(paths, path, symbols or ["BTC"], start, end)
        return path, report

    def check(self, path):
        return verify(path, digest((path / "ledger.json").read_bytes()))

    def test_roundtrip_dedup_and_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = self.snapshot(tmp, "one")
            before = {p.name: p.read_bytes() for p in snapshot.iterdir()}
            path, report = self.ledger(tmp, [snapshot, snapshot])
            self.assertEqual(self.check(path), report)
            self.assertEqual(len(report["snapshots"]), 1)
            archive = path / "snapshots" / report["snapshots"][0]["snapshot_sha256"]
            self.assertEqual({p.name: p.read_bytes() for p in archive.iterdir()}, before)
            self.assertEqual({p.name: p.read_bytes() for p in snapshot.iterdir()}, before)
            with self.assertRaises(FileExistsError):
                build([snapshot], path, ["BTC"], 0, 3000)

    def test_equal_snapshots_do_not_prove_intervals(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [self.snapshot(tmp, "one"), self.snapshot(tmp, "two", 2000)]
            _, report = self.ledger(tmp, paths)
            asset = report["assets"][0]
            self.assertEqual(asset["observed_changes"], [])
            self.assertEqual(asset["observations_in_window"], 2)
            self.assertEqual(asset["verified_coverage_seconds"], 0)
            self.assertEqual(asset["uncovered_intervals"], [dict(start=0, end=3000)])
            self.assertFalse(asset["historical_specs_verified"])
            self.assertFalse(asset["exact_costs_verified"])

    def test_sorted_change_has_no_invented_effective_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.snapshot(tmp, "one")
            second = self.snapshot(tmp, "two", 2000, order_price_round="0.2")
            path, report = self.ledger(tmp, [second, first])
            self.check(path)
            self.assertEqual(report["assets"][0]["observed_changes"],
                             [dict(previous_observed_at=1000, observed_at=2000,
                                   fields=["price_tick"], effective_time=None)])

    def test_equivalent_decimal_format_is_not_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.snapshot(tmp, "one")
            second = self.snapshot(tmp, "two", 2000, order_price_round="0.1000")
            _, report = self.ledger(tmp, [first, second])
            self.assertEqual(report["assets"][0]["observed_changes"], [])

    def test_missing_asset_and_half_open_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.snapshot(tmp, "one")
            _, report = self.ledger(tmp, [first], ["BTC", "ETH"], start=0, end=1000)
            self.assertEqual(report["assets"][0]["observations_in_window"], 0)
            self.assertIn("NO_SPEC_OBSERVATIONS", report["assets"][1]["reasons"])
            self.assertEqual(report["acceptance_status"], "NOT_VALIDATED")

    def test_decimal_and_halted_observations_report_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.snapshot(tmp, "one", enable_decimal=True, order_size_min="0", status="halted")
            _, report = self.ledger(tmp, [first])
            self.assertIn("UNRESOLVED_QUANTITY_PRECISION", report["assets"][0]["reasons"])
            self.assertIn("NON_TRADING_OBSERVATION", report["assets"][0]["reasons"])

    def test_conflicting_same_time_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.snapshot(tmp, "one")
            second = self.snapshot(tmp, "two", quanto_multiplier="0.001")
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                self.ledger(tmp, [first, second])
            self.assertFalse((Path(tmp) / "ledger").exists())

    def test_invalid_requests_have_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.snapshot(tmp, "one")
            for symbols, start, end in [([], 0, 1), (["BTC", "btc"], 0, 1),
                                        (["../BTC"], 0, 1), (["BTC"], True, 2),
                                        (["BTC"], 2, 1), (["BTC"], -1, 2)]:
                with self.subTest(symbols=symbols, start=start), self.assertRaises(ValueError):
                    build([first], Path(tmp) / "ledger", symbols, start, end)
            with self.assertRaises(ValueError):
                build([], Path(tmp) / "ledger", ["BTC"], 0, 1)
            self.assertFalse((Path(tmp) / "ledger").exists())

    def test_corrupt_source_and_duplicate_json_rejected(self):
        for content in (b"{}", b'{"name":"BTC_USDT","name":"BTC_USDT"}'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                first = self.snapshot(tmp, "one")
                (first / "BTC-raw.json").write_bytes(content)
                with self.assertRaises(ValueError):
                    self.ledger(tmp, [first])
                self.assertFalse((Path(tmp) / "ledger").exists())

    def test_pinned_hash_and_archived_bytes_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.snapshot(tmp, "one")
            path, report = self.ledger(tmp, [first])
            with self.assertRaisesRegex(ValueError, "reviewed"):
                verify(path, "0" * 64)
            archive = path / "snapshots" / report["snapshots"][0]["snapshot_sha256"]
            (archive / "BTC-raw.json").write_bytes(b"{}")
            with self.assertRaises(ValueError):
                self.check(path)

    def test_forged_coverage_cannot_pass_even_with_new_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.snapshot(tmp, "one")
            path, report = self.ledger(tmp, [first])
            report["assets"][0]["historical_specs_verified"] = True
            (path / "ledger.json").write_bytes(encoded(report))
            with self.assertRaisesRegex(ValueError, "recomputation"):
                self.check(path)

    def test_manifest_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.snapshot(tmp, "one")
            path, report = self.ledger(tmp, [first])
            report["snapshots"][0]["snapshot_sha256"] = "../outside"
            (path / "ledger.json").write_bytes(encoded(report))
            with self.assertRaisesRegex(ValueError, "Invalid snapshot"):
                self.check(path)


if __name__ == "__main__":
    unittest.main()
