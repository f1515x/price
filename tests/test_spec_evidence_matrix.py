import copy
from pathlib import Path
import tempfile
import unittest

from build_spec_evidence_matrix import FIELDS, PINS, build, period_rows, scalar_binding


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.scope = dict(historical_data={s: dict(start=0, end_exclusive=100) for s in ("BTC", "ETH")},
                          future_folds=[dict(index=0, test=dict(start=200, end_exclusive=300))])
        self.refs = {f: ["observation-" + f] for f in FIELDS}
        self.issues = {f: [] for f in FIELDS}

    def rows(self, symbol="ETH", events=(), claims=()):
        return period_rows(self.scope, symbol, events, claims, self.refs, self.issues)

    def event(self, symbol="ETH", field="min_quantity", timestamp=50):
        return dict(id="notice", symbol=symbol, field=field, effective_timestamp=timestamp,
                    before="1", after="0.1")

    def claim(self, **changes):
        return dict(dict(id="a", symbol="ETH", field="price_tick", value="0.1", start=10, end=80,
                         eligible_for_review_coverage=True), **changes)

    def test_notice_boundary_does_not_assign_values_or_validity(self):
        rows = self.rows(events=[self.event()])
        self.assertEqual(len(rows), 15)
        historical = [r for r in rows if r["field"] == "min_quantity" and r["target"] == "historical"]
        self.assertEqual([(r["required_window"]["start"], r["required_window"]["end_exclusive"])
                          for r in historical], [(0, 50), (50, 100)])
        self.assertTrue(all(r["certified_value"] is None and r["certified_effective_period"] is None
                            and r["certified_coverage_seconds"] == 0 for r in rows))

    def test_notice_does_not_supply_another_field_or_asset(self):
        event = self.event()
        self.assertTrue(all(not r["notice_context_refs"] for r in self.rows(symbol="BTC", events=[event])))
        eth = self.rows(events=[event])
        self.assertTrue(all(not r["notice_context_refs"] for r in eth if r["field"] == "quantity_step"))
        self.assertTrue(all("EXPLICIT_DECIMAL_QUANTITY_STEP_MISSING" in r["gaps"]
                            for r in eth if r["field"] == "quantity_step"))

    def test_half_open_endpoints_and_future_no_extrapolation(self):
        for timestamp in (-1, 0, 100, 150, 300):
            self.assertEqual(len(self.rows(events=[self.event(timestamp=timestamp)])), 10)
        future = [r for r in self.rows(events=[self.event(timestamp=250)]) if r["target"] == "future-0"]
        self.assertEqual(len(future), 10)
        self.assertTrue(all("FUTURE_VALIDITY_UNKNOWN_UNTIL_OBSERVED" in r["gaps"] for r in future))
        self.assertTrue(all(r["review_status"] == "NO_VALIDITY_ASSERTION" for r in future))

    def test_review_conflicts_remain_unresolved_and_uncertified(self):
        rows = self.rows(claims=[self.claim(), self.claim(id="b", value="0.2", start=50, end=90)])
        conflict = [r for r in rows if r["conflicting_claim_ids"]]
        self.assertEqual(len(conflict), 1)
        self.assertEqual(conflict[0]["conflicting_claim_ids"], ["a", "b"])
        self.assertEqual(conflict[0]["required_window"]["start"], 50)
        self.assertEqual(conflict[0]["required_window"]["end_exclusive"], 80)
        self.assertEqual(conflict[0]["certified_coverage_seconds"], 0)

    def test_decimal_equivalent_claims_not_conflicting_or_certified(self):
        rows = self.rows(claims=[self.claim(), self.claim(id="b", value="0.100")])
        self.assertFalse(any(r["conflicting_claim_ids"] for r in rows))
        covered = [r for r in rows if r["review_claim_ids"]]
        self.assertEqual(len(covered), 1)
        self.assertEqual(covered[0]["review_status"], "REVIEW_ASSERTIONS_ONLY")
        self.assertEqual(covered[0]["certification_status"], "NOT_CERTIFIED")

    def test_synthetic_and_observation_claims_do_not_partition_or_cover(self):
        self.assertEqual(self.rows(claims=[self.claim(eligible_for_review_coverage=False)]), self.rows())
        self.assertEqual(self.rows(claims=[self.claim(symbol="BTC")]), self.rows())

    def test_inputs_not_mutated(self):
        events, claims = [self.event()], [self.claim()]
        before = copy.deepcopy((self.scope, events, claims, self.refs, self.issues))
        self.rows(events=events, claims=claims)
        self.assertEqual(before, (self.scope, events, claims, self.refs, self.issues))

    def test_exact_utf8_binding_and_missing_or_duplicate_rejection(self):
        body = '{"备注":"字节偏移", "order_size_min":0.1,"enable_decimal":true}'.encode("utf-8")
        binding = scalar_binding(body, "order_size_min")
        self.assertEqual(body[binding["start"]:binding["end"]], binding["text"].encode("utf-8"))
        self.assertEqual(binding["text"], '"order_size_min":0.1')
        self.assertEqual(scalar_binding(body, "enable_decimal")["text"], '"enable_decimal":true')
        for broken in (b'{"other":1}', b'{"order_size_min":1,"order_size_min":2}'):
            with self.assertRaises(ValueError):
                scalar_binding(broken, "order_size_min")

    def test_pinned_scope_tamper_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            scope = root / next(iter(PINS))
            scope.parent.mkdir(parents=True)
            scope.write_text('{"assets":["BTC"]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Pinned evidence differs"):
                build(root)
            self.assertEqual(list(root.rglob("*.json")), [scope])


if __name__ == "__main__":
    unittest.main()
