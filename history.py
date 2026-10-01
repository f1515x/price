"""Reproducible Gate USDT perpetual daily research snapshots (standard library only)."""
import argparse
import csv
import hashlib
import io
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from kline import normalize_symbol

DAY = 86400
ENDPOINT = "https://api.gateio.ws/api/v4/futures/usdt/candlesticks"
VERSION = "gate-daily-v1"
FIELDS = ["timestamp", "symbol", "market", "interval", "source", "open", "high",
          "low", "close", "volume", "ret_30d", "return_status"]


def date_timestamp(value):
    return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def request_page(params):
    request = Request(ENDPOINT + "?" + urlencode(params), headers={"Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    if not isinstance(result, list):
        raise ValueError("Gate response must be a list")
    return result


def fetch_daily(symbol, start, end, fetch=request_page):
    """Fetch [start, end) in bounded pages, including empty pages in the audit."""
    symbol = normalize_symbol(symbol)
    if start % DAY or end % DAY or start >= end:
        raise ValueError("Expected increasing UTC midnight boundaries")
    rows, pages = [], []
    for left in range(start, end, 1000 * DAY):
        right = min(end, left + 1000 * DAY)
        params = {"contract": symbol + "_USDT", "interval": "1d", "timezone": "utc0",
                  "from": left, "to": right - 1}
        batch = fetch(params)
        if not isinstance(batch, list):
            raise ValueError("Gate response must be a list")
        rows.extend(batch)
        pages.append({"params": params, "count": len(batch)})
    return rows, pages


def prepare(raw, symbol, start, end, as_of):
    """Reject bad bars; conflicting duplicates invalidate that timestamp entirely."""
    symbol = normalize_symbol(symbol)
    if start % DAY or end % DAY or start >= end:
        raise ValueError("Expected increasing UTC midnight boundaries")
    issues, grouped = [], {}
    for index, item in enumerate(raw):
        try:
            value = float(item["t"])
            if not math.isfinite(value) or not value.is_integer() or value < 0:
                raise ValueError()
            stamp = int(value)
        except (KeyError, TypeError, ValueError, OverflowError):
            issues.append({"row": index, "reason": "INVALID_TIMESTAMP"})
            continue
        if stamp % DAY or not start <= stamp < end:
            issues.append({"row": index, "timestamp": stamp, "reason": "OFF_GRID_OR_OUTSIDE_RANGE"})
            continue
        if stamp + DAY > as_of:
            issues.append({"row": index, "timestamp": stamp, "reason": "UNCLOSED"})
            continue
        grouped.setdefault(stamp, []).append(item)
    valid = {}
    for stamp, items in grouped.items():
        values = []
        try:
            for item in items:
                o, h, l, c, v = (float(item[key]) for key in ("o", "h", "l", "c", "v"))
                if not all(math.isfinite(x) for x in (o, h, l, c, v)):
                    raise ValueError()
                if min(o, h, l, c) <= 0 or v < 0 or not l <= min(o, c) <= max(o, c) <= h:
                    raise ValueError()
                values.append((o, h, l, c, v))
        except (KeyError, TypeError, ValueError, OverflowError):
            issues.append({"timestamp": stamp, "reason": "INVALID_OHLCV"})
            continue
        if len(items) > 1:
            conflict = len(set(values)) > 1
            issues.append({"timestamp": stamp, "reason": "CONFLICTING_DUPLICATE" if conflict else "DUPLICATE",
                           "extra_rows": len(items) - 1})
            if conflict:
                continue
        valid[stamp] = values[0]
    closed_end = min(end, int(as_of) // DAY * DAY)
    missing = [t for t in range(start, closed_end, DAY) if t not in valid]
    rows, consecutive = [], 0
    previous = None
    for stamp, (o, h, l, c, v) in sorted(valid.items()):
        consecutive = consecutive + 1 if previous == stamp - DAY else 1
        previous = stamp
        ready = consecutive >= 31
        rows.append(dict(zip(FIELDS, [stamp, symbol, "gate_usdt_perpetual", "1d", ENDPOINT,
                                     o, h, l, c, v,
                                     c / valid[stamp - 30 * DAY][3] - 1 if ready else "",
                                     "OK" if ready else "INSUFFICIENT_DATA"])))
    report = {"version": VERSION, "symbol": symbol, "start": start, "end_exclusive": end,
              "as_of": as_of, "timestamp_semantics": "UTC daily bucket start; closed at t + 86400",
              "volume_unit": "contracts", "raw_count": len(raw), "valid_count": len(rows),
              "missing_timestamps": missing, "issues": issues,
              "latest_contiguous_bars": consecutive,
              "research_status": "READY" if consecutive >= 396 and previous == closed_end - DAY else "INSUFFICIENT_DATA"}
    return rows, report


def save_snapshot(directory, raw, rows, report):
    """New immutable directory per acquisition; failed writes never replace prior data."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    raw_bytes = (json.dumps(raw, ensure_ascii=False, indent=2) + "\n").encode()
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    csv_bytes = output.getvalue().encode()
    (directory / "raw.json").write_bytes(raw_bytes)
    (directory / "daily.csv").write_bytes(csv_bytes)
    report = dict(report, sha256={"raw.json": hashlib.sha256(raw_bytes).hexdigest(),
                                 "daily.csv": hashlib.sha256(csv_bytes).hexdigest()})
    (directory / "quality.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def load_snapshot(directory):
    """Validate checksums and re-run the exact original quality/return calculation."""
    directory = Path(directory)
    report = json.loads((directory / "quality.json").read_text(encoding="utf-8"))
    if report["version"] != VERSION:
        raise ValueError("Unsupported data version")
    for name in ("raw.json", "daily.csv"):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != report["sha256"][name]:
            raise ValueError("Snapshot checksum mismatch: " + name)
    raw = json.loads((directory / "raw.json").read_text(encoding="utf-8"))
    rows, rebuilt = prepare(raw, report["symbol"], report["start"], report["end_exclusive"], report["as_of"])
    if any(report[key] != value for key, value in rebuilt.items()):
        raise ValueError("Snapshot report mismatch")
    return rows, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    parser.add_argument("--start", required=True, type=date_timestamp)
    parser.add_argument("--end", required=True, type=date_timestamp, help="Exclusive UTC date")
    parser.add_argument("--output", required=True, help="New snapshot directory")
    args = parser.parse_args()
    as_of = int(time.time())
    raw, pages = fetch_daily(args.symbol, args.start, args.end)
    rows, report = prepare(raw, args.symbol, args.start, args.end, as_of)
    report["pages"] = pages
    save_snapshot(args.output, raw, rows, report)
    load_snapshot(args.output)
    print(json.dumps({k: report[k] for k in ("valid_count", "latest_contiguous_bars", "research_status")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
