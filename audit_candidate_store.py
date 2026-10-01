"""Reproduce E4 on an independent E3 database copy, preserving the baseline."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from candidate_store import build_candidates, query_candidates
from event_study import signals
from history import date_timestamp
from history_store import list_snapshots
from indicator_store import list_runs as indicator_runs, query_indicators
from structure_store import list_runs as structure_runs, query_structures


def audit(baseline, database, output):
    baseline, database, output = map(Path, (baseline, database, output))
    if database.exists() or output.exists():
        raise ValueError("Audit database and output must be new paths")
    baseline_hash = hashlib.sha256(baseline.read_bytes()).hexdigest()
    shutil.copyfile(baseline, database)
    snapshots = list_snapshots(database)
    runs = build_candidates(database, [s["snapshot_id"] for s in snapshots])
    indicators = {r["snapshot_id"]: r for r in indicator_runs(baseline)}
    structures = {r["snapshot_id"]: r for r in structure_runs(baseline)}
    for run in runs:
        sid, symbol = run["snapshot_id"], run["symbol"]
        rows = query_candidates(database, run["run_id"], symbol)
        a = query_indicators(baseline, indicators[sid]["run_id"], symbol)
        b = query_structures(baseline, structures[sid]["run_id"], symbol)
        assert len(rows) == len(a) == len(b) == run["row_count"]
        count = 0
        for row, indicator, structure in zip(rows, a, b):
            assert row["indicator"] == indicator and row["structure"] == structure
            eligible = (all(indicator[k] is not None for k in
                            ("ret_30d", "return_percentile", "signed_move", "stretch_atr"))
                        and structure["status"] == "OK")
            assert row["eligible"] == eligible
            expected = signals(indicator, structure) if eligible else dict.fromkeys(row["decisions"], 0)
            assert {k: v["direction"] for k, v in row["decisions"].items()} == expected
            assert not row["execution_authorized"] and row["opportunity_score"] is None
            assert all(d["reasons"] for d in row["decisions"].values())
            if structure["structure"]:
                assert structure["structure_confirmed_at"] <= row["signal_time"]
            count += eligible
        selected = query_candidates(database, run["run_id"], symbol,
                                    date_timestamp("2025-02-01"), date_timestamp("2025-03-01"))
        assert len(selected) == 28
        assert selected == [r for r in rows if date_timestamp("2025-02-01") <= r["timestamp"] < date_timestamp("2025-03-01")]
        run.update(exact_indicator_structure_roundtrip=True, exact_m4_signals=True,
                   eligible_rows=count, query_rows=len(selected),
                   candidate_bar_counts={rule: sum(bool(r["decisions"][rule]["direction"]) for r in rows)
                                         for rule in rows[0]["decisions"]})
    repeated = build_candidates(database, [s["snapshot_id"] for s in snapshots])
    assert all(not r["inserted"] for r in repeated)
    assert [r["run_id"] for r in repeated] == [r["run_id"] for r in runs]
    with closing(sqlite3.connect(baseline)) as original, closing(sqlite3.connect(database)) as db:
        tables = [r[0] for r in original.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            assert original.execute("SELECT * FROM " + quoted + " ORDER BY 1,2").fetchall() == db.execute(
                "SELECT * FROM " + quoted + " ORDER BY 1,2").fetchall()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        assert integrity == "ok" and not foreign_keys
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == baseline_hash
    record = dict(task="E4", date="2026-10-01", status="PASS", runs=runs,
                  rows=sum(r["row_count"] for r in runs),
                  baseline_sha256=baseline_hash, baseline_unchanged=True,
                  preserved_tables=tables, repeated_insertions=0,
                  integrity_check=integrity, foreign_key_errors=foreign_keys,
                  database_sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
                  strategy_validation="NOT_VALIDATED", hypothesis="TERMINATED",
                  candidate_counts="raw_bar_signals_not_deduplicated_events_or_trades")
    with output.open("x", encoding="utf-8") as target:
        target.write(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(args.baseline, args.database, args.output)
    print(json.dumps({k: result[k] for k in ("task", "status", "rows", "repeated_insertions")}))
