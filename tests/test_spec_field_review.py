import copy
from pathlib import Path
import tempfile
import unittest

from contract_specs import digest, encoded
from dated_specifications import FIELDS
from history import DAY
from spec_field_review import MARKET, VERSION, load


class FieldReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "review.json"
        self.body = "历史声明 fixture: BTC tick 0.1 effective [0,172800).\n".encode("utf-8")
        self.path.with_name("notice.txt").write_bytes(self.body)
        self.ledger = dict(version=VERSION, scope="REVIEW_ASSERTIONS_ONLY", market=MARKET,
                           documents=dict(notice=dict(file="notice.txt", sha256=digest(self.body),
                                                     origin="fixture, not real evidence", kind="effective_notice")),
                           claims=[self.claim()])

    def claim(self, **changes):
        return dict(dict(id="tick", symbol="BTC", field="price_tick", value="0.1", start=0, end=2*DAY,
                         document="notice", excerpt_start=0, excerpt_end=len(self.body),
                         excerpt=self.body.decode("utf-8"), reviewer="test reviewer",
                         rationale="Synthetic review assertion for coverage arithmetic"), **changes)

    def write(self):
        self.path.write_bytes(encoded(self.ledger))
        return digest(self.path.read_bytes())

    def load(self, symbols=("BTC",), start=0, end=3*DAY):
        return load(self.path, self.write(), symbols, start, end)

    def test_partial_coverage_and_no_authentication(self):
        result = self.load()
        field = result["assets"][0]["fields"]["price_tick"]
        self.assertEqual(field["reviewed_coverage_seconds"], 2*DAY)
        self.assertEqual(field["missing_intervals"], [dict(start=2*DAY, end=3*DAY)])
        self.assertEqual(field["verified_coverage_seconds"], 0)
        self.assertEqual(field["unverified_intervals"], [dict(start=0, end=3*DAY)])
        self.assertFalse(result["historical_specs_verified"])
        self.assertFalse(result["used_for_execution_parameters"])
        self.assertEqual(result["acceptance_status"], "NOT_VALIDATED")

    def test_conflicts_excluded_from_coverage(self):
        self.ledger["claims"].append(self.claim(id="conflict", value="0.2", start=DAY, end=3*DAY))
        field = self.load()["assets"][0]["fields"]["price_tick"]
        self.assertEqual(field["reviewed_coverage_seconds"], 2*DAY)
        self.assertEqual(field["conflicting_intervals"],
                         [dict(start=DAY, end=2*DAY, claim_ids=["conflict", "tick"])])
        self.assertFalse(field["missing_intervals"])

    def test_equal_decimals_merge_coverage(self):
        self.ledger["claims"].append(self.claim(id="equal", value="0.100", start=DAY, end=3*DAY))
        field = self.load()["assets"][0]["fields"]["price_tick"]
        self.assertEqual(field["reviewed_intervals"], [dict(start=0, end=3*DAY)])
        self.assertFalse(field["conflicting_intervals"])

    def test_observation_and_synthetic_cannot_supply_effective_coverage(self):
        for kind in ("observation", "synthetic"):
            self.ledger["documents"]["notice"]["kind"] = kind
            field = self.load()["assets"][0]["fields"]["price_tick"]
            self.assertEqual(field["reviewed_coverage_seconds"], 0)
            self.assertEqual(field["missing_intervals"], [dict(start=0, end=3*DAY)])

    def test_empty_real_evidence_and_multiasset_field_isolation(self):
        result = self.load(symbols=("BTC", "ETH"))
        self.assertTrue(all(v["reviewed_coverage_seconds"] == 0
                            for v in result["assets"][1]["fields"].values()))
        self.ledger["claims"], self.ledger["documents"] = [], {}
        result = self.load(symbols=("BTC", "ETH"))
        self.assertEqual(sum(v["reviewed_coverage_seconds"] for a in result["assets"]
                             for v in a["fields"].values()), 0)

    def test_intraday_review_and_clipping_without_execution(self):
        self.ledger["claims"][0].update(start=1, end=3*DAY+1)
        field = self.load(start=DAY, end=2*DAY)["assets"][0]["fields"]["price_tick"]
        self.assertEqual(field["reviewed_intervals"], [dict(start=DAY, end=2*DAY)])

    def test_all_fields_required_for_full_review_coverage(self):
        self.ledger["claims"] = [self.claim(id=k, field=k, value="1", end=3*DAY) for k in FIELDS]
        result = self.load()
        self.assertTrue(all(f["reviewed_coverage_seconds"] == 3*DAY
                            for f in result["assets"][0]["fields"].values()))
        self.assertFalse(result["historical_specs_verified"])

    def test_manifest_and_document_hashes(self):
        sha = self.write()
        self.path.write_bytes(self.path.read_bytes()+b" ")
        with self.assertRaisesRegex(ValueError, "ledger differs"):
            load(self.path, sha, ["BTC"], 0, 3*DAY)
        self.path.with_name("notice.txt").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Document hash"):
            self.load()

    def test_exact_byte_excerpts(self):
        original = copy.deepcopy(self.ledger)
        for changes in (dict(excerpt="invented"), dict(excerpt_start=1),
                        dict(excerpt_end=len(self.body)+1), dict(excerpt_start=True)):
            self.ledger = copy.deepcopy(original)
            self.ledger["claims"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load()

    def test_invalid_claims(self):
        original = copy.deepcopy(self.ledger)
        for key, value in (("field", "fee_rate"), ("symbol", "btc"), ("document", "missing"),
                           ("start", True), ("end", 0), ("start", -1), ("reviewer", ""),
                           ("value", "NaN"), ("value", "0"), ("value", 1), ("value", "oops")):
            self.ledger = copy.deepcopy(original)
            self.ledger["claims"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.load()

    def test_duplicate_claim_and_unreferenced_document(self):
        self.ledger["claims"].append(self.claim())
        with self.assertRaisesRegex(ValueError, "Duplicate claim"):
            self.load()
        self.ledger["claims"].pop()
        self.ledger["documents"]["unused"] = dict(self.ledger["documents"]["notice"])
        with self.assertRaisesRegex(ValueError, "Unreferenced"):
            self.load()

    def test_dangerous_paths(self):
        for path in ("../outside.txt", "C:/outside.txt", "notice.txt:stream"):
            self.ledger["documents"]["notice"]["file"] = path
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "Unsafe"):
                self.load()

    def test_invalid_window_assets_and_scope(self):
        for symbols, start, end in ((["BTC", "BTC"], 0, DAY), (["btc"], 0, DAY),
                                     ([], 0, DAY), (["BTC"], True, DAY), (["BTC"], DAY, 0)):
            with self.subTest(symbols=symbols, start=start), self.assertRaises(ValueError):
                self.load(symbols, start, end)
        self.ledger["scope"] = "CERTIFIED"
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            self.load()

    def test_forged_verified_fields_and_duplicate_json(self):
        self.ledger["claims"][0]["verified"] = True
        with self.assertRaises(ValueError):
            self.load()
        del self.ledger["claims"][0]["verified"]
        self.write()
        body = self.path.read_bytes().replace(b'"scope":', b'"scope":"fake","scope":')
        self.path.write_bytes(body)
        with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
            load(self.path, digest(body), ["BTC"], 0, 3*DAY)


if __name__ == "__main__":
    unittest.main()
