"""Retain and reproduce joint execution arithmetic without authenticating fixtures."""
import argparse
import json
from pathlib import Path

from contract_specs import digest, encoded
from dated_costs import VERSION as COST_VERSION
from dated_specifications import FIELDS
from funding_history import collect
from history import DAY
from joint_execution import simulate_joint, load
from portfolio_simulation import PortfolioConfig
from settlement_prices import VERSION as PRICE_VERSION
from spec_evidence import _json
from spec_field_review import VERSION as REVIEW_VERSION, MARKET
from trade_simulation import Config


def fixture(root):
    """Synthetic data only, including the funding API response."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    body = b"SYNTHETIC joint execution assertions; not issuer or account evidence.\n"
    (root / "fixture.txt").write_bytes(body)
    sources = dict(fixture=dict(file="fixture.txt", sha256=digest(body), description="synthetic fixture"))
    review = dict(version=REVIEW_VERSION, scope="REVIEW_ASSERTIONS_ONLY", market=MARKET,
        documents=dict(fixture=dict(file="fixture.txt", sha256=digest(body),
                                   origin="synthetic fixture", kind="effective_notice")), claims=[])
    costs = dict(version=COST_VERSION, scope="DECLARED_SCENARIO_ONLY", sources=sources, assets={})
    prices = dict(version=PRICE_VERSION, scope="DECLARED_SCENARIO_ONLY", sources=sources, assets={})
    for symbol in ("BTC", "ETH"):
        for i, (a, b) in enumerate(((0, DAY), (DAY, 4*DAY))):
            values = dict(multiplier="1" if symbol == "BTC" else "0.01", quantity_step="0.1",
                          min_quantity="0.1", max_quantity="2" if i == 0 else "2.5", price_tick="0.1")
            for field in FIELDS:
                review["claims"].append(dict(id=f"{symbol}-{i}-{field}", symbol=symbol, field=field,
                    value=values[field], start=a, end=b, document="fixture", excerpt_start=0,
                    excerpt_end=len(body), excerpt=body.decode(), reviewer="synthetic fixture",
                    rationale="Arithmetic only; no authenticity certification"))
        costs["assets"][symbol] = [dict(start=0, end=2*DAY,
            costs=dict(fee_rate="0.001", slippage="0"), sources=["fixture"]),
            dict(start=2*DAY, end=4*DAY, costs=dict(fee_rate="0.002", slippage="0.01"), sources=["fixture"])]
        funding = collect(symbol, 0, 4*DAY, root / symbol,
            fetch=lambda p: encoded([dict(t=t+1, r="0.001") for t in range(0, 4*DAY, 28800)]),
            clock=lambda: 4*DAY)
        prices["assets"][symbol] = dict(funding_snapshot=symbol,
            funding_sha256=digest((root / symbol / "funding.json").read_bytes()),
            prices=[dict(timestamp=r["timestamp"], mark_price=str(70+10*i), sources=["fixture"])
                    for i, r in enumerate(funding["records"])])
    inputs = dict(allow_scenario=True)
    for key, value in (("review", review), ("cost", costs), ("price", prices)):
        path = root / (key + ".json")
        path.write_bytes(encoded(value))
        inputs[key + "_path"] = path
        inputs[key + "_sha256"] = digest(path.read_bytes())
    rows = {s: [dict(timestamp=i*DAY, symbol=s, market=MARKET, interval="1d", source="synthetic",
                    open=100, high=105, low=95, close=100, volume=1) for i in range(4)] for s in ("BTC", "ETH")}
    candidates = {s: [dict(index=0, signal_time=DAY, direction=1 if s == "BTC" else -1,
                          raw_weak_price=100, strong_price=120 if s == "BTC" else 80, atr=10)] for s in rows}
    config = PortfolioConfig(Config(10000, .01, 1, .2, entry_atr=0, stop_atr=1,
                                   target_r=2, fee_rate=0, slippage=0, funding_daily=0), .05, 2)
    return rows, candidates, config, {s: "crypto" for s in rows}, inputs


def audit(registration, previous, expected_prior_sha256, real_review, output):
    output = Path(output)
    root = output.with_suffix("")
    if output.exists() or root.exists():
        raise FileExistsError("Acceptance output or inputs already exist")
    prior_bytes = Path(previous).read_bytes()
    if digest(prior_bytes) != expected_prior_sha256:
        raise ValueError("Prior acceptance hash mismatch")
    prior = _json(prior_bytes)
    registration = Path(registration)
    original = registration.read_bytes()
    if digest(original) != prior["registration_sha256"]:
        raise ValueError("Registration differs from prior acceptance")
    frozen = {name: digest(Path(__file__).with_name(name).read_bytes()) == sha
              for name, sha in _json(original)["source_sha256"].items()}
    if not all(frozen.values()):
        raise ValueError("Frozen sources changed")
    rows, candidates, config, groups, inputs = fixture(root)
    result = simulate_joint(rows, candidates, config, groups, **inputs)
    window = prior["real_review"]["required_window"]
    try:
        load(config.execution, ["BTC", "ETH"], window["start"], window["end"],
             **dict(inputs, review_path=real_review, review_sha256=prior["real_review_sha256"]))
    except ValueError as exc:
        rejection = str(exc)
    else:
        raise AssertionError("Empty real review must block execution")
    trades = {t["symbol"]: t for t in result["trades"]}
    expected = dict(BTC=-6.145, ETH=-.0093)
    checks = dict(frozen_sources_unchanged=all(frozen.values()),
        registration_unchanged=registration.read_bytes() == original,
        prior_acceptance_unchanged=Path(previous).read_bytes() == prior_bytes,
        real_missing_evidence_blocked=rejection.startswith("Incomplete or conflicting reviewed field"),
        multiasset_long_short=set(trades) == {"BTC", "ETH"} and trades["BTC"]["direction"] == 1
            and trades["ETH"]["direction"] == -1,
        joint_boundaries=all([(p["start"], p["end"]) for p in ps] == [(0,DAY),(DAY,2*DAY),(2*DAY,4*DAY)]
            for ps in result["joint_execution_evidence"]["execution_periods"].values()),
        fill_time_specs=all(t["quantity"] == 2.5 and t["entry_time"] == DAY for t in trades.values()),
        exit_day_costs=all(t["cost_application"]["entry_fee_rate"] == .001 and
            t["cost_application"]["exit_fee_rate"] == .002 and t["cost_application"]["exit_day"] == 3*DAY
            for t in trades.values()),
        declared_price_funding=abs(trades["BTC"]["funding"]-2.9)<1e-9 and
            abs(trades["ETH"]["funding"]+.02325)<1e-9,
        independent_net_pnl=all(abs(trades[s]["net_pnl"]-v)<1e-9 for s,v in expected.items()),
        independent_final_equity=abs(result["summary"]["final_equity"]-9993.8457)<1e-9,
        three_input_provenance=all(t["entry_specification_review"]["ledger_sha256"] == inputs["review_sha256"]
            and t["cost_application"]["manifest_sha256"] == inputs["cost_sha256"] and
            t["settlement_price_manifest_sha256"] == inputs["price_sha256"] for t in trades.values()),
        no_authentication=all(result["joint_execution_evidence"][k] is False for k in
            ("historical_specs_verified", "exact_costs_verified", "settlement_prices_verified")))
    if not all(checks.values()):
        raise AssertionError(checks)
    artifact = dict(engineering_status="PASSED", strategy_status="NOT_VALIDATED", checks=checks,
        registration_sha256=digest(original), prior_acceptance_sha256=expected_prior_sha256,
        real_review_sha256=prior["real_review_sha256"], real_execution_rejection=rejection,
        frozen_sources_unchanged=frozen, synthetic_result=result, expected_net_pnl=expected,
        input_sha256={str(p.relative_to(root)): digest(p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()},
        audit_code_sha256=digest(Path(__file__).read_bytes()))
    with output.open("xb") as target:
        target.write(encoded(artifact))
    print(json.dumps(dict(engineering_status="PASSED", checks=checks)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registration")
    parser.add_argument("previous")
    parser.add_argument("--expected-prior-sha256", required=True)
    parser.add_argument("real_review")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    audit(args.registration, args.previous, args.expected_prior_sha256, args.real_review, args.output)
