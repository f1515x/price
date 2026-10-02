import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_notice_execution import fixture_notice
from contract_specs import digest, encoded
from historical_notices import verify
from intraday_orders import replay
from spec_evidence import _json


class IntradayOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive = Path(self.tmp.name) / "notices"
        self.sha = fixture_notice(self.archive, effective_at="1970-01-01T00:00:10Z")
        self.scenario = dict(symbol="ETH", start=0, end=20,
            initial_specification=dict(multiplier="1", quantity_step="0.1", min_quantity="0.1",
                                       max_quantity="2", price_tick="0.01"), actions=[])

    def run_policy(self, scenario=None):
        s = scenario if scenario is not None else self.scenario
        return replay(self.archive, self.sha, s, digest(encoded(s)), allow_scenario=True)

    def submit(self, oid, t, direction=1, quantity="1", price="100"):
        return dict(kind="submit", timestamp=t, order_id=oid, direction=direction,
                    quantity=quantity, limit_price=price)

    def fill(self, oid, t, price="100"):
        return dict(kind="fill", timestamp=t, order_id=oid, price=price)

    def test_change_precedes_same_second_actions_and_cancels_old_order(self):
        self.scenario["actions"] = [self.submit("old", 9), self.submit("new", 10, quantity="2.5"),
                                    self.fill("new", 10)]
        result = self.run_policy()
        self.assertEqual(result["audit_log"][1]["cancelled_order_ids"], ["old"])
        self.assertEqual(result["fills"][0]["specification"]["max_quantity"], "2.5")
        self.assertEqual(result["net_position_contracts"], dict(numerator=5, denominator=2))

    def test_cancelled_order_cannot_fill(self):
        self.scenario["actions"] = [self.submit("old", 9), self.fill("old", 10)]
        with self.assertRaisesRegex(ValueError, "cancelled"):
            self.run_policy()

    def test_before_change_new_maximum_rejected(self):
        self.scenario["actions"] = [self.submit("old", 9, quantity="2.5")]
        with self.assertRaisesRegex(ValueError, "specification"):
            self.run_policy()

    def test_buy_sell_limits_and_exact_decimal_tick(self):
        for direction, price in ((1, "100.01"), (-1, "99.99"), (1, "99.999")):
            self.scenario["actions"] = [self.submit("a", 1, direction), self.fill("a", 2, price)]
            with self.subTest(direction=direction, price=price), self.assertRaises(ValueError):
                self.run_policy()

    def test_round_trip_exact_fractional_position(self):
        self.scenario["actions"] = [self.submit("a", 1, quantity="0.1"), self.fill("a", 2),
                                    self.submit("b", 3, -1, "0.1"), self.fill("b", 4)]
        self.assertEqual(self.run_policy()["net_position_contracts"], dict(numerator=0, denominator=1))

    def test_duplicate_ids_cancel_and_double_fill_rejected(self):
        for tail in (self.submit("a", 2), self.fill("a", 3)):
            self.scenario["actions"] = [self.submit("a", 1), self.fill("a", 2), tail]
            with self.assertRaises(ValueError):
                self.run_policy()

    def test_out_of_order_boundary_boolean_and_daily_inference_rejected(self):
        for actions in ([self.submit("a", 20)], [self.submit("a", True)],
                        [self.submit("a", 2), self.fill("a", 1)],
                        [dict(kind="ohlc_fill", timestamp=1, order_id="a")]):
            self.scenario["actions"] = actions
            with self.assertRaises(ValueError):
                self.run_policy()

    def test_invalid_values_and_quantity_alignment(self):
        for quantity in ("NaN", "Infinity", "-1", "0.15", 1, True):
            self.scenario["actions"] = [self.submit("a", 1, quantity=quantity)]
            with self.assertRaises(ValueError):
                self.run_policy()

    def test_before_conflict_and_impossible_spec_rejected(self):
        self.scenario["initial_specification"]["max_quantity"] = "3"
        with self.assertRaisesRegex(ValueError, "before value"):
            self.run_policy()
        self.scenario["initial_specification"].update(max_quantity="0.9", min_quantity="0.8", quantity_step="1")
        with self.assertRaisesRegex(ValueError, "No legal quantity"):
            self.run_policy()

    def test_explicit_opt_in_and_independent_hash_required(self):
        with self.assertRaises(ValueError):
            replay(self.archive, self.sha, self.scenario, digest(encoded(self.scenario)))
        with self.assertRaises(ValueError):
            replay(self.archive, self.sha, self.scenario, "0" * 64, allow_scenario=True)

    def test_notice_rechecked_and_inputs_not_mutated(self):
        original = copy.deepcopy(self.scenario)
        self.run_policy()
        self.assertEqual(original, self.scenario)
        evidence = verify(self.archive, self.sha)
        with patch("intraday_orders.verify", side_effect=[evidence, dict(evidence, changed=True)]):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.run_policy()

    def test_end_excluded_and_start_change_applied(self):
        self.scenario.update(start=10, end=11)
        self.assertEqual(len(self.run_policy()["audit_log"]), 1)
        self.scenario.update(start=0, end=10)
        self.assertEqual(self.run_policy()["audit_log"], [])

    def test_no_certification_and_full_provenance(self):
        self.scenario["actions"] = [self.submit("a", 10), self.fill("a", 11)]
        result = self.run_policy()
        self.assertFalse(result["market_fills_verified"])
        self.assertFalse(result["historical_specs_verified"])
        self.assertEqual(result["verified_coverage_seconds"], 0)
        self.assertEqual(result["acceptance_status"], "NOT_VALIDATED")
        self.assertEqual(result["fills"][0]["notice_manifest_sha256"], self.sha)

    def rewrite_events(self, events):
        path = self.archive / "notices.json"
        manifest = _json(path.read_bytes())
        manifest["events"] = events
        path.write_bytes(encoded(manifest))
        self.sha = digest(path.read_bytes())

    def test_duplicate_notice_applied_once(self):
        event = _json((self.archive / "notices.json").read_bytes())["events"][0]
        self.rewrite_events([event, dict(event, id="corroborating")])
        result = self.run_policy()
        self.assertEqual(len(result["audit_log"]), 1)
        self.assertEqual(len(result["audit_log"][0]["event_ids"]), 2)

    def test_simultaneous_fields_validate_final_combined_spec(self):
        # Synthetic review assertions intentionally exercise joint field transitions.
        event = _json((self.archive / "notices.json").read_bytes())["events"][0]
        self.rewrite_events([dict(event, id="a-min", field="min_quantity"),
                             dict(event, id="z-max", after="3")])
        self.scenario["initial_specification"]["min_quantity"] = "2"
        self.scenario["actions"] = [self.submit("a", 10, quantity="2.5"), self.fill("a", 11)]
        self.assertEqual(self.run_policy()["fills"][0]["specification"]["min_quantity"], "2.5")

    def test_held_multiplier_change_blocks_but_flat_change_passes(self):
        event = _json((self.archive / "notices.json").read_bytes())["events"][0]
        self.rewrite_events([dict(event, field="multiplier")])
        self.scenario["initial_specification"]["multiplier"] = "2"
        self.assertEqual(self.run_policy()["policy_status"], "PASSED")
        self.scenario["actions"] = [self.submit("a", 1), self.fill("a", 2)]
        with self.assertRaisesRegex(ValueError, "multiplier conversion"):
            self.run_policy()

    def test_explicit_cancel_and_no_reuse(self):
        self.scenario["actions"] = [self.submit("a", 1), dict(kind="cancel", timestamp=2, order_id="a")]
        self.assertEqual(self.run_policy()["pending_order_ids"], [])
        self.scenario["actions"].append(self.submit("a", 3))
        with self.assertRaises(ValueError):
            self.run_policy()


if __name__ == "__main__":
    unittest.main()
