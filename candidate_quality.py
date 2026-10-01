"""Read-only sample coverage and event spacing audit of an explicit candidate run."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from candidate_store import _digest, list_runs, query_candidates
from event_study import RULES
from history import DAY, date_timestamp, load_snapshot
from history_store import list_snapshots, query_daily
from kline import normalize_symbol

VERSION = "candidate-sample-quality-v1"


def quality_report(database, run_id, symbol, rule="percentile_structure", start=None,
                   end=None, dedup_days=30):
    """Count spaced event starts, never statistical independence or trades.

    Deduplication starts at the beginning of the selected run, across directions,
    before range filtering. This preserves event identity for sliced reports.
    """
    symbol = normalize_symbol(symbol)
    if rule not in RULES or type(dedup_days) is not int or dedup_days < 1:
        raise ValueError("Invalid rule/event spacing")
    for value in (start, end):
        if value is not None and (type(value) is not int or value % DAY):
            raise ValueError("Expected UTC midnight boundaries")
    if start is not None and end is not None and start >= end:
        raise ValueError("Expected increasing time boundaries")
    run = next((r for r in list_runs(database) if r["run_id"] == run_id), None)
    if run is None or run["symbol"] != symbol:
        raise ValueError("Candidate run does not belong to requested symbol")
    snapshot = next(s for s in list_snapshots(database) if s["snapshot_id"] == run["snapshot_id"])
    bars, quality = load_snapshot(snapshot["source_directory"])
    if (_digest(quality) != run["snapshot_id"] or quality != json.loads(snapshot["report_json"])
            or quality["sha256"] != run["input_sha256"]
            or bars != query_daily(database, run["snapshot_id"], symbol)):
        raise ValueError("Historical evidence mismatch")
    rows = query_candidates(database, run_id, symbol)
    if (len(rows) != run["row_count"] or _digest(rows) != run["output_sha256"]
            or [r["timestamp"] for r in rows] != [r["timestamp"] for r in bars]):
        raise ValueError("Candidate evidence mismatch")
    left = max(quality["start"], start if start is not None else quality["start"])
    closed_end = min(quality["end_exclusive"], int(quality["as_of"]) // DAY * DAY)
    right = min(closed_end, end if end is not None else closed_end)
    right = max(left, right)
    selected = [r for r in rows if left <= r["timestamp"] < right]
    observed = {r["timestamp"] for r in selected}
    missing = [t for t in range(left, right, DAY) if t not in observed]
    retained, last = [], None
    for row in rows:
        if row["decisions"][rule]["direction"] and (
                last is None or row["signal_time"] - last >= dedup_days * DAY):
            last = row["signal_time"]
            if left <= row["timestamp"] < right:
                retained.append(dict(timestamp=row["timestamp"], signal_time=last,
                                     direction=row["decisions"][rule]["direction"]))
    counts = Counter(r["decisions"][rule]["status"] for r in selected)
    history_counts = [r["indicator"]["history_count"] for r in selected]
    issues = Counter(i["reason"] for i in quality["issues"]
                     if "timestamp" in i and left <= i["timestamp"] < right)
    return dict(
        version=VERSION, run_id=run_id, snapshot_id=run["snapshot_id"], symbol=symbol,
        rule=rule, requested_range=dict(start=start, end_exclusive=end),
        coverage=dict(start=left, end_exclusive=right, calendar_days=(right-left)//DAY,
                      observations=len(selected), missing_count=len(missing),
                      missing_timestamps=missing,
                      first_observation=selected[0]["timestamp"] if selected else None,
                      last_observation=selected[-1]["timestamp"] if selected else None),
        availability=dict(eligible=sum(r["eligible"] for r in selected),
                          unavailable=counts["UNAVAILABLE"],
                          no_candidate=counts["NO_CANDIDATE"],
                          raw_candidate_bars=counts["RESEARCH_CANDIDATE"],
                          history_count_min=min(history_counts) if history_counts else None,
                          history_count_max=max(history_counts) if history_counts else None),
        quality=dict(range_timestamped_issues=dict(sorted(issues.items())),
                     source_total_issues=len(quality["issues"]),
                     source_issues_without_timestamp=sum("timestamp" not in i for i in quality["issues"])),
        events=dict(dedup_days=dedup_days, count=len(retained), retained=retained,
                    protocol="greedy_all_directions_full_run_then_range_filter",
                    independent_sample_count=None, trades=None,
                    future_label_completeness="NOT_EVALUATED"),
        validation=run["validation"], execution_authorized=run["execution_authorized"],
        evidence=dict(input_sha256=run["input_sha256"],
                      candidate_output_sha256=run["output_sha256"],
                      implementation_sha256=run["implementation_sha256"],
                      quality_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
        limitations=["Spaced event starts do not prove statistical independence or profitability.",
                     "No future labels, fills, returns or costs are evaluated.",
                     "Counts belong to one asset/run/rule; overlapping versions must not be added."])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("symbol")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--rule", choices=RULES, default="percentile_structure")
    parser.add_argument("--start", type=date_timestamp)
    parser.add_argument("--end", type=date_timestamp)
    parser.add_argument("--dedup-days", type=int, default=30)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = quality_report(args.database, args.run_id, args.symbol, args.rule,
                            args.start, args.end, args.dedup_days)
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        with Path(args.output).open("x", encoding="utf-8") as target:
            target.write(content)
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
