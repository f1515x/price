"""Persist reproducible confirmed daily SMC structures alongside E1 history snapshots."""
import argparse
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3

from history import date_timestamp, load_snapshot
from history_store import _read, list_snapshots, query_daily
from structure_history import Config, VERSION, replay
from kline import normalize_symbol


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def build_structures(database, snapshot_ids, config=Config()):
    """Recheck original evidence and stored rows before an atomic batch build.

    Versions bind the full input report, parameters, implementation bytes and
    output digest. No caller-supplied structure JSON is trusted or imported.
    """
    snapshots = {s["snapshot_id"]: s for s in list_snapshots(database)}
    implementation = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                      for name in ("structure_history.py", "smc.py", "indicators.py")}
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
        output = replay(rows, config)
        metadata = dict(snapshot_id=sid, symbol=snapshot["symbol"], version=VERSION,
                        parameters=asdict(config), implementation_sha256=implementation,
                        input_sha256=report["sha256"], output_sha256=_digest(output),
                        row_count=len(output))
        prepared.append((_digest(metadata), metadata, output))
    if not prepared:
        raise ValueError("At least one snapshot is required")
    result = []
    # mode=rw prevents accidentally creating a replacement if the DB disappeared.
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=rw", uri=True)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS structure_runs (
                run_id TEXT PRIMARY KEY,
                snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
                symbol TEXT NOT NULL, metadata_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS structure_rows (
                run_id TEXT NOT NULL REFERENCES structure_runs(run_id),
                timestamp INTEGER NOT NULL, payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, timestamp))""")
            for rid, metadata, rows in prepared:
                existing = db.execute("SELECT 1 FROM structure_runs WHERE run_id=?", (rid,)).fetchone()
                if not existing:
                    db.execute("INSERT INTO structure_runs VALUES (?, ?, ?, ?)",
                               (rid, metadata["snapshot_id"], metadata["symbol"], _json(metadata)))
                    db.executemany("INSERT INTO structure_rows VALUES (?, ?, ?)",
                                   [(rid, row["timestamp"], _json(row)) for row in rows])
                result.append(dict(run_id=rid, inserted=not bool(existing), **metadata))
            db.commit()
        except Exception:
            db.rollback()
            raise
    return result


def _has_runs(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='structure_runs'").fetchone()


def list_runs(database):
    with closing(_read(database)) as db:
        if not _has_runs(db):
            return []
        return [dict(run_id=row["run_id"], **json.loads(row["metadata_json"]))
                for row in db.execute("SELECT * FROM structure_runs ORDER BY symbol, run_id")]


def query_structures(database, run_id, symbol, start=None, end=None):
    """Return exact structure rows for an explicit version and UTC [start,end)."""
    symbol = normalize_symbol(symbol)
    if start is not None and end is not None and start >= end:
        raise ValueError("Expected increasing time boundaries")
    with closing(_read(database)) as db:
        run = db.execute("SELECT symbol FROM structure_runs WHERE run_id=?", (run_id,)).fetchone() if _has_runs(db) else None
        if run is None or run["symbol"] != symbol:
            raise ValueError("Structure run does not belong to requested symbol")
        conditions, args = ["run_id=?"], [run_id]
        for operator, value in ((">=", start), ("<", end)):
            if value is not None:
                conditions.append("timestamp " + operator + " ?")
                args.append(value)
        return [json.loads(row[0]) for row in db.execute(
            "SELECT payload_json FROM structure_rows WHERE " + " AND ".join(conditions)
            + " ORDER BY timestamp", args)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("snapshot_ids", nargs="+")
    build.add_argument("--swing-length", type=int, default=50)
    commands.add_parser("list")
    query = commands.add_parser("query")
    query.add_argument("symbol")
    query.add_argument("--run-id", required=True)
    query.add_argument("--start", type=date_timestamp)
    query.add_argument("--end", type=date_timestamp)
    args = parser.parse_args(argv)
    if args.command == "build":
        result = build_structures(args.database, args.snapshot_ids,
                                  Config(args.swing_length))
    elif args.command == "list":
        result = list_runs(args.database)
    else:
        result = query_structures(args.database, args.run_id, args.symbol, args.start, args.end)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
