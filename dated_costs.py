"""Pinned daily fee/slippage scenarios; no certification of realized costs."""
import argparse
from dataclasses import replace
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from contract_specs import digest, encoded
from dated_specifications import _keys, load as load_specs
from execution_history import at_time, validate_periods
from history import DAY
from kline import normalize_symbol
from portfolio_simulation import simulate
from spec_evidence import _json

VERSION = "dated-cost-scenario-v1"
FIELDS = ("fee_rate", "slippage")


def load(path, expected_sha256, base, symbols, start, end, *, allow_declared_scenario=False):
    if allow_declared_scenario is not True:
        raise ValueError("Explicit allow_declared_scenario=True required")
    if any(type(t) is not int or t < 0 or t % DAY for t in (start, end)) or start >= end:
        raise ValueError("Increasing UTC daily boundaries required")
    symbols = list(symbols)
    if not symbols or any(normalize_symbol(s) != s for s in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError("Unique canonical symbols required")
    path = Path(path)
    body = path.read_bytes()
    if digest(body) != expected_sha256:
        raise ValueError("Cost manifest differs from reviewed SHA-256")
    manifest = _json(body)
    _keys(manifest, ("version", "scope", "sources", "assets"))
    if manifest["version"] != VERSION or manifest["scope"] != "DECLARED_SCENARIO_ONLY":
        raise ValueError("Unsupported cost scope")
    sources = manifest["sources"]
    if not isinstance(sources, dict) or not sources:
        raise ValueError("Source documents required")
    root = path.parent.resolve()
    for name, source in sources.items():
        _keys(source, ("file", "sha256", "description"))
        if not isinstance(name, str) or not name.strip() or any(
                not isinstance(v, str) or not v.strip() for v in source.values()):
            raise ValueError("Invalid source declaration")
        relative = Path(source["file"])
        if relative.is_absolute() or relative.drive or ".." in relative.parts or ":" in source["file"]:
            raise ValueError("Unsafe cost source path")
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or digest(target.read_bytes()) != source["sha256"]:
            raise ValueError("Cost source path or hash mismatch")
    assets = manifest["assets"]
    if not isinstance(assets, dict) or set(assets) != set(symbols):
        raise ValueError("Cost manifest must cover exactly requested assets")
    periods, used = {}, set()
    for symbol in symbols:
        if not isinstance(assets[symbol], list) or not assets[symbol]:
            raise ValueError("Nonempty cost periods required")
        periods[symbol] = []
        for entry in assets[symbol]:
            _keys(entry, ("start", "end", "costs", "sources"))
            if any(type(entry[k]) is not int or entry[k] < 0 or entry[k] % DAY for k in ("start", "end")):
                raise ValueError("Intraday costs unsupported by daily simulation")
            _keys(entry["costs"], FIELDS)
            values = {}
            try:
                for key, value in entry["costs"].items():
                    if not isinstance(value, str):
                        raise ValueError("Costs must be decimal strings")
                    number = Decimal(value)
                    if not number.is_finite() or not 0 <= number < 1:
                        raise ValueError("Cost fractions must be in [0, 1)")
                    converted = float(number)
                    if (number != 0 and converted == 0) or converted >= 1:
                        raise ValueError("Cost fraction exceeds execution precision")
                    values[key] = converted
            except InvalidOperation as exc:
                raise ValueError("Invalid decimal cost") from exc
            refs = entry["sources"]
            if (not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in sources for r in refs)
                    or len(set(refs)) != len(refs)):
                raise ValueError("Each cost period needs unique known sources")
            used.update(refs)
            periods[symbol].append(dict(start=entry["start"], end=entry["end"],
                                        config=replace(base, **values),
                                        source="declared costs: " + ", ".join(refs), verified_fields=[]))
        validate_periods(periods[symbol], start, end)
    if used != set(sources):
        raise ValueError("Unreferenced cost sources")
    return periods, dict(version=VERSION, manifest_sha256=expected_sha256, sources=sources,
                         scope=manifest["scope"], required_window=dict(start=start, end=end, end_exclusive=True),
                         exact_costs_verified=False, historical_specs_verified=False,
                         acceptance_status="NOT_VALIDATED")


def simulate_manifest(asset_rows, candidates, config, groups, path, expected_sha256,
                      structures=None, *, funding=None, specification_path=None,
                      specification_sha256=None, allow_declared_scenario=False):
    if (specification_path is None) != (specification_sha256 is None):
        raise ValueError("Specification path and reviewed hash required together")
    rows = {s: list(r) for s, r in asset_rows.items()}
    if not rows or any(not r for r in rows.values()):
        raise ValueError("Nonempty bars required for every asset")
    first = next(iter(rows.values()))
    start, end = first[0]["timestamp"], first[-1]["timestamp"] + DAY
    periods, report = load(path, expected_sha256, config.execution, rows, start, end,
                           allow_declared_scenario=allow_declared_scenario)
    spec_report = None
    if specification_path is not None:
        specs, spec_report = load_specs(specification_path, specification_sha256, config.execution,
                                       rows, start, end, allow_declared_scenario=allow_declared_scenario)
        combined = {}
        for symbol in rows:
            boundaries = sorted({start, end} | {p[k] for group in (periods[symbol], specs[symbol])
                                                for p in group for k in ("start", "end") if start < p[k] < end})
            combined[symbol] = []
            for left, right in zip(boundaries, boundaries[1:]):
                costs = at_time(periods[symbol], left)
                base = at_time(specs[symbol], left)
                combined[symbol].append(dict(start=left, end=right,
                    config=replace(base, **{k: getattr(costs, k) for k in FIELDS}),
                    source="declared cost and specification manifests", verified_fields=[]))
        periods = combined
    result = simulate(rows, candidates, config, groups, structures,
                      funding=funding, execution_periods=periods)
    for trade in result["trades"]:
        # Exit timestamps label daily bar ends; the engine uses that bar's config.
        entry = at_time(periods[trade["symbol"]], trade["entry_time"])
        exit_day = trade["exit_time"] - DAY
        exit_config = at_time(periods[trade["symbol"]], exit_day)
        trade["cost_application"] = dict(entry_day=trade["entry_time"], exit_day=exit_day,
            entry_fee_rate=entry.fee_rate, exit_fee_rate=exit_config.fee_rate,
            entry_slippage=entry.slippage, exit_slippage=exit_config.slippage)
    report.update(used_for_execution_parameters=True,
        timestamp_policy="entry at daily open; exit uses exiting bar day, timestamp labels bar end",
        risk_policy="fill-time cost estimate; future cost changes do not resize existing positions",
        funding_policy=result["funding_model"])
    result["dated_cost_evidence"] = report
    result["dated_specification_evidence"] = spec_report
    if spec_report is not None:
        spec_report["used_for_execution_parameters"] = True
    result["dated_cost_code_sha256"] = {name: digest(Path(__file__).with_name(name).read_bytes())
        for name in ("dated_costs.py", "dated_specifications.py", "execution_history.py",
                     "portfolio_simulation.py", "trade_simulation.py", "contract_specs.py",
                     "spec_evidence.py", "history.py", "indicators.py", "funding_history.py", "kline.py")}
    return result


def main():
    from trade_simulation import Config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--base-config", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--allow-declared-scenario", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    _, report = load(args.manifest, args.expected_sha256, Config(**_json(Path(args.base_config).read_bytes())),
                     args.symbols, args.start, args.end, allow_declared_scenario=args.allow_declared_scenario)
    with Path(args.output).open("xb") as target:
        target.write(encoded(report))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
