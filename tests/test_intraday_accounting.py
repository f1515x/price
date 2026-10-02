"""Independent accounting identities on synthetic fills, never market evidence."""
from decimal import localcontext
from fractions import Fraction
import unittest

import test_intraday_orders as fixtures
from contract_specs import digest, encoded
from intraday_accounting import account
from intraday_orders import CONVERSION_POLICY
from spec_evidence import _json


def exact(value):
    return Fraction(value["numerator"], value["denominator"])


class IntradayAccountingTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.IntradayOrderTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.s = self.f.scenario
        self.p = dict(initial_collateral="1000", fee_periods=[dict(start=0, end=20, rate="0.001")])

    def run_account(self, **kwargs):
        return account(self.f.archive, self.f.sha, self.s, digest(encoded(self.s)),
                       self.p, digest(encoded(self.p)), allow_scenario=True, **kwargs)

    def trade(self, oid, t, direction, q, price):
        return [self.f.submit(oid, t, direction, q, price), self.f.fill(oid, t, price)]

    def test_long_roundtrip_and_collateral_identity(self):
        self.s["actions"] = self.trade("a", 1, 1, "1", "100") + self.trade("b", 2, -1, "1", "110")
        r = self.run_account()
        self.assertEqual(exact(r["realized_pnl"]), 10)
        self.assertEqual(exact(r["total_fees"]), Fraction(21, 100))
        self.assertEqual(exact(r["collateral_balance"]), Fraction(100979, 100))
        self.assertIsNone(r["average_entry_price"])
        self.assertIsNone(r["equity"])
        self.assertFalse(r["costs_verified"])

    def test_short_roundtrip(self):
        self.s["actions"] = self.trade("a", 1, -1, "1", "110") + self.trade("b", 2, 1, "1", "100")
        self.assertEqual(exact(self.run_account()["realized_pnl"]), 10)

    def test_average_entry_partial_close_and_reversal(self):
        self.s["actions"] = (self.trade("a", 1, 1, "0.5", "100")
            + self.trade("b", 2, 1, "0.5", "120") + self.trade("c", 3, -1, "0.2", "115")
            + self.trade("d", 4, -1, "1", "100"))
        r = self.run_account()
        self.assertEqual(exact(r["ledger"][1]["average_entry_price"]), 110)
        self.assertEqual(exact(r["realized_pnl"]), -7)
        self.assertEqual(exact(r["average_entry_price"]), 100)
        self.assertEqual(exact(r["ledger"][-1]["net_base_exposure"]), Fraction(-1, 5))

    def test_fractional_average_never_rounds(self):
        self.s["actions"] = self.trade("a", 1, 1, "0.1", "100") + self.trade("b", 2, 1, "0.2", "101")
        with localcontext() as ctx:
            ctx.prec = 2
            r = self.run_account()
        self.assertEqual(exact(r["average_entry_price"]), Fraction(302, 3))

    def test_fee_change_at_exact_second(self):
        self.p["fee_periods"] = [dict(start=0, end=2, rate="0.001"), dict(start=2, end=20, rate="0.002")]
        self.s["actions"] = self.trade("a", 1, 1, "1", "100") + self.trade("b", 2, -1, "1", "100")
        r = self.run_account()
        self.assertEqual(exact(r["total_fees"]), Fraction(3, 10))
        self.assertEqual([v["fee_period_index"] for v in r["ledger"]], [0, 1])

    def test_fragments_pay_only_executed_notional(self):
        self.s["actions"] = [self.f.submit("a", 1), dict(self.f.fill("a", 2), quantity="0.2"),
                              dict(kind="cancel", timestamp=3, order_id="a")]
        r = self.run_account()
        self.assertEqual(exact(r["total_fees"]), Fraction(1, 50))
        self.assertEqual(exact(r["realized_pnl"]), 0)

    def test_multiplier_uses_base_exposure(self):
        self.s["initial_specification"]["multiplier"] = "0.01"
        self.s["actions"] = self.trade("a", 1, 1, "1", "100") + self.trade("b", 2, -1, "1", "110")
        r = self.run_account()
        self.assertEqual(exact(r["realized_pnl"]), Fraction(1, 10))
        self.assertEqual(exact(r["total_fees"]), Fraction(21, 10000))

    def test_multiplier_conversion_does_not_create_pnl_or_fee(self):
        event = _json((self.f.archive / "notices.json").read_bytes())["events"][0]
        self.f.rewrite_events([dict(event, field="multiplier")])
        self.s["multiplier_conversion_policy"] = CONVERSION_POLICY
        self.s["initial_specification"]["multiplier"] = "2"
        self.s["actions"] = self.trade("a", 1, 1, "1", "100") + self.trade("b", 10, -1, "0.8", "110")
        r = self.run_account()
        self.assertEqual(len(r["ledger"]), 2)
        self.assertEqual(exact(r["realized_pnl"]), 20)
        self.assertEqual(exact(r["total_fees"]), Fraction(42, 100))
        self.assertIsNone(r["average_entry_price"])

    def test_empty_and_zero_costs(self):
        self.p["fee_periods"][0]["rate"] = "0"
        r = self.run_account()
        self.assertEqual(r["ledger"], [])
        self.assertEqual(exact(r["collateral_balance"]), 1000)

    def test_no_implicit_risk_or_balance_clamp(self):
        self.p["initial_collateral"] = "0"
        self.s["actions"] = self.trade("a", 1, 1, "1", "100")
        r = self.run_account()
        self.assertEqual(exact(r["collateral_balance"]), Fraction(-1, 10))
        self.assertFalse(r["risk_budget_enforced"])

    def test_invalid_fee_coverage(self):
        for periods in ([], [dict(start=1, end=20, rate="0")], [dict(start=0, end=19, rate="0")],
                        [dict(start=True, end=20, rate="0")],
                        [dict(start=0, end=10, rate="0"), dict(start=9, end=20, rate="0")]):
            self.p["fee_periods"] = periods
            with self.subTest(periods=periods), self.assertRaises(ValueError):
                self.run_account()

    def test_invalid_rate_or_collateral(self):
        for value in ("-0.1", "NaN", "Infinity", 0.001, True, "1", "2"):
            self.p["fee_periods"][0]["rate"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_account()

    def test_pins_opt_in_and_input_immutability(self):
        before = encoded(self.s), encoded(self.p)
        self.run_account()
        self.assertEqual(before, (encoded(self.s), encoded(self.p)))
        with self.assertRaisesRegex(ValueError, "pinned"):
            account(self.f.archive, self.f.sha, self.s, digest(encoded(self.s)), self.p, "0"*64,
                    allow_scenario=True)
        with self.assertRaisesRegex(ValueError, "allow_scenario"):
            account(self.f.archive, self.f.sha, self.s, digest(encoded(self.s)), self.p, digest(encoded(self.p)))


if __name__ == "__main__":
    unittest.main()
