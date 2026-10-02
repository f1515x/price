"""Extract the fixed M6 evidence scope without running or evaluating strategies."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace('+00:00', 'Z')


def interval(start, end):
    assert type(start) is int and type(end) is int and start < end
    return {'start': start, 'end_exclusive': end,
            'start_utc': utc(start), 'end_exclusive_utc': utc(end)}


def build(root):
    sources = {}

    def read(relative):
        path = root / relative
        sources[relative] = digest(path)
        return json.loads(path.read_text(encoding='utf-8'))

    registration = read('data/M6-restart-registration.json')
    final = read('data/M6-full-final.json')
    original = read('M6-full-protocol.json')
    notices = read('data/M6-historical-notices-acceptance.json')
    intraday = read('data/M6-intraday-funding-acceptance.json')
    batch = read('data/M6-intraday-batch-acceptance.json')
    assert sources['data/M6-restart-registration.json'] == 'b2bc4ddbf455c86dd53911d3814c27bd61026d89104fe58fffe15a4b005ea6cd'
    assert sources['data/M6-full-final.json'] == '6588932510f7084849dd4d3056cdde5e93261338064d55b47803503a4a2fbaa0'
    assert all(final['protocol'].get(k) == v for k, v in original.items())
    assert final['protocol']['preregistered_file_sha256'] == sources['M6-full-protocol.json']
    assets = registration['protocol']['assets']
    assert assets == original['assets'] == ['BTC', 'ETH']
    frozen = registration['source_sha256']
    source_dir = Path(__file__).resolve().parent
    assert len(frozen) == 37
    assert all(digest(source_dir / name) == sha for name, sha in frozen.items())

    simulations, orders, trades = [], [], []
    for section in ('experiments', 'recent_historical_funding', 'isolated_asset_tests'):
        for i, experiment in enumerate(final[section]):
            pointer = f'/{section}/{i}'
            result = experiment['result']
            if 'start' in experiment:
                start, end = experiment['start'], experiment['end']
            else:
                fold = final['folds'][experiment['fold']]
                start, end = fold['test_start'], fold['test_end']
            simulations.append({'source_pointer': pointer,
                                'context': {k: v for k, v in experiment.items() if k != 'result'},
                                'window': interval(start, end),
                                'orders': len(result['orders']), 'trades': len(result['trades'])})
            for j, order in enumerate(result['orders']):
                assert order['symbol'] in assets
                times = {k: order[k] for k in ('signal_time', 'expires_at', 'end_time') if k in order}
                orders.append({'source_pointer': f'{pointer}/result/orders/{j}',
                               'symbol': order['symbol'], 'status': order['status'],
                               'admitted': order['admitted'], 'times': times})
            for j, trade in enumerate(result['trades']):
                assert trade['symbol'] in assets
                assert start <= trade['entry_time'] <= trade['exit_time'] < end
                trades.append({'source_pointer': f'{pointer}/result/trades/{j}',
                               'symbol': trade['symbol'],
                               'times': {k: trade[k] for k in ('signal_time', 'entry_time', 'exit_time')}})
    assert len(simulations) == 524

    funding = {}
    for asset in assets:
        relative = f'data/M6-full-20261001/{asset}-funding-full/funding.json'
        data = read(relative)
        records = data['records']
        expected = list(range(data['start'], data['end_exclusive'], data['assumed_interval']))
        assert [r['timestamp'] for r in records] == expected
        assert len(records) == 7395 and not data['missing']
        funding[asset] = {'source': relative, 'window': interval(data['start'], data['end_exclusive']),
                          'status': data['status'], 'grid_seconds': data['assumed_interval'],
                          'timestamp_protocol': data['timestamp_protocol'],
                          'actual_account_settlements_verified': False,
                          'records': [{'source_pointer': f'/records/{i}',
                                       'timestamp': r['timestamp'], 'utc': utc(r['timestamp']),
                                       'reported_timestamp': r['reported_timestamp']}
                                      for i, r in enumerate(records)]}

    events = []
    for i, event in enumerate(notices['evidence']['events']):
        timestamp = event['effective_timestamp']
        policy = intraday['policies'][i]
        scenario = intraday['baseline']['scenarios'][i]
        assert scenario['symbol'] == policy['symbol'] == event['symbol']
        assert policy['start'] == scenario['start'] == timestamp - 1
        assert policy['end'] == scenario['end'] == timestamp + 2
        day = timestamp // 86400 * 86400
        events.append({'notice_id': event['id'], 'symbol': event['symbol'], 'field': event['field'],
                       'effective_timestamp': timestamp, 'effective_utc': utc(timestamp),
                       'notice_source_pointer': f'/evidence/events/{i}',
                       'authenticated': False, 'validity_end': None,
                       'daily_blocked_window': interval(day, day + 86400),
                       'declared_replay_window': interval(policy['start'], policy['end']),
                       'order_actions': scenario['actions'],
                       'declared_settlement_timestamps': policy['scheduled_timestamps'],
                       'same_second_ordering': policy['ordering'],
                       'actual_fills_verified': False, 'actual_funding_schedule_verified': False})

    historical_folds = [{'index': i,
                         'train': interval(f['train_start'], f['train_end']),
                         'embargo': interval(f['train_end'], f['test_start']),
                         'test': interval(f['test_start'], f['test_end'])}
                        for i, f in enumerate(final['folds'])]
    future = [{'index': i, 'test': interval(f['test_start'], f['test_end'])}
              for i, f in enumerate(registration['folds'])]
    assert len(future) == 5
    assert all(f['test']['end_exclusive'] - f['test']['start'] == 365 * 86400 for f in future)
    assert all(a['test']['end_exclusive'] == b['test']['start'] for a, b in zip(future, future[1:]))

    report = {'version': 'm6-evidence-scope-v1', 'task': 'plan.md 4.2 first checkbox',
              'scope_fixed_on': '2026-10-02 America/La_Paz', 'owner': 'Codex',
              'scope_status': 'FIXED', 'strategy_status': 'NOT_VALIDATED',
              'assets': assets, 'market': 'Gate USDT linear perpetual',
              'time_semantics': 'UTC half-open windows; daily model times are bucket labels, not exact fills',
              'historical_data': {a: interval(final['input_quality'][a]['start'],
                                             final['input_quality'][a]['end_exclusive']) for a in assets},
              'historical_folds': historical_folds, 'future_folds': future,
              'future_evaluation_not_before': utc(future[-1]['test']['end_exclusive']),
              'future_orders_and_settlements': 'UNKNOWN_UNTIL_OBSERVED; no inferred future schedule',
              'notice_windows': events,
              'minute_observations': {'assets': assets,
                                      'window': interval(batch['report']['start'], batch['report']['end_exclusive']),
                                      'valid_asset_minutes': batch['report']['valid_asset_minutes'],
                                      'actual_fills_verified': False},
              'historical_simulations': simulations, 'model_order_times': orders,
              'model_trade_times': trades, 'historical_funding_times': funding,
              'frozen_sources_verified': len(frozen), 'input_sha256': sources,
              'builder_sha256': digest(Path(__file__)),
              'excluded': ['New strategy evaluation', 'Real execution certification',
                           'Assumed notice validity endpoints', 'Frozen protocol changes'],
              'next_step': 'Build per-field specifications matrix for these windows; retain missing evidence'}
    assert all(digest(root / name) == sha for name, sha in sources.items())
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = build(args.evidence_root)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')
    print(json.dumps({'scope_status': report['scope_status'],
                      'simulations': len(report['historical_simulations']),
                      'model_orders': len(report['model_order_times']),
                      'model_trades': len(report['model_trade_times']),
                      'frozen_sources_verified': report['frozen_sources_verified'],
                      'output_sha256': digest(args.output)}))
