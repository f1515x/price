import copy
from dataclasses import asdict
import unittest

from portfolio_simulation import PortfolioConfig, simulate
from risk_policy_audit import audit_run
from test_portfolio_simulation import assets
from test_trade_simulation import candidate, cfg


class RiskPolicyAuditTests(unittest.TestCase):
    def fixture(self, halt=False):
        execution = cfg(max_drawdown=.005 if halt else .2)
        policy = dict(execution=asdict(execution), max_total_risk=.05,
                      max_same_direction=1, groups={"BTC": "btc", "ETH": "eth"})
        rows = assets([(100, 105, 95, 100)] * 4)
        candidates = {s: [candidate()] for s in rows}
        if halt:
            rows["BTC"][1].update(low=85)
            candidates["ETH"] = [candidate(1)]
        result = simulate(rows, candidates, PortfolioConfig(execution, .05, 1), policy["groups"])
        return result, policy

    def test_valid_records_and_halt(self):
        for halt in (False, True):
            result, policy = self.fixture(halt)
            checks = audit_run(result, policy)
            self.assertEqual(checks["halted"], halt)
            self.assertEqual(checks["trades"], 1 if halt else 2)

    def test_caps_and_nonfinite_allocations_rejected(self):
        for field, value in (("gross_exposure", 1e9), ("modeled_stop_risk", 1e9),
                             ("equity", float("nan"))):
            result, policy = self.fixture()
            result["allocations"][0][field] = value
            with self.assertRaises(ValueError):
                audit_run(result, policy)

    def test_changed_risk_in_any_config_rejected(self):
        for place in ("parameters", "asset", "period"):
            result, policy = self.fixture()
            if place == "parameters":
                target = result["parameters"]["execution"]
            elif place == "asset":
                target = result["execution_by_asset"]["BTC"]
            else:
                target = copy.deepcopy(result["execution_by_asset"]["BTC"])
                result["execution_periods"] = {"BTC": [dict(config=target)]}
            target["risk_fraction"] *= 2
            with self.assertRaisesRegex(ValueError, "risk policy differs"):
                audit_run(result, policy)

    def test_halt_missing_or_reset_rejected(self):
        for index in (1, -1):
            result, policy = self.fixture(True)
            result["equity_curve"][index]["halted"] = False
            with self.assertRaisesRegex(ValueError, "halt missing or reset"):
                audit_run(result, policy)

    def test_orders_after_halt_rejected(self):
        result, policy = self.fixture(True)
        result["orders"][1]["admitted"] = True
        with self.assertRaisesRegex(ValueError, "after account halt"):
            audit_run(result, policy)

    def test_same_direction_slots_rejected(self):
        result, policy = self.fixture()
        policy["groups"] = result["groups"] = {s: "crypto" for s in policy["groups"]}
        for order in result["orders"]:
            order["group"] = "crypto"
        with self.assertRaisesRegex(ValueError, "slot limit exceeded"):
            audit_run(result, policy)

    def test_trade_risk_and_reconciliation_rejected(self):
        for field, value in (("modeled_stop_risk", 1000), ("net_pnl", 1000), ("quantity", 1000)):
            result, policy = self.fixture()
            result["trades"][0][field] = value
            with self.assertRaises(ValueError):
                audit_run(result, policy)

    def test_drawdown_and_equity_tampering_rejected(self):
        for target, field in (("equity_curve", "drawdown"), ("summary", "max_drawdown"),
                              ("summary", "final_equity")):
            result, policy = self.fixture()
            record = result[target][-1] if target == "equity_curve" else result[target]
            record[field] += .1
            with self.assertRaises(ValueError):
                audit_run(result, policy)


if __name__ == "__main__":
    unittest.main()
