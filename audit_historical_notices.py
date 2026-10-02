"""Archive two web-tool reviewed real Gate notice excerpts and audit provenance."""
import argparse
from pathlib import Path

from contract_specs import digest, encoded
from historical_notices import VERSION, SCOPE, build, verify
from spec_evidence import _json


def inputs():
    # Short excerpts copied from official pages opened with the web tool on
    # 2026-10-01. These are selected, noncontiguous lines, NOT raw HTML bytes.
    entries = [
        ("47661", "price_tick", "0.05", "0.01", "2025-10-18T08:00:00Z",
         "effective October 18, 2025, 8:00 (UTC).", "Before | After",
         "USDT-M Perpetual Futures | ETH_USDT | 0.05 | 0.01", "lines 71, 73, 75"),
        ("50325", "min_quantity", "1", "0.1", "2026-03-24T02:00:00Z",
         "March 24, 2026, 02:00 (UTC)",
         "Min Order Size (Contracts)(Before) | Min Order Size (Contracts) (After)",
         "ETHUSDT | 1 | 0.1", "lines 73, 76, 80"),
    ]
    docs, events, blobs = {}, [], {}
    for number, field, before, after, effective, date, header, row, locator in entries:
        name = "gate-" + number + ".txt"
        body = (date + "\n" + header + "\n" + row + "\n").encode()
        blobs[name] = body
        docs[number] = dict(file=name, sha256=digest(body),
                            url="https://www.gate.com/announcements/article/" + number,
                            retrieved_at="2026-10-02T01:39:39Z",
                            capture_method="WEB_TOOL_SHORT_EXCERPT", source_locator=locator)
        bindings = {}
        for key, text in (("effective_time", date), ("table_header", header), ("table_row", row)):
            start = body.index(text.encode())
            bindings[key] = dict(start=start, end=start + len(text.encode()), text=text)
        events.append(dict(id="eth-" + number, symbol="ETH", field=field, before=before, after=after,
                           effective_at=effective, document=number, bindings=bindings,
                           reviewer="Codex source review 2026-10-01",
                           rationale="Official notice date and ETH row mapped to this field; no end date inferred."))
    return dict(version=VERSION, scope=SCOPE, market="gate_usdt_perpetual",
                documents=docs, events=events), blobs


def audit(destination, registration, expected_registration_sha256):
    original = Path(registration).read_bytes()
    if digest(original) != expected_registration_sha256:
        raise ValueError("Registration differs from pinned SHA-256")
    frozen = _json(original)
    source_root = Path(__file__).parent
    hashes = frozen["source_sha256"]
    if not all(digest((source_root / n).read_bytes()) == h for n, h in hashes.items()):
        raise ValueError("Frozen sources changed")
    manifest, blobs = inputs()
    build(manifest, blobs, destination)
    sha = digest((Path(destination) / "notices.json").read_bytes())
    report = verify(destination, sha)
    checks = dict(two_real_notice_events=len(report["events"]) == 2,
                  byte_bound_excerpts=all(e["bindings"] for e in report["events"]),
                  both_intraday=all(e["intraday_boundary"] for e in report["events"]),
                  no_inferred_end=all(e["inferred_validity_end"] is None for e in report["events"]),
                  no_certified_coverage=report["verified_coverage_seconds"] == 0,
                  no_execution_parameters=report["used_for_execution_parameters"] is False,
                  not_validated=report["acceptance_status"] == "NOT_VALIDATED",
                  frozen_source_unchanged=all(digest((source_root / n).read_bytes()) == h for n, h in hashes.items()),
                  registration_unchanged=Path(registration).read_bytes() == original)
    if not all(checks.values()):
        raise ValueError("Notice audit failed: " + str(checks))
    return dict(engineering_status="PASSED", checks=checks, frozen_files=len(hashes), evidence=report,
                registration_sha256=digest(original),
                audit_code_sha256=digest(Path(__file__).read_bytes()),
                direct_download_status="HTTP_403_NOT_ARCHIVED_AS_ORIGINAL_HTML")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--expected-registration-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if Path(args.output).exists():
        raise FileExistsError(args.output)
    report = audit(args.destination, args.registration, args.expected_registration_sha256)
    with Path(args.output).open("xb") as f:
        f.write(encoded(report))
    print(report["engineering_status"], len(report["checks"]), "checks")


if __name__ == "__main__":
    main()
