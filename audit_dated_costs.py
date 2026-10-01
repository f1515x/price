"""Reproduce declared cost/specification integration and frozen-source checks."""
import argparse
import json
import math
from pathlib import Path
import tempfile

from contract_specs import digest, encoded
from dated_costs import VERSION, simulate_manifest
from dated_specifications import VERSION as SPEC_VERSION
from history import DAY
from portfolio_simulation import PortfolioConfig
from spec_evidence import _json
from trade_simulation import Config


def audit(registration, expected_registration_sha256, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    registration = Path(registration)
    original = registration.read_bytes()
    if digest(original) != expected_registration_sha256:
        raise ValueError("Registration differs from reviewed hash")
    record = _json(original)
    frozen = {name: digest(Path(__file__).with_name(name).read_bytes()) == sha
              for name, sha in record["source_sha256"].items()}
    if not all(frozen.values()):
        raise ValueError("Registered sources changed")
    base = Config(10000, .01, 1, .2, entry_atr=0, stop_atr=1, fee_rate=0,
                  slippage=0, funding_daily=0, quantity_step=1, min_quantity=1,
                  max_quantity=2, price_tick=.1)
    with tempfile.TemporaryDirectory(prefix="price-dated-cost-") as tmp:
        root = Path(tmp)
        source = root / "synthetic.txt"
        source.write_bytes(b"Synthetic costs and specifications, not account or exchange evidence.\n")
        sources = dict(fixture=dict(file=source.name, sha256=digest(source.read_bytes()), description="synthetic fixture"))
        costs, specs = {}, {}
        for symbol, multiplier in (("BTC", "1"), ("ETH", "0.01")):
            costs[symbol] = [dict(start=0, end=2*DAY, costs=dict(fee_rate="0.001", slippage="0"), sources=["fixture"]),
                            dict(start=2*DAY, end=4*DAY, costs=dict(fee_rate="0.002", slippage="0.01"), sources=["fixture"])]
            spec = dict(multiplier=multiplier, quantity_step="1", min_quantity="1", max_quantity="2", price_tick="0.1")
            specs[symbol] = [dict(start=0, end=DAY, specification=spec, sources=["fixture"]),
                            dict(start=DAY, end=4*DAY, specification=dict(spec, max_quantity="3"), sources=["fixture"])]
        cost_manifest = dict(version=VERSION, scope="DECLARED_SCENARIO_ONLY", sources=sources, assets=costs)
        spec_manifest = dict(version=SPEC_VERSION, scope="DECLARED_SCENARIO_ONLY", sources=sources, assets=specs)
        cost_path, spec_path = root / "costs.json", root / "specs.json"
        cost_path.write_bytes(encoded(cost_manifest))
        spec_path.write_bytes(encoded(spec_manifest))
        rows = {s: [dict(timestamp=i*DAY, symbol=s, market="gate_usdt_perpetual", interval="1d", source="gate",
                         open=100, high=105, low=95, close=100, volume=1) for i in range(4)] for s in costs}
        candidate = dict(index=0, signal_time=DAY, direction=1, raw_weak_price=100, strong_price=120, atr=10)
        result = simulate_manifest(rows, {s: [dict(candidate)] for s in rows}, PortfolioConfig(base, .05, 2),
            {s: "crypto" for s in rows}, cost_path, digest(cost_path.read_bytes()),
            specification_path=spec_path, specification_sha256=digest(spec_path.read_bytes()), allow_declared_scenario=True)
        by_symbol = {t["symbol"]: t for t in result["trades"]}
        checks = dict(frozen_sources_unchanged=all(frozen.values()), registration_unchanged=registration.read_bytes() == original,
            two_asset_trades=set(by_symbol) == {"BTC", "ETH"},
            costs_match_independent_arithmetic=all(math.isclose(by_symbol[s]["net_pnl"], expected, abs_tol=1e-9)
                for s, expected in (("BTC", -3.894), ("ETH", -.03894))),
            entry_and_exit_dates=all(t["cost_application"]["entry_day"] == DAY and
                t["cost_application"]["exit_day"] == 3*DAY for t in by_symbol.values()),
            independent_boundary_union=all([(p["start"], p["end"]) for p in ps] ==
                [(0, DAY), (DAY, 2*DAY), (2*DAY, 4*DAY)] for ps in result["execution_periods"].values()),
            cash_reconciles=math.isclose(result["summary"]["final_equity"], 9996.06706, abs_tol=1e-9),
            no_certification=not result["dated_cost_evidence"]["exact_costs_verified"] and
                not result["dated_specification_evidence"]["historical_specs_verified"] and
                result["dated_cost_evidence"]["acceptance_status"] == "NOT_VALIDATED")
        if not all(checks.values()):
            raise AssertionError(checks)
        artifact = dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
            registration_sha256=expected_registration_sha256, frozen_sources_unchanged=frozen,
            synthetic_cost_manifest=cost_manifest, synthetic_specification_manifest=spec_manifest,
            synthetic_source_text=source.read_text(), synthetic_result=result,
            audit_code_sha256=digest(Path(__file__).read_bytes()))
    with output.open("xb") as target:
        target.write(encoded(artifact))
    print(json.dumps(dict(engineering_status="PASSED", checks=checks)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registration")
    parser.add_argument("--expected-registration-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    audit(args.registration, args.expected_registration_sha256, args.output)
