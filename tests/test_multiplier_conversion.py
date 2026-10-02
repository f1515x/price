"""Exact exposure conservation across declared multiplier transitions."""
import copy
from decimal import localcontext
from fractions import Fraction
import unittest

import test_intraday_orders as fixtures
from intraday_orders import CONVERSION_POLICY
from spec_evidence import _json


class MultiplierConversionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.IntradayOrderTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.s = self.f.scenario
        self.s["multiplier_conversion_policy"] = CONVERSION_POLICY
        self.s["initial_specification"]["multiplier"] = "2"
        self.event = _json((self.f.archive / "notices.json").read_bytes())["events"][0]
        self.f.rewrite_events([dict(self.event, field="multiplier")])

    def actions(self, direction=1, quantity="1"):
        self.s["actions"] = [self.f.submit("a", 1, direction, quantity), self.f.fill("a", 2)]

    def test_long_short_exact_exposure(self):
        for direction in (1, -1):
            self.actions(direction)
            r = self.f.run_policy()
            self.assertEqual(r["net_position_contracts"], dict(numerator=4*direction, denominator=5))
            self.assertEqual(r["net_base_exposure"], dict(numerator=2*direction, denominator=1))
            c = r["audit_log"][-1]["multiplier_conversion"]
            self.assertEqual(c["before_contracts"], dict(numerator=direction, denominator=1))
            self.assertEqual(c["after_contracts"], r["net_position_contracts"])

    def test_partial_fill_remainder_cancelled_before_same_second_close(self):
        self.s["actions"] = [self.f.submit("a", 1), dict(self.f.fill("a", 2), quantity="0.5"),
                             self.f.submit("close", 10, -1, "0.4"), self.f.fill("close", 10)]
        r = self.f.run_policy()
        self.assertEqual(r["audit_log"][2]["cancelled_quantities"], {"a": "0.5"})
        self.assertEqual(r["net_base_exposure"], dict(numerator=0, denominator=1))
        self.assertEqual(sum(Fraction(**f["signed_base_exposure"]) for f in r["fills"]), 0)

    def test_default_rejects_held_position(self):
        del self.s["multiplier_conversion_policy"]
        self.actions()
        with self.assertRaisesRegex(ValueError, "explicit multiplier conversion"):
            self.f.run_policy()

    def test_unknown_policy_rejected_even_when_flat(self):
        for policy in (None, True, "ROUND", [], {}):
            self.s["multiplier_conversion_policy"] = policy
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                self.f.run_policy()

    def test_misaligned_conversion_rejected_without_rounding(self):
        self.actions(quantity="0.1")
        with self.assertRaisesRegex(ValueError, "new quantity step"):
            self.f.run_policy()

    def test_simultaneous_new_step_used_not_old_step(self):
        self.f.rewrite_events([dict(self.event, field="multiplier"),
            dict(self.event, id="step", field="quantity_step", before="0.1", after="0.01")])
        self.actions(quantity="0.1")
        self.assertEqual(self.f.run_policy()["net_position_contracts"], dict(numerator=2, denominator=25))
        self.f.rewrite_events([dict(self.event, field="multiplier"),
            dict(self.event, id="step", field="quantity_step", before="0.1", after="0.3")])
        self.actions()
        with self.assertRaisesRegex(ValueError, "new quantity step"):
            self.f.run_policy()

    def test_low_decimal_precision_does_not_change_conversion(self):
        self.actions()
        expected = self.f.run_policy()
        with localcontext() as ctx:
            ctx.prec = 1
            self.assertEqual(self.f.run_policy(), expected)

    def test_multiple_transitions_and_corroboration(self):
        self.f.rewrite_events([dict(self.event, field="multiplier"),
            dict(self.event, id="duplicate", field="multiplier"),
            dict(self.event, id="second", field="multiplier", before="2.5", after="1",
                 effective_at="1970-01-01T00:00:15Z")])
        self.actions()
        r = self.f.run_policy()
        self.assertEqual(r["net_position_contracts"], dict(numerator=2, denominator=1))
        self.assertEqual(len([e for e in r["audit_log"] if e["kind"] == "notice"]), 2)
        self.assertEqual(r["net_base_exposure"], dict(numerator=2, denominator=1))

    def test_order_bounds_do_not_force_liquidation_of_position(self):
        self.f.rewrite_events([dict(self.event, field="multiplier", after="0.5")])
        self.actions()
        self.assertEqual(self.f.run_policy()["net_position_contracts"], dict(numerator=4, denominator=1))

    def test_flat_conversion_and_end_boundary(self):
        self.assertEqual(self.f.run_policy()["net_base_exposure"], dict(numerator=0, denominator=1))
        self.s["end"] = 10
        self.actions()
        r = self.f.run_policy()
        self.assertEqual(r["net_position_contracts"], dict(numerator=1, denominator=1))
        self.assertEqual(r["net_base_exposure"], dict(numerator=2, denominator=1))

    def test_policy_is_hash_pinned_and_input_immutable(self):
        from contract_specs import digest, encoded
        from intraday_orders import replay
        original = copy.deepcopy(self.s)
        sha = digest(encoded(self.s))
        self.f.run_policy()
        self.assertEqual(self.s, original)
        self.s["multiplier_conversion_policy"] = "REJECT_HELD_POSITION"
        with self.assertRaisesRegex(ValueError, "pinned SHA"):
            replay(self.f.archive, self.f.sha, self.s, sha, allow_scenario=True)

    def test_conversion_does_not_certify_execution(self):
        self.actions()
        r = self.f.run_policy()
        self.assertFalse(r["market_fills_verified"])
        self.assertFalse(r["historical_specs_verified"])
        self.assertEqual(r["acceptance_status"], "NOT_VALIDATED")


if __name__ == "__main__":
    unittest.main()
