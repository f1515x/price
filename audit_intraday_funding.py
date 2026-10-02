"""Audit declared funding on pinned real-notice partial-fill scenarios."""
import argparse
from fractions import Fraction
from pathlib import Path

from audit_intraday_accounting import audit as audit_accounting
from contract_specs import digest, encoded
from intraday_funding import ORDERING, exact, settle


def audit(previous, prior_sha256, registration, archive):
    baseline = audit_accounting(previous, prior_sha256, registration, archive)
    policies, results = [], []
    for scenario, fees, old in zip(baseline["scenarios"], baseline["policies"], baseline["results"]):
        stamps = list(range(scenario["start"], scenario["end"]))
        policy = dict(symbol=scenario["symbol"], start=scenario["start"], end=scenario["end"],
                      ordering=ORDERING, scheduled_timestamps=stamps, settlements=[
                          dict(timestamp=t, rate="0.01", settlement_price="100") for t in stamps])
        policies.append(policy)
        results.append(settle(archive, old["replay"]["notice_evidence"]["manifest_sha256"],
                              scenario, digest(encoded(scenario)), fees, digest(encoded(fees)),
                              policy, digest(encoded(policy)), allow_scenario=True))
    checks = dict(baseline["checks"])
    checks.update(
        fee_accounting_unchanged=all(r["accounting"] == old for r, old in zip(results, baseline["results"])),
        complete_declared_schedule=all([e["timestamp"] for e in r["settlement_ledger"]]
                                      == p["scheduled_timestamps"] for r, p in zip(results, policies)),
        exact_pre_second_exposures=all([exact(e["net_base_exposure"]) for e in r["settlement_ledger"]]
                                      == [0, Fraction(1, 10), 0] for r in results),
        exact_funding_cashflows=all([exact(e["funding_cashflow"]) for e in r["settlement_ledger"]]
                                    == [0, Fraction(-1, 10), 0] for r in results),
        settlement_balances_reconcile=all([exact(e["collateral_balance"]) for e in r["settlement_ledger"]]
                                          == [1000, Fraction(99989, 100), Fraction(99987, 100)] for r in results),
        exact_final_balance=all(exact(r["collateral_balance"]) == Fraction(99969, 100) for r in results),
        fill_balances_include_prior_funding=all([exact(e["collateral_balance"]) for e in r["fill_ledger"]]
                                               == [Fraction(99999, 100), Fraction(99987, 100), Fraction(99969, 100)]
                                               for r in results),
        funding_policies_pinned=all(r["funding_policy_sha256"] == digest(encoded(p)) for r, p in zip(results, policies)),
        no_funding_certification=all(not r["funding_schedule_verified"] and not r["costs_verified"]
                                     and not r["risk_budget_enforced"] and r["equity"] is None
                                     and r["acceptance_status"] == "NOT_VALIDATED" for r in results),
        final_accounting_evidence_recheck=audit_accounting(previous, prior_sha256, registration, archive) == baseline)
    if not all(checks.values()):
        raise AssertionError(checks)
    return dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
                scenario_origin="DECLARED_FUNDING_SCHEDULE_RATES_PRICES_AND_FILLS_REAL_NOTICE_TIMESTAMPS",
                policies=policies, results=results, baseline=baseline,
                registration_sha256=baseline["registration_sha256"],
                source_sha256={n: digest(Path(__file__).with_name(n).read_bytes()) for n in
                               ("intraday_funding.py", "audit_intraday_funding.py")})


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
