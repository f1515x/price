import unittest
from dataclasses import replace

from history import DAY
from portfolio_simulation import PortfolioConfig, simulate
from trade_simulation import simulate as single
from test_trade_simulation import candidate, cfg, data


def assets(prices=None, names=("BTC", "ETH")):
    prices = prices or [(100, 105, 95, 100)]*3
    return {s: [dict(r, symbol=s) for r in data(prices)] for s in names}


def pc(**kwargs):
    return PortfolioConfig(cfg(**kwargs), .05, 2)


class PortfolioTests(unittest.TestCase):
    def test_shared_equity_stop_losses_not_independent_accounts(self):
        rows = assets([(100, 105, 95, 100), (100, 105, 85, 100)])
        r = simulate(rows, {s: [candidate()] for s in rows}, pc(), {s: s for s in rows})
        self.assertEqual(r['summary']['final_equity'], 9800)
        self.assertEqual(sum(t['net_pnl'] for t in r['trades']), -200)
        self.assertAlmostEqual(r['summary']['max_drawdown'], .02)

    def test_total_gross_cap_including_opposite_direction(self):
        rows = assets()
        r = simulate(rows, {'BTC': [candidate()], 'ETH': [candidate(direction=-1)]},
                     pc(max_exposure=.15), {s: 'crypto' for s in rows})
        self.assertEqual([t['quantity'] for t in r['trades']], [10, 5])
        self.assertEqual(r['allocations'][-1]['gross_exposure'], 1500)

    def test_total_risk_cap_and_fee_reservation(self):
        rows = assets(names=('BTC', 'ETH', 'SOL'))
        config = replace(pc(), max_total_risk=.015)
        r = simulate(rows, {s: [candidate()] for s in rows}, config, {s: s for s in rows})
        self.assertEqual([t['quantity'] for t in r['trades']], [10, 5])
        self.assertEqual(r['orders'][-1]['status'], 'TOTAL_RISK_BLOCKED')
        config = replace(pc(fee_rate=.001, slippage=.001, funding_daily=.001,
                            quantity_step=.000001, max_exposure=.15), max_total_risk=.015)
        r = simulate(rows, {s: [candidate()] for s in rows}, config, {s: s for s in rows})
        for a in r['allocations']:
            self.assertLessEqual(a['gross_exposure'], a['equity']*.15+1e-8)
            self.assertLessEqual(a['modeled_stop_risk'], a['equity']*.015+1e-8)
        self.assertAlmostEqual(r['summary']['final_equity'], 10000+sum(t['net_pnl'] for t in r['trades']))

    def test_group_limit_counts_pending_and_positions(self):
        rows = assets([(110, 115, 105, 110)]*3)
        config = replace(pc(), max_same_direction=1)
        r = simulate(rows, {s: [candidate()] for s in rows}, config, {s: 'crypto' for s in rows})
        self.assertEqual(r['orders'][1]['status'], 'CORRELATION_BLOCKED')
        self.assertEqual(r['orders'][0]['status'], 'END_OF_SAMPLE')
        rows = assets()
        r = simulate(rows, {'BTC': [candidate()], 'ETH': [candidate(1)]}, config, {s: 'crypto' for s in rows})
        self.assertEqual(r['orders'][1]['status'], 'CORRELATION_BLOCKED')

    def test_opposite_directions_and_separate_groups(self):
        rows = assets()
        config = replace(pc(), max_same_direction=1)
        for cs, groups in (({'BTC': [candidate()], 'ETH': [candidate(direction=-1)]}, {s: 'crypto' for s in rows}),
                           ({s: [candidate()] for s in rows}, {s: s for s in rows})):
            self.assertEqual(len(simulate(rows, cs, config, groups)['trades']), 2)

    def test_exits_do_not_release_same_day_capacity(self):
        rows = assets([(100, 105, 95, 100)]*4)
        rows['BTC'][2].update(high=125, close=120)
        r = simulate(rows, {'BTC': [candidate()], 'ETH': [candidate(1)]},
                     pc(max_exposure=.1), {s: s for s in rows})
        self.assertEqual(r['orders'][1]['status'], 'TOTAL_EXPOSURE_BLOCKED')
        self.assertEqual(r['trades'][0]['reason'], 'TARGET')
        self.assertEqual(r['summary']['final_equity'], 10200)

    def test_use_open_marks_not_future_closes(self):
        rows = assets([(100, 105, 95, 100)]*4)
        rows['BTC'][2].update(high=119, close=118)
        r = simulate(rows, {'BTC': [candidate()], 'ETH': [candidate(1)]}, pc(), {s: s for s in rows})
        eth = next(t for t in r['trades'] if t['symbol'] == 'ETH')
        self.assertEqual(eth['quantity'], 10)
        self.assertEqual(eth['risk_budget'], 100)

    def test_drawdown_halts_whole_account(self):
        rows = assets([(100, 105, 95, 100)]*4)
        rows['BTC'][1].update(low=85)
        r = simulate(rows, {'BTC': [candidate()], 'ETH': [candidate(1)]},
                     pc(max_drawdown=.005), {s: s for s in rows})
        self.assertEqual(r['orders'][1]['status'], 'RISK_HALTED')
        self.assertTrue(r['equity_curve'][-1]['halted'])

    def test_resting_order_rechecks_marked_exposure_at_fill(self):
        rows = assets([(100, 105, 95, 100)]*4)
        rows['ETH'][1].update(open=110, high=115, low=105, close=110)
        rows['BTC'][2].update(open=110, high=115, low=105, close=110)
        r = simulate(rows, {s: [candidate()] for s in rows}, pc(max_exposure=.15), {s: s for s in rows})
        eth = next(t for t in r['trades'] if t['symbol'] == 'ETH')
        self.assertEqual(eth['entry_time'], 2*DAY)
        self.assertEqual(eth['quantity'], 4)
        self.assertEqual(r['allocations'][-1]['equity'], 10100)
        self.assertEqual(r['allocations'][-1]['gross_exposure'], 1500)

    def test_symbol_order_is_reproducible(self):
        rows = assets()
        config = replace(pc(), max_same_direction=1)
        cs, groups = {s: [candidate()] for s in rows}, {s: 'crypto' for s in rows}
        r = simulate(rows, cs, config, groups)
        self.assertEqual(r, simulate(dict(reversed(list(rows.items()))), cs, config, groups))
        self.assertEqual(r['trades'][0]['symbol'], 'BTC')

    def test_single_asset_execution_compatibility(self):
        for direction in (1, -1):
            for prices in ([(100, 105, 95, 100)]*3,
                           [(100, 105, 95, 100), (100, 130, 80, 100)],
                           [(100, 105, 95, 100), (100, 105, 95, 100), (80, 85, 75, 80)]):
                rows = assets(prices, ('BTC',))
                r = simulate(rows, {'BTC': [candidate(direction=direction)]}, pc(), {'BTC': 'crypto'})
                baseline = single(rows['BTC'], [candidate(direction=direction)], cfg())
                self.assertEqual(r['summary']['final_equity'], baseline['summary']['final_equity'])
                self.assertEqual([t['reason'] for t in r['trades']], [t['reason'] for t in baseline['trades']])

    def test_expiry_and_confirmed_structure_invalidation(self):
        rows = assets([(110, 115, 105, 110)]*4)
        cs, groups = {s: [candidate()] for s in rows}, {s: s for s in rows}
        r = simulate(rows, cs, pc(expiry_days=1), groups)
        self.assertTrue(all(o['status'] == 'EXPIRED' for o in r['orders']))
        structures = {s: [dict(status='OK', weak_type='low', raw_weak_price=100, strong_price=120)]*4 for s in rows}
        structures['BTC'][1] = dict(structures['BTC'][1], raw_weak_price=99)
        r = simulate(rows, cs, pc(), groups, structures)
        self.assertEqual(r['orders'][0]['status'], 'STRUCTURE_INVALIDATED')
        self.assertEqual(r['orders'][0]['end_time'], 2*DAY)

    def test_invalid_and_missing_grid_rejected(self):
        rows = assets()
        cs, groups = {s: [] for s in rows}, {s: s for s in rows}
        for bad in ({'BTC': rows['BTC'][:-1], 'ETH': rows['ETH']},
                    {s: [dict(r, timestamp=r['timestamp']+(DAY if i >= 1 else 0))
                         for i, r in enumerate(rs)] for s, rs in rows.items()}):
            with self.assertRaises(ValueError):
                simulate(bad, cs, pc(), groups)
        with self.assertRaises(ValueError):
            simulate(rows, cs, pc(), {'BTC': 'crypto'})
        with self.assertRaises(ValueError):
            simulate(rows, {'BTC': [dict(candidate(), signal_time=0)], 'ETH': []}, pc(), groups)
        for v in (0, 2, float('nan')):
            with self.assertRaises(ValueError):
                replace(pc(), max_total_risk=v)
        with self.assertRaises(ValueError):
            replace(pc(), max_same_direction=True)

    def test_no_signals_is_insufficient_not_validated(self):
        rows = assets()
        r = simulate(rows, {s: [] for s in rows}, pc(), {s: s for s in rows})
        self.assertEqual(r['summary']['final_equity'], 10000)
        self.assertIsNone(r['summary']['fill_rate'])
        self.assertEqual(r['status'], 'INSUFFICIENT_TRADES')


if __name__ == '__main__':
    unittest.main()
