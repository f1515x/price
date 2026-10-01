"""Reproduce synthetic mapping acceptance and real observation-only gaps."""
import argparse
import json
from pathlib import Path
import tempfile

from contract_specs import digest, encoded
from dated_specifications import VERSION, load, simulate_manifest
from history import DAY
from portfolio_simulation import PortfolioConfig
from spec_evidence import verify
from trade_simulation import Config


def audit(registration, ledger, ledger_sha256, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    registration = Path(registration)
    original = registration.read_bytes()
    record = json.loads(original)
    frozen = {name: digest(Path(__file__).with_name(name).read_bytes()) == sha
              for name, sha in record["source_sha256"].items()}
    observed = verify(ledger, ledger_sha256)
    base = Config(10000, .01, 1, .2, entry_atr=0, stop_atr=1,
                  fee_rate=0, slippage=0, funding_daily=0)
    with tempfile.TemporaryDirectory(prefix="price-dated-spec-") as tmp:
        root = Path(tmp)
        source = root / "synthetic.txt"
        source.write_bytes(b"Synthetic specification declarations; no historical exchange evidence.\n")
        spec = dict(multiplier="1", quantity_step="1", min_quantity="1", max_quantity="2", price_tick="0.1")
        assets = {}
        for symbol, multiplier in (("BTC", "1"), ("ETH", "0.01")):
            assets[symbol] = [dict(start=0, end=DAY, specification=dict(spec, multiplier=multiplier), sources=["fixture"]),
                              dict(start=DAY, end=3*DAY, specification=dict(spec, multiplier=multiplier,
                                   quantity_step="0.1", min_quantity="0.1", max_quantity="2.5"), sources=["fixture"])]
        manifest = dict(version=VERSION, scope="DECLARED_SCENARIO_ONLY",
                        sources=dict(fixture=dict(file=source.name, sha256=digest(source.read_bytes()),
                                                  description="synthetic daily precision change")), assets=assets)
        path = root / "manifest.json"
        path.write_bytes(encoded(manifest))
        sha = digest(path.read_bytes())
        rows = {s: [dict(timestamp=i*DAY, symbol=s, market="gate_usdt_perpetual", interval="1d", source="gate",
                         open=100, high=105, low=95, close=100, volume=1) for i in range(3)] for s in assets}
        candidate = dict(index=0, signal_time=DAY, direction=1, raw_weak_price=100, strong_price=120, atr=10)
        result = simulate_manifest(rows, {s: [dict(candidate)] for s in assets}, PortfolioConfig(base, .05, 2),
                                   {s: "crypto" for s in assets}, path, sha, allow_declared_scenario=True)
        ledger_path = Path(ledger) / "ledger.json"
        rejected = False
        try:
            load(ledger_path, ledger_sha256, base, ["BTC", "ETH"], 0, 3*DAY, allow_declared_scenario=True)
        except ValueError:
            rejected = True
        checks = dict(frozen_sources_unchanged=all(frozen.values()),
                      registration_unchanged=registration.read_bytes() == original,
                      real_ledger_still_pinned=digest(ledger_path.read_bytes()) == ledger_sha256,
                      observations_not_execution_periods=rejected,
                      two_asset_fill_time_mapping=len(result["trades"]) == 2 and all(
                          t["quantity"] == 2.5 and t["entry_time"] == DAY for t in result["trades"]),
                      cash_reconciles=result["summary"]["final_equity"] == 10000 + sum(t["net_pnl"] for t in result["trades"]),
                      real_coverage_remains_zero=all(a["verified_coverage_seconds"] == 0 for a in observed["assets"]),
                      no_promotion=result["dated_specification_evidence"]["acceptance_status"] == "NOT_VALIDATED")
        if not all(checks.values()):
            raise AssertionError(checks)
        artifact = dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
                        registration_sha256=digest(original), ledger_sha256=ledger_sha256,
                        frozen_sources_unchanged=frozen, synthetic_manifest=manifest,
                        synthetic_source_text=source.read_text(), synthetic_result=result,
                        real_assets=observed["assets"],
                        audit_code_sha256=digest(Path(__file__).read_bytes()))
    with output.open("xb") as target:
        target.write(encoded(artifact))
    print(json.dumps(dict(engineering_status="PASSED", checks=checks)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registration")
    parser.add_argument("ledger")
    parser.add_argument("--expected-ledger-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    audit(args.registration, args.ledger, args.expected_ledger_sha256, args.output)
