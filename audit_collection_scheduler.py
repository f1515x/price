"""Reproducible scheduler acceptance using verified archived Gate responses."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from candidate_store import decisions, query_candidates
from collection_scheduler import Config, collect
from history import load_snapshot
from history_store import query_daily
from indicator_store import query_indicators
from indicators import calculate
from structure_history import replay
from structure_store import query_structures


def audit(root, inputs):
    root = Path(root).resolve()
    if root.exists():
        raise ValueError("Acceptance root must be new")
    verified = [load_snapshot(p) for p in inputs]
    reports = [v[1] for v in verified]
    if len({(r['start'], r['end_exclusive']) for r in reports}) != 1:
        raise ValueError("Expected matching acquisition ranges")
    raw = {r['symbol']: json.loads((Path(p) / 'raw.json').read_text(encoding='utf-8'))
           for p, r in zip(inputs, reports)}
    config = Config(tuple(r['symbol'] for r in reports), reports[0]['start'])
    hashes = {str(Path(p).resolve() / name): hashlib.sha256((Path(p) / name).read_bytes()).hexdigest()
              for p in inputs for name in ('raw.json', 'daily.csv', 'quality.json')}
    calls = []
    def fetch(params):
        calls.append(params)
        return [r for r in raw[params['contract'].removesuffix('_USDT')]
                if params['from'] <= int(r['t']) <= params['to']]
    now = reports[0]['end_exclusive'] + config.close_delay
    first = collect(root, config, now, fetch)
    again = collect(root, config, now, fetch)
    database = root / 'research.sqlite'
    counts = {}
    for index, (rows, _) in enumerate(verified):
        symbol = reports[index]['symbol']
        sid = first['stages']['history'][index]['snapshot_id']
        assert query_daily(database, sid, symbol) == rows
        ir = first['stages']['indicators'][index]['run_id']
        sr = first['stages']['structures'][index]['run_id']
        cr = first['stages']['candidates'][index]['run_id']
        assert query_indicators(database, ir, symbol) == calculate(rows)
        assert query_structures(database, sr, symbol) == replay(rows)
        stored = query_candidates(database, cr, symbol)
        assert stored == decisions(rows)
        assert all(not r['execution_authorized'] and r['validation'] == 'NOT_VALIDATED' for r in stored)
        counts[symbol] = dict(rows=len(rows), eligible=sum(r['eligible'] for r in stored))
    assert len(calls) == len(inputs)
    assert all(not r['inserted'] for stage in again['stages'].values() for r in stage)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == value for p, value in hashes.items())
    with closing(sqlite3.connect(database)) as db:
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        foreign = db.execute('PRAGMA foreign_key_check').fetchall()
        assert integrity == 'ok' and not foreign
    result = dict(status='PASS', mode='VERIFIED_ARCHIVED_RESPONSE_REPLAY_NOT_LIVE',
                  cycle=first['cycle'], counts=counts, source_sha256=hashes,
                  fetch_calls=len(calls), repeated_insertions=0,
                  integrity_check=integrity, foreign_key_errors=foreign,
                  all_four_layers_match_recomputation=True,
                  original_evidence_unchanged=True,
                  validation='NOT_VALIDATED', execution_authorized=False)
    (root / 'acceptance.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('snapshots', nargs='+')
    args = parser.parse_args()
    print(json.dumps(audit(args.root, args.snapshots), indent=2))


if __name__ == '__main__':
    main()
