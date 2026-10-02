"""Immutable Gate one-minute market observations; never infer executions."""
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from contract_specs import digest, encoded, DOCS
from history import ENDPOINT
from kline import normalize_symbol
from spec_evidence import _json

VERSION = "gate-intraday-observations-v1"
STEP = 60
PAGE_SIZE = 1000


def boundaries(start, end, as_of):
    if (any(type(t) is not int or t < 0 for t in (start, end, as_of))
            or start >= end or start % STEP or end % STEP):
        raise ValueError("Increasing UTC minute boundaries and integer as_of required")


def page_parameters(symbol, start, end):
    return [dict(contract=normalize_symbol(symbol) + "_USDT", interval="1m",
                 **{"from": left, "to": min(end, left + PAGE_SIZE * STEP) - 1})
            for left in range(start, end, PAGE_SIZE * STEP)]


def request_bytes(url):
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=30) as response:
        return response.read()


def value(raw, positive=True):
    if type(raw) not in (int, str):
        raise ValueError("Exact numeric string/integer required")
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError("Invalid price or volume")
    return result


def prepare(pages, symbol, start, end, as_of):
    boundaries(start, end, as_of)
    symbol = normalize_symbol(symbol)
    grouped, issues = {}, []
    expected = page_parameters(symbol, start, end)
    if len(pages) != len(expected):
        raise ValueError("Incomplete page inventory")
    raw_count = 0
    for index, (raw, params) in enumerate(zip(pages, expected)):
        if not isinstance(raw, list):
            raise ValueError("API response must be a list")
        raw_count += len(raw)
        for row_index, item in enumerate(raw):
            location = dict(page=index, row=row_index)
            if (not isinstance(item, dict) or type(item.get("t")) is not int
                    or item["t"] < 0):
                issues.append(dict(location, reason="INVALID_TIMESTAMP"))
                continue
            stamp = item["t"]
            if stamp % STEP or not params["from"] <= stamp <= params["to"]:
                issues.append(dict(location, timestamp=stamp, reason="OFF_GRID_OR_OUTSIDE_PAGE"))
                continue
            if stamp + STEP > as_of:
                issues.append(dict(location, timestamp=stamp, reason="UNCLOSED"))
                continue
            grouped.setdefault(stamp, []).append(item)
    rows = []
    for stamp, items in sorted(grouped.items()):
        try:
            values = [tuple(value(item[k], positive=k != "v")
                            for k in ("o", "h", "l", "c", "v")) for item in items]
            for o, h, l, c, v in values:
                if not l <= min(o, c) <= max(o, c) <= h:
                    raise ValueError("Invalid OHLC ordering")
        except (KeyError, TypeError, ValueError):
            issues.append(dict(timestamp=stamp, reason="INVALID_OHLCV"))
            continue
        if len(items) > 1:
            conflict = len(set(values)) != 1
            issues.append(dict(timestamp=stamp, reason="CONFLICTING_DUPLICATE" if conflict else "DUPLICATE"))
            if conflict:
                continue
        rows.append(dict(timestamp=stamp, symbol=symbol, interval="1m",
                         market="gate_usdt_perpetual", source=ENDPOINT,
                         **dict(zip(("open", "high", "low", "close", "volume"),
                                    map(str, values[0])))))
    observed = {r["timestamp"] for r in rows}
    closed_end = min(end, as_of // STEP * STEP)
    missing = [t for t in range(start, closed_end, STEP) if t not in observed]
    report = dict(version=VERSION, symbol=symbol, start=start, end_exclusive=end, as_of=as_of,
                  raw_count=raw_count, valid_count=len(rows), missing_timestamps=missing,
                  issues=issues, timestamp_semantics="UTC minute start; closed at t + 60",
                  volume_unit="contracts", market_fills_verified=False,
                  historical_specs_verified=False, acceptance_status="NOT_VALIDATED",
                  quality_status="COMPLETE" if not missing and not issues and closed_end == end
                  else "INCOMPLETE_OR_ISSUES")
    return rows, report


def collect(directory, symbol, start, end, *, as_of=None, fetch=request_bytes):
    as_of = int(time.time()) if as_of is None else as_of
    boundaries(start, end, as_of)
    symbol = normalize_symbol(symbol)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    pages, inventory = [], []
    for index, params in enumerate(page_parameters(symbol, start, end)):
        url = ENDPOINT + "?" + urlencode(params)
        body = fetch(url)
        if not isinstance(body, bytes):
            raise ValueError("Transport must return original response bytes")
        name = f"page-{index:04d}.json"
        (directory / name).write_bytes(body)
        pages.append(_json(body))
        inventory.append(dict(file=name, params=params, url=url, sha256=digest(body)))
    rows, report = prepare(pages, symbol, start, end, as_of)
    row_bytes = encoded(rows)
    (directory / "minutes.json").write_bytes(row_bytes)
    manifest = dict(report=report, pages=inventory, rows_sha256=digest(row_bytes),
                    documentation_url=DOCS, source_sha256=digest(Path(__file__).read_bytes()))
    body = encoded(manifest)
    (directory / "manifest.json").write_bytes(body)
    sha = digest(body)
    verify(directory, sha)
    return sha, report


def verify(directory, expected_sha256):
    directory = Path(directory)
    body = (directory / "manifest.json").read_bytes()
    if digest(body) != expected_sha256:
        raise ValueError("Manifest differs from pinned SHA-256")
    manifest = _json(body)
    report = manifest["report"]
    if report["version"] != VERSION:
        raise ValueError("Unsupported observation version")
    boundaries(report["start"], report["end_exclusive"], report["as_of"])
    expected = page_parameters(report["symbol"], report["start"], report["end_exclusive"])
    if len(manifest["pages"]) != len(expected):
        raise ValueError("Incomplete page inventory")
    pages = []
    for index, (entry, params) in enumerate(zip(manifest["pages"], expected)):
        name = f"page-{index:04d}.json"
        if (entry["file"] != name or entry["params"] != params
                or entry["url"] != ENDPOINT + "?" + urlencode(params)):
            raise ValueError("Page provenance mismatch")
        raw = (directory / name).read_bytes()
        if digest(raw) != entry["sha256"]:
            raise ValueError("Page checksum mismatch")
        pages.append(_json(raw))
    rows, rebuilt = prepare(pages, report["symbol"], report["start"], report["end_exclusive"], report["as_of"])
    row_bytes = (directory / "minutes.json").read_bytes()
    if digest(row_bytes) != manifest["rows_sha256"] or row_bytes != encoded(rows):
        raise ValueError("Derived rows differ from raw observations")
    if rebuilt != report:
        raise ValueError("Rebuilt quality report mismatch")
    return rows, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    parser.add_argument("--start", type=int, required=True, help="Inclusive UTC epoch second")
    parser.add_argument("--end", type=int, required=True, help="Exclusive UTC epoch second")
    parser.add_argument("--output", required=True, help="New archive directory")
    args = parser.parse_args()
    sha, report = collect(args.output, args.symbol, args.start, args.end)
    print(json.dumps(dict(manifest_sha256=sha, report=report)))


if __name__ == "__main__":
    main()
