"""Recompute a pinned real minute archive and check frozen research sources."""
import argparse
from pathlib import Path

from contract_specs import digest, encoded
from intraday_history import verify, STEP
from spec_evidence import _json


def audit(archive, manifest_sha256, registration, registration_sha256):
    rows, report = verify(archive, manifest_sha256)
    body = Path(registration).read_bytes()
    if digest(body) != registration_sha256:
        raise ValueError("Registration differs from pinned SHA-256")
    frozen = _json(body)["source_sha256"]
    root = Path(__file__).parent
    source_checks = {name: digest((root / name).read_bytes()) == sha
                     for name, sha in frozen.items()}
    checks = dict(
        frozen_sources_unchanged=all(source_checks.values()),
        complete_closed_window=report["quality_status"] == "COMPLETE",
        exact_minute_inventory=[r["timestamp"] for r in rows]
        == list(range(report["start"], report["end_exclusive"], STEP)),
        nonempty_real_observations=bool(rows),
        no_quality_issues=not report["issues"],
        no_missing_minutes=not report["missing_timestamps"],
        no_execution_certification=report["market_fills_verified"] is False,
        no_spec_certification=report["historical_specs_verified"] is False,
        strategy_still_unvalidated=report["acceptance_status"] == "NOT_VALIDATED",
        repeated_archive_verification=verify(archive, manifest_sha256) == (rows, report))
    if not all(checks.values()):
        raise AssertionError(checks)
    return dict(engineering_status="PASSED", acceptance_status="NOT_VALIDATED",
                manifest_sha256=manifest_sha256, registration_sha256=registration_sha256,
                checks=checks, frozen_source_checks=source_checks, report=report,
                source_sha256={p.name: digest(p.read_bytes()) for p in
                               (root / "intraday_history.py", Path(__file__))})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--registration-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(args.archive, args.manifest_sha256, args.registration, args.registration_sha256)
    with Path(args.output).open("xb") as output:
        output.write(encoded(result))
    print(result["engineering_status"], len(result["checks"]), "checks")


if __name__ == "__main__":
    main()
