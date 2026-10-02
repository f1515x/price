"""Audit multi-asset coverage against a pinned registration asset inventory."""
import argparse
from pathlib import Path

from audit_intraday_history import audit as audit_asset
from contract_specs import digest, encoded
from intraday_batch import assets, verify_batch
from spec_evidence import _json


def audit(directory, batch_sha256, registration, registration_sha256):
    directory = Path(directory)
    report = verify_batch(directory, batch_sha256)
    raw = Path(registration).read_bytes()
    if digest(raw) != registration_sha256:
        raise ValueError("Registration differs from pinned SHA-256")
    registered_assets = assets(_json(raw)["protocol"]["assets"])
    if set(report["symbols"]) != set(registered_assets):
        raise ValueError("Batch does not cover the registered asset inventory")
    inventory = _json((directory / "batch.json").read_bytes())["archives"]
    asset_audits = {entry["symbol"]: audit_asset(directory / entry["directory"],
                    entry["manifest_sha256"], registration, registration_sha256)
                    for entry in inventory}
    checks = dict(
        registered_assets_covered=set(asset_audits) == set(registered_assets),
        all_asset_audits_passed=all(a["engineering_status"] == "PASSED" for a in asset_audits.values()),
        complete_shared_window=report["quality_status"] == "COMPLETE",
        expected_asset_minutes_observed=report["valid_asset_minutes"] == report["expected_asset_minutes"],
        no_unclosed_minutes=all(a["unclosed_minutes"] == 0 for a in report["assets"].values()),
        no_execution_certification=report["market_fills_verified"] is False,
        no_spec_certification=report["historical_specs_verified"] is False,
        strategy_still_unvalidated=report["acceptance_status"] == "NOT_VALIDATED",
        repeated_verification=verify_batch(directory, batch_sha256) == report)
    if not all(checks.values()):
        raise AssertionError(checks)
    root = Path(__file__).parent
    return dict(engineering_status="PASSED", acceptance_status="NOT_VALIDATED",
                batch_sha256=batch_sha256, registration_sha256=registration_sha256,
                checks=checks, asset_audits=asset_audits, report=report,
                source_sha256={name: digest((root / name).read_bytes()) for name in
                               ("intraday_batch.py", "audit_intraday_batch.py")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--batch-sha256", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--registration-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(args.archive, args.batch_sha256, args.registration, args.registration_sha256)
    with Path(args.output).open("xb") as output:
        output.write(encoded(result))
    print(result["engineering_status"], len(result["checks"]), "batch checks;",
          sum(len(a["checks"]) for a in result["asset_audits"].values()), "asset checks")


if __name__ == "__main__":
    main()
