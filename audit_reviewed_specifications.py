"""Reproduce reviewed scenario execution and real historical evidence rejection."""
import argparse
import json
from pathlib import Path

from contract_specs import digest, encoded
from dated_specifications import FIELDS
from history import DAY
from portfolio_simulation import PortfolioConfig
from reviewed_specifications import load, simulate_review
from spec_evidence import _json
from spec_field_review import MARKET, VERSION, load as review
from trade_simulation import Config


def audit(registration, expected_registration_sha256, real_review, expected_review_sha256,
          symbols, start, end, output):
    output = Path(output)
    inputs = output.with_suffix("")
    if output.exists() or inputs.exists():
        raise FileExistsError("Acceptance output or inputs already exist")
    registration = Path(registration)
    original = registration.read_bytes()
    if digest(original) != expected_registration_sha256:
        raise ValueError("Registration hash mismatch")
    record = _json(original)
    frozen = {name: digest(Path(__file__).with_name(name).read_bytes()) == sha
              for name, sha in record["source_sha256"].items()}
    if not all(frozen.values()):
        raise ValueError("Frozen source changed")
    real_review = Path(real_review)
    # Preserve the previous audit's genuine empty historical review input.
    config = Config(10000, .01, 1, .2, entry_atr=0, stop_atr=1, target_r=2,
                    fee_rate=.001, slippage=.001, funding_daily=0)
    actual = review(real_review, expected_review_sha256, symbols, start, end)
    try:
        load(real_review, expected_review_sha256, config, symbols, start, end,
             allow_reviewed_scenario=True)
    except ValueError as exc:
        rejection = str(exc)
    else:
        raise AssertionError("Real missing evidence must block execution")
    inputs.mkdir(parents=True, exist_ok=False)
    body = b"SYNTHETIC field assertions for execution arithmetic; not issuer evidence.\n"
    (inputs / "fixture.txt").write_bytes(body)
    fixture = dict(version=VERSION, scope="REVIEW_ASSERTIONS_ONLY", market=MARKET,
        documents=dict(fixture=dict(file="fixture.txt", sha256=digest(body),
            origin="synthetic acceptance fixture", kind="effective_notice")), claims=[])
    for symbol in ("BTC", "ETH"):
        for i, (a, b) in enumerate(((0, DAY), (DAY, 3*DAY))):
            values = dict(multiplier="1" if symbol == "BTC" else "0.01", quantity_step="0.1",
                          min_quantity="0.1", max_quantity="2" if i == 0 else "2.5", price_tick="0.1")
            for field in FIELDS:
                fixture["claims"].append(dict(id=f"{symbol}-{i}-{field}", symbol=symbol, field=field,
                    value=values[field], start=a, end=b, document="fixture", excerpt_start=0,
                    excerpt_end=len(body), excerpt=body.decode(), reviewer="synthetic fixture",
                    rationale="Execution arithmetic, not authentication"))
    path = inputs / "synthetic-review.json"
    path.write_bytes(encoded(fixture))
    sha = digest(path.read_bytes())
    rows = {s: [dict(timestamp=i*DAY, symbol=s, market=MARKET, interval="1d", source="synthetic",
                    open=100, high=105, low=95, close=100, volume=1) for i in range(3)] for s in ("BTC", "ETH")}
    candidates = {s: [dict(index=0, signal_time=DAY, direction=1 if s == "BTC" else -1,
                          raw_weak_price=100, strong_price=120 if s == "BTC" else 80, atr=10)] for s in rows}
    result = simulate_review(rows, candidates, PortfolioConfig(config, .05, 2),
        {s: "crypto" for s in rows}, path, sha, allow_reviewed_scenario=True)
    trades = {t["symbol"]: t for t in result["trades"]}
    # Entry is capped at the 100 limit by the existing engine. Exit slippage
    # is 0.1; fees use 100 and 99.9/100.1. Contract units differ by 100x.
    # Funding is explicitly zero; no claim about realized exchange execution.
    expected_pnl = {"BTC": -2.5*(.1+.1+.0999), "ETH": -.025*(.1+.1+.1001)}
    checks = dict(frozen_sources_unchanged=all(frozen.values()),
        registration_unchanged=registration.read_bytes() == original,
        real_review_unchanged=review(real_review, expected_review_sha256, symbols, start, end) == actual,
        real_fields_missing=all(f["reviewed_coverage_seconds"] == 0 and f["missing_intervals"]
            for a in actual["assets"] for f in a["fields"].values()),
        real_execution_blocked=rejection.startswith("Incomplete or conflicting"),
        multiasset_long_short=set(trades) == {"BTC", "ETH"} and trades["BTC"]["direction"] == 1
            and trades["ETH"]["direction"] == -1,
        fill_time_specs=all(t["entry_time"] == DAY and t["quantity"] == 2.5 for t in trades.values()),
        trade_provenance=all(t["entry_specification_review"]["ledger_sha256"] == sha and
            t["entry_specification_review"]["claim_ids_by_field"]["max_quantity"] == [f"{s}-1-max_quantity"]
            for s,t in trades.items()),
        independent_net_pnl=all(abs(trades[s]["net_pnl"]-value) < 1e-9 for s,value in expected_pnl.items()),
        independent_final_equity=abs(result["summary"]["final_equity"]-9999.2427475) < 1e-9,
        no_authentication=not result["reviewed_specification_evidence"]["historical_specs_verified"]
            and not result["reviewed_specification_evidence"]["exact_costs_verified"]
            and result["reviewed_specification_evidence"]["acceptance_status"] == "NOT_VALIDATED")
    if not all(checks.values()):
        raise AssertionError(checks)
    artifact = dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
        registration_sha256=expected_registration_sha256, real_review_sha256=expected_review_sha256,
        frozen_sources_unchanged=frozen, real_review=actual, real_execution_rejection=rejection,
        synthetic_result=result, expected_net_pnl=expected_pnl,
        input_sha256={p.name: digest(p.read_bytes()) for p in sorted(inputs.iterdir())},
        audit_code_sha256=digest(Path(__file__).read_bytes()))
    with output.open("xb") as target:
        target.write(encoded(artifact))
    print(json.dumps(dict(engineering_status="PASSED", checks=checks)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registration")
    parser.add_argument("real_review")
    parser.add_argument("--expected-registration-sha256", required=True)
    parser.add_argument("--expected-review-sha256", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    audit(args.registration, args.expected_registration_sha256, args.real_review,
          args.expected_review_sha256, args.symbols, args.start, args.end, args.output)
