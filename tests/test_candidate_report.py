import csv
import hashlib
from io import StringIO
import math
from pathlib import Path
import tempfile
import unittest

from candidate_report import COLUMNS, main, render, report
from candidate_store import build_candidates, query_candidates
from history import DAY, prepare, save_snapshot
from history_store import import_snapshots
from indicators import Config as IndicatorConfig
from structure_history import Config as StructureConfig


class CandidateReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        raw = [dict(t=i * DAY, o=c, h=c+1, l=c-1, c=c, v=10)
               for i in range(75) for c in [100 + 15*math.sin(i/3) + i/5]]
        rows, quality = prepare(raw, "BTC", 0, 75*DAY, 75*DAY)
        save_snapshot(self.root / "BTC", raw, rows, quality)
        self.db = self.root / "research.sqlite"
        snapshot = import_snapshots(self.db, [self.root / "BTC"])[0]
        self.run = build_candidates(self.db, [snapshot['snapshot_id']],
                                    indicator_config=IndicatorConfig(5),
                                    structure_config=StructureConfig(2))[0]
        self.rid = self.run['run_id']

    def test_utc_units_directions_and_unavailable_rows(self):
        metadata, rows = report(self.db, self.rid, 'btc')
        original = query_candidates(self.db, self.rid, 'BTC')
        self.assertEqual(len(rows), 75)
        self.assertEqual(rows[0]['bar_time_utc'], '1970-01-01T00:00:00Z')
        self.assertEqual(rows[0]['signal_time_utc'], '1970-01-02T00:00:00Z')
        self.assertEqual(rows[0]['decision_status'], 'UNAVAILABLE')
        self.assertIn('MISSING_RET_30D', rows[0]['reasons'])
        self.assertTrue(any(r['decision_status'] == 'RESEARCH_CANDIDATE' for r in rows))
        for row, stored in zip(rows, original):
            ret = stored['indicator']['ret_30d']
            self.assertEqual(row['ret_30d_pct'], None if ret is None else 100*ret)
            self.assertEqual(row['sample_count'], stored['indicator']['history_count'])
            self.assertEqual(row['direction'], {1:'LONG', -1:'SHORT', 0:'NONE'}[
                stored['decisions']['percentile_structure']['direction']])
            self.assertFalse(row['execution_authorized'])
        self.assertEqual(metadata['run_id'], self.rid)

    def test_csv_roundtrip_missing_values_and_version_trace(self):
        metadata, rows = report(self.db, self.rid, 'BTC')
        reader = csv.DictReader(StringIO(render(metadata, rows, 'percentile_structure', 'csv')))
        self.assertEqual(reader.fieldnames, list(COLUMNS))
        exported = list(reader)
        self.assertEqual(len(exported), 75)
        self.assertEqual(exported[0]['ret_30d_pct'], 'N/A')
        self.assertTrue(all(r['opportunity_score'] == r['structure_percentile'] == 'N/A' for r in exported))
        for original, row in zip(rows, exported):
            self.assertEqual(row['parameters_json'], original['parameters_json'])
            self.assertEqual(row['implementation_sha256_json'], original['implementation_sha256_json'])
            if original['ret_30d_pct'] is not None:
                self.assertEqual(float(row['ret_30d_pct']), original['ret_30d_pct'])

    def test_boundaries_empty_table_and_rule_selection(self):
        metadata, rows = report(self.db, self.rid, 'BTC', 'move', 30*DAY, 33*DAY)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['rule'] == 'move' for r in rows))
        self.assertEqual(rows[-1]['bar_time_utc'], '1970-02-02T00:00:00Z')
        metadata, rows = report(self.db, self.rid, 'BTC', start=100*DAY)
        self.assertIn('No rows', render(metadata, rows, 'percentile_structure'))
        self.assertEqual(len(list(csv.DictReader(StringIO(render(metadata, rows, 'percentile_structure', 'csv'))))), 0)

    def test_invalid_selection_and_missing_database(self):
        for kwargs in (dict(run_id='unknown', symbol='BTC'), dict(run_id=self.rid, symbol='ETH'),
                       dict(run_id=self.rid, symbol='BTC', rule='typo'),
                       dict(run_id=self.rid, symbol='BTC', start=DAY, end=DAY)):
            with self.assertRaises(ValueError):
                report(self.db, **kwargs)
        absent = self.root / 'missing.sqlite'
        with self.assertRaises(Exception):
            report(absent, self.rid, 'BTC')
        self.assertFalse(absent.exists())

    def test_cli_readonly_and_output_no_overwrite(self):
        digest = hashlib.sha256(self.db.read_bytes()).hexdigest()
        output = self.root / 'candidates.csv'
        args = ['--database', str(self.db), 'BTC', '--run-id', self.rid,
                '--start', '1970-01-31', '--end', '1970-02-03', '--format', 'csv', '--output', str(output)]
        self.assertEqual(main(args), 0)
        before = output.read_bytes()
        self.assertEqual(len(list(csv.DictReader(StringIO(before.decode())))), 3)
        with self.assertRaises(FileExistsError):
            main(args)
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
