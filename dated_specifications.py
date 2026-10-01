"""Pinned declared specification periods for offline daily scenario simulation."""
import argparse
from dataclasses import replace
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from contract_specs import digest, encoded
from execution_history import validate_periods
from history import DAY
from kline import normalize_symbol
from portfolio_simulation import simulate
from spec_evidence import _json

VERSION = "dated-specification-scenario-v1"
FIELDS = ("multiplier", "quantity_step", "min_quantity", "max_quantity", "price_tick")


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("Unexpected or missing manifest fields")


def load(path, expected_sha256, base, symbols, start, end, *, allow_declared_scenario=False):
    """Resolve declarations only; hashes cannot certify historical validity."""
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
        raise ValueError("Manifest differs from reviewed SHA-256")
    manifest = _json(body)
    _keys(manifest, ("version", "scope", "sources", "assets"))
    if manifest["version"] != VERSION or manifest["scope"] != "DECLARED_SCENARIO_ONLY":
        raise ValueError("Unsupported specification scope")
    sources = manifest["sources"]
    if not isinstance(sources, dict) or not sources:
        raise ValueError("Source documents required")
    source_report = {}
    root = path.parent.resolve()
    for name, source in sources.items():
        _keys(source, ("file", "sha256", "description"))
        if not isinstance(name, str) or not name.strip() or any(
                not isinstance(source[k], str) or not source[k].strip() for k in source):
            raise ValueError("Invalid source declaration")
        relative = Path(source["file"])
        if relative.is_absolute() or ".." in relative.parts or relative.drive:
            raise ValueError("Source path must remain within manifest directory")
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or ":" in source["file"]:
            raise ValueError("Unsafe source path")
        if digest(target.read_bytes()) != source["sha256"]:
            raise ValueError("Source document hash mismatch")
        source_report[name] = dict(source)
    assets = manifest["assets"]
    if not isinstance(assets, dict) or set(assets) != set(symbols):
        raise ValueError("Manifest must cover exactly the requested assets")
    periods = {}
    used_sources = set()
    for symbol in symbols:
        if not isinstance(assets[symbol], list) or not assets[symbol]:
            raise ValueError("Nonempty specification periods required")
        periods[symbol] = []
        for entry in assets[symbol]:
            _keys(entry, ("start", "end", "specification", "sources"))
            if any(type(entry[k]) is not int or entry[k] < 0 or entry[k] % DAY for k in ("start", "end")):
                raise ValueError("Intraday changes unsupported by daily simulation")
            spec = entry["specification"]
            _keys(spec, FIELDS)
            values = {}
            try:
                for key, value in spec.items():
                    if not isinstance(value, str):
                        raise ValueError("Specification numbers must be decimal strings")
                    number = Decimal(value)
                    if not number.is_finite() or number <= 0:
                        raise ValueError("Positive finite specification required")
                    values[key] = number
            except InvalidOperation as exc:
                raise ValueError("Invalid decimal specification") from exc
            if any(values[k] % values["quantity_step"] for k in ("min_quantity", "max_quantity")):
                raise ValueError("Quantity bounds must align with explicit step")
            refs = entry["sources"]
            if (not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in sources for r in refs)
                    or len(set(refs)) != len(refs)):
                raise ValueError("Each period needs unique known source references")
            used_sources.update(refs)
            config = replace(base, **{k: float(v) for k, v in values.items()})
            periods[symbol].append(dict(start=entry["start"], end=entry["end"], config=config,
                                        source="declared documents: " + ", ".join(refs),
                                        verified_fields=[]))
        validate_periods(periods[symbol], start, end)
    if used_sources != set(sources):
        raise ValueError("Unreferenced source documents")
    return periods, dict(version=VERSION, manifest_sha256=expected_sha256,
                         scope=manifest["scope"], sources=source_report,
                         required_window=dict(start=start, end=end, end_exclusive=True),
                         historical_specs_verified=False, exact_costs_verified=False,
                         acceptance_status="NOT_VALIDATED")


def simulate_manifest(asset_rows, candidates, config, groups, path, expected_sha256,
                      structures=None, *, funding=None, allow_declared_scenario=False):
    """Apply daily periods at fill time through the existing shared-account engine."""
    rows = {s: list(r) for s, r in asset_rows.items()}
    if not rows or any(not r for r in rows.values()):
        raise ValueError("Nonempty bars required for every asset")
    first = next(iter(rows.values()))
    periods, report = load(path, expected_sha256, config.execution, list(rows),
                           first[0]["timestamp"], first[-1]["timestamp"] + DAY,
                           allow_declared_scenario=allow_declared_scenario)
    result = simulate(rows, candidates, config, groups, structures,
                      funding=funding, execution_periods=periods)
    report["used_for_execution_parameters"] = True
    result["dated_specification_evidence"] = report
    result["dated_specification_code_sha256"] = {
        name: digest(Path(__file__).with_name(name).read_bytes())
        for name in ("dated_specifications.py", "execution_history.py", "portfolio_simulation.py",
                     "trade_simulation.py", "contract_specs.py", "spec_evidence.py",
                     "history.py", "indicators.py", "funding_history.py", "kline.py")}
    return result


def main():
    from trade_simulation import Config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--base-config", required=True, help="JSON object of simulation Config fields")
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", type=int, required=True, help="Inclusive UTC Unix daily boundary")
    parser.add_argument("--end", type=int, required=True, help="Exclusive UTC Unix daily boundary")
    parser.add_argument("--allow-declared-scenario", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    _, report = load(args.manifest, args.expected_sha256,
                     Config(**_json(Path(args.base_config).read_bytes())), args.symbols, args.start, args.end,
                     allow_declared_scenario=args.allow_declared_scenario)
    with Path(args.output).open("xb") as target:
        target.write(encoded(report))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
