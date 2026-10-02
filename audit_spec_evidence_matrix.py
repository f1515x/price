"""Recompute and verify the fixed specification inventory, without strategy evaluation."""
import argparse
from pathlib import Path

from build_spec_evidence_matrix import FIELDS, PINS, build, markdown
from contract_specs import digest, encoded
from spec_evidence import _json


def audit(root, matrix_dir):
    root, matrix_dir = Path(root), Path(matrix_dir)
    original = (matrix_dir / "matrix.json").read_bytes()
    matrix = _json(original)
    recomputed = build(root)
    scope = _json((root / "data/M6-evidence-scope.json").read_bytes())
    rows = matrix["rows"]
    complete = True
    for symbol in scope["assets"]:
        targets = [("historical", scope["historical_data"][symbol])]
        targets += [(f"future-{f['index']}", f["test"]) for f in scope["future_folds"]]
        for target, w in targets:
            for field in FIELDS:
                spans = sorted((r["required_window"]["start"], r["required_window"]["end_exclusive"])
                               for r in rows if (r["symbol"], r["target"], r["field"]) == (symbol, target, field))
                complete &= bool(spans) and spans[0][0] == w["start"] and spans[-1][1] == w["end_exclusive"]
                complete &= all(a < b for a, b in spans) and all(a[1] == b[0] for a, b in zip(spans, spans[1:]))
    byte_bindings = True
    for source in matrix["sources"].values():
        body = (root / source["file"]).read_bytes()
        byte_bindings &= digest(body) == source["sha256"]
        bindings = [source["byte_binding"]] if "byte_binding" in source else source["bindings"].values()
        byte_bindings &= all(body[b["start"]:b["end"]] == b["text"].encode("utf-8") for b in bindings)
    checks = dict(
        repeat_build_identical=matrix == recomputed and original == encoded(recomputed),
        markdown_matches=(matrix_dir / "matrix.md").read_bytes() == markdown(recomputed),
        all_asset_field_periods_complete_without_overlap=complete,
        expected_inventory=matrix["summary"] == dict(rows=70, historical_rows=20, future_rows=50,
                                                    certified_coverage_seconds=0, rows_missing_certification=70,
                                                    rows_with_review_conflicts=0, observed_discrepancies=1, notice_events=2),
        raw_hashes_and_exact_byte_bindings=byte_bindings,
        no_certified_values_or_periods=all(r["certified_value"] is None and r["certified_effective_period"] is None
                                         and r["certified_coverage_seconds"] == 0 for r in rows),
        empty_real_review_retained=not matrix["real_review"]["claims"] and not matrix["real_review"]["documents"],
        decimal_step_not_inferred=all(o["values"]["quantity_step"] is None for o in matrix["observations"] if o["symbol"] == "ETH"),
        observed_difference_retained=matrix["issues"][0]["field"] == "min_quantity"
                                    and matrix["issues"][0]["resolution"] == "UNRESOLVED"
                                    and not matrix["issues"][0]["certified_interval_conflict"],
        no_notice_validity_extrapolation=all(s["effective_period_start"] is None and s["effective_period_end"] is None
                                            and not s["authenticated"] for s in matrix["sources"].values()),
        future_still_unknown=all("FUTURE_VALIDITY_UNKNOWN_UNTIL_OBSERVED" in r["gaps"]
                                 for r in rows if r["target"].startswith("future-")),
        frozen_registration_and_37_sources_unchanged=matrix["frozen_sources_verified"] == 37
            and digest((root / "data/M6-restart-registration.json").read_bytes()) == PINS["data/M6-restart-registration.json"],
        strategy_and_execution_not_promoted=matrix["strategy_status"] == "NOT_VALIDATED"
            and not matrix["historical_specs_verified"] and not matrix["used_for_execution_parameters"],
    )
    return dict(engineering_status="PASSED" if all(checks.values()) else "FAILED",
                strategy_status="NOT_VALIDATED", checks=checks, summary=matrix["summary"],
                matrix_sha256=digest(original), markdown_sha256=digest((matrix_dir / "matrix.md").read_bytes()),
                audit_code_sha256=digest(Path(__file__).read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--matrix-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = audit(args.evidence_root, args.matrix_dir)
    with args.output.open("xb") as target:
        target.write(encoded(result))
    print(encoded(result).decode("utf-8"))
    if result["engineering_status"] != "PASSED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
