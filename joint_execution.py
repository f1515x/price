"""Joint reviewed specifications and declared costs/settlement prices; no orders."""
from dataclasses import replace
from pathlib import Path

from contract_specs import digest
from dated_costs import FIELDS as COST_FIELDS, load as load_costs
from execution_history import at_time, evidence, validate_periods
from history import DAY
from portfolio_simulation import simulate
from reviewed_specifications import load as load_specs
from settlement_prices import load as load_prices

VERSION = "joint-execution-scenario-v1"


def load(base, symbols, start, end, *, review_path, review_sha256,
         cost_path, cost_sha256, price_path, price_sha256, allow_scenario=False):
    """Require all three independently pinned inputs; never fill evidence gaps."""
    if allow_scenario is not True:
        raise ValueError("Explicit allow_scenario=True required")
    symbols = list(symbols)
    specs, spec_report = load_specs(review_path, review_sha256, base, symbols, start, end,
                                   allow_reviewed_scenario=True)
    costs, cost_report = load_costs(cost_path, cost_sha256, base, symbols, start, end,
                                   allow_declared_scenario=True)
    funding, price_report = load_prices(price_path, price_sha256, symbols, start, end,
                                       allow_declared_scenario=True)
    periods = {}
    for symbol in symbols:
        boundaries = sorted({start, end} | {p[k] for group in (specs[symbol], costs[symbol])
            for p in group for k in ("start", "end") if start < p[k] < end})
        periods[symbol] = []
        for left, right in zip(boundaries, boundaries[1:]):
            cost_config = at_time(costs[symbol], left)
            periods[symbol].append(dict(start=left, end=right,
                config=replace(at_time(specs[symbol], left),
                               **{k: getattr(cost_config, k) for k in COST_FIELDS}),
                source="joint pinned review, cost and settlement declarations", verified_fields=[]))
        validate_periods(periods[symbol], start, end)
    report = dict(version=VERSION, scope="JOINT_SCENARIO_ONLY", acceptance_status="NOT_VALIDATED",
        historical_specs_verified=False, exact_costs_verified=False, settlement_prices_verified=False,
        used_for_execution_parameters=False, specification_review=spec_report,
        cost_evidence=cost_report, settlement_price_evidence=price_report,
        execution_periods={s: evidence(p) for s, p in periods.items()},
        timestamp_policy="entry uses open day; exit uses exit_time minus DAY",
        ownership_policy="daily ambiguity: charge debits, withhold credits; skip entry-open settlement",
        risk_policy="fill-time risk estimate; later costs do not resize existing positions",
        source_sha256={name: digest(Path(__file__).with_name(name).read_bytes()) for name in
            ("joint_execution.py", "reviewed_specifications.py", "spec_field_review.py", "dated_costs.py",
             "settlement_prices.py", "dated_specifications.py", "execution_history.py", "portfolio_simulation.py",
             "trade_simulation.py", "funding_history.py", "contract_specs.py", "spec_evidence.py",
             "history.py", "kline.py", "indicators.py")})
    return periods, funding, report


def simulate_joint(asset_rows, candidates, config, groups, structures=None, **inputs):
    """Run one shared account and recheck every input before releasing results."""
    rows = {s: list(bars) for s, bars in asset_rows.items()}
    if not rows or any(not bars for bars in rows.values()):
        raise ValueError("Nonempty bars required for every asset")
    first = next(iter(rows.values()))
    args = (config.execution, list(rows), first[0]["timestamp"], first[-1]["timestamp"] + DAY)
    periods, funding, report = load(*args, **inputs)
    result = simulate(rows, candidates, config, groups, structures,
                      funding=funding, execution_periods=periods)
    if load(*args, **inputs) != (periods, funding, report):
        raise ValueError("Joint evidence changed during simulation")
    for trade in result["trades"]:
        symbol = trade["symbol"]
        spec = next(p for p in report["specification_review"]["provenance"][symbol]
                    if p["start"] <= trade["entry_time"] < p["end"])
        trade["entry_specification_review"] = dict(spec, ledger_sha256=inputs["review_sha256"])
        entry = at_time(periods[symbol], trade["entry_time"])
        exit_day = trade["exit_time"] - DAY
        exit_config = at_time(periods[symbol], exit_day)
        trade["cost_application"] = dict(manifest_sha256=inputs["cost_sha256"],
            entry_day=trade["entry_time"], exit_day=exit_day,
            entry_fee_rate=entry.fee_rate, exit_fee_rate=exit_config.fee_rate,
            entry_slippage=entry.slippage, exit_slippage=exit_config.slippage)
        trade["settlement_price_manifest_sha256"] = inputs["price_sha256"]
    report["used_for_execution_parameters"] = True
    for key in ("specification_review", "cost_evidence", "settlement_price_evidence"):
        report[key]["used_for_execution_parameters"] = True
    result["funding_model"] = "historical_rates_declared_settlement_prices_conservative_daily_ownership"
    result["joint_execution_evidence"] = report
    return result
