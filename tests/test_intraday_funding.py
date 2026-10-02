"""Funding identities and exact-time ordering, using declared synthetic fills."""
import copy
from decimal import localcontext
import unittest

import test_intraday_accounting as fixtures
from contract_specs import digest, encoded
from intraday_funding import ORDERING, exact, settle
from intraday_orders import CONVERSION_POLICY
from spec_evidence import _json


class IntradayFundingTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.IntradayAccountingTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.s = self.f.s
        self.p = dict(symbol="ETH", start=0, end=20, ordering=ORDERING,
                      scheduled_timestamps=[5], settlements=[
                          dict(timestamp=5, rate="0.01", settlement_price="100")])

    def run_settle(self, pin=None, allow=True):
        return settle(self.f.f.archive, self.f.f.sha, self.s, digest(encoded(self.s)),
                      self.f.p, digest(encoded(self.f.p)), self.p,
                      pin or digest(encoded(self.p)), allow_scenario=allow)

    def test_long_short_positive_negative_rates(self):
        for direction in (1, -1):
            for rate in ("0.01", "-0.01", "0"):
                self.s["actions"] = self.f.trade("a", 1, direction, "1", "100")
                self.p["settlements"][0]["rate"] = rate
                r = self.run_settle()
                from fractions import Fraction
                expected = -direction * 100 * Fraction(rate)
                self.assertEqual(exact(r["total_funding_cashflow"]), expected)
                self.assertEqual(exact(r["collateral_balance"]),
                                 exact(r["accounting"]["collateral_balance"]) + expected)

    def test_settlement_precedes_same_second_entry(self):
        self.s["actions"] = self.f.trade("a", 5, 1, "1", "100")
        r = self.run_settle()
        self.assertEqual(exact(r["total_funding_cashflow"]), 0)

    def test_settlement_precedes_same_second_exit_and_reversal(self):
        self.s["actions"] = (self.f.trade("a", 1, 1, "1", "100")
                             + self.f.trade("b", 5, -1, "2", "100"))
        r = self.run_settle()
        self.assertEqual(exact(r["total_funding_cashflow"]), -1)
        self.assertEqual(exact(r["fill_ledger"][-1]["cumulative_funding"]), -1)

    def test_partial_fill_cancel_and_multiple_settlements(self):
        self.s["actions"] = [self.f.f.submit("a", 1),
                             dict(self.f.f.fill("a", 2), quantity="0.2"),
                             dict(kind="cancel", timestamp=3, order_id="a")]
        self.p["scheduled_timestamps"] = [5, 6]
        self.p["settlements"].append(dict(timestamp=6, rate="-0.02", settlement_price="100"))
        from fractions import Fraction
        self.assertEqual(exact(self.run_settle()["total_funding_cashflow"]), Fraction(1, 5))

    def test_flat_after_close_receives_zero(self):
        self.s["actions"] = self.f.trade("a", 1, 1, "1", "100") + self.f.trade("b", 4, -1, "1", "110")
        r = self.run_settle()
        self.assertEqual(exact(r["total_funding_cashflow"]), 0)
        self.assertEqual(exact(r["net_realized_pnl"]), exact(r["accounting"]["net_realized_pnl"]))

    def test_multiplier_conversion_preserves_funding_exposure(self):
        event = _json((self.f.f.archive / "notices.json").read_bytes())["events"][0]
        self.f.f.rewrite_events([dict(event, field="multiplier")])
        self.s["multiplier_conversion_policy"] = CONVERSION_POLICY
        self.s["initial_specification"]["multiplier"] = "2"
        self.s["actions"] = self.f.trade("a", 1, 1, "1", "100")
        self.p["scheduled_timestamps"] = [5, 10, 11]
        self.p["settlements"] = [dict(timestamp=t, rate="0.01", settlement_price="100") for t in [5, 10, 11]]
        self.assertEqual(exact(self.run_settle()["total_funding_cashflow"]), -6)

    def test_schedule_boundaries_and_no_fills(self):
        self.p["scheduled_timestamps"] = [0, 19]
        self.p["settlements"] = [dict(timestamp=t, rate="0.01", settlement_price="100") for t in [0, 19]]
        r = self.run_settle()
        self.assertEqual(exact(r["total_funding_cashflow"]), 0)
        self.assertEqual(len(r["settlement_ledger"]), 2)

    def test_empty_declared_schedule(self):
        self.p.update(scheduled_timestamps=[], settlements=[])
        self.assertEqual(self.run_settle()["settlement_ledger"], [])
        self.assertFalse(self.run_settle()["funding_schedule_verified"])

    def test_missing_duplicate_unsorted_extra_outside_schedule(self):
        original = copy.deepcopy(self.p)
        for schedule, stamps in (([5], []), ([5], [5, 5]), ([5], [6]),
                                 ([5, 4], [5, 4]), ([5, 5], [5, 5]),
                                 ([20], [20]), ([-1], [-1]), ([True], [True])):
            self.p = copy.deepcopy(original)
            self.p["scheduled_timestamps"] = schedule
            self.p["settlements"] = [dict(timestamp=t, rate="0", settlement_price="100") for t in stamps]
            with self.subTest(schedule=schedule, stamps=stamps), self.assertRaises(ValueError):
                self.run_settle()

    def test_invalid_rates_prices_and_metadata(self):
        original = copy.deepcopy(self.p)
        for field, values in (("rate", [True, 0.01, "NaN", "Infinity", "1", "-1"]),
                              ("settlement_price", [True, 100, "NaN", "0", "-1"]),
                              ("timestamp", [True, 5.0])):
            for value in values:
                self.p = copy.deepcopy(original)
                self.p["settlements"][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.run_settle()
        for field, value in (("symbol", "BTC"), ("start", True), ("end", 21), ("ordering", "INFER")):
            self.p = copy.deepcopy(original)
            self.p[field] = value
            with self.assertRaises(ValueError):
                self.run_settle()

    def test_exact_precision_negative_balance_and_no_risk_claim(self):
        self.f.p["initial_collateral"] = "0"
        self.s["actions"] = self.f.trade("a", 1, 1, "1", "100")
        self.p["settlements"][0]["rate"] = "0.0123456789"
        with localcontext() as ctx:
            ctx.prec = 2
            r = self.run_settle()
        from fractions import Fraction
        self.assertEqual(exact(r["total_funding_cashflow"]), Fraction(-123456789, 100000000))
        self.assertLess(exact(r["collateral_balance"]), 0)
        self.assertFalse(r["costs_verified"])
        self.assertFalse(r["risk_budget_enforced"])
        self.assertIsNone(r["equity"])
        self.assertEqual(r["acceptance_status"], "NOT_VALIDATED")

    def test_hash_opt_in_and_immutability(self):
        before = encoded(self.p), encoded(self.s), encoded(self.f.p)
        self.run_settle()
        self.assertEqual(before, (encoded(self.p), encoded(self.s), encoded(self.f.p)))
        with self.assertRaisesRegex(ValueError, "pinned"):
            self.run_settle(pin="0" * 64)
        with self.assertRaisesRegex(ValueError, "allow_scenario"):
            self.run_settle(allow=False)


if __name__ == "__main__":
    unittest.main()
