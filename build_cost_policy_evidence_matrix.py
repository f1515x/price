"""Inventory archived costs and execution policies; never certify model evidence."""
import argparse
from bisect import bisect_left
from pathlib import Path

from build_market_fill_evidence_matrix import PINS as MARKET_PINS
from contract_specs import digest, encoded
from funding_history import load_snapshot, load_marks
from spec_evidence import _json

FIELDS = {
    'fee': ('手续费', 'ACCOUNT_FEE_TIER_MAKER_TAKER_REBATES_AND_FILL_BILLS_MISSING'),
    'slippage': ('滑点', 'TIMESTAMPED_REFERENCE_QUOTES_AND_ACTUAL_FILLS_MISSING'),
    'funding_schedule': ('资金费计划', 'HISTORICAL_SCHEDULE_EFFECTIVE_INTERVALS_AND_ACCOUNT_SETTLEMENTS_MISSING'),
    'funding_rate': ('资金费率', 'OBSERVED_RATES_NOT_AUTHENTICATED_OR_LINKED_TO_ACCOUNT_SETTLEMENTS'),
    'settlement_price': ('资金费结算价', 'EXACT_SETTLEMENT_MARK_PRICE_AND_ACCOUNT_CASHFLOW_MISSING'),
    'notice': ('公告执行', 'NOTICE_EXECUTION_POLICY_AND_FULL_VALIDITY_INTERVALS_MISSING'),
    'cancel': ('撤单', 'EXCHANGE_CANCEL_ACCEPTANCE_PRIORITY_AND_REMAINDER_POLICY_MISSING'),
    'partial_fill': ('部分成交', 'ACTUAL_FRAGMENTS_QUEUE_AND_MINIMUM_FILL_POLICY_MISSING'),
    'multiplier_conversion': ('持仓乘数换算', 'REAL_MULTIPLIER_CHANGE_POSITION_AND_COST_BASIS_POLICY_MISSING'),
}
ACCEPTANCES = ['dated-costs', 'settlement-prices', 'notice-execution', 'partial-orders',
               'multiplier-conversion', 'intraday-accounting', 'intraday-funding']
DOCS = ['M6-full-audit.md', 'M6-dated-costs-audit.md', 'M6-settlement-prices-audit.md',
        'M6-notice-execution-audit.md', 'M6-partial-orders-audit.md',
        'M6-multiplier-conversion-audit.md', 'M6-intraday-accounting-audit.md',
        'M6-intraday-funding-audit.md']


def pointer(value, path):
    for token in path.strip('/').split('/') if path else []:
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def rate_slice(records, start, end):
    if type(start) is not int or type(end) is not int or start >= end:
        raise ValueError('Invalid half-open interval')
    stamps = [r['timestamp'] for r in records]
    if any(type(t) is not int for t in stamps) or stamps != sorted(set(stamps)):
        raise ValueError('Rate records must have unique increasing integer timestamps')
    left, right = bisect_left(stamps, start), bisect_left(stamps, end)
    return dict(first_record_index=left, end_record_index_exclusive=right, count=right-left)


def build(root):
    root = Path(root).resolve()
    inputs = {}

    def track(name, expected=None):
        p = (root/name).resolve()
        if not p.is_relative_to(root):
            raise ValueError('Evidence path escapes root')
        body = p.read_bytes()
        sha = digest(body)
        if (expected is not None and sha != expected) or (name in inputs and sha != inputs[name]):
            raise ValueError('Evidence checksum mismatch: '+name)
        inputs[name] = sha
        return _json(body) if p.suffix == '.json' else body

    fixed = {n: track(n, h) for n, h in PINS.items()}
    scope = fixed['data/M6-evidence-scope.json']
    registration = fixed['data/M6-restart-registration.json']
    market = fixed['data/M6-market-fill-evidence-matrix/matrix.json']
    for name, sha in scope['input_sha256'].items():
        track(name, sha)
    for name, sha in market['input_sha256'].items():
        track(name, sha)
    frozen = registration['source_sha256']
    source_dir = Path(__file__).resolve().parent
    if len(frozen) != 37 or any(digest((source_dir/n).read_bytes()) != h for n, h in frozen.items()):
        raise ValueError('Frozen source constraint failed')
    if scope['assets'] != ['BTC', 'ETH'] or market['assets'] != scope['assets']:
        raise ValueError('Fixed assets differ')
    sources = []

    def add(name, path, fields, kind, symbols, value=None, note=''):
        doc = track(name)
        facts = pointer(doc, path) if value is None else value
        ref = f'S{len(sources):03d}'
        sources.append(dict(id=ref, file=name, pointer=path, fields=fields, kind=kind,
                            symbols=symbols, facts=facts, note=note,
                            authenticated=False, certified_valid_window=None))
        return ref

    for name in DOCS:
        body = track(name).decode('utf-8-sig')
        # Keep original lines; an audit report is not an exchange-issued policy.
        sources.append(dict(id=f'S{len(sources):03d}', file=name, pointer=None,
                            fields=list(FIELDS), kind='LOCAL_AUDIT_REPORT', symbols=scope['assets'],
                            facts=body, note='Local historical explanation only.',
                            authenticated=False, certified_valid_window=None))
    full = track('data/M6-full-final.json')
    add('M6-full-protocol.json', '/execution', ['fee', 'slippage', 'funding_rate'],
        'MODEL_PARAMETERS', scope['assets'])
    add('data/M6-dated-costs-acceptance.json', '/synthetic_cost_manifest', ['fee', 'slippage'],
        'SYNTHETIC_DECLARATION', scope['assets'], note='Unix-day fixture, not historical effective periods.')
    add('data/M6-settlement-prices-acceptance/prices.json', '/assets', ['settlement_price'],
        'SYNTHETIC_DECLARATION', scope['assets'])
    add('data/M6-notice-execution-acceptance.json', '/real_reports', ['notice'],
        'DECLARED_DAILY_REJECTION_POLICY', ['ETH'],
        value=[{k: r[k] for k in ('start', 'end', 'policy_status', 'checked_events', 'blockers')}
               for r in track('data/M6-notice-execution-acceptance.json')['real_reports']],
        note='Real notice timestamps; model rejects intraday changes on daily bars.')
    add('data/M6-partial-orders-acceptance.json', '/partial_fill_policy', ['partial_fill'],
        'SYNTHETIC_DECLARATION', ['ETH'])
    add('data/M6-partial-orders-acceptance.json', '/scenarios', ['cancel', 'partial_fill', 'notice'],
        'SYNTHETIC_DECLARATION', ['ETH'], note='Declared fragments at real notice seconds; no exchange orders.')
    add('data/M6-multiplier-conversion-acceptance.json', '/scenarios', ['multiplier_conversion', 'cancel'],
        'SYNTHETIC_DECLARATION', ['ETH'], note='Synthetic multiplier notices and 1970 fixture times.')
    add('data/M6-intraday-accounting-acceptance.json', '/policies', ['fee'],
        'SYNTHETIC_DECLARATION', ['ETH'])
    add('data/M6-intraday-funding-acceptance.json', '/policies',
        ['funding_schedule', 'funding_rate', 'settlement_price'], 'SYNTHETIC_DECLARATION', ['ETH'],
        note='Declared one-second schedule and settlement-before-fill priority, not real settlements.')
    # Bind all persistent fixtures and their source texts, including synthetic notices.
    for dirname in ['M6-settlement-prices-acceptance', 'M6-multiplier-conversion', 'M6-historical-notices']:
        for p in sorted((root/'data'/dirname).rglob('*')):
            if p.is_file():
                track(p.relative_to(root).as_posix())
    notices = track('data/M6-historical-notices/notices.json')
    for i, event in enumerate(notices['events']):
        add('data/M6-historical-notices/notices.json', f'/events/{i}', ['notice'],
            'ARCHIVED_NOTICE_EXCERPT', [event['symbol']], note='Change facts do not certify cancellation or conversion policy.')
    specs = track('data/M6-full-20261001/specs/specs.json')
    for i, spec in enumerate(specs['contracts']):
        track('data/M6-full-20261001/specs/'+spec['raw_file'], spec['raw_sha256'])
        add('data/M6-full-20261001/specs/specs.json', f'/contracts/{i}', ['fee', 'funding_schedule'],
            'CURRENT_PUBLIC_SNAPSHOT', [spec['symbol']],
            value={k: spec[k] for k in ('maker_fee_rate', 'taker_fee_rate', 'funding_interval_seconds',
                                       'source_url', 'observed_at')}, note='No historical validity or account fee tier inferred.')
    rates, settlements = {}, []
    for symbol in scope['assets']:
        name = f'data/M6-full-20261001/{symbol}-funding-full/funding.json'
        report = track(name)
        for p in report['pages']:
            track(str(Path(name).parent/p['raw_file']).replace('\\', '/'), p['sha256'])
        if load_snapshot(root/Path(name).parent) != report:
            raise ValueError('Funding reconstruction mismatch')
        rates[symbol] = report['records']
        add(name, '', ['funding_rate', 'funding_schedule'], 'PUBLIC_RATE_OBSERVATION_ASSUMED_GRID', [symbol],
            value={k: report[k] for k in ('source_url', 'start', 'end_exclusive', 'assumed_interval', 'status', 'missing')},
            note='Original report delays retained; assumed grid is not authenticated schedule.')
        mark_name = f'data/M6-full-20261001/{symbol}-marks-full.json'
        marks = track(mark_name)
        if load_marks(root/mark_name) != marks:
            raise ValueError('Mark reconstruction mismatch')
        add(mark_name, '', ['settlement_price'], 'DAILY_MARK_PROXY', [symbol],
            value={k: marks[k] for k in ('symbol', 'start', 'end_exclusive', 'interval')},
            note='Daily high/low conservative funding bounds; never exact settlement price.')
        settlements.extend(dict(symbol=symbol, file=name, pointer=f'/records/{i}', **record,
                                schedule_status='ASSUMED_GRID', exact_settlement_price=None,
                                account_settlement_ref=None, authenticated=False)
                           for i, record in enumerate(report['records']))
    simulations = []
    for sim in scope['historical_simulations']:
        result = pointer(full, sim['source_pointer']+'/result')
        simulations.append(dict(source_pointer=sim['source_pointer'], context=sim['context'],
                                window=sim['window'], execution=result['parameters']['execution'],
                                execution_by_asset=result['execution_by_asset'],
                                cost_mode=sim['context'].get('cost_mode'), authenticated=False))
    rows = []
    for target in market['rows']:
        symbol = target['symbol']; w = target['required_window']
        observed = rate_slice(rates[symbol], w['start'], w['end_exclusive'])
        for field, (label, gap) in FIELDS.items():
            candidates = [s['id'] for s in sources if field in s['fields'] and symbol in s['symbols']]
            rows.append(dict(id=target['id']+'-'+field, window_ref=target['id'], symbol=symbol,
                             target=target['target'], required_window=w, field=field, label=label,
                             inventory_source_refs=candidates,
                             inventory_reference_semantics='Candidates only; no certified applicability inferred.',
                             simulation_scope_pointers=target['simulation_scope_pointers'],
                             rate_record_slice=observed if field in ('funding_rate', 'funding_schedule', 'settlement_price') else None,
                             authentic_effective_window=None, actual_account_evidence=[],
                             certified_coverage_seconds=0, certification_status='NOT_CERTIFIED',
                             gaps=[gap] + (['FUTURE_EXECUTION_AND_SETTLEMENT_TIMES_UNKNOWN']
                                           if target['target'].startswith('future-') else [])))
    result = dict(version='m6-cost-policy-evidence-matrix-v1', owner='Codex', date='2026-10-02 America/La_Paz',
                  task='plan.md 4.2 fourth checkbox', strategy_status='NOT_VALIDATED', assets=scope['assets'],
                  scope_ref='data/M6-evidence-scope.json', window_ref='data/M6-market-fill-evidence-matrix/matrix.json',
                  fields=list(FIELDS), sources=sources, rows=rows, historical_model_costs=simulations,
                  observed_settlement_index=settlements, input_sha256=inputs, frozen_sources_verified=37,
                  summary=dict(windows=len(market['rows']), rows=len(rows), fields=len(FIELDS),
                               sources=len(sources), historical_simulations=len(simulations),
                               observed_rates={s: len(rates[s]) for s in scope['assets']}, certified_coverage_seconds=0),
                  limitations=['Hashes prove archived bytes, not issuer authenticity.',
                               'Repeated rate slices/windows are overlapping references, not independent settlements.',
                               'Declared fee/price/schedule/fragments/conversion policies receive no certification credit.',
                               'Account fee tier, fills, quotes, settlements and policy effective periods remain missing.',
                               'No future evaluation, new account access or frozen protocol changes.'],
                  next_step='4.2 fifth item: register acquisition feasibility, authentication basis, blockers and supplement order.')
    for name, sha in inputs.items():
        if digest((root/name).read_bytes()) != sha:
            raise ValueError('Evidence changed during build')
    return result


def markdown(report):
    lines = ['# M6 成本与执行政策证据矩阵', '', '2026-10-02（America/La_Paz）；负责人 Codex。', '',
             '覆盖固定的 40 个资产/窗口 × 9 类成本及政策。全部真实认证覆盖为 0，M6 NOT_VALIDATED。',
             '来源索引是库存候选，不能证明适用于对应期间。有效期未知；声明与公开观察不提升真实认证。', '',
             '| 资产 | 窗口 | UTC [起点, 终点) | 字段 | 现有依据索引 | 费率记录引用数 | 缺口 |',
             '|---|---|---|---|---|---|---|']
    for r in report['rows']:
        w = r['required_window']; count = r['rate_record_slice']
        lines.append(f"| {r['symbol']} | {r['target']} | {w['start_utc']} → {w['end_exclusive_utc']} | {r['label']} | "
                     + ', '.join(r['inventory_source_refs']) + f" | {count['count'] if count else 'N/A'} | "
                     + '; '.join(r['gaps']) + ' |')
    lines += ['', '## 现有依据与认证边界', '', '| ID | 来源/指针 | 类型 | 说明 |', '|---|---|---|---|']
    for s in report['sources']:
        lines.append(f"| {s['id']} | [{s['file']}](../../{s['file']}) {s['pointer'] or ''} | {s['kind']} | {s['note']} |")
    lines += ['', 'matrix.json 保存来源原文/精确声明、输入哈希、全部模型参数版本以及逐条费率的报告时间。',
              '费率索引各 7,395 条按假定 28,800 秒网格重建；计划未认证，日线 mark 不是精确结算价。',
              'Unix 时间 0 起点的费用/结算价/乘数情景均为合成验证，不外推到历史期间。',
              '费用声明 0.001→0.002、资金费声明每秒结算、部分成交及乘数换算政策均无真实认证。',
              '撤单只取消声明挂单余量，已成交敞口保留；实际接纳/撤单优先级与队列仍未知。',
              '下一步按 4.2 第五项登记逐缺口获取路径、可行性、认证依据、阻塞及补证顺序。', '']
    return '\n'.join(lines).encode('utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    report = build(args.evidence_root)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir/'matrix.json').write_bytes(encoded(report))
    (args.output_dir/'matrix.md').write_bytes(markdown(report))
    print(encoded(report['summary']).decode())


PINS = dict(MARKET_PINS)
PINS['data/M6-market-fill-evidence-matrix/matrix.json'] = '8ae5cd55d73cc744d3f958a3eb0f804e6e1137981b2c736d9ad0dcbf33b9b80e'
PINS.update({'M6-full-audit.md': 'b7597d71329335e37aa0c3c7843bef716630f20a7c94ec93817593dea1c5b40f',
 'M6-dated-costs-audit.md': '827a391c94004e80a82f5e5d04b9f5f1aec7c535b82f822e1e4c91fd66debec4',
 'M6-settlement-prices-audit.md': 'c92ea14bf682b961f68e08df03b88025ceba34a0ed2a8b4706115c614aa0831c',
 'M6-notice-execution-audit.md': '78fabc5d773d71f10adfa4aa37dd4e278b080eb05716577e8a4902211ab78a5e',
 'M6-partial-orders-audit.md': '4dfb7bda3c7b6baf84da1cb46a2260f62344da87e299f2b7e5994e6d6cf4244f',
 'M6-multiplier-conversion-audit.md': '699aa8825d97e33b75de2a409558c759110dea724e08b18d2169253e1103d864',
 'M6-intraday-accounting-audit.md': 'e92257359ca1e9a07818a7f6278774824414071ea1d1e6b8aab29378ef4e1c58',
 'M6-intraday-funding-audit.md': 'd8e129b1f36b55eec84399d3c6ac7098eb0ffb33f0bdeefe751f330df7d666f2',
 'data/M6-dated-costs-acceptance.json': '1630e31069040259a8657ff62943b3d57a2461a45c9f3bbe2e809d5f2c5ce083',
 'data/M6-settlement-prices-acceptance.json': '5a31b82e69441e6043e37655bde5839fd0cd7d427c46880595bc79cd79b77e0f',
 'data/M6-notice-execution-acceptance.json': '8d2222ec57fe46a803ab7db37873ad3c1e5f902c8c4f910301419723f45612fc',
 'data/M6-partial-orders-acceptance.json': '60d27b169cff392c570264f2bdf4ab21d50192042bc70d8d1b3d31c5d512fdfe',
 'data/M6-multiplier-conversion-acceptance.json': '7568e36efc74d93949699b2db093da2d4c0fd856af0b32d39669129daefa7f9f',
 'data/M6-intraday-accounting-acceptance.json': '032218dddbc15b9c7999ba9fa43d3f660cf7801dd25f5ccf86f7b99bce513db1',
 'data/M6-intraday-funding-acceptance.json': '1daf8853b6af5db486539ae81bc00685135359239946fc541609e4b5735361ca',
 'data/M6-settlement-prices-acceptance/prices.json': 'b2bdb5c6fba4bf6c3b219dddc5a685091af5e49fa11055c6339d3fd555c5d357',
 'data/M6-historical-notices/notices.json': 'e05867d17b1c461875f97b3c329aaad6a2b1b721483f2b195ae74eb9113d94e6',
 'data/M6-full-20261001/specs/specs.json': '58c69c4772ce09163ebda9d19b41d85b4d5aabd81321570716952e73f6604081',
 'data/M6-full-20261001/BTC-marks-full.json': '31a04786d15a033f58a6f198c77d897d6054fd33c90ac8084eceb7bb97f95ed0',
 'data/M6-full-20261001/ETH-marks-full.json': '111ff27eacc81d570c0fd5f9252b7a5a1a44175d01bfb1b25076a9717e6af7e1'})

if __name__ == '__main__':
    main()
