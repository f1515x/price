"""Verify a deployed default BTC/ETH collector without changing its evidence."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET

from candidate_store import decisions, query_candidates
from collection_scheduler import Config, _identity
from history import load_snapshot
from history_store import query_daily
from indicator_store import query_indicators
from indicators import calculate
from structure_history import replay
from structure_store import query_structures


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(root):
    root = Path(root).resolve()
    target = root / 'deployment-acceptance.json'
    if target.exists():
        raise FileExistsError(target)
    deployment = json.loads((root / 'deployment.json').read_text(encoding='utf-8-sig'))
    task = json.loads((root / 'task-status.json').read_text(encoding='utf-8-sig'))
    require(task['enabled'] and task['state'] == 3 and task['last_result'] == 0,
            'Task must be enabled, ready and successfully completed')
    require(task['task_name'] == deployment['task_name'], 'Task name mismatch')
    saved_xml = ET.fromstring((root / 'scheduled-task.xml').read_bytes())
    live_xml = ET.fromstring((root / 'live-task.xml').read_bytes())
    require(ET.tostring(saved_xml) == ET.tostring(live_xml), 'Registered task changed')
    ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    require(live_xml.findtext('.//t:DaysInterval', namespaces=ns) == '1', 'Not daily')
    boundary = datetime.fromisoformat(live_xml.findtext('.//t:StartBoundary', namespaces=ns))
    require(boundary.tzinfo is not None, 'Schedule must specify timezone')
    utc_boundary = boundary.astimezone(timezone.utc)
    require((utc_boundary.hour, utc_boundary.minute, utc_boundary.second) == (0, 5, 0),
            'UTC schedule mismatch')
    require(live_xml.findtext('.//t:LogonType', namespaces=ns) == 'InteractiveToken',
            'Unexpected credentials mode')
    require(live_xml.findtext('.//t:MultipleInstancesPolicy', namespaces=ns) == 'IgnoreNew',
            'Overlapping tasks allowed')
    state = json.loads((root / 'state.json').read_bytes())
    config = Config()
    identity, evidence = _identity(config)
    evidence = json.loads(json.dumps(evidence))
    require(state['status'] == 'COMPLETE' and state['evidence'] == evidence,
            'Collector state or implementation mismatch')
    end = state['end_exclusive']
    require(state['cycle'] == f'{end}-{identity}', 'Cycle identity mismatch')
    require(not state['execution_authorized'] and state['validation'] == 'NOT_VALIDATED',
            'Research restrictions missing')
    cycles = [json.loads(line) for line in (root / 'cycles.jsonl').read_text().splitlines()]
    require(len(cycles) >= 2 and all(c['status'] == 'COMPLETE' for c in cycles),
            'Expected at least two completed scheduled executions')
    require(all(not r['inserted'] for stage in state['stages'].values() for r in stage),
            'Repeated execution inserted duplicate versions')
    database = root / 'research.sqlite'
    counts, hashes = {}, {}
    for index, symbol in enumerate(config.symbols):
        snapshot = root / 'snapshots' / f'{symbol}-{config.start}-{end}'
        rows, quality = load_snapshot(snapshot)
        require(not quality['missing_timestamps'] and not quality['issues'], 'Daily quality failed')
        sid = state['stages']['history'][index]['snapshot_id']
        ir = state['stages']['indicators'][index]['run_id']
        sr = state['stages']['structures'][index]['run_id']
        cr = state['stages']['candidates'][index]['run_id']
        require(query_daily(database, sid, symbol) == rows, 'History mismatch')
        require(query_indicators(database, ir, symbol) == calculate(rows), 'Indicator mismatch')
        require(query_structures(database, sr, symbol) == replay(rows), 'Structure mismatch')
        stored = query_candidates(database, cr, symbol)
        require(stored == decisions(rows), 'Candidate mismatch')
        require(all(not r['execution_authorized'] and r['validation'] == 'NOT_VALIDATED'
                    for r in stored), 'Candidate research restrictions missing')
        counts[symbol] = {'daily_rows': len(rows), 'eligible_rows': sum(r['eligible'] for r in stored)}
        for name in ('raw.json', 'daily.csv', 'quality.json'):
            path = snapshot / name
            hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    with closing(sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True)) as db:
        require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite integrity')
        require(not db.execute('PRAGMA foreign_key_check').fetchall(), 'SQLite foreign keys')
    result = dict(status='PASS', mode='LIVE_HTTP_WINDOWS_SCHEDULED_TASK',
                  audited_at_utc=datetime.now(timezone.utc).isoformat(),
                  task=task, counts=counts, cycle=state['cycle'],
                  all_four_layers_match_recomputation=True, repeated_insertions=0,
                  integrity_check='ok', foreign_key_errors=0, input_sha256=hashes,
                  evidence=evidence, deployment=deployment,
                  deployment_source_sha256={name: hashlib.sha256(
                      Path(__file__).with_name(name).read_bytes()).hexdigest()
                      for name in ('install_daily_collection.ps1', 'run_daily_collection.ps1',
                                   'audit_daily_collection.py')},
                  validation='NOT_VALIDATED', execution_authorized=False,
                  limitations=['Interactive user logon required.',
                               'Two immediate runs do not establish long-term uptime.'])
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    result = audit(args.root)
    print(json.dumps({k: result[k] for k in ('status', 'counts', 'repeated_insertions')}))
