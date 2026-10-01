import hashlib
from contextlib import closing
import json
import sqlite3
import unittest

from candidate_quality import main, quality_report
from candidate_report import main as report_main
from candidate_store import build_candidates, query_candidates
from history import DAY, prepare, save_snapshot
from history_store import import_snapshots
from indicators import Config as IndicatorConfig
from structure_history import Config as StructureConfig
import test_candidate_report


class CandidateQualityTests(unittest.TestCase):
    setUp = test_candidate_report.CandidateReportTests.setUp

    def test_observations_availability_and_spacing(self):
        value = quality_report(self.db, self.rid, 'BTC', 'move', dedup_days=7)
        self.assertEqual(value['coverage']['observations'], 75)
        self.assertEqual(value['coverage']['calendar_days'], 75)
        self.assertEqual(value['coverage']['missing_count'], 0)
        a = value['availability']
        self.assertEqual(a['eligible'] + a['unavailable'], 75)
        self.assertEqual(a['no_candidate'] + a['raw_candidate_bars'], a['eligible'])
        source = query_candidates(self.db, self.rid, 'BTC')
        expected, last = [], None
        for row in source:
            if row['decisions']['move']['direction'] and (last is None or row['signal_time'] >= last+7*DAY):
                last = row['signal_time']
                expected.append(row['timestamp'])
        self.assertTrue(expected)
        self.assertEqual([e['timestamp'] for e in value['events']['retained']], expected)
        self.assertIsNone(value['events']['independent_sample_count'])
        self.assertIsNone(value['events']['trades'])

    def test_slice_preserves_prior_event_exclusion(self):
        full = quality_report(self.db, self.rid, 'BTC', 'percentile', dedup_days=30)
        first = full['events']['retained'][0]['timestamp']
        sliced = quality_report(self.db, self.rid, 'BTC', 'percentile', first+DAY, first+30*DAY)
        self.assertGreater(sliced['availability']['raw_candidate_bars'], 0)
        self.assertEqual(sliced['events']['count'], 0)

    def test_missing_and_invalid_bars_are_distinct_from_warmup(self):
        raw = [dict(t=i*DAY, o=100, h=101, l=99, c=100, v=1) for i in range(80) if i != 10]
        raw[19]['c'] = 200  # invalid OHLC at day 20
        raw.append(dict(t='bad'))  # unassignable source issue
        rows, quality = prepare(raw, 'BTC', 0, 80*DAY, 80*DAY)
        save_snapshot(self.root/'gaps', raw, rows, quality)
        sid = import_snapshots(self.db, [self.root/'gaps'])[0]['snapshot_id']
        rid = build_candidates(self.db, [sid], indicator_config=IndicatorConfig(5),
                               structure_config=StructureConfig(2))[0]['run_id']
        value = quality_report(self.db, rid, 'BTC', start=0, end=30*DAY)
        self.assertEqual(value['coverage']['missing_timestamps'], [10*DAY, 20*DAY])
        self.assertEqual(value['coverage']['observations'], 28)
        self.assertEqual(value['quality']['range_timestamped_issues'], {'INVALID_OHLCV': 1})
        self.assertEqual(value['quality']['source_issues_without_timestamp'], 1)
        self.assertEqual(value['availability']['unavailable'], 28)

    def test_empty_clipped_range_and_invalid_arguments(self):
        value = quality_report(self.db, self.rid, 'BTC', start=100*DAY)
        self.assertEqual(value['coverage']['calendar_days'], 0)
        self.assertEqual(value['coverage']['missing_count'], 0)
        self.assertIsNone(value['availability']['history_count_min'])
        for kwargs in (dict(dedup_days=True), dict(dedup_days=0), dict(rule='bad'),
                       dict(start=1), dict(start=DAY, end=DAY), dict(symbol='ETH')):
            args = dict(database=self.db, run_id=self.rid, symbol='BTC')
            args.update(kwargs)
            with self.assertRaises(ValueError):
                quality_report(**args)

    def test_tampering_rejected(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            body = json.loads(db.execute('SELECT payload_json FROM candidate_rows WHERE run_id=? LIMIT 1',
                                         (self.rid,)).fetchone()[0])
            body['eligible'] = True
            db.execute('UPDATE candidate_rows SET payload_json=? WHERE run_id=? AND timestamp=0',
                       (json.dumps(body), self.rid))
        with self.assertRaisesRegex(ValueError, 'Candidate evidence mismatch'):
            quality_report(self.db, self.rid, 'BTC')

    def test_both_clis_readonly_and_no_overwrite(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        output = self.root/'quality.json'
        args = ['--database', str(self.db), 'BTC', '--run-id', self.rid, '--output', str(output)]
        self.assertEqual(main(args), 0)
        with self.assertRaises(FileExistsError):
            main(args)
        second = self.root/'report.json'
        self.assertEqual(report_main(args[:-1]+[str(second), '--format', 'quality-json']), 0)
        self.assertEqual(json.loads(output.read_text()), json.loads(second.read_text()))
        table = self.root/'table.txt'
        report_main(args[:-1]+[str(table)])
        self.assertIn('sample_quality=', table.read_text())
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
