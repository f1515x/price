"""Bind every pinned M6 evidence gap to an acquisition and acceptance workflow."""
import argparse
from copy import deepcopy
from pathlib import Path

from contract_specs import digest, encoded
from spec_evidence import _json

PINS = {
    'data/M6-spec-evidence-matrix/matrix.json': 'c2f39e24f247992893aa4a0de6be223c57307cabd72d8f6b9c9b2fcb272acc1c',
    'data/M6-market-fill-evidence-matrix/matrix.json': '8ae5cd55d73cc744d3f958a3eb0f804e6e1137981b2c736d9ad0dcbf33b9b80e',
    'data/M6-cost-policy-evidence-matrix/matrix.json': '7cf6c3b8e9ddc75e756acc3e13eed7cf5ab2e70f07a3a2a2cd499badb6b884b9',
    'data/M6-restart-registration.json': 'b2bc4ddbf455c86dd53911d3814c27bd61026d89104fe58fffe15a4b005ea6cd',
}
DOCS = 'https://www.gate.com/docs/developers/apiv4/en/futures/'


def task(id, title, dependencies, routes, feasibility, blockers, acceptance, action):
    return dict(id=id, title=title, dependencies=dependencies, acquisition_routes=routes,
                feasibility=feasibility, feasibility_basis='Planning judgement; historical retrieval not probed in this task.',
                blockers=blockers, authentication_requirements=acceptance, next_action=action,
                owner_role='Codex public-evidence preparation; account owner for private exports; issuer for historical confirmation',
                retrieval_status='NOT_ATTEMPTED', evidence_status='UNSATISFIED')


TASKS = [
    task('A01', '历史规格、完整公告与字段语义', [],
         ['Gate official announcement originals and attachments; archive each full page with URL and retrieval time.',
          'GET /futures/usdt/contracts/{BTC_USDT|ETH_USDT}: current snapshot only.',
          'If historical baseline or superseded fields are absent, request issuer historical records via owner support ticket.'],
         'PUBLIC_PARTIAL_HISTORY_UNCONFIRMED',
         ['Historical baseline and all effective changes not yet established; snapshots cannot backfill validity.',
          'Decimal quantity step must be explicit; min size is not a step.'],
         ['Issuer provenance, original bytes/hash, publication time and effective UTC intervals for all five fields.',
          'Partition each asset/window; zero unexplained gaps and conflicts; independent field review.'],
         'Inventory full originals for existing notice refs first; establish pre-change baseline; record unavailable intervals.'),
    task('A02', 'ETH 最小张数差异处置', ['A01'],
         ['Compare both archived ETH observations with complete request context and issuer change history.'],
         'ISSUER_CONFIRMATION_REQUIRED', ['Observed values differ; no proven effective change timestamp.'],
         ['Explain request/contract context and each applicable effective interval with issuer evidence; retain both originals.',
          'Absent proof, retain UNRESOLVED; do not invent an interval boundary.'],
         'Prepare the two observation refs and contexts for review; seek issuer explanation if public originals are insufficient.'),
    task('A03', '日线与分钟覆盖补采', [],
         ['GET /futures/usdt/candlesticks with contract, from, to, interval; batch at most 2000 points.',
          'Existing history.py and intraday_history.py collectors; use missing_ranges from each source row.'],
         'PUBLIC_RETRIEVAL_CANDIDATE_RETENTION_UNCONFIRMED',
         ['Old minute retention and full-period retrieval are unconfirmed; future bars are unavailable.'],
         ['Archive request/response provenance and hashes; verify closed bars, OHLCV quality, continuity and exact half-open coverage.',
          'Deduplicate overlapping target windows; minute bars establish neither second path nor account fills.'],
         'Dry-plan requests only for historical missing_ranges; prioritize notice windows, then remaining research execution windows.'),
    task('A04', '精确执行路径与滑点参照价', ['A03', 'A05'],
         ['Official timestamped public trade/quote archives or issuer historical tick/book exports.',
          'For future observations, persist exchange trade/book events with exchange timestamp and local receipt timestamp.'],
         'HISTORICAL_ARCHIVE_UNCONFIRMED_FUTURE_CAPTURE_REQUIRED',
         ['Historical second/tick book reconstruction may be impossible; OHLC bars omit within-bar ordering.'],
         ['Document precision, clock and sequence ordering at each execution/notice second; reconcile reference bid/ask to actual fill.',
          'Use contemporaneous executable quotes and a fixed slippage definition; never substitute bar close or synthetic fills.'],
         'Enumerate required notice seconds and model execution refs; test archive availability without asserting complete history.'),
    task('A05', '真实订单、成交片段和撤单回执', [],
         ['Owner read-only export: GET /futures/usdt/my_trades; older records via /my_trades_timerange.',
          'Owner order exports and timestamped submit/accept/cancel receipts, including original event logs.'],
         'OWNER_EXPORT_REQUIRED_EXISTENCE_UNCONFIRMED',
         ['No actual account evidence provided; simulated orders have no exchange order IDs.',
          'If this research was never executed, matching historical account fills do not exist.'],
         ['Bind contract, account alias, order/fill IDs, UTC time, side, quantity, price, remaining quantity and cancellation status.',
          'Retain raw exports privately and hash/redacted audit indexes; reconcile duplicates, missing fragments and sequence.'],
         'Owner establishes whether matching real orders exist; export available records, otherwise explicitly mark unavailable.'),
    task('A06', '真实逐笔手续费与返佣', ['A05'],
         ['Owner trade fee/role records, historical fee tier/discount/rebate statements and account_book exports.'],
         'OWNER_EXPORT_REQUIRED', ['Historical account tier, discounts, rebates and complete bill links missing.'],
         ['Reconcile each fill to charged fee, currency, maker/taker role and applicable fee tier plus rebates/discounts.',
          'Current public fee snapshots cannot certify historical account charges.'],
         'Join real fill IDs to fee bills; list unmatched records and request missing historical statements.'),
    task('A07', '资金费计划、费率与结算价', ['A01'],
         ['GET /futures/usdt/funding_rate plus archived raw pages; issuer schedule change originals.',
          'Issuer exact settlement mark records; owner account_book funding cashflows and position-at-settlement statements.'],
         'PUBLIC_PARTIAL_PLUS_OWNER_AND_ISSUER_RECORDS',
         ['Historical effective schedules and exact marks not established; public rate authenticity/account linkage pending.'],
         ['For every applicable settlement: asset, exact time, schedule effective interval, rate, mark and position basis.',
          'Separate report time from assumed grid time; reconcile account funding cashflow; daily mark bounds remain proxies.'],
         'Review existing raw rate pages first; obtain actual schedule changes and precise settlement/account references.'),
    task('A08', '公告执行、撤单及部分成交政策', ['A01', 'A05'],
         ['Issuer effective-dated execution policies and notice originals; owner actual order event/fragment logs.'],
         'ISSUER_POLICY_PLUS_OWNER_LOGS_REQUIRED',
         ['Same-second priority, order remainder handling and minimum-fill semantics are not authenticated.'],
         ['Establish policy validity, notice cutoff and event ordering; validate cancel/remainder and partial-fill semantics on actual events.',
          'Submission minimum, quantity step and minimum fill must be distinguished; synthetic fragments provide no certification.'],
         'List unanswered policy questions by notice and field; associate actual receipt evidence when available.'),
    task('A09', '持仓乘数换算与成本基础政策', ['A01', 'A05'],
         ['Issuer real multiplier-change notices and position/cost-basis conversion policy; owner before/after statements.'],
         'REAL_EVENT_AND_ISSUER_POLICY_REQUIRED',
         ['No authenticated real multiplier-change event; exposure-conserving arithmetic is a model declaration.'],
         ['Establish real event time/validity, multiplier, rounding, residual treatment, position and cost-basis cashflows.',
          'Without a relevant event, retain evidence requirement; do not map 1970 fixtures into historical validity.'],
         'Determine applicability from official change history; obtain actual policy and statements or record unavailable evidence.'),
    task('A10', '未来证据与冻结约束', [],
         ['Existing daily collection plus prospective public snapshots and owner execution/settlement exports when events occur.',
          'Frozen registration and 37 source hashes; plan.md 4.5 certification-integration design before runner changes.'],
         'WAIT_FOR_FUTURE_OBSERVATIONS', ['Future validity, executions and settlements cannot be known before occurrence.'],
         ['Keep registered windows unchanged; timestamp provenance; no backfilled fabricated events or premature return evaluation.',
          'Authentication integrations affecting frozen code/parameters require version and preregistration handling.'],
         'Continue existing collection; design missing prospective capture under 4.5; do not evaluate future strategy returns.'),
    task('A11', '逐笔认证、覆盖复核与现金流对账', ['A02', 'A04', 'A06', 'A07', 'A08', 'A09', 'A10'],
         ['Join authenticated spec intervals, real fills, cost bills, precise marks and effective execution policies.'],
         'BLOCKED_BY_UNSATISFIED_UPSTREAM_EVIDENCE', ['All upstream required evidence and applicability checks remain open.'],
         ['Zero unexplained coverage/conflict gaps; per-fill/settlement reconciliation of fees, funding, realized PnL and exposure.',
          'Unavailable evidence remains UNSATISFIED; engineering completion does not upgrade strategy/execution certification.'],
         'Produce coverage and reconciliation report after upstream acquisition; list every refusal and unmatched item.'),
]
# Account exports are independent; quote-to-fill reconciliation needs them first.
TASKS.sort(key=lambda t: ['A01', 'A02', 'A03', 'A05', 'A04', 'A06', 'A07', 'A08', 'A09', 'A10', 'A11'].index(t['id']))

GAP_TASK = {
    'ISSUER_FIELD_SEMANTICS_AND_EFFECTIVE_PERIOD_NOT_AUTHENTICATED': 'A01',
    'FULL_EFFECTIVE_PERIOD_EVIDENCE_MISSING': 'A01',
    'EXPLICIT_DECIMAL_QUANTITY_STEP_MISSING': 'A01',
    'FUTURE_VALIDITY_UNKNOWN_UNTIL_OBSERVED': 'A10',
    'ACTUAL_ORDER_IDS_ACCEPT_CANCEL_PARTIAL_FILL_LOGS_MISSING': 'A05',
    'PUBLIC_OHLCV_IS_NOT_ACCOUNT_EXECUTION_OR_INTRABAR_PATH': 'A04',
    'MINUTE_COVERAGE_INCOMPLETE': 'A03',
    'DAILY_COVERAGE_INCOMPLETE': 'A03',
    'EXACT_SECOND_OR_FINER_PATH_MISSING': 'A04',
    'FUTURE_EXECUTION_TIMES_UNKNOWN': 'A10',
    'ACCOUNT_FEE_TIER_MAKER_TAKER_REBATES_AND_FILL_BILLS_MISSING': 'A06',
    'TIMESTAMPED_REFERENCE_QUOTES_AND_ACTUAL_FILLS_MISSING': 'A04',
    'HISTORICAL_SCHEDULE_EFFECTIVE_INTERVALS_AND_ACCOUNT_SETTLEMENTS_MISSING': 'A07',
    'OBSERVED_RATES_NOT_AUTHENTICATED_OR_LINKED_TO_ACCOUNT_SETTLEMENTS': 'A07',
    'EXACT_SETTLEMENT_MARK_PRICE_AND_ACCOUNT_CASHFLOW_MISSING': 'A07',
    'NOTICE_EXECUTION_POLICY_AND_FULL_VALIDITY_INTERVALS_MISSING': 'A08',
    'EXCHANGE_CANCEL_ACCEPTANCE_PRIORITY_AND_REMAINDER_POLICY_MISSING': 'A08',
    'ACTUAL_FRAGMENTS_QUEUE_AND_MINIMUM_FILL_POLICY_MISSING': 'A08',
    'REAL_MULTIPLIER_CHANGE_POSITION_AND_COST_BASIS_POLICY_MISSING': 'A09',
    'FUTURE_EXECUTION_AND_SETTLEMENT_TIMES_UNKNOWN': 'A10',
}


def build(root):
    root = Path(root)
    loaded = {}
    for name, sha in PINS.items():
        body = (root/name).read_bytes()
        if digest(body) != sha:
            raise ValueError('Input checksum mismatch: ' + name)
        loaded[name] = _json(body)
    frozen = loaded['data/M6-restart-registration.json']['source_sha256']
    if len(frozen) != 37 or any(digest((root.parent/'source'/name).read_bytes()) != sha for name, sha in frozen.items()):
        raise ValueError('Frozen source checksum mismatch')
    entries = []
    for name, matrix in loaded.items():
        if 'rows' not in matrix:
            continue
        for index, row in enumerate(matrix['rows']):
            for gap_index, gap in enumerate(row['gaps']):
                entries.append(dict(id=f'G{len(entries):04d}', source_file=name,
                    source_pointer=f'/rows/{index}/gaps/{gap_index}', source_row_id=row['id'],
                    symbol=row['symbol'], target=row['target'], field=row.get('field', 'market_and_fills'),
                    required_window=deepcopy(row['required_window']), gap=gap, task_ref=GAP_TASK[gap],
                    evidence_status='UNSATISFIED', certified_coverage_seconds=0))
        for index, issue in enumerate(matrix.get('issues', [])):
            entries.append(dict(id=f'G{len(entries):04d}', source_file=name, source_pointer=f'/issues/{index}',
                source_row_id=issue['id'], symbol=issue['symbol'], target='UNPROVEN_EFFECTIVE_PERIOD',
                field=issue['field'], required_window=None, gap=issue['kind'], task_ref='A02',
                evidence_status='UNSATISFIED', certified_coverage_seconds=0))
    return dict(version='m6-evidence-acquisition-plan-v1', owner='Codex', date='2026-10-02',
                date_timezone='America/La_Paz', task='plan.md 4.2 fifth item',
                strategy_status='NOT_VALIDATED', certification_status='NOT_CERTIFIED',
                input_sha256=PINS, frozen_sources_verified=37,
                route_documentation=dict(url=DOCS, checked_on='2026-10-02',
                    limitation='Documentation verifies candidate routes only, not historical availability or issuer authenticity.'),
                tasks=deepcopy(TASKS), entries=entries,
                order=[t['id'] for t in TASKS],
                order_policy='Topological plan, not a stop-the-world sequence. Public and owner exports can run concurrently; A10 waits for events.',
                account_evidence_policy='Historical simulated trades cannot be certified by unrelated real fills or by placing new orders.',
                unavailable_policy='Record attempted route, period, response/export absence, reason and follow-up; retain UNSATISFIED and refuse certification.',
                summary=dict(source_rows=sum(len(m.get('rows', [])) for m in loaded.values()),
                             gap_occurrences=sum(len(r['gaps']) for m in loaded.values() for r in m.get('rows', [])),
                             unresolved_issues=sum(len(m.get('issues', [])) for m in loaded.values()),
                             entries=len(entries), acquisition_tasks=len(TASKS), evidence_acquired=0))


def markdown(plan):
    lines = ['# M6 证据缺口获取与补证顺序', '',
             '日期：2026-10-02（America/La_Paz）；负责人：Codex。仅完成获取方案；全部证据仍未满足。', '',
             f"覆盖 {plan['summary']['source_rows']} 行、{plan['summary']['gap_occurrences']} 条缺口及 1 项未解决差异。", '',
             '顺序为依赖拓扑顺序，公开采集与账户导出可并行；未来事项等待实际发生。',
             '每条缺口的原文件、JSON 指针、资产、字段和半开目标窗口见 plan.json 的 entries。', '',
             f"候选接口核对：[Gate 官方文档]({DOCS})。历史可得性未探测，不承诺可补齐。", '']
    for t in plan['tasks']:
        lines += [f"## {t['id']} {t['title']}", '', f"依赖：{', '.join(t['dependencies']) or '无'}；可行性：{t['feasibility']}。", '',
                  '获取路径：', ''] + ['- '+s for s in t['acquisition_routes']]
        lines += ['', '认证要求：', ''] + ['- '+s for s in t['authentication_requirements']]
        lines += ['', '阻塞项：', ''] + ['- '+s for s in t['blockers']]
        lines += ['', '下一步：'+t['next_action'], '',
                  '关联未满足项：'+str(sum(e['task_ref'] == t['id'] for e in plan['entries'])), '']
    lines += ['## 无法获取时的处理', '', plan['unavailable_policy'], '', plan['account_evidence_policy'], '',
              '本次不调用私人账户接口、不发送支持请求、不下单，不开展未来收益评估。', '']
    return '\n'.join(lines).encode('utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    plan = build(args.evidence_root)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir/'plan.json').write_bytes(encoded(plan))
    (args.output_dir/'plan.md').write_bytes(markdown(plan))
    print(plan['summary'])


if __name__ == '__main__':
    main()
