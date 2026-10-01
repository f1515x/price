from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collection_scheduler import collect, main as collect_main
from event_study import Config as EventConfig
from history import DAY
from research_config import load_profile
from trade_simulation import main as simulation_main, proposals


def parameters():
    return dict(schema_version=1, collection=dict(symbols=['BTC'], start='1970-01-01', close_delay=300),
                indicators=dict(window=10, ema_period=5, atr_period=3), structures=dict(swing_length=3),
                events=dict(tail=5, move=3, stretch=4, train_fraction=.6, seed=123, min_events=30),
                execution=dict(initial_equity=10000, risk_fraction=.005, max_exposure=1, max_drawdown=.15,
                               entry_atr=.75, stop_atr=2, fee_rate=.001, slippage=.002))


class ResearchConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'config.json'
        self.write(parameters())

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding='utf-8')
        return load_profile(self.path)

    def test_semantic_version_and_file_identity(self):
        first = load_profile(self.path)
        self.path.write_text(json.dumps(parameters(), indent=2), encoding='utf-8-sig')
        second = load_profile(self.path)
        self.assertEqual(first.evidence['parameter_version'], second.evidence['parameter_version'])
        self.assertNotEqual(first.evidence['file_sha256'], second.evidence['file_sha256'])
        altered = parameters()
        altered['execution']['fee_rate'] *= 2
        self.assertNotEqual(first.evidence['parameter_version'], self.write(altered).evidence['parameter_version'])

    def test_bad_keys_duplicates_and_schema(self):
        for section in (None, 'indicators', 'execution', 'collection'):
            value = parameters()
            (value if section is None else value[section])['typo'] = 1
            with self.assertRaises(ValueError):
                self.write(value)
        self.path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            load_profile(self.path)
        value = parameters()
        value['schema_version'] = True
        with self.assertRaises(ValueError):
            self.write(value)

    def test_invalid_types_nonfinite_and_missing_risk(self):
        for section, key, number in [('events', 'tail', True), ('events', 'tail', float('nan')),
                                     ('indicators', 'window', 10.5), ('structures', 'swing_length', 0),
                                     ('execution', 'fee_rate', -1), ('execution', 'slippage', float('inf')),
                                     ('collection', 'close_delay', True)]:
            value = parameters()
            value[section][key] = number
            with self.assertRaises(ValueError):
                self.write(value)
        value = parameters()
        del value['execution']['risk_fraction']
        with self.assertRaises(ValueError):
            self.write(value)

    def test_collection_provenance_and_effective_parameters(self):
        profile = load_profile(self.path)
        config = profile.collector()
        def fetch(p):
            return [dict(t=t, o=100, h=105, l=95, c=100 + t//DAY % 3, v=1)
                    for t in range(p['from'], p['to']+1, DAY)]
        state = collect(self.root / 'cycle', config, now=45*DAY+300, fetch=fetch)
        recorded = state['evidence']['parameters']
        self.assertEqual(recorded['parameter_profile'], profile.evidence)
        self.assertEqual(recorded['indicators'], asdict(profile.indicators))
        self.assertEqual(recorded['candidates'], dict(tail=5, move=3, stretch=4))
        from candidate_store import query_candidates
        run = state['stages']['candidates'][0]
        rows = query_candidates(self.root / 'cycle/research.sqlite', run['run_id'], 'BTC')
        self.assertEqual(rows[-1]['indicator']['parameters'], asdict(profile.indicators))
        self.assertFalse(state['execution_authorized'])
        again = collect(self.root / 'cycle', config, now=45*DAY+300, fetch=fetch)
        self.assertTrue(all(not r['inserted'] for rs in again['stages'].values() for r in rs))

    def test_collector_cli_rejects_overrides_and_preserves_defaults(self):
        with self.assertRaises(SystemExit), patch('collection_scheduler.collect') as run:
            collect_main(['--root', str(self.root), '--research-config', str(self.path), '--tail', '5'])
        run.assert_not_called()
        with patch('collection_scheduler.collect', return_value=dict(status='COMPLETE', cycle='x')) as run:
            collect_main(['--root', str(self.root)])
        self.assertEqual(run.call_args.args[1].candidates.tail, 10)
        self.assertEqual(run.call_args.args[1].indicators.window, 365)

    def test_threshold_changes_actual_proposals(self):
        bars = [dict(timestamp=0)]
        indicator = dict(ret_30d=-.2, return_percentile=7, signed_move=-3, stretch_atr=-3,
                         atr=10, signal_time=DAY)
        structure = dict(status='OK', weak_type='low', raw_weak_price=100, strong_price=120, ratio=-.2)
        kwargs = dict(indicators=[indicator], structures=[structure])
        self.assertEqual(len(proposals(bars, 'percentile_structure', **kwargs)), 1)
        self.assertEqual(proposals(bars, 'percentile_structure', event_config=EventConfig(tail=5), **kwargs), [])

    def test_simulation_cli_uses_all_sections_and_records_version(self):
        profile = load_profile(self.path)
        output = self.root / 'result.json'
        with patch('trade_simulation.load_snapshot', return_value=([], dict(sha256='input'))), \
                patch('trade_simulation.research', return_value=dict(experiments=[], conclusion='NOT_VALIDATED')) as run:
            simulation_main(['snapshot', '--research-config', str(self.path), '--output', str(output)])
        self.assertEqual(run.call_args.args[1:], (profile.execution, profile.indicators, profile.structures, profile.events))
        recorded = json.loads(output.read_text())
        self.assertEqual(recorded['parameter_profile'], profile.evidence)
        self.assertIn('research_config.py', recorded['code_sha256'])
        with patch('trade_simulation.load_snapshot', return_value=([], dict(sha256='input'))), \
                patch('trade_simulation.research', return_value=dict(experiments=[], conclusion='NOT_VALIDATED')):
            with self.assertRaises(FileExistsError):
                simulation_main(['snapshot', '--research-config', str(self.path), '--output', str(output)])


if __name__ == '__main__':
    unittest.main()
