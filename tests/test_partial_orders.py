"""Quantity conservation and cancellation boundaries for declared fragments."""
from decimal import localcontext
import unittest

import test_intraday_orders as fixtures


class PartialOrderTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IntradayOrderTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.s = self.fixture.scenario

    def fill(self, t, quantity=None, price="100"):
        action = self.fixture.fill("a", t, price)
        if quantity is not None:
            action["quantity"] = quantity
        return action

    def run_actions(self, *actions):
        self.s["actions"] = list(actions)
        return self.fixture.run_policy()

    def test_fragments_then_legacy_fill_consumes_only_remainder(self):
        r = self.run_actions(self.fixture.submit("a", 1), self.fill(2, "0.2"),
                             self.fill(3, "0.3"), self.fill(4))
        self.assertEqual([f["quantity"] for f in r["fills"]], ["0.2", "0.3", "0.5"])
        self.assertEqual([f["remaining_quantity"] for f in r["fills"]], ["0.8", "0.5", "0"])
        self.assertEqual(r["pending_quantities"], {})
        self.assertEqual(r["net_position_contracts"], dict(numerator=1, denominator=1))

    def test_notice_cancels_remainder_without_reversing_position(self):
        r = self.run_actions(self.fixture.submit("a", 1), self.fill(2, "0.3"))
        self.assertEqual(r["audit_log"][-1]["cancelled_quantities"], {"a": "0.7"})
        self.assertEqual(r["net_position_contracts"], dict(numerator=3, denominator=10))

    def test_same_second_notice_blocks_fragment(self):
        with self.assertRaisesRegex(ValueError, "cancelled"):
            self.run_actions(self.fixture.submit("a", 1), self.fill(2, "0.3"), self.fill(10, "0.1"))

    def test_manual_cancel_records_unfilled_quantity(self):
        r = self.run_actions(self.fixture.submit("a", 1), self.fill(2, "0.4"),
                             dict(kind="cancel", timestamp=3, order_id="a"))
        self.assertEqual(r["audit_log"][2]["remaining_quantity"], "0.6")
        self.assertEqual(r["pending_quantities"], {})

    def test_invalid_or_excess_fragment_rejected(self):
        for q in ("0", "-0.1", "NaN", "Infinity", "0.15", "0.8", True, 0.1):
            with self.subTest(quantity=q), self.assertRaises(ValueError):
                self.run_actions(self.fixture.submit("a", 1), self.fill(2, "0.3"), self.fill(3, q))

    def test_fragment_below_submission_minimum_is_allowed(self):
        self.s["initial_specification"]["min_quantity"] = "1"
        r = self.run_actions(self.fixture.submit("a", 1), self.fill(2, "0.1"), self.fill(3))
        self.assertEqual(r["fills"][1]["quantity"], "0.9")

    def test_pending_remainder_at_end_and_input_immutable(self):
        self.s["end"] = 9
        r = self.run_actions(self.fixture.submit("a", 1), self.fill(2, "0.1"))
        self.assertEqual(r["pending_quantities"], {"a": "0.9"})
        self.assertNotIn("remaining_quantity", self.s["actions"][0])

    def test_sell_fragments_and_limits(self):
        r = self.run_actions(self.fixture.submit("a", 1, -1), self.fill(2, "0.2", "100.01"),
                             self.fill(3))
        self.assertEqual(r["net_position_contracts"], dict(numerator=-1, denominator=1))
        with self.assertRaisesRegex(ValueError, "limit"):
            self.run_actions(self.fixture.submit("a", 1, -1), self.fill(2, "0.2", "99.99"))

    def test_exact_remainders_ignore_decimal_context(self):
        self.s["initial_specification"]["quantity_step"] = "0.00000000000000000000000000001"
        self.s["end"] = 9
        with localcontext() as ctx:
            ctx.prec = 3
            r = self.run_actions(self.fixture.submit("a", 1), self.fill(2, "0.12345678901234567890123456789"),
                                 self.fill(3))
        self.assertEqual(r["fills"][1]["quantity"], "0.87654321098765432109876543211")
        self.assertEqual(r["net_position_contracts"], dict(numerator=1, denominator=1))

    def test_completed_order_cannot_fill_cancel_or_reuse(self):
        for tail in (self.fill(4, "0.1"), dict(kind="cancel", timestamp=4, order_id="a"),
                     self.fixture.submit("a", 4)):
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                self.run_actions(self.fixture.submit("a", 1), self.fill(2, "0.2"), self.fill(3), tail)


if __name__ == "__main__":
    unittest.main()
