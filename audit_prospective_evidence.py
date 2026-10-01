"""Audit real archived observation evidence in the frozen prospective runner."""
import argparse
import json
from pathlib import Path
import tempfile

from m6_research import sha
from prospective_research import SOURCE, load_registration, run


def audit(args):
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(output)
    ledger = Path(args.evidence_ledger)
    watched = [Path(args.registration), Path(args.candidate), Path(args.previous_protocol)]
    watched += [p for p in ledger.rglob("*") if p.is_file()]
    before = {str(p.resolve()): sha(p) for p in watched}
    record = load_registration(args.registration, args.candidate, args.previous_protocol,
                               args.expected_registration_sha256)
    with tempfile.TemporaryDirectory(prefix="price-evidence-audit-") as temporary:
        result = run(args.snapshot, args.registration, args.candidate, args.previous_protocol,
                     args.expected_registration_sha256, Path(temporary) / "status.json",
                     evidence_ledger=ledger, expected_evidence_sha256=args.expected_evidence_sha256)
        evidence = result["specification_evidence"]
        checks = dict(
            reviewed_ledger=evidence["ledger_sha256"] == args.expected_evidence_sha256,
            observations_verified=evidence["status"] == "VERIFIED_OBSERVATIONS_ONLY",
            all_registered_folds=len(evidence["folds"]) == len(record["folds"]),
            all_registered_assets=True, registered_windows=True, zero_certified_coverage=True,
            no_execution_parameter_mapping=evidence["used_for_execution_parameters"] is False,
            no_promotion=result["acceptance"]["status"] == "NOT_VALIDATED",
            historical_specs_blocked=result["acceptance"]["checks"]["verified_historical_specs"] is False,
            exact_costs_blocked=result["acceptance"]["checks"]["exact_cost_evidence"] is False,
            awaiting_future_data=result["status"] == "AWAITING_FUTURE_DATA" and not result["experiments"])
        for fold, bounds in zip(evidence["folds"], record["folds"]):
            checks["registered_windows"] &= fold["required_window"] == dict(
                start=bounds["test_start"], end=bounds["test_end"], end_exclusive=True)
            checks["all_registered_assets"] &= [a["symbol"] for a in fold["assets"]] == record["protocol"]["assets"]
            checks["zero_certified_coverage"] &= all(
                a["verified_coverage_seconds"] == 0 and a["historical_specs_verified"] is False
                and a["exact_costs_verified"] is False
                and a["uncovered_intervals"] == [dict(start=bounds["test_start"], end=bounds["test_end"])]
                for a in fold["assets"])
        frozen = {name: sha(SOURCE / name) == digest for name, digest in record["source_sha256"].items()}
        checks["frozen_sources_unchanged"] = all(frozen.values())
        checks["archive_and_registration_unchanged"] = before == {str(p.resolve()): sha(p) for p in watched}
        if not all(checks.values()):
            raise AssertionError(checks)
        artifact = dict(version="m6-prospective-evidence-audit-v1", engineering_status="PASSED",
                        evaluated_at=result["evaluated_at"], checks=checks,
                        registration_sha256=args.expected_registration_sha256,
                        input_sha256=before, frozen_sources_unchanged=frozen,
                        current_status=result["status"], strategy_status=result["acceptance"]["status"],
                        specification_evidence=evidence, acceptance=result["acceptance"],
                        code_sha256=result["code_sha256"])
        with output.open("x", encoding="utf-8") as target:
            target.write(json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        print(json.dumps(dict(engineering_status=artifact["engineering_status"], checks=checks)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot")
    parser.add_argument("registration")
    parser.add_argument("candidate")
    parser.add_argument("--previous-protocol", default=str(SOURCE / "research/m6_protocol.json"))
    parser.add_argument("--expected-registration-sha256", required=True)
    parser.add_argument("--evidence-ledger", required=True)
    parser.add_argument("--expected-evidence-sha256", required=True)
    parser.add_argument("--output", required=True)
    audit(parser.parse_args())


if __name__ == "__main__":
    main()
