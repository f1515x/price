"""Reconstruct cost/policy inventory and reject missing rows or false certification."""
import argparse
from pathlib import Path

from build_cost_policy_evidence_matrix import FIELDS, build, markdown, pointer, rate_slice
from contract_specs import digest, encoded
from spec_evidence import _json


def checks_for(matrix, rebuilt):
    rows = matrix['rows']
    windows = {r['window_ref'] for r in rebuilt['rows']}
    expected = {(w, f) for w in windows for f in FIELDS}
    sources = {s['id']: s for s in matrix['sources']}
    rates = {s: [r for r in matrix['observed_settlement_index'] if r['symbol'] == s]
             for s in matrix['assets']}
    return dict(
        rebuild_identical=matrix == rebuilt,
        complete_field_window_grid=len(rows) == 360 and len(windows) == 40
            and {(r['window_ref'], r['field']) for r in rows} == expected,
        nine_fields=set(matrix['fields']) == set(FIELDS) and len(matrix['fields']) == 9,
        all_source_refs_bound=all(r['inventory_source_refs'] and all(s in sources for s in r['inventory_source_refs']) for r in rows),
        no_certification=all(r['certification_status'] == 'NOT_CERTIFIED' and r['certified_coverage_seconds'] == 0
            and r['authentic_effective_window'] is None and not r['actual_account_evidence'] and r['gaps'] for r in rows)
            and all(not s['authenticated'] and s['certified_valid_window'] is None for s in sources.values()),
        observed_rates_complete=len(rates['BTC']) == len(rates['ETH']) == 7395
            and all(not r['authenticated'] and r['exact_settlement_price'] is None
                    and r['account_settlement_ref'] is None and r['schedule_status'] == 'ASSUMED_GRID'
                    for rs in rates.values() for r in rs),
        rate_slices_match=all(r['rate_record_slice'] == rate_slice(rates[r['symbol']],
            r['required_window']['start'], r['required_window']['end_exclusive'])
            for r in rows if r['field'] in ('funding_rate', 'funding_schedule', 'settlement_price')),
        future_unknown=sum(r['target'].startswith('future-') for r in rows) == 90
            and all(r['rate_record_slice'] is None or r['rate_record_slice']['count'] == 0
                    for r in rows if r['target'].startswith('future-')),
        model_variants_retained=len(matrix['historical_model_costs']) == 524
            and all(not s['authenticated'] for s in matrix['historical_model_costs']),
        declarations_and_proxies_separate={'SYNTHETIC_DECLARATION', 'CURRENT_PUBLIC_SNAPSHOT',
            'PUBLIC_RATE_OBSERVATION_ASSUMED_GRID', 'DAILY_MARK_PROXY', 'ARCHIVED_NOTICE_EXCERPT'}
            <= {s['kind'] for s in sources.values()},
        frozen_and_strategy=matrix['frozen_sources_verified'] == 37 and matrix['strategy_status'] == 'NOT_VALIDATED',
    )


def audit(root, directory):
    directory = Path(directory)
    body = (directory/'matrix.json').read_bytes()
    matrix = _json(body)
    rebuilt = build(root)
    checks = checks_for(matrix, rebuilt)
    checks['canonical_bytes'] = body == encoded(rebuilt)
    checks['markdown_matches'] = (directory/'matrix.md').read_bytes() == markdown(rebuilt)
    # Resolve every original JSON pointer independently of the matrix builder.
    checks['source_pointers_resolve'] = all(pointer(_json((Path(root)/s['file']).read_bytes()), s['pointer']) is not None
        for s in matrix['sources'] if s['pointer'] is not None)
    return dict(engineering_status='PASSED' if all(checks.values()) else 'FAILED', strategy_status='NOT_VALIDATED',
                checks=checks, summary=matrix['summary'], matrix_sha256=digest(body),
                audit_code_sha256=digest(Path(__file__).read_bytes()))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root', type=Path, required=True)
    p.add_argument('--matrix-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = audit(args.evidence_root, args.matrix_dir)
    with args.output.open('xb') as target:
        target.write(encoded(result))
    print(encoded(result).decode())
    if result['engineering_status'] != 'PASSED':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
