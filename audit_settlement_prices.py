"""Reproduce settlement-price scenario accounting without altering frozen research."""
import argparse
import json
import math
from pathlib import Path

from contract_specs import digest, encoded
from dated_costs import VERSION as COST_VERSION, load as load_costs
from funding_history import collect
from history import DAY
from portfolio_simulation import PortfolioConfig
from settlement_prices import VERSION, load, simulate_manifest
from spec_evidence import _json
from trade_simulation import Config


def audit(registration, expected_registration_sha256, output):
    output = Path(output)
    fixture = output.with_suffix("")
    if output.exists() or fixture.exists():
        raise FileExistsError("Audit output or fixture directory already exists")
    registration = Path(registration)
    original = registration.read_bytes()
    if digest(original) != expected_registration_sha256:
        raise ValueError("Registration differs from reviewed hash")
    record = _json(original)
    frozen = {name: digest(Path(__file__).with_name(name).read_bytes()) == sha
              for name, sha in record["source_sha256"].items()}
    if not all(frozen.values()):
        raise ValueError("Registered sources changed")
    fixture.mkdir(parents=True)
    source = fixture / "synthetic.txt"
    source.write_bytes(b"Synthetic settlement prices and costs; not certified exchange or account evidence.\n")
    sources = dict(fixture=dict(file=source.name, sha256=digest(source.read_bytes()), description="synthetic fixture"))
    assets = {}
    for symbol in ("BTC", "ETH"):
        snapshot = collect(symbol, 0, 4*DAY, fixture / symbol,
            fetch=lambda p: encoded([dict(t=t+1, r="0.001") for t in range(0, 4*DAY, 28800)]), clock=lambda: 4*DAY)
        assets[symbol] = dict(funding_snapshot=symbol,
            funding_sha256=digest((fixture / symbol / "funding.json").read_bytes()),
            prices=[dict(timestamp=r["timestamp"], mark_price=str(70+10*i), sources=["fixture"])
                    for i, r in enumerate(snapshot["records"])])
    path = fixture / "prices.json"
    path.write_bytes(encoded(dict(version=VERSION, scope="DECLARED_SCENARIO_ONLY", sources=sources, assets=assets)))
    price_sha = digest(path.read_bytes())
    cost_path = fixture / "costs.json"
    cost_path.write_bytes(encoded(dict(version=COST_VERSION, scope="DECLARED_SCENARIO_ONLY", sources=sources,
        assets={s: [dict(start=0, end=4*DAY, costs=dict(fee_rate="0.001", slippage="0"), sources=["fixture"])]
                for s in assets})))
    base = Config(10000, .01, 1, .2, entry_atr=0, stop_atr=1, fee_rate=0, slippage=0,
                  funding_daily=0, quantity_step=1, min_quantity=1, max_quantity=2, price_tick=.1)
    periods, _ = load_costs(cost_path, digest(cost_path.read_bytes()), base, assets, 0, 4*DAY,
                            allow_declared_scenario=True)
    rows = {s: [dict(timestamp=i*DAY, symbol=s, market="gate_usdt_perpetual", interval="1d", source="gate",
                    open=100, high=105, low=95, close=100, volume=1) for i in range(4)] for s in assets}
    candidate = dict(index=0, signal_time=DAY, direction=1, raw_weak_price=100, strong_price=120, atr=10)
    results = {}
    for direction in (1, -1):
        results[str(direction)] = simulate_manifest(rows, {s: [dict(candidate, direction=direction,
            strong_price=120 if direction == 1 else 80)] for s in assets}, PortfolioConfig(base, .05, 2),
            {s: "crypto" for s in assets}, path, price_sha, execution_periods=periods, allow_declared_scenario=True)
    funding, evidence = load(path, price_sha, assets, 0, 4*DAY, allow_declared_scenario=True)
    checks = dict(frozen_sources_unchanged=all(frozen.values()),
        registration_unchanged=registration.read_bytes() == original,
        two_assets_both_directions=all({t["symbol"] for t in r["trades"]} == set(assets) for r in results.values()),
        independent_funding_arithmetic=all(math.isclose(t["funding"], expected, abs_tol=1e-9)
            for direction, expected in (("1", 2.32), ("-1", -1.86)) for t in results[direction]["trades"]),
        declared_fees_preserved=all(math.isclose(t["entry_fee"]+t["exit_fee"], .4, abs_tol=1e-9)
                                  for r in results.values() for t in r["trades"]),
        cash_reconciles=all(math.isclose(r["summary"]["final_equity"], expected, abs_tol=1e-9)
                           for r, expected in ((results["1"], 9994.56), (results["-1"], 10002.92))),
        reported_timestamps_retained=all(e["reported_timestamp"] == e["timestamp"]+1
                                        for days in funding.values() for events in days.values() for e in events),
        no_daily_mark_bounds=all("mark_high" not in e and "mark_low" not in e
                                for days in funding.values() for events in days.values() for e in events),
        no_certification=not evidence["settlement_prices_verified"] and not evidence["exact_costs_verified"])
    if not all(checks.values()):
        raise AssertionError(checks)
    artifact = dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
        registration_sha256=expected_registration_sha256, frozen_sources_unchanged=frozen,
        fixture_directory=fixture.name, price_manifest_sha256=price_sha,
        cost_manifest_sha256=digest(cost_path.read_bytes()), synthetic_results=results,
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
