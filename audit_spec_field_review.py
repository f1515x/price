"""Reproduce field-review coverage and preserve actual historical evidence gaps."""
import argparse
import json
from pathlib import Path

from contract_specs import digest, encoded
from dated_specifications import FIELDS
from history import DAY
from spec_evidence import _json, verify
from spec_field_review import MARKET, VERSION, load


def audit(registration, expected_registration_sha256, ledger, expected_ledger_sha256, output):
    output = Path(output)
    inputs = output.with_suffix("")
    if output.exists() or inputs.exists():
        raise FileExistsError("Acceptance output or inputs already exist")
    registration = Path(registration)
    original = registration.read_bytes()
    if digest(original) != expected_registration_sha256:
        raise ValueError("Registration hash mismatch")
    record = _json(original)
    frozen = {name: digest(Path(__file__).with_name(name).read_bytes()) == sha
              for name, sha in record["source_sha256"].items()}
    if not all(frozen.values()):
        raise ValueError("Frozen source changed")
    observed = verify(ledger, expected_ledger_sha256)
    window = observed["required_window"]
    symbols = [a["symbol"] for a in observed["assets"]]
    # The actual archive contains observations, no effective historical notices.
    # Preserve that absence; do not invent effective dates or reviewer records.
    real = dict(version=VERSION, scope="REVIEW_ASSERTIONS_ONLY", market=MARKET,
                documents={}, claims=[])
    inputs.mkdir(parents=True, exist_ok=False)
    real_path = inputs / "real-review.json"
    real_path.write_bytes(encoded(real))
    actual = load(real_path, digest(real_path.read_bytes()), symbols, window["start"], window["end"])
    body = b"SYNTHETIC review assertions for coverage arithmetic; not issuer evidence.\n"
    (inputs / "fixture.txt").write_bytes(body)
    def claim(symbol, field, start, end, value, identifier):
        return dict(id=identifier, symbol=symbol, field=field, value=value, start=start, end=end,
                    document="fixture", excerpt_start=0, excerpt_end=len(body), excerpt=body.decode(),
                    reviewer="synthetic acceptance fixture", rationale="Coverage arithmetic only")
    claims = [claim(s, f, 0, 2*DAY, "1", s+"-"+f) for s in ("BTC", "ETH") for f in FIELDS]
    claims += [claim("BTC", "price_tick", DAY, 3*DAY, "2", "BTC-tick-conflict"),
               claim("ETH", "price_tick", DAY, 3*DAY, "1.00", "ETH-tick-equal")]
    synthetic = dict(real, documents=dict(fixture=dict(file="fixture.txt", sha256=digest(body),
                     origin="synthetic effective_notice label tests assertions, not authenticity", kind="effective_notice")),
                     claims=claims)
    synthetic_path = inputs / "synthetic-review.json"
    synthetic_path.write_bytes(encoded(synthetic))
    result = load(synthetic_path, digest(synthetic_path.read_bytes()), ["BTC", "ETH"], 0, 3*DAY)
    btc, eth = (a["fields"]["price_tick"] for a in result["assets"])
    synthetic["documents"]["fixture"]["kind"] = "observation"
    observation_path = inputs / "observation-review.json"
    observation_path.write_bytes(encoded(synthetic))
    ignored = load(observation_path, digest(observation_path.read_bytes()), ["BTC", "ETH"], 0, 3*DAY)
    checks = dict(frozen_sources_unchanged=all(frozen.values()),
                  registration_unchanged=registration.read_bytes() == original,
                  real_ledger_still_pinned=digest((Path(ledger)/"ledger.json").read_bytes()) == expected_ledger_sha256,
                  actual_observations_unverified=all(a["verified_coverage_seconds"] == 0 for a in observed["assets"]),
                  real_fields_all_missing=all(f["missing_intervals"] == [dict(start=window["start"], end=window["end"])]
                       and f["reviewed_coverage_seconds"] == 0 for a in actual["assets"] for f in a["fields"].values()),
                  conflict_excluded=btc["reviewed_coverage_seconds"] == 2*DAY
                       and btc["conflicting_intervals"] == [dict(start=DAY, end=2*DAY,
                            claim_ids=["BTC-price_tick", "BTC-tick-conflict"])],
                  equal_decimal_union=eth["reviewed_intervals"] == [dict(start=0, end=3*DAY)],
                  observation_cannot_supply_periods=all(f["reviewed_coverage_seconds"] == 0
                       for a in ignored["assets"] for f in a["fields"].values()),
                  no_promotion=all(r["acceptance_status"] == "NOT_VALIDATED" and not r["historical_specs_verified"]
                       and not r["used_for_execution_parameters"] for r in (actual, result, ignored)))
    if not all(checks.values()):
        raise AssertionError(checks)
    artifact = dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
                    registration_sha256=expected_registration_sha256, ledger_sha256=expected_ledger_sha256,
                    frozen_sources_unchanged=frozen, real_observation_report=observed,
                    real_review=actual, synthetic_review=result, observation_review=ignored,
                    input_sha256={p.name: digest(p.read_bytes()) for p in sorted(inputs.iterdir())},
                    audit_code_sha256=digest(Path(__file__).read_bytes()))
    with output.open("xb") as target:
        target.write(encoded(artifact))
    print(json.dumps(dict(engineering_status="PASSED", checks=checks)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registration")
    parser.add_argument("ledger")
    parser.add_argument("--expected-registration-sha256", required=True)
    parser.add_argument("--expected-ledger-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    audit(args.registration, args.expected_registration_sha256, args.ledger,
          args.expected_ledger_sha256, args.output)
