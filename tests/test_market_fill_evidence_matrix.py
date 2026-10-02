import tempfile
import unittest
from pathlib import Path

from build_market_fill_evidence_matrix import PINS, build, coverage


class MarketFillMatrixTests(unittest.TestCase):
    def test_half_open_endpoint(self):
        c=coverage(60,120,60,[60,120])
        self.assertEqual((c['expected_bars'],c['observed_bars']), (1,1))

    def test_second_window_only_has_containing_buckets(self):
        c=coverage(119,122,60,[60,120])
        self.assertEqual(c['observed_bars'],2)
        self.assertFalse(c['exact_path_verified'])

    def test_duplicates_do_not_increase_coverage(self):
        c=coverage(0,180,60,[0,0,120])
        self.assertEqual(c['observed_bars'],2)
        self.assertEqual(c['missing_bucket_starts'],[60])

    def test_daily_candles_do_not_supply_minutes(self):
        self.assertEqual(coverage(0,86400,60,[0])['observed_bars'],1)

    def test_invalid_windows_rejected(self):
        for start,end,step in [(1,1,60),(2,1,60),(0,60,0)]:
            with self.assertRaises(ValueError):
                coverage(start,end,step,[])

    def test_pinned_scope_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/next(iter(PINS))
            p.parent.mkdir(parents=True)
            p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'checksum'):
                build(tmp)


if __name__=='__main__':
    unittest.main()
