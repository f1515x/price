"""Evidence boundary and time-window checks for cost/policy inventory."""
import copy
from pathlib import Path
import tempfile
import unittest

from audit_cost_policy_evidence_matrix import checks_for
from build_cost_policy_evidence_matrix import PINS, build, pointer, rate_slice


class RateWindowTests(unittest.TestCase):
    def test_half_open_exact_seconds(self):
        rs = [dict(timestamp=t) for t in (10, 20, 30)]
        self.assertEqual(rate_slice(rs, 20, 30), dict(first_record_index=1, end_record_index_exclusive=2, count=1))
        self.assertEqual(rate_slice(rs, 21, 30)['count'], 0)
        self.assertEqual(rate_slice(rs, 31, 40)['count'], 0)

    def test_invalid_grid_or_window_rejected(self):
        for rs in ([dict(timestamp=20), dict(timestamp=10)], [dict(timestamp=10)]*2, [dict(timestamp=True)]):
            with self.assertRaises(ValueError):
                rate_slice(rs, 1, 30)
        for start, end in ((1, 1), (2, 1), (True, 10)):
            with self.assertRaises(ValueError):
                rate_slice([], start, end)

    def test_json_pointer_escapes_and_missing(self):
        self.assertEqual(pointer({'a/b': {'~': [7]}}, '/a~1b/~0/0'), 7)
        with self.assertRaises(KeyError):
            pointer({}, '/fee')

    def test_pinned_scope_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/next(iter(PINS))
            p.parent.mkdir(parents=True)
            p.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                build(tmp)


class CertificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = build(Path(__file__).resolve().parents[2]/'1')

    def test_real_inventory_complete(self):
        self.assertTrue(all(checks_for(self.matrix, self.matrix).values()))

    def test_false_certification_rejected(self):
        fake = copy.deepcopy(self.matrix)
        fake['rows'][0]['certified_coverage_seconds'] = 1
        fake['rows'][0]['actual_account_evidence'] = ['invented-bill']
        self.assertFalse(checks_for(fake, self.matrix)['no_certification'])

    def test_duplicate_row_cannot_replace_missing_field(self):
        fake = copy.deepcopy(self.matrix)
        fake['rows'][1] = copy.deepcopy(fake['rows'][0])
        self.assertFalse(checks_for(fake, self.matrix)['complete_field_window_grid'])

    def test_proxy_cannot_become_exact_price(self):
        fake = copy.deepcopy(self.matrix)
        fake['observed_settlement_index'][0]['exact_settlement_price'] = '100'
        self.assertFalse(checks_for(fake, self.matrix)['observed_rates_complete'])

    def test_future_has_no_backfilled_history(self):
        fake = copy.deepcopy(self.matrix)
        r = next(r for r in fake['rows'] if r['target'].startswith('future-') and r['field'] == 'funding_rate')
        r['rate_record_slice']['count'] = 1
        checks = checks_for(fake, self.matrix)
        self.assertFalse(checks['future_unknown'])
        self.assertFalse(checks['rate_slices_match'])


if __name__ == '__main__':
    unittest.main()
