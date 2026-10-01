"""Read-only table/CSV presentation of versioned offline research candidates."""
import argparse
import csv
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path

from candidate_store import list_runs, query_candidates
from candidate_quality import quality_report
from event_study import RULES
from history import date_timestamp
from kline import normalize_symbol

VERSION = "offline-candidate-report-v1"
TABLE_COLUMNS = ("bar_time_utc", "close", "ret_30d_pct", "return_percentile",
                 "signed_move", "stretch_atr", "trend", "weak_type",
                 "raw_weak_price", "strong_price", "data_status", "direction",
                 "decision_status", "reasons", "opportunity_score", "structure_percentile")
COLUMNS = ("report_version", "run_id", "snapshot_id", "symbol", "market", "interval",
           "source", "rule", "bar_time_utc", "signal_time_utc", "earliest_execution_time_utc",
           "close", "ret_30d_pct", "return_percentile", "signed_move", "stretch_atr",
           "sample_count", "trend", "weak_type", "raw_weak_price", "strong_price",
           "structure_confirmed_at_utc", "data_status", "indicator_status", "structure_status",
           "direction", "decision_status", "reasons", "indicator_reasons", "structure_reasons",
           "opportunity_score", "structure_percentile", "validation", "execution_authorized",
           "parameters_json", "input_sha256_json", "implementation_sha256_json")


def _utc(stamp):
    return None if stamp is None else datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def report(database, run_id, symbol, rule="percentile_structure", start=None, end=None):
    """Explicit version and rule; preserve unavailable/nontriggered rows and reasons."""
    if rule not in RULES:
        raise ValueError("Unknown candidate rule")
    symbol = normalize_symbol(symbol)
    metadata = next((r for r in list_runs(database) if r["run_id"] == run_id), None)
    if metadata is None or metadata["symbol"] != symbol:
        raise ValueError("Candidate run does not belong to requested symbol")
    rows = query_candidates(database, run_id, symbol, start, end)
    parameters = _json({k: metadata[k] for k in
                        ("parameters", "indicator_parameters", "structure_parameters")})
    output = []
    for row in rows:
        a, b, decision = row["indicator"], row["structure"], row["decisions"][rule]
        output.append(dict(
            report_version=VERSION, run_id=run_id, snapshot_id=metadata["snapshot_id"],
            symbol=symbol, market=row["market"], interval=row["interval"], source=row["source"], rule=rule,
            bar_time_utc=_utc(row["timestamp"]), signal_time_utc=_utc(row["signal_time"]),
            earliest_execution_time_utc=_utc(row["earliest_execution_time"]), close=row["close"],
            ret_30d_pct=None if a["ret_30d"] is None else 100 * a["ret_30d"],
            return_percentile=a["return_percentile"], signed_move=a["signed_move"], stretch_atr=a["stretch_atr"],
            sample_count=a["history_count"], trend=b["trend"], weak_type=b["weak_type"],
            raw_weak_price=b["raw_weak_price"], strong_price=b["strong_price"],
            structure_confirmed_at_utc=_utc(b["structure_confirmed_at"]),
            data_status="OK" if row["eligible"] else "UNAVAILABLE",
            indicator_status=a["status"], structure_status=b["status"],
            direction={1: "LONG", -1: "SHORT", 0: "NONE"}[decision["direction"]],
            decision_status=decision["status"], reasons=";".join(decision["reasons"]),
            indicator_reasons=_json(a["reasons"]), structure_reasons=";".join(b["reasons"]),
            opportunity_score=row["opportunity_score"], structure_percentile=row["structure_percentile"],
            validation=row["validation"], execution_authorized=row["execution_authorized"],
            parameters_json=parameters, input_sha256_json=_json(metadata["input_sha256"]),
            implementation_sha256_json=_json(metadata["implementation_sha256"])))
    return metadata, output


def render(metadata, rows, rule, format="table"):
    if format == "csv":
        stream = StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: "N/A" if v is None else v for k, v in row.items()} for row in rows)
        return stream.getvalue()
    if format != "table":
        raise ValueError("Unknown report format")
    def display(value):
        return "N/A" if value is None else format_number(value)
    values = [[display(row[k]) for k in TABLE_COLUMNS] for row in rows]
    widths = [max([len(k)] + [len(row[i]) for row in values]) for i, k in enumerate(TABLE_COLUMNS)]
    lines = [f"{VERSION} | {metadata['symbol']} | {rule} | {len(rows)} bars (not independent events/trades)",
             f"run_id={metadata['run_id']} | snapshot_id={metadata['snapshot_id']}",
             f"validation={metadata['validation']} | execution_authorized={metadata['execution_authorized']}",
             "parameters=" + _json({k: metadata[k] for k in
                                     ("parameters", "indicator_parameters", "structure_parameters")}),
             " | ".join(k.ljust(w) for k, w in zip(TABLE_COLUMNS, widths)),
             "-+-".join("-" * w for w in widths)]
    lines.extend(" | ".join(v.ljust(w) for v, w in zip(row, widths)) for row in values)
    if "sample_quality" in metadata:
        lines.insert(3, "sample_quality=" + _json(metadata["sample_quality"]))
    if not rows:
        lines.append("No rows in requested UTC bar range.")
    return "\n".join(lines) + "\n"


def format_number(value):
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("symbol")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--rule", choices=RULES, default="percentile_structure")
    parser.add_argument("--start", type=date_timestamp, help="Inclusive UTC bar date")
    parser.add_argument("--end", type=date_timestamp, help="Exclusive UTC bar date")
    parser.add_argument("--format", choices=("table", "csv", "quality-json"), default="table")
    parser.add_argument("--output", help="New UTF-8 file; existing files are never overwritten")
    args = parser.parse_args(argv)
    metadata, rows = report(args.database, args.run_id, args.symbol, args.rule, args.start, args.end)
    if args.format in ("table", "quality-json"):
        quality = quality_report(args.database, args.run_id, args.symbol, args.rule, args.start, args.end)
        metadata["sample_quality"] = {k: quality[k] for k in ("coverage", "availability", "quality")}
        metadata["sample_quality"]["events"] = {k: v for k, v in quality["events"].items() if k != "retained"}
    content = (json.dumps(quality, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
               if args.format == "quality-json" else render(metadata, rows, args.rule, args.format))
    if args.output:
        with Path(args.output).open("x", encoding="utf-8", newline="") as target:
            target.write(content)
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
