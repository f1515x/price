"""Immutable current-spec evidence ledger; never certifies historical validity."""
import argparse
from decimal import Decimal
import json
from pathlib import Path

from contract_specs import digest, encoded, load_snapshot
from history import date_timestamp
from kline import normalize_symbol

VERSION = "contract-spec-evidence-v1"
NUMERIC = ("multiplier", "min_quantity", "max_quantity", "quantity_step",
           "price_tick", "maker_fee_rate", "taker_fee_rate")
FIELDS = NUMERIC + ("funding_interval_seconds", "status")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def _json(body):
    return json.loads(body, object_pairs_hook=_object,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def _snapshot(path):
    """Validate original evidence and retain exact bytes, including API responses."""
    path = Path(path)
    body = (path / "specs.json").read_bytes()
    parsed = _json(body)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("contracts"), list):
        raise ValueError("Expected contract snapshot")
    raw = {}
    for record in parsed["contracts"]:
        symbol = normalize_symbol(record["symbol"])
        if record.get("raw_file") != symbol + "-raw.json":
            raise ValueError("Unsafe raw evidence path")
        raw[record["raw_file"]] = (path / record["raw_file"]).read_bytes()
        _json(raw[record["raw_file"]])
    report = load_snapshot(path)
    # Catch accidental concurrent changes during collection/verification.
    if (path / "specs.json").read_bytes() != body or any(
            (path / name).read_bytes() != value for name, value in raw.items()):
        raise ValueError("Snapshot changed during read")
    return report, {"specs.json": body, **raw}


def _value(record, field):
    value = record[field]
    if field in NUMERIC and value is not None:
        return str(Decimal(value).normalize())
    return value


def summarize(snapshots, symbols, start, end):
    """Count observations and differences; no interpolation between observations."""
    if (type(start) is not int or type(end) is not int or start < 0 or start >= end):
        raise ValueError("Expected increasing nonnegative UTC Unix boundaries")
    symbols = [normalize_symbol(s) for s in symbols]
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("Provide unique required symbols")
    result = []
    for symbol in symbols:
        observations = []
        for sha, report in sorted(snapshots.items()):
            for record in report["contracts"]:
                if record["symbol"] == symbol:
                    observations.append(dict(record, snapshot_sha256=sha))
        observations.sort(key=lambda r: (r["observed_at"], r["snapshot_sha256"]))
        changes, previous = [], None
        for record in observations:
            if previous is not None:
                changed = [k for k in FIELDS if _value(record, k) != _value(previous, k)]
                if changed and record["observed_at"] == previous["observed_at"]:
                    raise ValueError("Conflicting same-time specifications: " + symbol)
                if changed:
                    changes.append(dict(previous_observed_at=previous["observed_at"],
                                        observed_at=record["observed_at"], fields=changed,
                                        effective_time=None))
            previous = record
        reasons = ["NO_HISTORICAL_VALIDITY_INTERVALS", "PUBLIC_FEES_NOT_REALIZED_COSTS"]
        if not observations:
            reasons.append("NO_SPEC_OBSERVATIONS")
        if any(r["quantity_step"] is None or Decimal(r["min_quantity"]) <= 0 for r in observations):
            reasons.append("UNRESOLVED_QUANTITY_PRECISION")
        if any(r["status"] == "NOT_TRADING" for r in observations):
            reasons.append("NON_TRADING_OBSERVATION")
        result.append(dict(symbol=symbol, observations=observations,
                           observation_count=len(observations),
                           observations_in_window=sum(start <= r["observed_at"] < end for r in observations),
                           observed_changes=changes, historical_specs_verified=False,
                           exact_costs_verified=False, verified_coverage_seconds=0,
                           uncovered_intervals=[dict(start=start, end=end)], reasons=reasons))
    return dict(required_window=dict(start=start, end=end, end_exclusive=True), assets=result,
                acceptance_status="NOT_VALIDATED", temporal_scope="OBSERVATIONS_ONLY")


def build(snapshot_paths, destination, symbols, start, end):
    """Bundle verified snapshots and a reproducible gap report; never overwrite."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    snapshots, blobs = {}, {}
    for path in snapshot_paths:
        report, files = _snapshot(path)
        sha = digest(files["specs.json"])
        snapshots[sha], blobs[sha] = report, files
    if not snapshots:
        raise ValueError("At least one verified snapshot required")
    analysis = summarize(snapshots, symbols, start, end)
    manifest = dict(version=VERSION, source_sha256=digest(Path(__file__).read_bytes()),
                    validator_sha256=digest(Path(__file__).with_name("contract_specs.py").read_bytes()),
                    snapshots=[dict(snapshot_sha256=sha,
                                    files={name: digest(body) for name, body in sorted(blobs[sha].items())})
                               for sha in sorted(snapshots)], **analysis)
    # All inputs and schema pass before the first write.
    destination.mkdir(parents=True, exist_ok=False)
    for sha, files in sorted(blobs.items()):
        target = destination / "snapshots" / sha
        target.mkdir(parents=True)
        for name, body in files.items():
            (target / name).write_bytes(body)
    (destination / "ledger.json").write_bytes(encoded(manifest))
    return manifest


def verify(destination, expected_sha256):
    """Pin the reviewed ledger and recompute every snapshot and gap finding."""
    destination = Path(destination)
    body = (destination / "ledger.json").read_bytes()
    if digest(body) != expected_sha256:
        raise ValueError("Ledger differs from reviewed SHA-256")
    ledger = _json(body)
    if ledger.get("version") != VERSION:
        raise ValueError("Unsupported evidence ledger")
    snapshots = {}
    for entry in ledger["snapshots"]:
        sha = entry["snapshot_sha256"]
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("Invalid snapshot SHA-256")
        if sha in snapshots:
            raise ValueError("Duplicate snapshot entry")
        report, files = _snapshot(destination / "snapshots" / sha)
        if digest(files["specs.json"]) != sha or entry["files"] != {
                name: digest(value) for name, value in files.items()}:
            raise ValueError("Archived evidence hash mismatch")
        snapshots[sha] = report
    if not snapshots:
        raise ValueError("Empty evidence ledger")
    window = ledger["required_window"]
    computed = summarize(snapshots, [r["symbol"] for r in ledger["assets"]], window["start"], window["end"])
    if any(ledger.get(k) != value for k, value in computed.items()):
        raise ValueError("Evidence findings differ from recomputation")
    return ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("build")
    create.add_argument("snapshots", nargs="+")
    create.add_argument("--symbols", nargs="+", required=True)
    create.add_argument("--start", required=True, help="UTC YYYY-MM-DD inclusive")
    create.add_argument("--end", required=True, help="UTC YYYY-MM-DD exclusive")
    create.add_argument("--output", required=True)
    check = sub.add_parser("verify")
    check.add_argument("ledger_directory")
    check.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    if args.command == "build":
        report = build(args.snapshots, args.output, args.symbols,
                       date_timestamp(args.start), date_timestamp(args.end))
        sha = digest((Path(args.output) / "ledger.json").read_bytes())
    else:
        report = verify(args.ledger_directory, args.expected_sha256)
        sha = args.expected_sha256
    print(json.dumps(dict(status=report["acceptance_status"], ledger_sha256=sha,
                          assets=[dict(symbol=r["symbol"], observations=r["observation_count"],
                                       changes=len(r["observed_changes"]), reasons=r["reasons"])
                                  for r in report["assets"]]), indent=2))


if __name__ == "__main__":
    main()
