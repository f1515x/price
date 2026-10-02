"""Reproduce daily notice gates with retained synthetic and pinned real inputs."""
import argparse
from pathlib import Path

from audit_joint_execution import fixture
from contract_specs import digest, encoded
from historical_notices import build, VERSION, SCOPE
from history import DAY
from notice_execution import inspect, simulate_notice_joint
from spec_evidence import _json


def fixture_notice(destination, effective_at="1970-01-02T00:00:00Z", before="2", after="2.5"):
    body = f"{effective_at}\nBefore | After\nETH | {before} | {after}\n".encode()
    def binding(text):
        a = body.index(text.encode())
        return dict(start=a, end=a+len(text.encode()), text=text)
    manifest = dict(version=VERSION, scope=SCOPE, market="gate_usdt_perpetual",
        documents=dict(fixture=dict(file="fixture.txt", sha256=digest(body),
            url="https://www.gate.com/announcements/article/1", retrieved_at="2026-10-01T00:00:00Z",
            capture_method="WEB_TOOL_SHORT_EXCERPT", source_locator="SYNTHETIC fixture, not collected evidence")),
        events=[dict(id="synthetic-change", symbol="ETH", field="max_quantity", before=before,
            after=after, effective_at=effective_at, document="fixture", reviewer="synthetic fixture",
            rationale="Synthetic event to check daily scenario gating", bindings=dict(
                effective_time=binding(effective_at), table_header=binding("Before | After"),
                table_row=binding(f"ETH | {before} | {after}")))])
    build(manifest, {"fixture.txt": body}, destination)
    return digest((Path(destination) / "notices.json").read_bytes())


def audit(destination, previous, expected_prior_sha256, registration, archive):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    prior_bytes = Path(previous).read_bytes()
    if digest(prior_bytes) != expected_prior_sha256:
        raise ValueError("Prior acceptance hash mismatch")
    prior = _json(prior_bytes)
    registration_bytes = Path(registration).read_bytes()
    if digest(registration_bytes) != prior["registration_sha256"]:
        raise ValueError("Registration hash mismatch")
    frozen = _json(registration_bytes)["source_sha256"]
    def unchanged():
        return all(digest(Path(__file__).with_name(n).read_bytes()) == h for n, h in frozen.items())
    if not unchanged():
        raise ValueError("Frozen sources changed")
    real_reports = []
    for event in prior["evidence"]["events"]:
        start = event["effective_timestamp"] // DAY * DAY
        real_reports.append(inspect(archive, prior["evidence"]["manifest_sha256"],
                                    ["ETH"], start, start+DAY))
    rows, candidates, config, groups, inputs = fixture(destination / "joint")
    sha = fixture_notice(destination / "notices")
    result = simulate_notice_joint(rows, candidates, config, groups,
        notice_archive=destination / "notices", notice_sha256=sha, **inputs)
    checks = dict(real_intraday_events_blocked=all(r["policy_status"] == "BLOCKED" and
        r["blockers"][0]["reason"] == "INTRADAY_CHANGE_UNRESOLVABLE_WITH_DAILY_BARS" for r in real_reports),
        exact_real_timestamps=all(r["checked_events"][0]["effective_timestamp"] == e["effective_timestamp"]
            for r, e in zip(real_reports, prior["evidence"]["events"])),
        midnight_mapping_passed=result["daily_notice_policy"]["policy_status"] == "PASSED",
        both_trade_directions={t["direction"] for t in result["trades"]} == {-1, 1},
        unchanged_accounting=abs(result["summary"]["final_equity"]-9993.8457) < 1e-9,
        trade_notice_provenance=all(t["notice_manifest_sha256"] == sha for t in result["trades"]),
        no_certification=all(not r["historical_specs_verified"] and r["verified_coverage_seconds"] == 0
            and r["acceptance_status"] == "NOT_VALIDATED" for r in real_reports+[result["daily_notice_policy"]]),
        frozen_sources_unchanged=unchanged(), registration_unchanged=Path(registration).read_bytes() == registration_bytes,
        prior_unchanged=Path(previous).read_bytes() == prior_bytes)
    if not all(checks.values()):
        raise AssertionError(checks)
    return dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
        registration_sha256=prior["registration_sha256"], prior_acceptance_sha256=expected_prior_sha256,
        real_reports=real_reports, synthetic_result=result, frozen_files=len(frozen),
        input_sha256={str(p.relative_to(destination)): digest(p.read_bytes())
                      for p in sorted(destination.rglob("*")) if p.is_file()},
        audit_code_sha256=digest(Path(__file__).read_bytes()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--expected-prior-sha256", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if Path(args.output).exists():
        raise FileExistsError(args.output)
    report = audit(args.destination, args.previous, args.expected_prior_sha256, args.registration, args.archive)
    with Path(args.output).open("xb") as target:
        target.write(encoded(report))
    print(report["engineering_status"], len(report["checks"]), "checks")
