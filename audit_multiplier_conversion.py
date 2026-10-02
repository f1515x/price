"""Audit synthetic multiplier policy and recheck pinned real-notice regressions."""
import argparse
from fractions import Fraction
from pathlib import Path

from audit_notice_execution import fixture_notice
from audit_partial_orders import audit as audit_partial
from contract_specs import digest, encoded
from intraday_orders import CONVERSION_POLICY, replay
from spec_evidence import _json


def audit(destination, previous, prior_sha256, registration, archive):
    baseline = audit_partial(previous, prior_sha256, registration, archive)
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    synthetic = destination / "synthetic-notices"
    fixture_notice(synthetic, effective_at="1970-01-01T00:00:10Z")
    manifest_path = synthetic / "notices.json"
    manifest = _json(manifest_path.read_bytes())
    event = manifest["events"][0]
    manifest["events"] = [dict(event, field="multiplier",
        rationale="SYNTHETIC declared multiplier change; not real exchange evidence"),
        dict(event, id="step", field="quantity_step", before="0.1", after="0.01",
             rationale="SYNTHETIC simultaneous quantity step assertion"),
        dict(event, id="second", field="multiplier", before="2.5", after="1",
             effective_at="1970-01-01T00:00:15Z",
             rationale="SYNTHETIC second multiplier assertion, not real evidence")]
    manifest_path.write_bytes(encoded(manifest))
    sha = digest(manifest_path.read_bytes())
    scenarios, results = [], []
    for direction in (1, -1):
        scenario = dict(symbol="ETH", start=0, end=20,
            multiplier_conversion_policy=CONVERSION_POLICY,
            initial_specification=dict(multiplier="2", quantity_step="0.1",
                min_quantity="0.1", max_quantity="2", price_tick="0.01"), actions=[
                dict(kind="submit", timestamp=1, order_id="open", direction=direction,
                     quantity="1", limit_price="100"),
                dict(kind="fill", timestamp=2, order_id="open", price="100", quantity="0.1"),
                dict(kind="submit", timestamp=10, order_id="close", direction=-direction,
                     quantity="0.08", limit_price="100"),
                dict(kind="fill", timestamp=10, order_id="close", price="100")])
        # The reduced minimum is part of this synthetic simultaneous transition.
        scenarios.append(scenario)
    manifest["events"].append(dict(event, id="minimum", field="min_quantity",
        before="0.1", after="0.01", rationale="SYNTHETIC new order minimum assertion"))
    manifest_path.write_bytes(encoded(manifest))
    sha = digest(manifest_path.read_bytes())
    for scenario in scenarios:
        results.append(replay(synthetic, sha, scenario, digest(encoded(scenario)), allow_scenario=True))
    def reject(scenario):
        try:
            replay(synthetic, sha, scenario, digest(encoded(scenario)), allow_scenario=True)
        except ValueError as exc:
            return str(exc)
        raise AssertionError("Expected rejection")
    default = dict(scenarios[0])
    del default["multiplier_conversion_policy"]
    default_error = reject(default)
    # First conversion leaves 0.08 contracts; make the new step incompatible.
    bad_manifest = _json(manifest_path.read_bytes())
    bad_manifest["events"][1]["after"] = "0.03"
    from historical_notices import build
    bad_archive = destination / "misaligned-synthetic-notices"
    blobs = {d["file"]: (synthetic / d["file"]).read_bytes()
             for d in bad_manifest["documents"].values()}
    build(bad_manifest, blobs, bad_archive)
    bad_sha = digest((bad_archive / "notices.json").read_bytes())
    try:
        replay(bad_archive, bad_sha, scenarios[0], digest(encoded(scenarios[0])), allow_scenario=True)
    except ValueError as exc:
        alignment_error = str(exc)
    else:
        raise AssertionError("Misaligned conversion unexpectedly passed")
    checks = dict(baseline["checks"])
    checks.update(
        two_directions={r["fills"][0]["direction"] for r in results} == {-1, 1},
        remainder_cancelled=all(r["audit_log"][2]["cancelled_quantities"] == {"open": "0.9"} for r in results),
        exact_converted_contracts=all(r["audit_log"][2]["multiplier_conversion"]["after_contracts"]
            == dict(numerator=r["fills"][0]["direction"]*2, denominator=25) for r in results),
        same_second_close_after_conversion=all(r["fills"][1]["timestamp"] == 10 for r in results),
        base_exposure_conservation=all(sum(Fraction(**f["signed_base_exposure"]) for f in r["fills"])
            == Fraction(**r["net_base_exposure"]) == 0 for r in results),
        flat_final_contracts=all(r["net_position_contracts"] == dict(numerator=0, denominator=1) for r in results),
        repeated_transition_processed=all(len([e for e in r["audit_log"] if e["kind"] == "notice"]) == 2 for r in results),
        default_rejects_held="explicit multiplier conversion" in default_error,
        misaligned_rejected="new quantity step" in alignment_error,
        policy_hash_pinned=all(r["scenario_sha256"] == digest(encoded(s)) for s, r in zip(scenarios, results)),
        no_conversion_certification=all(r["acceptance_status"] == "NOT_VALIDATED"
            and not r["market_fills_verified"] and not r["historical_specs_verified"] for r in results),
        real_evidence_final_recheck=audit_partial(previous, prior_sha256, registration, archive) == baseline)
    if not all(checks.values()):
        raise AssertionError(checks)
    return dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
        scenario_origin="SYNTHETIC_MULTIPLIER_EVENTS_ORDERS_AND_FILLS_NOT_REAL_EVIDENCE",
        policy=CONVERSION_POLICY, scenarios=scenarios, results=results,
        rejection_reasons=dict(default=default_error, misaligned=alignment_error), baseline=baseline,
        input_sha256={str(p.relative_to(destination)): digest(p.read_bytes())
                      for p in sorted(destination.rglob("*")) if p.is_file()},
        source_sha256={n: digest(Path(__file__).with_name(n).read_bytes()) for n in
            ("intraday_orders.py", "audit_multiplier_conversion.py")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("destination", "previous", "expected-prior-sha256", "registration", "archive", "output"):
        parser.add_argument("--" + option, required=True)
    args = parser.parse_args()
    if Path(args.output).exists():
        raise FileExistsError(args.output)
    result = audit(args.destination, args.previous, args.expected_prior_sha256, args.registration, args.archive)
    with Path(args.output).open("xb") as target:
        target.write(encoded(result))
    print(result["engineering_status"], len(result["checks"]), "checks")
