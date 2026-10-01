"""Pinned settlement-price declarations joined to archived historical funding."""
import argparse
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path

from contract_specs import digest, encoded
from dated_specifications import _keys
from funding_history import load_snapshot, validate_execution_funding
from history import DAY
from kline import normalize_symbol
from portfolio_simulation import simulate
from spec_evidence import _json

VERSION = "settlement-price-scenario-v1"
INTERVAL = 28800


def _local(root, relative):
    if (not isinstance(relative, str) or not relative.strip() or
            Path(relative).is_absolute() or Path(relative).drive or
            ".." in Path(relative).parts or ":" in relative):
        raise ValueError("Unsafe settlement evidence path")
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Settlement evidence escapes manifest directory")
    return target


def _positive(value):
    if not isinstance(value, str):
        raise ValueError("Settlement prices must be decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid settlement price") from exc
    converted = float(number)
    if not number.is_finite() or number <= 0 or not math.isfinite(converted) or converted <= 0:
        raise ValueError("Positive finite execution price required")
    return converted


def load(path, expected_sha256, symbols, start, end, *, allow_declared_scenario=False):
    """No interpolation, daily OHLC substitute, missing-zero fill or certification."""
    if allow_declared_scenario is not True:
        raise ValueError("Explicit allow_declared_scenario=True required")
    if any(type(t) is not int or t < 0 or t % DAY for t in (start, end)) or start >= end:
        raise ValueError("Increasing UTC daily boundaries required")
    symbols = list(symbols)
    if (not symbols or len(set(symbols)) != len(symbols) or
            any(normalize_symbol(s) != s for s in symbols)):
        raise ValueError("Unique canonical symbols required")
    path = Path(path)
    body = path.read_bytes()
    if digest(body) != expected_sha256:
        raise ValueError("Settlement manifest differs from reviewed SHA-256")
    manifest = _json(body)
    _keys(manifest, ("version", "scope", "sources", "assets"))
    if manifest["version"] != VERSION or manifest["scope"] != "DECLARED_SCENARIO_ONLY":
        raise ValueError("Unsupported settlement-price scope")
    root = path.parent.resolve()
    sources = manifest["sources"]
    if not isinstance(sources, dict) or not sources:
        raise ValueError("Price source documents required")
    pinned = {path.resolve(): body}
    for name, source in sources.items():
        _keys(source, ("file", "sha256", "description"))
        if (not isinstance(name, str) or not name.strip() or
                any(not isinstance(v, str) or not v.strip() for v in source.values())):
            raise ValueError("Invalid price source declaration")
        target = _local(root, source["file"])
        original = target.read_bytes()
        if digest(original) != source["sha256"]:
            raise ValueError("Price source hash mismatch")
        pinned[target] = original
    assets = manifest["assets"]
    if not isinstance(assets, dict) or set(assets) != set(symbols):
        raise ValueError("Settlement manifest must cover exactly requested assets")
    funding, summaries, used = {}, {}, set()
    for symbol in symbols:
        asset = assets[symbol]
        _keys(asset, ("funding_snapshot", "funding_sha256", "prices"))
        directory = _local(root, asset["funding_snapshot"])
        snapshot_path = _local(root, str((directory / "funding.json").relative_to(root)))
        original = snapshot_path.read_bytes()
        if digest(original) != asset["funding_sha256"]:
            raise ValueError("Funding snapshot differs from reviewed SHA-256")
        raw_report = _json(original)
        # Read strict JSON and pin raw page bytes before the existing archive verifier.
        pinned[snapshot_path] = original
        for i, page in enumerate(raw_report["pages"]):
            if page["raw_file"] != f"page-{i:04d}.json":
                raise ValueError("Unsafe funding raw path")
            raw_path = _local(root, str((directory / page["raw_file"]).relative_to(root)))
            raw = raw_path.read_bytes()
            _json(raw)
            if digest(raw) != page["sha256"]:
                raise ValueError("Funding raw hash mismatch")
            pinned[raw_path] = raw
        report = load_snapshot(directory)
        if (report["symbol"] != symbol or report.get("market") != "gate_usdt_perpetual" or
                report["start"] != start or report["end_exclusive"] != end or
                report["assumed_interval"] != INTERVAL or report["status"] != "COMPLETE_ASSUMED_GRID"):
            raise ValueError("Complete matching eight-hour funding snapshot required")
        prices = asset["prices"]
        if not isinstance(prices, list):
            raise ValueError("Settlement prices must be a list")
        if len(prices) != len(report["records"]):
            raise ValueError("One declared price per settlement required")
        funding[symbol] = {}
        for price, rate in zip(prices, report["records"]):
            _keys(price, ("timestamp", "mark_price", "sources"))
            t = price["timestamp"]
            if type(t) is not int or t != rate["timestamp"]:
                raise ValueError("Price timestamps must match ordered scheduled settlements exactly")
            refs = price["sources"]
            if (not isinstance(refs, list) or not refs or
                    any(not isinstance(r, str) or r not in sources for r in refs) or len(set(refs)) != len(refs)):
                raise ValueError("Each price needs unique known sources")
            used.update(refs)
            event = dict(rate, mark_price=_positive(price["mark_price"]))
            funding[symbol].setdefault(t // DAY * DAY, []).append(event)
        summaries[symbol] = dict(settlements=len(prices), funding_sha256=asset["funding_sha256"],
                                 funding_snapshot=asset["funding_snapshot"],
                                 assumed_interval=INTERVAL, certified_settlements=0)
    if used != set(sources):
        raise ValueError("Unreferenced price sources")
    validate_execution_funding({s: [dict(timestamp=t) for t in range(start, end, DAY)] for s in symbols}, funding)
    if any(p.read_bytes() != original for p, original in pinned.items()):
        raise ValueError("Settlement evidence changed during read")
    evidence = dict(version=VERSION, scope=manifest["scope"], manifest_sha256=expected_sha256,
        sources=sources, assets=summaries, required_window=dict(start=start, end=end, end_exclusive=True),
        price_model="declared_price_at_scheduled_settlement_not_certified",
        timestamp_policy="eight-hour assumed grid; original funding report timestamp retained",
        settlement_prices_verified=False, exact_costs_verified=False, acceptance_status="NOT_VALIDATED")
    return funding, evidence


def simulate_manifest(asset_rows, candidates, config, groups, path, expected_sha256,
                      structures=None, *, execution_periods=None, allow_declared_scenario=False):
    rows = {s: list(bars) for s, bars in asset_rows.items()}
    if not rows or any(not bars for bars in rows.values()):
        raise ValueError("Nonempty bars required for every asset")
    first = next(iter(rows.values()))
    funding, evidence = load(path, expected_sha256, rows, first[0]["timestamp"],
                             first[-1]["timestamp"] + DAY, allow_declared_scenario=allow_declared_scenario)
    result = simulate(rows, candidates, config, groups, structures,
                      funding=funding, execution_periods=execution_periods)
    # The base engine labels point-mark funding generically; expose its actual provenance.
    result["funding_model"] = "historical_rates_declared_settlement_prices_conservative_daily_ownership"
    evidence.update(used_for_execution_parameters=True,
                    ownership_policy="daily ambiguity: charge debits, withhold credits; skip entry-open settlement")
    result["settlement_price_evidence"] = evidence
    result["settlement_price_code_sha256"] = {name: digest(Path(__file__).with_name(name).read_bytes())
        for name in ("settlement_prices.py", "funding_history.py", "portfolio_simulation.py",
                     "trade_simulation.py", "execution_history.py", "contract_specs.py",
                     "dated_specifications.py", "spec_evidence.py", "history.py", "indicators.py", "kline.py")}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--allow-declared-scenario", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    _, evidence = load(args.manifest, args.expected_sha256, args.symbols, args.start, args.end,
                       allow_declared_scenario=args.allow_declared_scenario)
    with Path(args.output).open("xb") as target:
        target.write(encoded(evidence))
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
