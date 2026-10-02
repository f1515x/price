"""Rebuild market/fill inventory and check scope, coverage and evidence boundaries."""
import argparse
from pathlib import Path

from build_market_fill_evidence_matrix import build, markdown
from contract_specs import digest, encoded
from spec_evidence import _json


def audit(root, directory):
    directory = Path(directory)
    original = (directory/'matrix.json').read_bytes()
    matrix = _json(original)
    rebuilt = build(root)
    rows = matrix['rows']
    model = [r for r in rows if r['target']=='model-execution']
    historical = [r for r in rows if r['target']=='historical-total']
    notices = [r for r in rows if r['target'].startswith('notice-')]
    future = [r for r in rows if r['target'].startswith('future-')]
    checks = dict(
        rebuild_identical=matrix==rebuilt and original==encoded(rebuilt),
        markdown_matches=(directory/'matrix.md').read_bytes()==markdown(rebuilt),
        inventory=matrix['summary']==dict(rows=40, daily_archives=12, minute_archives=3,
            unique_daily_bars=dict(BTC=2466, ETH=2466), unique_minute_bars=dict(BTC=2880,ETH=2880),
            model_orders=84196, model_trades=2462, certified_fill_coverage_seconds=0),
        all_order_trade_records_preserved=sum(r['model_order_records'] for r in model)==84196
            and sum(r['model_trade_records'] for r in model)==2462
            and len(matrix['model_trade_time_index'])==2462,
        historical_daily_complete=len(historical)==2 and all(r['daily']['observed_bars']==2465
            and not r['daily']['missing_ranges'] for r in historical),
        historical_minutes_partial=all(r['minute']['observed_bars']==2880
            and r['minute']['missing_ranges'] for r in historical),
        notice_minute_gap_retained=len(notices)==4 and all(r['minute']['observed_bars']==0
            and 'EXACT_SECOND_OR_FINER_PATH_MISSING' in r['gaps'] for r in notices),
        future_unknown=len(future)==10 and all(r['daily']['observed_bars']==0
            and r['minute']['observed_bars']==0 and 'FUTURE_EXECUTION_TIMES_UNKNOWN' in r['gaps'] for r in future),
        no_actual_fill_credit=all(not r['actual_fill_evidence'] and r['certified_fill_coverage_seconds']==0
            and r['certification_status']=='NOT_CERTIFIED' for r in rows)
            and all(not t['actual_fill_verified'] for t in matrix['model_trade_time_index']),
        no_path_inferred=all(not r[k]['exact_path_verified'] for r in rows for k in ('daily','minute')),
        declarations_excluded=not matrix['declared_replays']['actual_fill_verified']
            and matrix['declared_replays']['evidence_credit_seconds']==0,
        frozen_sources_and_strategy=matrix['frozen_sources_verified']==37 and matrix['strategy_status']=='NOT_VALIDATED',
    )
    return dict(engineering_status='PASSED' if all(checks.values()) else 'FAILED',
                strategy_status='NOT_VALIDATED', checks=checks, summary=matrix['summary'],
                matrix_sha256=digest(original), audit_code_sha256=digest(Path(__file__).read_bytes()))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root', type=Path, required=True)
    p.add_argument('--matrix-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result=audit(args.evidence_root,args.matrix_dir)
    with args.output.open('xb') as f:
        f.write(encoded(result))
    print(encoded(result).decode())
    if result['engineering_status']!='PASSED':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
