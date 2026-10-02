"""Reproduce intraday order policy scenarios against pinned real notice events."""
import argparse
from pathlib import Path

from contract_specs import digest, encoded
from historical_notices import verify
from intraday_orders import replay
from spec_evidence import _json


def audit(previous, prior_sha256, registration, archive):
    prior_bytes = Path(previous).read_bytes()
    if digest(prior_bytes) != prior_sha256:
        raise ValueError("Prior acceptance hash mismatch")
    prior = _json(prior_bytes)
    registration_bytes = Path(registration).read_bytes()
    if digest(registration_bytes) != prior["registration_sha256"]:
        raise ValueError("Registration hash mismatch")
    frozen = _json(registration_bytes)["source_sha256"]
    def unchanged():
        return all(digest(Path(__file__).with_name(n).read_bytes()) == h for n, h in frozen.items())
    if not unchanged():
        raise ValueError("Frozen source changed")
    sha = prior["real_reports"][0]["notice_evidence"]["manifest_sha256"]
    evidence = verify(archive, sha)
    scenarios, results = [], []
    for event in evidence["events"]:
        t = event["effective_timestamp"]
        spec = dict(multiplier="1", quantity_step="0.1", min_quantity="1",
                    max_quantity="100", price_tick="0.05")
        spec[event["field"]] = event["before"]
        scenario = dict(symbol=event["symbol"], start=t-1, end=t+2,
                        initial_specification=spec, actions=[
            dict(kind="submit", timestamp=t-1, order_id="old", direction=1,
                 quantity="1", limit_price="100"),
            dict(kind="submit", timestamp=t, order_id="new", direction=-1,
                 quantity="1", limit_price="100"),
            dict(kind="fill", timestamp=t+1, order_id="new", price="100")])
        result = replay(archive, sha, scenario, digest(encoded(scenario)), allow_scenario=True)
        scenarios.append(scenario)
        results.append(result)
    checks = dict(
        two_real_events=len(results) == 2,
        exact_notice_seconds=all(r["audit_log"][1]["timestamp"] == e["effective_timestamp"]
                                for r, e in zip(results, evidence["events"])),
        old_orders_cancelled=all(r["audit_log"][1]["cancelled_order_ids"] == ["old"] for r in results),
        new_orders_filled=all(len(r["fills"]) == 1 and r["fills"][0]["order_id"] == "new" for r in results),
        after_fields_applied=all(r["fills"][0]["specification"][e["field"]] == e["after"]
                                 for r, e in zip(results, evidence["events"])),
        no_certification=all(not r["historical_specs_verified"] and not r["market_fills_verified"]
            and r["verified_coverage_seconds"] == 0 and r["acceptance_status"] == "NOT_VALIDATED" for r in results),
        notices_unchanged=verify(archive, sha) == evidence,
        registration_unchanged=Path(registration).read_bytes() == registration_bytes,
        prior_unchanged=Path(previous).read_bytes() == prior_bytes,
        frozen_sources_unchanged=unchanged())
    if not all(checks.values()):
        raise AssertionError(checks)
    return dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
                scenario_origin="SYNTHETIC_ORDERS_AND_FILLS_REAL_NOTICE_TIMESTAMPS",
                initial_specification_origin="DECLARED_IMMEDIATELY_BEFORE_WINDOW_NOT_CERTIFIED",
                scenarios=scenarios, results=results, frozen_files=len(frozen),
                registration_sha256=prior["registration_sha256"], prior_acceptance_sha256=prior_sha256,
                source_sha256={n: digest(Path(__file__).with_name(n).read_bytes()) for n in
                               ("intraday_orders.py", "audit_intraday_orders.py")})


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
