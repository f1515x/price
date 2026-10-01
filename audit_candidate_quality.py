"""Verify coverage/event summaries for every stored run and rule, without writes."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from candidate_quality import quality_report
from candidate_store import list_runs, query_candidates
from event_study import RULES
from history import DAY


def audit(database):
    before = hashlib.sha256(Path(database).read_bytes()).hexdigest()
    results = []
    for run in list_runs(database):
        rows = query_candidates(database, run['run_id'], run['symbol'])
        for rule in RULES:
            result = quality_report(database, run['run_id'], run['symbol'], rule)
            c, a, events = (result[k] for k in ('coverage', 'availability', 'events'))
            assert c['observations'] + c['missing_count'] == c['calendar_days']
            assert a['eligible'] + a['unavailable'] == len(rows)
            assert a['no_candidate'] + a['raw_candidate_bars'] == a['eligible']
            assert events['count'] <= a['raw_candidate_bars']
            candidate_times = {r['timestamp'] for r in rows if r['decisions'][rule]['direction']}
            assert all(e['timestamp'] in candidate_times for e in events['retained'])
            assert all(y['signal_time']-x['signal_time'] >= 30*DAY
                       for x, y in zip(events['retained'], events['retained'][1:]))
            # Independent interval selection: greedily consume candidates from a set.
            pending = sorted(candidate_times)
            expected = []
            while pending:
                first = pending[0]
                expected.append(first)
                pending = [t for t in pending if t >= first+30*DAY]
            assert [e['timestamp'] for e in events['retained']] == expected
            if rows:
                left = rows[len(rows)//2]['timestamp']
                sliced = quality_report(database, run['run_id'], run['symbol'], rule, start=left)
                assert sliced['events']['retained'] == [e for e in events['retained'] if e['timestamp'] >= left]
            results.append(result)
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert hashlib.sha256(Path(database).read_bytes()).hexdigest() == before
    return dict(status='PASS', database_sha256=before, reports=len(results), results=results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = audit(args.database)
    with Path(args.output).open('x', encoding='utf-8') as target:
        target.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: result[k] for k in ('status', 'database_sha256', 'reports')}))
