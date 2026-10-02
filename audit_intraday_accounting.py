"""Audit fee declarations on pinned real-notice partial-order scenarios."""
import argparse
from fractions import Fraction
from pathlib import Path

from audit_partial_orders import audit as audit_partial
from contract_specs import digest, encoded
from intraday_accounting import account


def exact(value):
    return Fraction(value["numerator"], value["denominator"])


def audit(previous, prior_sha256, registration, archive):
    baseline = audit_partial(previous, prior_sha256, registration, archive)
    policies, results = [], []
    for scenario, replayed in zip(baseline["scenarios"], baseline["results"]):
        stamp = next(e["timestamp"] for e in replayed["audit_log"] if e["kind"] == "notice")
        policy = dict(initial_collateral="1000", fee_periods=[
            dict(start=scenario["start"], end=stamp, rate="0.001"),
            dict(start=stamp, end=scenario["end"], rate="0.002")])
        policies.append(policy)
        results.append(account(archive, replayed["notice_evidence"]["manifest_sha256"],
            scenario, digest(encoded(scenario)), policy, digest(encoded(policy)), allow_scenario=True))
    checks = dict(baseline["checks"])
    checks.update(
        partial_order_replays_unchanged=all(r["replay"] == old for r, old in zip(results, baseline["results"])),
        exact_fill_second_rates=all([f["fee_period_index"] for f in r["ledger"]] == [0, 1, 1] for r in results),
        exact_gross_fees=all(exact(r["total_fees"]) == Fraction(21, 100) for r in results),
        zero_same_price_realized_pnl=all(exact(r["realized_pnl"]) == 0 for r in results),
        collateral_reconciles=all(exact(r["collateral_balance"]) == Fraction(99979, 100) for r in results),
        no_inferred_equity_or_funding=all(r["equity"] is None and r["unrealized_pnl"] is None
                                         and not r["funding_included"] for r in results),
        no_cost_certification_or_risk_claim=all(not r["costs_verified"] and not r["risk_budget_enforced"]
                                               and r["acceptance_status"] == "NOT_VALIDATED" for r in results),
        policies_pinned=all(r["policy_sha256"] == digest(encoded(p)) for r, p in zip(results, policies)),
        final_evidence_recheck=audit_partial(previous, prior_sha256, registration, archive) == baseline)
    if not all(checks.values()):
        raise AssertionError(checks)
    return dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
                scenario_origin="DECLARED_COSTS_AND_FILLS_REAL_NOTICE_TIMESTAMPS",
                policies=policies, scenarios=baseline["scenarios"], results=results, baseline=baseline,
                registration_sha256=baseline["registration_sha256"],
                source_sha256={n: digest(Path(__file__).with_name(n).read_bytes()) for n in
                               ("intraday_accounting.py", "audit_intraday_accounting.py")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--expected-prior-sha256", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if Path(args.output).exists():
        raise FileExistsError(args.output)
    result = audit(args.previous, args.expected_prior_sha256, args.registration, args.archive)
    with Path(args.output).open("xb") as target:
        target.write(encoded(result))
    print(result["engineering_status"], len(result["checks"]), "checks")
