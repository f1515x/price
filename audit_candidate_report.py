"""Verify E6 exports against all stored E4 decisions without modifying evidence."""
import argparse
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path

from candidate_report import COLUMNS, main as export, render, report
from candidate_store import list_runs, query_candidates
from event_study import RULES
from history import date_timestamp


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(database, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    baseline_hash = sha(database)
    runs = list_runs(database)
    if not runs:
        raise ValueError("No candidate runs available")
    records = []
    for run in runs:
        rid, symbol = run['run_id'], run['symbol']
        original = query_candidates(database, rid, symbol)
        checked = 0
        statuses = {}
        for rule in RULES:
            metadata, rows = report(database, rid, symbol, rule)
            assert len(rows) == len(original) == run['row_count']
            exported = list(csv.DictReader(StringIO(render(metadata, rows, rule, 'csv'))))
            assert len(exported) == len(rows)
            for row, source, flat in zip(rows, original, exported):
                assert set(row) == set(COLUMNS)
                for key, value in row.items():
                    assert flat[key] == ('N/A' if value is None else str(value))
                for key in ('close', 'symbol', 'market', 'interval', 'source', 'validation', 'execution_authorized'):
                    assert row[key] == source[key]
                a, b, decision = source['indicator'], source['structure'], source['decisions'][rule]
                assert row['ret_30d_pct'] == (None if a['ret_30d'] is None else 100*a['ret_30d'])
                for key in ('return_percentile', 'signed_move', 'stretch_atr'):
                    assert row[key] == a[key]
                for key in ('trend', 'weak_type', 'raw_weak_price', 'strong_price'):
                    assert row[key] == b[key]
                assert row['sample_count'] == a['history_count']
                assert row['direction'] == {1:'LONG', -1:'SHORT', 0:'NONE'}[decision['direction']]
                assert row['decision_status'] == decision['status']
                assert row['reasons'] == ';'.join(decision['reasons'])
                assert row['data_status'] == ('OK' if source['eligible'] else 'UNAVAILABLE')
                assert row['opportunity_score'] is None and row['structure_percentile'] is None
                assert row['validation'] == 'NOT_VALIDATED' and not row['execution_authorized']
                checked += 1
            statuses[rule] = {s: sum(r['decision_status'] == s for r in rows)
                              for s in ('UNAVAILABLE', 'NO_CANDIDATE', 'RESEARCH_CANDIDATE')}
        filename = f"{symbol}-{rid[:16]}.csv"
        export(['--database', str(database), symbol, '--run-id', rid,
                '--start', '2025-02-01', '--end', '2025-03-01',
                '--format', 'csv', '--output', str(output / filename)])
        with (output / filename).open(encoding='utf-8', newline='') as handle:
            exported = list(csv.DictReader(handle))
        expected = [r for r in original if date_timestamp('2025-02-01') <= r['timestamp'] < date_timestamp('2025-03-01')]
        assert len(exported) == len(expected) == 28
        metadata, rows = report(database, rid, symbol, end=original[0]['timestamp'] + 3*86400)
        table = render(metadata, rows, 'percentile_structure')
        assert 'N/A' in table and 'NOT_VALIDATED' in table and 'UNAVAILABLE' in table
        table_path = output / f"{symbol}-{rid[:16]}-warmup.txt"
        table_path.write_text(table, encoding='utf-8')
        records.append(dict(run_id=rid, symbol=symbol, bars=len(original),
                            rule_decisions_checked=checked, statuses=statuses,
                            csv=filename, csv_rows=len(exported), csv_sha256=sha(output / filename),
                            table=table_path.name, table_sha256=sha(table_path)))
    assert sha(database) == baseline_hash
    record = dict(task='E6', date='2026-10-01', status='PASS', runs=records,
                  bars=sum(r['bars'] for r in records),
                  rule_decisions_checked=sum(r['rule_decisions_checked'] for r in records),
                  database_sha256=baseline_hash, database_unchanged=True,
                  exact_csv_roundtrip=True, rules=list(RULES),
                  implementation_sha256={name: sha(Path(__file__).with_name(name))
                                         for name in ('candidate_report.py', 'audit_candidate_report.py')},
                  strategy_validation='NOT_VALIDATED', hypothesis='TERMINATED',
                  execution_authorized=False)
    (output / 'acceptance.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', required=True, help='New directory for audit and sample exports')
    args = parser.parse_args()
    result = audit(args.database, args.output)
    print(json.dumps({k: result[k] for k in ('task', 'status', 'bars', 'rule_decisions_checked', 'database_unchanged')}))
