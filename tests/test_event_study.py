import unittest
from unittest.mock import patch

from event_study import Config, label, signals, study, summarize
from history import DAY
from test_history import bars
from test_indicators import rows


class EventTests(unittest.TestCase):
    def test_next_open_and_directional_excursions(self):
        data = [dict(timestamp=0, open=10, high=10, low=10, close=10),
                dict(timestamp=DAY, open=100, high=120, low=90, close=110)]
        long = label(data, 0, 1, 1)
        short = label(data, 0, -1, 1)
        self.assertAlmostEqual(long['return_'], .1)
        self.assertAlmostEqual(long['mae'], -.1)
        self.assertAlmostEqual(long['mfe'], .2)
        self.assertAlmostEqual(short['return_'], -.1)
        self.assertAlmostEqual(short['mae'], -.2)
        self.assertAlmostEqual(short['mfe'], .1)
        self.assertEqual(long['entry_time'], DAY)
        self.assertEqual(long['exit_time'], 2*DAY)

    def test_gaps_and_truncated_labels(self):
        data = rows(bars(5))
        self.assertIsNone(label(data, 0, 1, 7))
        del data[2]
        self.assertIsNone(label(data, 0, 1, 3))
        self.assertIsNotNone(label(data, 0, 1, 1))

    def test_rule_thresholds_and_direction(self):
        for direction in (1, -1):
            a = dict(ret_30d=-direction*.2, return_percentile=5 if direction == 1 else 95,
                     signed_move=-direction*3, stretch_atr=-direction*3)
            b = dict(status='OK', weak_type='low' if direction == 1 else 'high', ratio=-direction*.2)
            self.assertTrue(all(v == direction for v in signals(a, b).values()))
            a['ret_30d'] = -direction*.15
            self.assertEqual(signals(a, b)['legacy_proxy'], 0)
            b['status'] = 'UNAVAILABLE'
            self.assertEqual(signals(a, b)['percentile_structure'], 0)
            a['return_percentile'] = None
            self.assertEqual(signals(a, b)['percentile'], 0)

    def test_summary_empty_and_distribution(self):
        self.assertIsNone(summarize([])['mean'])
        value = summarize([dict(return_=x, mae=-.2, mfe=.3) for x in (-.1, .1, .3)])
        self.assertAlmostEqual(value['mean'], .1)
        self.assertAlmostEqual(value['p10'], -.06)
        self.assertAlmostEqual(value['positive_rate'], 2/3)

    def test_split_purge_dedup_and_reproducibility(self):
        data = rows(bars(150))
        indicators = [dict(ret_30d=.2, return_percentile=95, signed_move=3, stretch_atr=3,
                           signal_time=r['timestamp']+DAY) for r in data]
        structures = [dict(status='OK', weak_type='high', ratio=.2, trend='BULLISH') for r in data]
        with patch('event_study.calculate', return_value=indicators), patch('event_study.replay', return_value=structures):
            result = study(data)
            self.assertEqual(result, study(data))
        for event in result['events']:
            if event['partition'] == 'train':
                self.assertLessEqual(event['exit_time'], result['split_time'])
            else:
                self.assertGreaterEqual(event['entry_time'], result['split_time'])
        selected = [e for e in result['events'] if e['kind'] == 'signal' and e['rule'] == 'percentile' and e['horizon'] == 1 and e['partition'] == 'train']
        self.assertEqual(len(selected), 4)
        self.assertTrue(all(b['timestamp']-a['timestamp'] >= 30*DAY for a, b in zip(selected, selected[1:])))
        for summary in result['summaries']:
            self.assertEqual(summary['result']['n'], summary['random_control']['n'])

    def test_no_eligible_data_and_invalid_config(self):
        result = study(rows(bars(20)))
        self.assertEqual(result['eligible'], 0)
        self.assertIsNone(result['split_time'])
        self.assertTrue(all(s['status'] == 'INSUFFICIENT_EVENTS' for s in result['summaries']))
        for kwargs in (dict(tail=50), dict(move=float('nan')), dict(stretch=0), dict(train_fraction=1), dict(min_events=0)):
            with self.assertRaises(ValueError):
                Config(**kwargs)

    def test_future_prices_do_not_change_candidates(self):
        data = rows(bars(100))
        # Real indicator/structure pipeline; future extension must preserve features/signals.
        from indicators import Config as IC
        from structure_history import Config as SC
        import math
        for i, row in enumerate(data):
            c = 100 + .2*i + 10*math.sin(i/3)
            row.update(open=c, close=c, high=c+1, low=c-1)
        short = study(data[:80], indicator_config=IC(window=3), structure_config=SC(3))
        full = study(data, indicator_config=IC(window=3), structure_config=SC(3))
        self.assertTrue(short['candidates'])
        self.assertEqual(short['candidates'], [c for c in full['candidates'] if c['index'] < 80])


if __name__ == '__main__':
    unittest.main()
