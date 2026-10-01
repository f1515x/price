"""Versioned SQLite storage for verified daily research snapshots."""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from history import FIELDS, date_timestamp, load_snapshot
from kline import normalize_symbol

SCHEMA_VERSION = 1


def _schema(db, create=False):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if not create or version != 0 or db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchone():
        raise ValueError("Unsupported SQLite schema")
    db.execute("""CREATE TABLE snapshots (
        snapshot_id TEXT PRIMARY KEY, symbol TEXT NOT NULL,
        source_directory TEXT NOT NULL, report_json TEXT NOT NULL,
        row_count INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE daily (
        snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
        timestamp INTEGER NOT NULL, symbol TEXT NOT NULL, market TEXT NOT NULL,
        interval TEXT NOT NULL, source TEXT NOT NULL,
        open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
        close REAL NOT NULL, volume REAL NOT NULL, ret_30d REAL,
        return_status TEXT NOT NULL,
        PRIMARY KEY (snapshot_id, timestamp))""")
    db.execute("PRAGMA user_version = 1")


def import_snapshots(database, directories):
    """Validate the whole batch first, then atomically insert immutable versions.

    Reimporting identical evidence is a no-op. Overlapping acquisitions stay in
    separate versions; callers must explicitly select a version for queries.
    """
    prepared = []
    for directory in directories:
        rows, report = load_snapshot(directory)
        report_json = json.dumps(report, sort_keys=True, separators=(",", ":"))
        identity = hashlib.sha256(report_json.encode("utf-8")).hexdigest()
        prepared.append((identity, str(Path(directory).resolve()), rows, report, report_json))
    if not prepared:
        raise ValueError("At least one snapshot is required")
    results = []
    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            _schema(db, create=True)
            for identity, directory, rows, report, report_json in prepared:
                existing = db.execute("SELECT snapshot_id FROM snapshots WHERE snapshot_id = ?",
                                      (identity,)).fetchone()
                if not existing:
                    db.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?, ?)",
                               (identity, report["symbol"], directory, report_json, len(rows)))
                    db.executemany("INSERT INTO daily VALUES (" + ",".join("?" for _ in range(13)) + ")",
                                   [(identity,) + tuple(None if key == "ret_30d" and row[key] == ""
                                                       else row[key] for key in FIELDS) for row in rows])
                results.append({"snapshot_id": identity, "symbol": report["symbol"],
                                "row_count": len(rows), "inserted": not bool(existing)})
            db.commit()
        except Exception:
            db.rollback()
            raise
    return results


def _read(database):
    # URI read-only mode prevents a typo from silently creating an empty database.
    db = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        _schema(db)
    except Exception:
        db.close()
        raise
    db.row_factory = sqlite3.Row
    return db


def list_snapshots(database):
    with closing(_read(database)) as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM snapshots ORDER BY symbol, snapshot_id")]


def query_daily(database, snapshot_id, symbol, start=None, end=None):
    """Return history-compatible rows for [start, end), ordered by UTC bucket.

    Missing returns retain the original empty-string convention. Querying a
    different symbol or an unknown version fails rather than borrowing history.
    """
    symbol = normalize_symbol(symbol)
    if start is not None and end is not None and start >= end:
        raise ValueError("Expected increasing time boundaries")
    with closing(_read(database)) as db:
        snapshot = db.execute("SELECT symbol FROM snapshots WHERE snapshot_id = ?",
                              (snapshot_id,)).fetchone()
        if snapshot is None or snapshot["symbol"] != symbol:
            raise ValueError("Snapshot does not belong to requested symbol")
        conditions, args = ["snapshot_id = ?"], [snapshot_id]
        for operator, value in ((">=", start), ("<", end)):
            if value is not None:
                conditions.append("timestamp " + operator + " ?")
                args.append(value)
        rows = [dict(row) for row in db.execute(
            "SELECT " + ",".join(FIELDS) + " FROM daily WHERE " + " AND ".join(conditions)
            + " ORDER BY timestamp", args)]
        for row in rows:
            if row["ret_30d"] is None:
                row["ret_30d"] = ""
        return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("import")
    ingest.add_argument("directories", nargs="+")
    commands.add_parser("list")
    query = commands.add_parser("query")
    query.add_argument("symbol")
    query.add_argument("--snapshot-id", required=True)
    query.add_argument("--start", type=date_timestamp)
    query.add_argument("--end", type=date_timestamp)
    args = parser.parse_args(argv)
    if args.command == "import":
        result = import_snapshots(args.database, args.directories)
    elif args.command == "list":
        result = list_snapshots(args.database)
    else:
        result = query_daily(args.database, args.snapshot_id, args.symbol, args.start, args.end)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
