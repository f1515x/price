"""Check declared partial fills using the pinned real-notice audit inputs."""
import argparse
from fractions import Fraction
from pathlib import Path

from audit_intraday_orders import audit as audit_full
from contract_specs import digest, encoded
from intraday_orders import replay


def audit(previous, prior_sha256, registration, archive):
    baseline = audit_full(previous, prior_sha256, registration, archive)
    scenarios, results = [], []
    for original, full in zip(baseline["scenarios"], baseline["results"]):
        old, new, final = original["actions"]
        scenario = dict(original, actions=[old,
            dict(kind="fill", timestamp=old["timestamp"], order_id="old", price="100", quantity="0.1"),
            new, dict(kind="fill", timestamp=new["timestamp"], order_id="new", price="100", quantity="0.1"),
            final])
        r = replay(archive, full["notice_evidence"]["manifest_sha256"], scenario,
                   digest(encoded(scenario)), allow_scenario=True)
        scenarios.append(scenario)
        results.append(r)
    checks = dict(baseline["checks"])
    checks.update(
        three_fragments_each=all(len(r["fills"]) == 3 for r in results),
        cancellation_preserves_filled_quantity=all(
            r["audit_log"][2]["cancelled_quantities"] == {"old": "0.9"} for r in results),
        legacy_fill_consumes_remainder=all(r["fills"][-1]["quantity"] == "0.9" for r in results),
        exact_signed_conservation=all(
            sum(f["direction"] * Fraction(f["quantity"]) for f in r["fills"]) == Fraction(-9, 10)
            and r["net_position_contracts"] == dict(numerator=-9, denominator=10) for r in results),
        no_pending_remainders=all(r["pending_quantities"] == {} for r in results),
        partial_scenarios_pinned=all(r["scenario_sha256"] == digest(encoded(s))
                                   for s, r in zip(scenarios, results)))
    # Recheck pinned documents and frozen sources after both partial scenarios.
    repeated = audit_full(previous, prior_sha256, registration, archive)
    checks["final_evidence_recheck"] = repeated == baseline
    if not all(checks.values()):
        raise AssertionError(checks)
    return dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
                scenario_origin="DECLARED_PARTIAL_FILLS_REAL_NOTICE_TIMESTAMPS",
                partial_fill_policy="QUANTITY_STEP_ONLY_MINIMUM_APPLIES_AT_SUBMISSION",
                scenarios=scenarios, results=results, baseline=baseline,
                registration_sha256=baseline["registration_sha256"],
                source_sha256={n: digest(Path(__file__).with_name(n).read_bytes()) for n in
                    ("intraday_orders.py", "audit_partial_orders.py", "audit_intraday_orders.py")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--expected-prior-sha256", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(args.previous, args.expected_prior_sha256, args.registration, args.archive)
    with Path(args.output).open("xb") as target:
        target.write(encoded(result))
    print(result["engineering_status"], len(result["checks"]), "checks")
