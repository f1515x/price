import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from candidate_store import list_runs, query_candidates
from collection_scheduler import Config, collect, watch, _lock
from history import DAY
from indicators import Config as IndicatorConfig
from structure_history import Config as StructureConfig


class CollectionSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = Config(start=0, indicators=IndicatorConfig(window=10),
                             structures=StructureConfig(3))
        self.calls = []

    def fetch(self, params):
        self.calls.append(params)
        return [dict(t=t, o=100, h=105, l=95, c=100 + (t // DAY % 3), v=1)
                for t in range(params['from'], params['to'] + 1, DAY)]

    def run_cycle(self, days=45):
        return collect(self.root, self.config, now=days * DAY + 300, fetch=self.fetch)

    def test_closed_bars_and_all_stores(self):
        result = self.run_cycle()
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(p['to'] == 45 * DAY - 1 for p in self.calls))
        for runs in result['stages'].values():
            self.assertEqual(len(runs), 2)
        for run in list_runs(self.root / 'research.sqlite'):
            rows = query_candidates(self.root / 'research.sqlite', run['run_id'], run['symbol'])
            self.assertEqual(len(rows), 45)
            self.assertTrue(all(r['signal_time'] <= 45 * DAY for r in rows))
            self.assertTrue(all(not r['execution_authorized'] for r in rows))
        with closing(sqlite3.connect(self.root / 'research.sqlite')) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_restart_idempotent_and_catchup(self):
        first = self.run_cycle()
        again = self.run_cycle()
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(not r['inserted'] for runs in again['stages'].values() for r in runs))
        latest = self.run_cycle(48)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(latest['quality']['BTC']['valid_count'], 48)
        self.assertEqual(first['quality']['BTC']['valid_count'], 45)

    def test_stage_failure_resumes_without_refetch(self):
        with patch('collection_scheduler.build_structures', side_effect=RuntimeError('temporary')):
            with self.assertRaisesRegex(RuntimeError, 'temporary'):
                self.run_cycle()
        state = json.loads((self.root / 'state.json').read_text())
        self.assertEqual(state['status'], 'FAILED')
        self.assertNotIn('candidates', state['stages'])
        self.assertFalse((self.root / 'collector.lock').exists())
        result = self.run_cycle()
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(not r['inserted'] for r in result['stages']['history']))

    def test_network_failure_retries_and_tampering_rejected(self):
        with self.assertRaises(OSError):
            collect(self.root, self.config, now=45 * DAY + 300,
                    fetch=lambda _: (_ for _ in ()).throw(OSError('offline')))
        self.assertEqual(self.run_cycle()['status'], 'COMPLETE')
        raw = next((self.root / 'snapshots').glob('BTC-*/raw.json'))
        raw.write_text('[]')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.run_cycle()
        self.assertEqual(json.loads((self.root / 'state.json').read_text())['status'], 'FAILED')

    def test_lock_and_invalid_config(self):
        with _lock(self.root):
            with self.assertRaisesRegex(RuntimeError, 'lock'):
                self.run_cycle()
        for kwargs in (dict(symbols=('BTC', 'btc')), dict(start=1), dict(close_delay=DAY)):
            with self.assertRaises(ValueError):
                Config(**kwargs)

    def test_close_delay_and_missing_bars_preserved(self):
        result = collect(self.root, self.config, now=46 * DAY + 299,
                         fetch=lambda p: self.fetch(p)[1:])
        self.assertEqual(result['end_exclusive'], 45 * DAY)
        self.assertEqual(result['quality']['BTC']['missing_timestamps'], [0])
        self.assertEqual(result['quality']['BTC']['research_status'], 'INSUFFICIENT_DATA')

    def test_watch_retries_then_waits_until_next_day(self):
        ticks = iter([45 * DAY + 299, 45 * DAY + 300, 45 * DAY + 301,
                      45 * DAY + 302, 46 * DAY + 300])
        calls = []
        def run(root, config, now):
            calls.append(now)
            if len(calls) == 2:
                raise OSError('temporary')
            return dict(status='COMPLETE', end_exclusive=(now - config.close_delay) // DAY * DAY)
        with self.assertRaises(StopIteration):
            watch(self.root, self.config, clock=lambda: next(ticks), sleep=lambda _: None, run=run)
        self.assertEqual(calls, [45 * DAY + 299, 45 * DAY + 300, 45 * DAY + 301, 46 * DAY + 300])


if __name__ == '__main__':
    unittest.main()
