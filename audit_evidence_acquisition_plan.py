"""Check exact gap coverage, dependency order, source binding and no certification."""
import argparse
from pathlib import Path

from build_evidence_acquisition_plan import build, markdown, PINS
from build_cost_policy_evidence_matrix import pointer
from contract_specs import digest, encoded
from spec_evidence import _json


def checks_for(plan, expected):
    tasks = {t['id']: t for t in plan['tasks']}
    order = plan['order']
    positions = {id: i for i, id in enumerate(order)}
    refs = [(e['source_file'], e['source_pointer']) for e in plan['entries']]
    expected_refs = {(e['source_file'], e['source_pointer']) for e in expected['entries']}
    return dict(
        exact_rebuild=plan == expected,
        every_gap_and_issue_once=len(refs) == len(set(refs)) == 791 and set(refs) == expected_refs,
        all_tasks_bound=all(e['task_ref'] in tasks for e in plan['entries']),
        executable_requirements=all(all(t[k] for k in ('acquisition_routes', 'feasibility', 'feasibility_basis',
            'blockers', 'authentication_requirements', 'next_action', 'owner_role')) for t in tasks.values()),
        dependency_order=len(order) == len(tasks) == len(positions) and set(order) == set(tasks)
            and all(d in positions and t['id'] in positions and positions[d] < positions[t['id']]
                    for t in tasks.values() for d in t['dependencies']),
        no_evidence_upgrade=all(e['evidence_status'] == 'UNSATISFIED' and e['certified_coverage_seconds'] == 0
                               for e in plan['entries'])
            and all(t['retrieval_status'] == 'NOT_ATTEMPTED' and t['evidence_status'] == 'UNSATISFIED'
                    for t in tasks.values()) and plan['summary']['evidence_acquired'] == 0,
        certification_unchanged=plan['strategy_status'] == 'NOT_VALIDATED'
            and plan['certification_status'] == 'NOT_CERTIFIED' and plan['frozen_sources_verified'] == 37,
        pinned_inputs=plan['input_sha256'] == PINS,
        future_waits=all(e['task_ref'] == 'A10' for e in plan['entries'] if e['gap'].startswith('FUTURE_')),
        unresolved_difference_retained=sum(e['task_ref'] == 'A02' for e in plan['entries']) == 1,
    )


def audit(root, directory):
    root, directory = Path(root), Path(directory)
    body = (directory/'plan.json').read_bytes()
    plan = _json(body)
    expected = build(root)
    checks = checks_for(plan, expected)
    originals = {name: _json((root/name).read_bytes()) for name in PINS}
    checks['original_pointers_resolve'] = all(
        pointer(originals[e['source_file']], e['source_pointer']) == e['gap']
        if e['task_ref'] != 'A02' else
        pointer(originals[e['source_file']], e['source_pointer'])['kind'] == e['gap']
        for e in plan['entries'])
    checks['canonical_bytes'] = body == encoded(expected)
    checks['readable_plan_matches'] = (directory/'plan.md').read_bytes() == markdown(expected)
    return dict(engineering_status='PASSED' if all(checks.values()) else 'FAILED',
                strategy_status='NOT_VALIDATED', checks=checks, summary=plan['summary'],
                plan_sha256=digest(body), audit_code_sha256=digest(Path(__file__).read_bytes()))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-root', type=Path, required=True)
    p.add_argument('--plan-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = audit(args.evidence_root, args.plan_dir)
    with args.output.open('xb') as f:
        f.write(encoded(result))
    print(encoded(result).decode())
    if result['engineering_status'] != 'PASSED':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
