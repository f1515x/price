"""Resolve reviewed field assertions into explicit offline scenario periods."""
import argparse
from dataclasses import replace
from decimal import Decimal, DecimalException
import json
import math
from pathlib import Path

from contract_specs import digest, encoded
from dated_specifications import FIELDS
from execution_history import validate_periods, evidence
from history import DAY
from portfolio_simulation import simulate
from spec_evidence import _json
from spec_field_review import load as review

VERSION = "reviewed-specification-scenario-v1"


def load(path, expected_sha256, base, symbols, start, end, *, allow_reviewed_scenario=False):
    """Require complete, nonconflicting joint fields; never authenticate claims."""
    if allow_reviewed_scenario is not True:
        raise ValueError("Explicit allow_reviewed_scenario=True required")
    if any(type(t) is not int or t < 0 or t % DAY for t in (start, end)) or start >= end:
        raise ValueError("Increasing UTC daily boundaries required")
    symbols = list(symbols)
    reviewed = review(path, expected_sha256, symbols, start, end)
    for asset in reviewed["assets"]:
        for field, coverage in asset["fields"].items():
            if coverage["missing_intervals"] or coverage["conflicting_intervals"]:
                raise ValueError(f"Incomplete or conflicting reviewed field: {asset['symbol']} {field}")
    periods, provenance = {}, {}
    for symbol in symbols:
        claims = [c for c in reviewed["claims"] if c["symbol"] == symbol
                  and c["eligible_for_review_coverage"] and c["start"] < end and c["end"] > start]
        boundaries = sorted({start, end, *(max(start, c["start"]) for c in claims),
                             *(min(end, c["end"]) for c in claims)})
        if any(t % DAY for t in boundaries):
            raise ValueError("Intraday review boundaries unsupported by daily simulation")
        periods[symbol], provenance[symbol] = [], []
        for a, b in zip(boundaries, boundaries[1:]):
            values, refs = {}, {}
            for field in FIELDS:
                active = [c for c in claims if c["field"] == field and c["start"] <= a and c["end"] >= b]
                unique = {Decimal(c["value"]) for c in active}
                if len(unique) != 1:
                    raise ValueError("Joint field coverage missing or conflicting")
                values[field] = unique.pop()
                refs[field] = sorted(c["id"] for c in active)
            try:
                if any(values[k] % values["quantity_step"] for k in ("min_quantity", "max_quantity")):
                    raise ValueError("Quantity bounds must align with explicit step")
                floats = {k: float(v) for k, v in values.items()}
                if any(not math.isfinite(floats[k]) or floats[k] <= 0
                       or Decimal(str(floats[k])) != v for k, v in values.items()):
                    raise ValueError("Specification cannot be represented by simulation precision")
            except DecimalException as exc:
                raise ValueError("Unsupported decimal precision") from exc
            config = replace(base, **floats)
            periods[symbol].append(dict(start=a, end=b, config=config,
                source="review assertions: " + ", ".join(sorted({i for ids in refs.values() for i in ids})),
                verified_fields=[]))
            provenance[symbol].append(dict(start=a, end=b, claim_ids_by_field=refs,
                                           specification={k: str(v) for k, v in values.items()}))
        validate_periods(periods[symbol], start, end)
    # Recheck documents and ledger before exposing executable parameters.
    if review(path, expected_sha256, symbols, start, end) != reviewed:
        raise ValueError("Evidence changed during period resolution")
    return periods, dict(version=VERSION, scope="REVIEWED_SCENARIO_ONLY", review=reviewed,
        execution_periods={s: evidence(p) for s, p in periods.items()}, provenance=provenance,
        historical_specs_verified=False, exact_costs_verified=False,
        used_for_execution_parameters=False, acceptance_status="NOT_VALIDATED",
        source_sha256={name: digest(Path(__file__).with_name(name).read_bytes()) for name in
            ("reviewed_specifications.py", "spec_field_review.py", "dated_specifications.py",
             "execution_history.py", "portfolio_simulation.py", "trade_simulation.py",
             "contract_specs.py", "spec_evidence.py", "history.py", "kline.py",
             "indicators.py", "funding_history.py")})


def simulate_review(asset_rows, candidates, config, groups, path, expected_sha256,
                    structures=None, *, funding=None, allow_reviewed_scenario=False):
    rows = {s: list(r) for s, r in asset_rows.items()}
    if not rows or any(not r for r in rows.values()):
        raise ValueError("Nonempty bars required for every asset")
    first = next(iter(rows.values()))
    start, end = first[0]["timestamp"], first[-1]["timestamp"] + DAY
    periods, report = load(path, expected_sha256, config.execution, list(rows), start, end,
                          allow_reviewed_scenario=allow_reviewed_scenario)
    result = simulate(rows, candidates, config, groups, structures,
                      funding=funding, execution_periods=periods)
    if review(path, expected_sha256, list(rows), start, end) != report["review"]:
        raise ValueError("Evidence changed during simulation")
    for trade in result["trades"]:
        period = next(p for p in report["provenance"][trade["symbol"]]
                      if p["start"] <= trade["entry_time"] < p["end"])
        trade["entry_specification_review"] = dict(period, ledger_sha256=expected_sha256)
    report["used_for_execution_parameters"] = True
    result["reviewed_specification_evidence"] = report
    return result


def main():
    from trade_simulation import Config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--base-config", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--allow-reviewed-scenario", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    _, report = load(args.ledger, args.expected_sha256,
        Config(**_json(Path(args.base_config).read_bytes())), args.symbols, args.start, args.end,
        allow_reviewed_scenario=args.allow_reviewed_scenario)
    with Path(args.output).open("xb") as target:
        target.write(encoded(report))
    print(json.dumps(dict(status=report["acceptance_status"], scope=report["scope"])))


if __name__ == "__main__":
    main()
