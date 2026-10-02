"""Pinned multi-asset minute archives with independently rebuilt coverage."""
import argparse
import json
from pathlib import Path
import time

from contract_specs import digest, encoded
from intraday_history import boundaries, collect, request_bytes, verify, STEP
from kline import normalize_symbol
from spec_evidence import _json

VERSION = "gate-intraday-batch-v1"


def assets(symbols):
    if not isinstance(symbols, (list, tuple)) or not symbols:
        raise ValueError("Nonempty asset inventory required")
    result = [normalize_symbol(s) for s in symbols]
    if len(set(result)) != len(result):
        raise ValueError("Duplicate normalized asset")
    return result


def coverage(directory, symbols, start, end, as_of, archives):
    boundaries(start, end, as_of)
    symbols = assets(symbols)
    if not isinstance(archives, list) or len(archives) != len(symbols):
        raise ValueError("Incomplete asset inventory")
    reports = {}
    for symbol, entry in zip(symbols, archives):
        if entry["symbol"] != symbol or entry["directory"] != symbol:
            raise ValueError("Asset identity or archive path mismatch")
        rows, report = verify(Path(directory) / symbol, entry["manifest_sha256"])
        if (report["symbol"], report["start"], report["end_exclusive"], report["as_of"]) != (
                symbol, start, end, as_of):
            raise ValueError("Asset window mismatch")
        expected = (end - start) // STEP
        reports[symbol] = dict(expected_minutes=expected, valid_minutes=len(rows),
                               missing_timestamps=report["missing_timestamps"],
                               unclosed_minutes=max(0, (end - max(start, min(end, as_of // STEP * STEP))) // STEP),
                               issues=report["issues"], quality_status=report["quality_status"])
    return dict(version=VERSION, symbols=symbols, start=start, end_exclusive=end,
                as_of=as_of, assets=reports,
                expected_asset_minutes=sum(r["expected_minutes"] for r in reports.values()),
                valid_asset_minutes=sum(r["valid_minutes"] for r in reports.values()),
                quality_status="COMPLETE" if all(r["quality_status"] == "COMPLETE"
                                                 for r in reports.values()) else "INCOMPLETE_OR_ISSUES",
                market_fills_verified=False, historical_specs_verified=False,
                acceptance_status="NOT_VALIDATED")


def collect_batch(directory, symbols, start, end, *, as_of=None, fetch=request_bytes):
    as_of = int(time.time()) if as_of is None else as_of
    boundaries(start, end, as_of)
    symbols = assets(symbols)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    inventory = []
    for symbol in symbols:
        sha, _ = collect(directory / symbol, symbol, start, end, as_of=as_of, fetch=fetch)
        inventory.append(dict(symbol=symbol, directory=symbol, manifest_sha256=sha))
    report = coverage(directory, symbols, start, end, as_of, inventory)
    body = encoded(dict(report=report, archives=inventory,
                        source_sha256=digest(Path(__file__).read_bytes())))
    (directory / "batch.json").write_bytes(body)
    sha = digest(body)
    verify_batch(directory, sha)
    return sha, report


def verify_batch(directory, expected_sha256):
    directory = Path(directory)
    body = (directory / "batch.json").read_bytes()
    if digest(body) != expected_sha256:
        raise ValueError("Batch differs from pinned SHA-256")
    manifest = _json(body)
    report = manifest["report"]
    if report["version"] != VERSION:
        raise ValueError("Unsupported batch version")
    rebuilt = coverage(directory, report["symbols"], report["start"], report["end_exclusive"],
                       report["as_of"], manifest["archives"])
    if rebuilt != report:
        raise ValueError("Rebuilt multi-asset coverage mismatch")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--start", required=True, type=int)
    parser.add_argument("--end", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--verify-sha256", help="Verify an existing batch offline instead of collecting")
    args = parser.parse_args()
    if args.verify_sha256:
        report = verify_batch(args.output, args.verify_sha256)
        if (report["symbols"], report["start"], report["end_exclusive"]) != (
                assets(args.symbols), args.start, args.end):
            raise ValueError("Verified batch differs from requested assets/window")
        sha = args.verify_sha256
    else:
        sha, report = collect_batch(args.output, args.symbols, args.start, args.end)
    print(json.dumps(dict(batch_sha256=sha, report=report)))


if __name__ == "__main__":
    main()
