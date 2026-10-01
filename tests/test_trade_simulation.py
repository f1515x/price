import unittest
from dataclasses import replace
from unittest.mock import patch

from history import DAY
from trade_simulation import Config, proposals, research, simulate


def data(prices):
    return [dict(timestamp=i*DAY, symbol="BTC", market="gate_usdt_perpetual", interval="1d",
                 source="gate", open=o, high=h, low=l, close=c, volume=1)
            for i, (o, h, l, c) in enumerate(prices)]


def candidate(index=0, direction=1):
    return dict(index=index, signal_time=(index+1)*DAY, direction=direction,
                raw_weak_price=100, strong_price=120 if direction == 1 else 80, atr=10)


def cfg(**kwargs):
    return replace(Config(10000, .01, 1, .2, entry_atr=0, stop_atr=1, target_r=2,
                          fee_rate=0, slippage=0, funding_daily=0, quantity_step=1, min_quantity=1), **kwargs)


class SimulationTests(unittest.TestCase):
    def test_next_day_stop_first_and_accounting(self):
        bars = data([(100, 150, 50, 100), (100, 130, 80, 100)])
        r = simulate(bars, [candidate()], cfg())
        t = r['trades'][0]
        self.assertEqual(t['entry_time'], DAY)
        self.assertEqual(t['reason'], 'STOP')
        self.assertEqual(t['quantity'], 10)
        self.assertEqual(t['net_pnl'], -100)
        self.assertEqual(r['summary']['final_equity'], 9900)
        self.assertAlmostEqual(r['summary']['max_drawdown'], .01)

    def test_short_symmetry(self):
        r = simulate(data([(100, 100, 100, 100), (100, 120, 70, 100)]), [candidate(direction=-1)], cfg())
        self.assertEqual(r['trades'][0]['reason'], 'STOP')
        self.assertEqual(r['trades'][0]['net_pnl'], -100)

    def test_entry_bar_target_deferred_then_target(self):
        bars = data([(100, 100, 100, 100), (105, 125, 95, 110), (110, 125, 105, 120)])
        r = simulate(bars, [candidate()], cfg())
        self.assertEqual(r['trades'][0]['exit_time'], 3*DAY)
        self.assertEqual(r['trades'][0]['reason'], 'TARGET')
        self.assertEqual(r['trades'][0]['net_pnl'], 200)

    def test_stop_gap_exceeds_budget(self):
        bars = data([(100, 100, 100, 100), (100, 105, 95, 100), (80, 85, 75, 80)])
        r = simulate(bars, [candidate()], cfg())
        self.assertEqual(r['trades'][0]['exit_price'], 80)
        self.assertEqual(r['trades'][0]['net_pnl'], -200)

    def test_open_beyond_stop_invalidates_unfilled_order(self):
        r = simulate(data([(100, 100, 100, 100), (80, 85, 75, 80)]), [candidate()], cfg())
        self.assertEqual(r['orders'][0]['status'], 'PRICE_INVALIDATED')
        self.assertEqual(r['summary']['unfilled_rate'], 1)
        self.assertFalse(r['trades'])

    def test_expiry_and_structure_cancel(self):
        bars = data([(110, 115, 105, 110)]*4)
        r = simulate(bars, [candidate()], cfg(expiry_days=1))
        self.assertEqual(r['orders'][0]['status'], 'EXPIRED')
        self.assertEqual(r['orders'][0]['end_time'], 2*DAY)
        structures = [dict(status='OK', weak_type='low', raw_weak_price=100, strong_price=120)]*4
        structures[1] = dict(structures[1], raw_weak_price=99)
        r = simulate(bars, [candidate()], cfg(), structures)
        self.assertEqual(r['orders'][0]['status'], 'STRUCTURE_INVALIDATED')
        self.assertEqual(r['orders'][0]['end_time'], 2*DAY)

    def test_costs_funding_and_limit_price(self):
        bars = data([(100, 100, 100, 100), (98, 105, 95, 100), (100, 105, 95, 100)])
        config = cfg(fee_rate=.001, slippage=.001, funding_daily=.001)
        r = simulate(bars, [candidate()], config)
        t = r['trades'][0]
        self.assertLessEqual(t['entry_price'], 100)
        self.assertAlmostEqual(t['entry_price'], 98*1.001)
        expected = t['quantity']*(t['exit_price']-t['entry_price']) - t['entry_fee'] - t['exit_fee'] - t['funding']
        self.assertAlmostEqual(t['net_pnl'], expected)
        self.assertAlmostEqual(r['summary']['final_equity'], 10000+expected)
        modeled_risk = t['quantity']*(abs(t['entry_price']-90*.999)+.001*(t['entry_price']+90*.999))
        self.assertLessEqual(modeled_risk, t['risk_budget'])

    def test_exposure_step_and_one_position(self):
        bars = data([(100, 105, 95, 100)]*4)
        r = simulate(bars, [candidate(), candidate(1)], cfg(max_exposure=.02))
        self.assertEqual(r['trades'][0]['quantity'], 2)
        self.assertEqual(r['orders'][1]['status'], 'EXPOSURE_BLOCKED')
        r = simulate(bars, [candidate()], cfg(max_exposure=.001))
        self.assertEqual(r['orders'][0]['status'], 'QUANTITY_BLOCKED')

    def test_drawdown_halt_and_funding_short_credit(self):
        bars = data([(100, 100, 100, 100), (100, 105, 85, 100), (100, 105, 95, 100)])
        r = simulate(bars, [candidate(), candidate(1)], cfg(max_drawdown=.005))
        self.assertEqual(r['orders'][1]['status'], 'RISK_HALTED')
        r = simulate(data([(100, 105, 95, 100)]*2), [candidate(direction=-1)], cfg(funding_daily=.001))
        self.assertLess(r['trades'][0]['funding'], 0)
        self.assertGreater(r['trades'][0]['net_pnl'], 0)

    def test_gap_and_time_exit(self):
        bars = data([(100, 105, 95, 100)]*4)
        bars[2]['timestamp'] = 4*DAY
        bars[3]['timestamp'] = 5*DAY
        r = simulate(bars, [candidate()], cfg())
        self.assertEqual(r['trades'][0]['reason'], 'DATA_GAP')
        self.assertEqual(r['trades'][0]['exit_time'], 2*DAY)
        r = simulate(data([(100, 105, 95, 100)]*4), [candidate()], cfg(holding_days=1))
        self.assertEqual(r['trades'][0]['reason'], 'TIME_EXIT')

    def test_invalid_config_and_candidate(self):
        for kwargs in (dict(risk_fraction=0), dict(max_drawdown=1), dict(fee_rate=-1),
                       dict(funding_daily=float('nan')), dict(expiry_days=1.5), dict(quantity_step=0)):
            with self.assertRaises(ValueError):
                cfg(**kwargs)
        with self.assertRaises(ValueError):
            simulate(data([(100, 105, 95, 100)]*2), [dict(candidate(), signal_time=0)], cfg())

    def test_no_candidate_and_reproducible_partition_purge(self):
        bars = data([(100, 105, 95, 100)]*8)
        r = simulate(bars, [], cfg())
        self.assertIsNone(r['summary']['fill_rate'])
        self.assertEqual(r['summary']['net_pnl'], 0)
        structures = [dict(status='OK', weak_type='low', raw_weak_price=100, strong_price=120)]*8
        with patch('trade_simulation.study', return_value=dict(split_time=4*DAY, candidates=[dict(index=0), dict(index=4)])), \
             patch('trade_simulation.replay', return_value=structures), \
             patch('trade_simulation.proposals', return_value=[candidate(), candidate(4)]):
            result = research(bars, cfg())
            self.assertEqual(result, research(bars, cfg()))
        self.assertEqual(len(result['experiments']), 48)
        for e in result['experiments']:
            for t in e['trades']:
                if e['partition'] == 'train':
                    self.assertLessEqual(t['exit_time'], 4*DAY)
                else:
                    self.assertGreaterEqual(t['entry_time'], 4*DAY)

    def test_proposals_prefix_invariance(self):
        from test_history import bars
        from test_indicators import rows
        from indicators import Config as IC
        from structure_history import Config as SC
        import math
        values = rows(bars(100))
        for i, r in enumerate(values):
            close = 100+.2*i+10*math.sin(i/3)
            r.update(open=close, close=close, high=close+1, low=close-1)
        short = proposals(values[:80], 'percentile_structure', IC(window=3), SC(3))
        full = proposals(values, 'percentile_structure', IC(window=3), SC(3))
        self.assertTrue(short)
        self.assertEqual(short, [c for c in full if c['index'] < 80])


if __name__ == '__main__':
    unittest.main()
