import json
from pathlib import Path
import tempfile
import unittest

from contract_specs import digest, encoded
from audit_intraday_batch import audit
from intraday_batch import collect_batch, verify_batch


def fetch(url):
    return encoded([dict(t=0, o="100", h="102", l="99", c="101", v=1)])


class IntradayBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "batch"

    def collect(self, **kwargs):
        return collect_batch(self.path, ["btc", "ETH"], 0, 60, as_of=60, fetch=fetch, **kwargs)

    def rewrite(self, mutate):
        body = json.loads((self.path / "batch.json").read_bytes())
        mutate(body)
        raw = encoded(body)
        (self.path / "batch.json").write_bytes(raw)
        return digest(raw)

    def test_complete_multi_asset_roundtrip(self):
        sha, report = self.collect()
        self.assertEqual(verify_batch(self.path, sha), report)
        self.assertEqual(report["symbols"], ["BTC", "ETH"])
        self.assertEqual(report["expected_asset_minutes"], 2)
        self.assertEqual(report["valid_asset_minutes"], 2)
        self.assertEqual(report["quality_status"], "COMPLETE")
        self.assertFalse(report["market_fills_verified"])
        self.assertFalse(report["historical_specs_verified"])
        self.assertEqual(report["acceptance_status"], "NOT_VALIDATED")

    def test_duplicate_and_empty_assets_rejected_before_creation(self):
        for symbols in ([], ["btc", "BTC"], "BTC"):
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                collect_batch(self.path, symbols, 0, 60, as_of=60, fetch=fetch)
            self.assertFalse(self.path.exists())

    def test_partial_asset_does_not_hide_gaps(self):
        sha, report = collect_batch(self.path, ["BTC", "ETH"], 0, 60, as_of=60,
                                    fetch=lambda url: b"[]" if "ETH_USDT" in url else fetch(url))
        self.assertEqual(report["quality_status"], "INCOMPLETE_OR_ISSUES")
        self.assertEqual(report["assets"]["ETH"]["missing_timestamps"], [0])
        self.assertEqual(report["valid_asset_minutes"], 1)
        self.assertEqual(verify_batch(self.path, sha), report)

    def test_unclosed_window_reported_for_every_asset(self):
        sha, report = collect_batch(self.path, ["BTC", "ETH"], 0, 120, as_of=60, fetch=fetch)
        self.assertEqual(report["quality_status"], "INCOMPLETE_OR_ISSUES")
        for asset in report["assets"].values():
            self.assertEqual(asset["unclosed_minutes"], 1)
        self.assertEqual(verify_batch(self.path, sha), report)

    def test_failed_asset_preserves_evidence_without_batch_manifest(self):
        with self.assertRaises(ValueError):
            collect_batch(self.path, ["BTC", "ETH"], 0, 60, as_of=60,
                          fetch=lambda url: b"error" if "ETH_USDT" in url else fetch(url))
        self.assertTrue((self.path / "BTC" / "manifest.json").exists())
        self.assertEqual((self.path / "ETH" / "page-0000.json").read_bytes(), b"error")
        self.assertFalse((self.path / "batch.json").exists())

    def test_overwrite_and_pinned_manifest_tampering(self):
        sha, _ = self.collect()
        with self.assertRaises(FileExistsError):
            self.collect()
        (self.path / "batch.json").write_bytes(b"{}")
        with self.assertRaises(ValueError):
            verify_batch(self.path, sha)

    def test_recomputed_hash_cannot_hide_coverage_or_inventory_changes(self):
        self.collect()
        original = (self.path / "batch.json").read_bytes()
        mutations = [lambda b: b["report"].update(valid_asset_minutes=100),
                     lambda b: b["report"].update(market_fills_verified=True),
                     lambda b: b["archives"].pop(),
                     lambda b: b["archives"][0].update(directory="../BTC"),
                     lambda b: b["archives"][0].update(symbol="ETH"),
                     lambda b: b["report"].update(end_exclusive=120),
                     lambda b: b["report"].update(version="unknown")]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                (self.path / "batch.json").write_bytes(original)
                sha = self.rewrite(mutate)
                with self.assertRaises(ValueError):
                    verify_batch(self.path, sha)

    def test_child_raw_tampering_rejected(self):
        sha, _ = self.collect()
        (self.path / "ETH" / "page-0000.json").write_bytes(b"[]")
        with self.assertRaises(ValueError):
            verify_batch(self.path, sha)

    def registration(self, symbols):
        path = Path(self.tmp.name) / "registration.json"
        source = Path(__file__).parents[1] / "intraday_history.py"
        body = encoded(dict(protocol=dict(assets=symbols),
                            source_sha256={source.name: digest(source.read_bytes())}))
        path.write_bytes(body)
        return path, digest(body)

    def test_audit_checks_registered_inventory_and_frozen_sources(self):
        sha, _ = self.collect()
        registration, pinned = self.registration(["BTC", "ETH"])
        result = audit(self.path, sha, registration, pinned)
        self.assertEqual(result["engineering_status"], "PASSED")
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(set(result["asset_audits"]), {"BTC", "ETH"})
        registration, pinned = self.registration(["BTC", "ETH", "SOL"])
        with self.assertRaises(ValueError):
            audit(self.path, sha, registration, pinned)

    def test_audit_rejects_registration_tampering(self):
        sha, _ = self.collect()
        registration, pinned = self.registration(["BTC", "ETH"])
        registration.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            audit(self.path, sha, registration, pinned)

    def test_audit_rejects_missing_minutes(self):
        sha, _ = collect_batch(self.path, ["BTC", "ETH"], 0, 60, as_of=60, fetch=lambda url: b"[]")
        registration, pinned = self.registration(["BTC", "ETH"])
        with self.assertRaises(AssertionError):
            audit(self.path, sha, registration, pinned)


if __name__ == "__main__":
    unittest.main()
