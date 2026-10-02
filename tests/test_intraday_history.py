import copy
from decimal import localcontext
import tempfile
from pathlib import Path
import unittest

from contract_specs import digest, encoded
from intraday_history import collect, prepare, verify


def bar(t=0, **changes):
    return dict(t=t, o="100.000000000000000001", h="102", l="99", c="101", v=0, **changes)


class IntradayHistoryTests(unittest.TestCase):
    def test_exact_decimal_and_precision_independence(self):
        expected = prepare([[bar()]], "ETH", 0, 60, 60)
        with localcontext() as ctx:
            ctx.prec = 1
            self.assertEqual(prepare([[bar()]], "ETH", 0, 60, 60), expected)
        self.assertEqual(expected[0][0]["open"], "100.000000000000000001")
        self.assertEqual(expected[1]["quality_status"], "COMPLETE")

    def test_invalid_values_and_timestamps(self):
        for changes in ({"o": True}, {"o": 100.1}, {"o": "NaN"}, {"v": -1},
                        {"h": "1"}, {"t": False}, {"t": "0"}, {"t": 1}, {"t": 60}):
            item = bar()
            item.update(changes)
            with self.subTest(changes=changes):
                rows, report = prepare([[item]], "ETH", 0, 60, 60)
                self.assertEqual(rows, [])
                self.assertEqual(report["missing_timestamps"], [0])
                self.assertEqual(len(report["issues"]), 1)

    def test_duplicates_and_conflicts(self):
        rows, report = prepare([[bar(), bar()]], "ETH", 0, 60, 60)
        self.assertEqual(len(rows), 1)
        self.assertEqual(report["issues"][0]["reason"], "DUPLICATE")
        second = bar()
        second["v"] = 1
        self.assertEqual(prepare([[bar(), second]], "ETH", 0, 60, 60)[0], [])

    def test_unclosed_and_missing(self):
        rows, report = prepare([[bar(), bar(60)]], "ETH", 0, 120, 61)
        self.assertEqual(len(rows), 1)
        self.assertEqual(report["missing_timestamps"], [])
        self.assertEqual(report["issues"][0]["reason"], "UNCLOSED")
        self.assertEqual(prepare([[]], "ETH", 0, 120, 120)[1]["missing_timestamps"], [0, 60])

    def test_pagination_roundtrip_and_no_overwrite(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return b"[]"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive"
            sha, report = collect(path, "eth", 0, 60060, as_of=60060, fetch=fetch)
            self.assertEqual(len(calls), 2)
            self.assertIn("from=60000&to=60059", calls[-1])
            self.assertNotIn("limit=", calls[0])
            self.assertEqual(verify(path, sha)[1], report)
            self.assertEqual(len(report["missing_timestamps"]), 1001)
            with self.assertRaises(FileExistsError):
                collect(path, "ETH", 0, 60, as_of=60, fetch=fetch)

    def test_tampering_and_recomputation(self):
        import json
        for target in ("page-0000.json", "minutes.json", "manifest.json", "quality", "provenance", "derived"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "archive"
                sha, _ = collect(path, "ETH", 0, 60, as_of=60, fetch=lambda url: encoded([bar()]))
                if target.endswith(".json"):
                    (path / target).write_bytes(b"[]")
                else:
                    manifest = json.loads((path / "manifest.json").read_bytes())
                    if target == "quality":
                        manifest["report"]["market_fills_verified"] = True
                    elif target == "provenance":
                        manifest["pages"][0]["file"] = "../outside.json"
                    else:
                        body = encoded([])
                        (path / "minutes.json").write_bytes(body)
                        manifest["rows_sha256"] = digest(body)
                    body = encoded(manifest)
                    (path / "manifest.json").write_bytes(body)
                    sha = digest(body)
                with self.assertRaises(ValueError):
                    verify(path, sha)

    def test_response_errors_never_create_verified_manifest(self):
        for body in (b'{"label":"ERROR"}', b"invalid"):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "archive"
                with self.assertRaises(ValueError):
                    collect(path, "ETH", 0, 60, as_of=60, fetch=lambda url: body)
                self.assertFalse((path / "manifest.json").exists())
                self.assertEqual((path / "page-0000.json").read_bytes(), body)

    def test_boundaries_and_page_inventory(self):
        for start, end, as_of in ((True, 60, 60), (1, 60, 60), (0, 0, 60), (0, 60, -1)):
            with self.assertRaises(ValueError):
                prepare([[]], "ETH", start, end, as_of)
        with self.assertRaises(ValueError):
            prepare([], "ETH", 0, 60, 60)

    def test_input_immutable_and_no_execution_certification(self):
        pages = [[bar()]]
        before = copy.deepcopy(pages)
        _, report = prepare(pages, "ETH", 0, 60, 60)
        self.assertEqual(pages, before)
        self.assertFalse(report["market_fills_verified"])
        self.assertFalse(report["historical_specs_verified"])
        self.assertEqual(report["acceptance_status"], "NOT_VALIDATED")


if __name__ == "__main__":
    unittest.main()
