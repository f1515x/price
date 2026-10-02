import copy
from pathlib import Path
import tempfile
import unittest

from contract_specs import digest, encoded
from historical_notices import analyze, build, verify


class HistoricalNoticeTests(unittest.TestCase):
    def setUp(self):
        # Fictional dates/prices: tests never masquerade as collected evidence.
        body = b"January 2, 2025, 08:00 (UTC)\nBefore | After\nETH_USDT | 2 | 3\n"
        def binding(text):
            a = body.index(text.encode())
            return dict(start=a, end=a+len(text.encode()), text=text)
        self.blobs = {"fixture.txt": body}
        self.m = dict(version="historical-notice-events-v1", scope="NOTICE_CHANGE_EVENTS_ONLY",
                      market="gate_usdt_perpetual", documents={"fixture": dict(file="fixture.txt",
                      sha256=digest(body), url="https://www.gate.com/announcements/article/1",
                      retrieved_at="2026-10-01T18:00:00Z", capture_method="WEB_TOOL_SHORT_EXCERPT",
                      source_locator="synthetic test fixture")}, events=[dict(id="one", symbol="ETH",
                      field="price_tick", before="2", after="3", effective_at="2025-01-02T08:00:00Z",
                      document="fixture", reviewer="synthetic test", rationale="synthetic mapping",
                      bindings={"effective_time": binding("January 2, 2025, 08:00 (UTC)"),
                                "table_header": binding("Before | After"),
                                "table_row": binding("ETH_USDT | 2 | 3")})])
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "archive"

    def test_roundtrip_retains_intraday_without_validity_or_certification(self):
        build(self.m, self.blobs, self.path)
        sha = digest((self.path / "notices.json").read_bytes())
        r = verify(self.path, sha)
        self.assertTrue(r["events"][0]["intraday_boundary"])
        self.assertIsNone(r["events"][0]["inferred_validity_end"])
        self.assertEqual(r["events"][0]["effective_timestamp"], 1735804800)
        self.assertEqual(r["verified_coverage_seconds"], 0)
        self.assertFalse(r["historical_specs_verified"])
        self.assertFalse(r["used_for_execution_parameters"])

    def test_pinned_manifest_and_excerpt_tampering(self):
        build(self.m, self.blobs, self.path)
        sha = digest((self.path / "notices.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "pinned"):
            verify(self.path, "0"*64)
        (self.path / "fixture.txt").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify(self.path, sha)

    def test_mismatched_text_and_nonbyte_boundaries(self):
        for changes in (dict(text="invented"), dict(start=True), dict(end=999), dict(start=-1)):
            m = copy.deepcopy(self.m)
            m["events"][0]["bindings"]["table_row"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                analyze(m, self.blobs)

    def test_source_url_spoofing(self):
        for url in ("http://www.gate.com/announcements/article/1", "https://www.gate.com.evil/announcements/article/1",
                    "https://www.gate.com@evil/announcements/article/1", "https://testnet.gate.com/announcements/article/1",
                    "https://www.gate.com/announcements/article/1?redirect=evil"):
            self.m["documents"]["fixture"]["url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                analyze(self.m, self.blobs)

    def test_path_escape_rejected_before_reading(self):
        for name in ("../fixture.txt", "E:/fixture.txt", "sub/fixture.txt"):
            self.m["documents"]["fixture"]["file"] = name
            with self.subTest(name=name), self.assertRaises(ValueError):
                analyze(self.m, self.blobs)

    def test_effective_time_must_be_historical_and_explicit_utc(self):
        for date in ("2027-01-01T00:00:00Z", "2025-02-30T00:00:00Z", "2025-01-02", "2025-01-02T08:00:00+08:00"):
            self.m["events"][0]["effective_at"] = date
            with self.subTest(date=date), self.assertRaises(ValueError):
                analyze(self.m, self.blobs)

    def test_no_execution_or_certification_fields(self):
        for key in ("end", "authenticated", "verified_fields"):
            m = copy.deepcopy(self.m)
            m["events"][0][key] = True
            with self.subTest(key=key), self.assertRaises(ValueError):
                analyze(m, self.blobs)

    def test_conflicting_change_and_duplicate_ids(self):
        self.m["events"].append(copy.deepcopy(self.m["events"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            analyze(self.m, self.blobs)
        self.m["events"][1].update(id="two", after="4")
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            analyze(self.m, self.blobs)

    def test_invalid_values_and_unknown_fields(self):
        for key, value in (("after", "NaN"), ("after", "0"), ("before", 1),
                           ("after", "2.0"), ("field", "fee"), ("symbol", "eth")):
            m = copy.deepcopy(self.m)
            m["events"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                analyze(m, self.blobs)

    def test_empty_inputs_and_unreferenced_documents(self):
        for key, value in (("events", []), ("documents", {})):
            m = copy.deepcopy(self.m); m[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analyze(m, self.blobs)
        self.m["documents"]["second"] = dict(self.m["documents"]["fixture"], file="second.txt")
        with self.assertRaisesRegex(ValueError, "Unreferenced"):
            analyze(self.m, dict(self.blobs, **{"second.txt": self.blobs["fixture.txt"]}))

    def test_overwrite_and_failed_build_leave_no_archive(self):
        self.m["events"][0]["after"] = "0"
        with self.assertRaises(ValueError):
            build(self.m, self.blobs, self.path)
        self.assertFalse(self.path.exists())
        self.path.mkdir()
        with self.assertRaises(FileExistsError):
            build(self.m, self.blobs, self.path)

    def test_duplicate_json_keys_rejected(self):
        build(self.m, self.blobs, self.path)
        p = self.path / "notices.json"
        p.write_bytes(p.read_bytes().replace(b'"market":', b'"market": "fake", "market":'))
        with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
            verify(self.path, digest(p.read_bytes()))


if __name__ == "__main__":
    unittest.main()
