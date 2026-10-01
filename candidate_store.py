"""Versioned offline candidate decision logs; research only, never orders."""
import argparse
from contextlib import closing
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from event_study import Config as EventConfig, RULES, signals
from history import date_timestamp, load_snapshot
from history_store import _read, list_snapshots, query_daily
from indicators import Config as IndicatorConfig, calculate
from kline import normalize_symbol
from structure_history import Config as StructureConfig, replay

VERSION = "daily-candidate-log-v1"


@dataclass(frozen=True)
class Config:
    tail: float = 10
    move: float = 2
    stretch: float = 2

    def __post_init__(self):
        EventConfig(tail=self.tail, move=self.move, stretch=self.stretch)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def decisions(rows, config=Config(), indicator_config=IndicatorConfig(),
              structure_config=StructureConfig()):
    """Log every closed bar using M4's common eligibility and unchanged rules.

    No future labels, event deduplication, score, risk approval or price orders.
    Unavailable observations remain visible rather than silently disappearing.
    """
    rows = list(rows)
    indicators = calculate(rows, indicator_config)
    structures = replay(rows, structure_config)
    thresholds = EventConfig(**asdict(config))
    output = []
    for indicator, structure in zip(indicators, structures):
        reasons = ["MISSING_" + key.upper() for key in
                   ("ret_30d", "return_percentile", "signed_move", "stretch_atr")
                   if indicator[key] is None]
        if structure["status"] != "OK":
            reasons.append("STRUCTURE_UNAVAILABLE")
        values = signals(indicator, structure, thresholds) if not reasons else dict.fromkeys(RULES, 0)
        missed = {}
        if not reasons:
            ret = indicator["ret_30d"]
            direction = 1 if ret < 0 else -1 if ret > 0 else 0
            aligned = structure["weak_type"] == ("low" if direction == 1 else "high")
            gates = dict(
                percentile=[] if values["percentile"] else ["RETURN_TAIL_NOT_MET"],
                move=[] if values["move"] else ["MOVE_THRESHOLD_NOT_MET"],
                stretch=[] if values["stretch"] else ["STRETCH_THRESHOLD_NOT_MET"],
                structure=[] if aligned else ["STRUCTURE_DIRECTION_CONFLICT"])
            missed = {rule: gates[rule] for rule in ("percentile", "move", "stretch")}
            for rule, extra in (("percentile_move", "move"), ("percentile_stretch", "stretch"),
                                ("percentile_structure", "structure")):
                missed[rule] = gates["percentile"] + gates[extra]
            missed["legacy_proxy"] = (gates["structure"]
                                      + ([] if abs(ret) > .15 else ["LEGACY_RETURN_THRESHOLD_NOT_MET"])
                                      + ([] if structure["ratio"] is not None and -direction*structure["ratio"] > .10
                                         else ["LEGACY_RATIO_THRESHOLD_NOT_MET"]))
            if not direction:
                missed = {rule: ["ZERO_RETURN"] for rule in RULES}
        rule_decisions = {}
        for rule, direction in values.items():
            rule_decisions[rule] = dict(
                direction=direction,
                status="UNAVAILABLE" if reasons else "RESEARCH_CANDIDATE" if direction else "NO_CANDIDATE",
                reasons=reasons if reasons else ["RULE_TRIGGERED"] if direction else missed[rule])
        output.append(dict(timestamp=indicator["timestamp"], symbol=indicator["symbol"],
                           market=indicator["market"], interval=indicator["interval"],
                           source=indicator["source"], close=indicator["close"],
                           signal_time=indicator["signal_time"],
                           earliest_execution_time=structure["earliest_execution_time"],
                           eligible=not reasons, reasons=reasons,
                           indicator=indicator, structure=structure, decisions=rule_decisions,
                           opportunity_score=None, structure_percentile=None,
                           validation="NOT_VALIDATED", execution_authorized=False))
    return output


def build_candidates(database, snapshot_ids, config=Config(),
                     indicator_config=IndicatorConfig(), structure_config=StructureConfig()):
    snapshots = {s["snapshot_id"]: s for s in list_snapshots(database)}
    implementation = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                      for name in ("candidate_store.py", "event_study.py", "history.py",
                                   "indicators.py", "structure_history.py", "smc.py")}
    prepared = []
    for sid in snapshot_ids:
        if sid not in snapshots:
            raise ValueError("Unknown snapshot")
        snapshot = snapshots[sid]
        rows, report = load_snapshot(snapshot["source_directory"])
        if (_digest(report) != sid or report != json.loads(snapshot["report_json"])
                or len(rows) != snapshot["row_count"]
                or rows != query_daily(database, sid, snapshot["symbol"])):
            raise ValueError("Stored snapshot differs from verified original evidence")
        output = decisions(rows, config, indicator_config, structure_config)
        metadata = dict(snapshot_id=sid, symbol=snapshot["symbol"], version=VERSION,
                        parameters=asdict(config), indicator_parameters=asdict(indicator_config),
                        structure_parameters=asdict(structure_config), rules=list(RULES),
                        implementation_sha256=implementation, input_sha256=report["sha256"],
                        output_sha256=_digest(output), row_count=len(output),
                        protocol="M4_common_eligibility_all_bars_no_labels_no_dedup",
                        validation="NOT_VALIDATED", execution_authorized=False)
        prepared.append((_digest(metadata), metadata, output))
    if not prepared:
        raise ValueError("At least one snapshot is required")
    result = []
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=rw", uri=True)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS candidate_runs (
                run_id TEXT PRIMARY KEY,
                snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
                symbol TEXT NOT NULL, metadata_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS candidate_rows (
                run_id TEXT NOT NULL REFERENCES candidate_runs(run_id),
                timestamp INTEGER NOT NULL, payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, timestamp))""")
            for rid, metadata, rows in prepared:
                existing = db.execute("SELECT 1 FROM candidate_runs WHERE run_id=?", (rid,)).fetchone()
                if not existing:
                    db.execute("INSERT INTO candidate_runs VALUES (?, ?, ?, ?)",
                               (rid, metadata["snapshot_id"], metadata["symbol"], _json(metadata)))
                    db.executemany("INSERT INTO candidate_rows VALUES (?, ?, ?)",
                                   [(rid, row["timestamp"], _json(row)) for row in rows])
                result.append(dict(run_id=rid, inserted=not bool(existing), **metadata))
            db.commit()
        except Exception:
            db.rollback()
            raise
    return result


def _has_runs(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidate_runs'").fetchone()


def list_runs(database):
    with closing(_read(database)) as db:
        if not _has_runs(db):
            return []
        return [dict(run_id=row["run_id"], **json.loads(row["metadata_json"]))
                for row in db.execute("SELECT * FROM candidate_runs ORDER BY symbol, run_id")]


def query_candidates(database, run_id, symbol, start=None, end=None):
    """Explicit run and asset; UTC daily bucket boundaries [start,end)."""
    symbol = normalize_symbol(symbol)
    if start is not None and end is not None and start >= end:
        raise ValueError("Expected increasing time boundaries")
    with closing(_read(database)) as db:
        run = db.execute("SELECT symbol FROM candidate_runs WHERE run_id=?", (run_id,)).fetchone() if _has_runs(db) else None
        if run is None or run["symbol"] != symbol:
            raise ValueError("Candidate run does not belong to requested symbol")
        conditions, args = ["run_id=?"], [run_id]
        for operator, value in ((">=", start), ("<", end)):
            if value is not None:
                conditions.append("timestamp " + operator + " ?")
                args.append(value)
        return [json.loads(row[0]) for row in db.execute(
            "SELECT payload_json FROM candidate_rows WHERE " + " AND ".join(conditions)
            + " ORDER BY timestamp", args)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("snapshot_ids", nargs="+")
    build.add_argument("--window", type=int, default=365)
    build.add_argument("--ema-period", type=int, default=50)
    build.add_argument("--atr-period", type=int, default=14)
    build.add_argument("--swing-length", type=int, default=50)
    build.add_argument("--tail", type=float, default=10)
    build.add_argument("--move", type=float, default=2)
    build.add_argument("--stretch", type=float, default=2)
    commands.add_parser("list")
    query = commands.add_parser("query")
    query.add_argument("symbol")
    query.add_argument("--run-id", required=True)
    query.add_argument("--start", type=date_timestamp)
    query.add_argument("--end", type=date_timestamp)
    args = parser.parse_args(argv)
    if args.command == "build":
        result = build_candidates(args.database, args.snapshot_ids,
                                  Config(args.tail, args.move, args.stretch),
                                  IndicatorConfig(args.window, args.ema_period, args.atr_period),
                                  StructureConfig(args.swing_length))
    elif args.command == "list":
        result = list_runs(args.database)
    else:
        result = query_candidates(args.database, args.run_id, args.symbol, args.start, args.end)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
