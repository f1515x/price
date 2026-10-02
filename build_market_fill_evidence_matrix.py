"""Inventory archived market data and model executions without certifying fills."""
import argparse
from collections import defaultdict
from pathlib import Path

from build_spec_evidence_matrix import PINS as SPEC_PINS, window
from contract_specs import digest, encoded
from history import load_snapshot
from intraday_history import verify as verify_minutes
from intraday_batch import verify_batch
from spec_evidence import _json

PINS = {k: SPEC_PINS[k] for k in ('data/M6-evidence-scope.json', 'data/M6-restart-registration.json')}
PINS.update({
    'data/M6-intraday-batch-20260928-30/batch.json': '265b9cd30f35d596246874c1d9a4c8d9b85b5cc0117d5d9f06e5b2701a2e6333',
    'data/M6-intraday-history-ETH-20260929/manifest.json': '67a7c7f9925695260be857f4289d5b3b80ef0ae0f39ba1662e186310090b88b8',
    'data/M6-intraday-funding-acceptance.json': '1daf8853b6af5db486539ae81bc00685135359239946fc541609e4b5735361ca',
    'data/M6-full-20261001/BTC-daily/quality.json': '221bf2ec98cb6566376244bb0fc6badf444d9770d4b67b61ab88ff9a2d7b6eed',
    'data/M6-full-20261001/ETH-daily/quality.json': 'ed5e376108fdb498be52f61b44686acbc3cce2d110fc269056f9a3c57f4caa9f',
})


def coverage(start, end, step, timestamps):
    """Count containing buckets; a bucket never proves an exact intrabar path."""
    if type(step) is not int or step <= 0 or start >= end:
        raise ValueError('Increasing window and positive integer step required')
    first = start // step * step
    expected = range(first, ((end - 1) // step + 1) * step, step)
    observed = set(timestamps)
    missing = [t for t in expected if t not in observed]
    return dict(bar_seconds=step, expected_bars=len(expected), observed_bars=len(expected)-len(missing),
                missing_bucket_starts=missing, exact_path_verified=False)


def build(root):
    root = Path(root).resolve()
    inputs = {}

    def track(name, expected=None):
        p = (root / name).resolve()
        if not p.is_relative_to(root):
            raise ValueError('Evidence path escapes root')
        body = p.read_bytes()
        sha = digest(body)
        if (expected is not None and sha != expected) or (name in inputs and sha != inputs[name]):
            raise ValueError('Evidence checksum mismatch: ' + name)
        inputs[name] = sha
        return _json(body) if p.suffix == '.json' else body

    fixed = {n: track(n, h) for n, h in PINS.items()}
    scope = fixed['data/M6-evidence-scope.json']
    registration = fixed['data/M6-restart-registration.json']
    for n, h in scope['input_sha256'].items():
        track(n, h)
    source_dir = Path(__file__).resolve().parent
    frozen = registration['source_sha256']
    if len(frozen) != 37 or any(digest((source_dir/n).read_bytes()) != h for n, h in frozen.items()):
        raise ValueError('Frozen source constraint failed')
    if scope['assets'] != registration['protocol']['assets'] or scope['assets'] != ['BTC', 'ETH']:
        raise ValueError('Assets differ from fixed registration')

    archives = []
    stamps = {s: {86400: set(), 60: set()} for s in scope['assets']}

    def add_archive(directory, rows, report, step, kind):
        symbol = report['symbol']
        if symbol not in stamps or any(r['symbol'] != symbol for r in rows):
            raise ValueError('Archive asset mismatch')
        # Bind every raw and derived byte used by the existing offline verifier.
        files = sorted(p for p in directory.iterdir() if p.is_file())
        refs = []
        for p in files:
            name = p.relative_to(root).as_posix()
            track(name)
            refs.append(name)
        stamps[symbol][step].update(r['timestamp'] for r in rows)
        archives.append(dict(id=directory.relative_to(root).as_posix(), symbol=symbol, kind=kind,
                             window=window(report['start'], report['end_exclusive']),
                             bar_seconds=step, bars=len(rows), files=refs,
                             missing=report['missing_timestamps'], issues=report['issues'],
                             provenance='ARCHIVED_PUBLIC_MARKET_OBSERVATION_NOT_ACCOUNT_FILL',
                             timestamp_semantics=report['timestamp_semantics'],
                             market_fills_verified=False, exact_path_verified=False))

    # Inventory all currently archived daily snapshots, including overlapping collection copies.
    for quality in sorted((root/'data').rglob('quality.json')):
        name = quality.relative_to(root).as_posix()
        report = track(name)
        if report.get('version') != 'gate-daily-v1':
            continue
        rows, report = load_snapshot(quality.parent)
        add_archive(quality.parent, rows, report, 86400, 'DAILY_TRADE_OHLCV')
    batch_name = 'data/M6-intraday-batch-20260928-30/batch.json'
    batch = fixed[batch_name]
    verify_batch(root/Path(batch_name).parent, PINS[batch_name])
    for entry in batch['archives']:
        directory = root/Path(batch_name).parent/entry['directory']
        rows, report = verify_minutes(directory, entry['manifest_sha256'])
        add_archive(directory, rows, report, 60, 'MINUTE_TRADE_OHLCV')
    single = 'data/M6-intraday-history-ETH-20260929/manifest.json'
    rows, report = verify_minutes(root/Path(single).parent, PINS[single])
    add_archive(root/Path(single).parent, rows, report, 60, 'MINUTE_TRADE_OHLCV_OVERLAPPING_COPY')

    # Collapse repeated parameter/cost runs into required windows, preserving every source reference.
    grouped = defaultdict(list)
    for i, sim in enumerate(scope['historical_simulations']):
        symbols = [sim['context']['symbol']] if 'symbol' in sim['context'] else scope['assets']
        for symbol in symbols:
            grouped[(symbol, sim['window']['start'], sim['window']['end_exclusive'])].append(i)
    counts = defaultdict(lambda: dict(orders=0, trades=0))
    sim_index = {s['source_pointer']: i for i, s in enumerate(scope['historical_simulations'])}
    for kind, key in [('orders', 'model_order_times'), ('trades', 'model_trade_times')]:
        for record in scope[key]:
            prefix = record['source_pointer'].split('/result/')[0]
            counts[(sim_index[prefix], record['symbol'])][kind] += 1
    rows = []

    def add_row(symbol, target, w, refs=None, precision='DAILY_MODEL; FINER_PATH_REQUIRED_FOR_AMBIGUOUS_BARS'):
        start, end = w['start'], w['end_exclusive']
        daily = coverage(start, end, 86400, stamps[symbol][86400])
        minute = coverage(start, end, 60, stamps[symbol][60])
        # Store long missing ranges compactly; no fictitious minute coverage from daily candles.
        for c in (daily, minute):
            missing = c.pop('missing_bucket_starts')
            ranges = []
            for t in missing:
                if ranges and ranges[-1]['end_exclusive'] == t:
                    ranges[-1]['end_exclusive'] += c['bar_seconds']
                else:
                    ranges.append(dict(start=t, end_exclusive=t+c['bar_seconds']))
            c['missing_ranges'] = ranges
        refs = refs or []
        rows.append(dict(id=f'{symbol}-{target}-{len(rows)}', symbol=symbol, target=target,
                         required_window=window(start,end), required_precision=precision,
                         archive_refs=[a['id'] for a in archives if a['symbol']==symbol
                                       and a['window']['start'] < end and a['window']['end_exclusive'] > start],
                         daily=daily, minute=minute, simulation_scope_pointers=[f'/historical_simulations/{i}' for i in refs],
                         model_order_records=sum(counts[(i,symbol)]['orders'] for i in refs),
                         model_trade_records=sum(counts[(i,symbol)]['trades'] for i in refs),
                         actual_fill_evidence=[], certified_fill_coverage_seconds=0,
                         certification_status='NOT_CERTIFIED', gaps=[
                             'ACTUAL_ORDER_IDS_ACCEPT_CANCEL_PARTIAL_FILL_LOGS_MISSING',
                             'PUBLIC_OHLCV_IS_NOT_ACCOUNT_EXECUTION_OR_INTRABAR_PATH',
                             *(['MINUTE_COVERAGE_INCOMPLETE'] if minute['missing_ranges'] else []),
                             *(['DAILY_COVERAGE_INCOMPLETE'] if daily['missing_ranges'] else []),
                             *(['FUTURE_EXECUTION_TIMES_UNKNOWN'] if target.startswith('future-') else []),
                             *(['EXACT_SECOND_OR_FINER_PATH_MISSING'] if target.startswith('notice-') else [])]))

    for symbol in scope['assets']:
        add_row(symbol, 'historical-total', scope['historical_data'][symbol])
    for (symbol,start,end), refs in sorted(grouped.items()):
        add_row(symbol, 'model-execution', window(start,end), refs)
    for f in scope['future_folds']:
        for symbol in scope['assets']:
            add_row(symbol, f"future-{f['index']}", f['test'], precision='REGISTERED_DAILY; ACTUAL_EXECUTIONS_UNKNOWN')
    for event in scope['notice_windows']:
        add_row(event['symbol'], 'notice-day-'+event['notice_id'], event['daily_blocked_window'], precision='INTRADAY_PATH_REQUIRED; DAILY_BUCKET_INSUFFICIENT')
        add_row(event['symbol'], 'notice-second-'+event['notice_id'], event['declared_replay_window'], precision='EXACT_SECOND_OR_FINER_AND_ORDER_EVENT_SEQUENCE')
    for symbol in scope['assets']:
        add_row(symbol, 'minute-observation', scope['minute_observations']['window'], precision='OBSERVED_60_SECOND_OHLCV_ONLY')

    # Trade timestamps remain model daily labels. Keep all 2,462 provenance links, not independent sample counts.
    trade_index = []
    for i, t in enumerate(scope['model_trade_times']):
        trade_index.append(dict(scope_pointer=f'/model_trade_times/{i}', source_pointer=t['source_pointer'],
                                symbol=t['symbol'], times=t['times'], time_semantics='MODEL_DAILY_BUCKET_LABELS',
                                market_buckets={k: {str(step): v//step*step in stamps[t['symbol']][step]
                                                   for step in (86400,60)} for k,v in t['times'].items()},
                                actual_fill_verified=False))
    declared = fixed['data/M6-intraday-funding-acceptance.json']
    result = dict(version='m6-market-fill-evidence-matrix-v1', owner='Codex', date='2026-10-02 America/La_Paz',
                  task='plan.md 4.2 third checkbox', strategy_status='NOT_VALIDATED',
                  scope_ref='data/M6-evidence-scope.json', assets=scope['assets'], archives=archives, rows=rows,
                  model_trade_time_index=trade_index,
                  order_reference_policy='Use simulation_scope_pointers and scope.model_order_times source_pointer prefix; signal/expires/end are model labels, planned expires is not an actual order event.',
                  declared_replays=dict(source='data/M6-intraday-funding-acceptance.json',
                                        origin=declared['scenario_origin'], windows=[e['declared_replay_window'] for e in scope['notice_windows']],
                                        actual_fill_verified=False, evidence_credit_seconds=0),
                  summary=dict(rows=len(rows), daily_archives=sum(a['bar_seconds']==86400 for a in archives),
                               minute_archives=sum(a['bar_seconds']==60 for a in archives),
                               unique_daily_bars={s:len(stamps[s][86400]) for s in scope['assets']},
                               unique_minute_bars={s:len(stamps[s][60]) for s in scope['assets']},
                               model_orders=len(scope['model_order_times']), model_trades=len(trade_index),
                               certified_fill_coverage_seconds=0),
                  input_sha256=inputs, frozen_sources_verified=37,
                  limitations=['Hashes establish archived byte integrity, not issuer authenticity.',
                               'Minute bars do not establish second prices, queue position, account fills or slippage.',
                               'Daily mark high/low funding bounds are price proxies, not trade candles or settlement/fill evidence; costs remain 4.2 fourth item.',
                               'No future strategy evaluation or frozen code changes.'],
                  next_step='Build cost and execution policy evidence matrix; obtain real executions separately under 4.3.')
    for n,h in inputs.items():
        if digest((root/n).read_bytes()) != h:
            raise ValueError('Evidence changed during build')
    return result


def markdown(report):
    lines=['# M6 行情与成交证据矩阵', '', '2026-10-02（America/La_Paz）；负责人 Codex。', '',
           '行情覆盖按已归档且重建通过的 OHLCV 计算；重叠快照去重。真实成交证据为空，M6 NOT_VALIDATED。',
           '日线桶标签、模型成交、声明部分成交均不是交易所真实成交；分钟线不能证明秒内路径。', '',
           '| 资产 | 窗口类别 | UTC [起点, 终点) | 所需精度 | 日线覆盖 | 分钟覆盖 | 模型订单/成交记录 | 真实成交与缺口 |',
           '|---|---|---|---|---|---|---|---|']
    for r in report['rows']:
        w=r['required_window']; d=r['daily']; m=r['minute']
        lines.append(f"| {r['symbol']} | {r['target']} | {w['start_utc']} → {w['end_exclusive_utc']} | {r['required_precision']} | {d['observed_bars']}/{d['expected_bars']} | {m['observed_bars']}/{m['expected_bars']} | {r['model_order_records']}/{r['model_trade_records']} | 未认证；"+'；'.join(r['gaps'])+' |')
    lines += ['', '## 来源库存', '', '| 归档 | 资产 | 类型 | 条数 |', '|---|---|---|---|']
    for a in report['archives']:
        lines.append(f"| [{a['id']}](../../{a['id']}/{'quality.json' if a['bar_seconds']==86400 else 'manifest.json'}) | {a['symbol']} | {a['kind']} | {a['bars']} |")
    lines += ['', '来源文件、SHA-256、缺失区间、原模拟引用及逐笔模型时间覆盖详见 matrix.json。',
              '未来十个资产/区间的实际订单与成交时间仍未知。公告三秒声明不提供真实成交覆盖。',
              '缺口获取路径：公开精细行情归档用于路径复核；账户订单/撤单/部分成交/成交导出用于真实执行核对。可得性与认证顺序待 4.2 后续补证任务登记。', '']
    return '\n'.join(lines).encode('utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args=p.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    report=build(args.evidence_root)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir/'matrix.json').write_bytes(encoded(report))
    (args.output_dir/'matrix.md').write_bytes(markdown(report))
    print(encoded(report['summary']).decode())


if __name__ == '__main__':
    main()
