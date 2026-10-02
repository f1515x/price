"""Exact fee and realized-PnL accounting for explicitly declared linear fills."""
from fractions import Fraction
from pathlib import Path

from contract_specs import digest, encoded
from dated_specifications import _keys
from intraday_orders import number, ratio, replay
from spec_evidence import _json

VERSION = "declared-intraday-accounting-v1"


def nonnegative(value):
    if value == "0":
        return Fraction(0)
    return Fraction(number(value))


def account(archive, notice_sha256, scenario, scenario_sha256, policy,
            policy_sha256, *, allow_scenario=False):
    """Zero initial position; fees use the fill-second rate and gross notional.

    Cash is collateral plus realized PnL less fees, not spot purchase cash flow.
    No mark prices, funding, margin, slippage or actual-fill certification inferred.
    """
    body = encoded(policy)
    if digest(body) != policy_sha256:
        raise ValueError("Accounting policy differs from pinned SHA-256")
    policy = _json(body)
    _keys(policy, ("initial_collateral", "fee_periods"))
    initial = nonnegative(policy["initial_collateral"])
    periods = policy["fee_periods"]
    if not isinstance(periods, list) or not periods:
        raise ValueError("Nonempty fee periods required")
    cursor = scenario["start"]
    rates = []
    for period in periods:
        _keys(period, ("start", "end", "rate"))
        left, right = period["start"], period["end"]
        if (type(left) is not int or type(right) is not int
                or left != cursor or not left < right <= scenario["end"]):
            raise ValueError("Contiguous exact-second fee coverage required")
        rate = nonnegative(period["rate"])
        if rate >= 1:
            raise ValueError("Fee rate must be less than one")
        rates.append((left, right, rate))
        cursor = right
    if cursor != scenario["end"]:
        raise ValueError("Incomplete fee coverage")
    replayed = replay(archive, notice_sha256, scenario, scenario_sha256,
                      allow_scenario=allow_scenario)
    position = average = realized = fees = Fraction(0)
    ledger = []
    for fill in replayed["fills"]:
        delta = Fraction(fill["signed_base_exposure"]["numerator"],
                         fill["signed_base_exposure"]["denominator"])
        price = Fraction(fill["price"])
        period_index = next(i for i, (a, b, _) in enumerate(rates)
                            if a <= fill["timestamp"] < b)
        rate = rates[period_index][2]
        notional = abs(delta) * price
        fee = notional * rate
        pnl = Fraction(0)
        if not position or position * delta > 0:
            average = (abs(position) * average + abs(delta) * price) / abs(position + delta)
        else:
            closed = min(abs(position), abs(delta))
            pnl = closed * (price - average) * (1 if position > 0 else -1)
            if abs(delta) > abs(position):
                average = price
            elif abs(delta) == abs(position):
                average = Fraction(0)
        position += delta
        realized += pnl
        fees += fee
        ledger.append(dict(timestamp=fill["timestamp"], order_id=fill["order_id"],
                           base_delta=ratio(delta), gross_notional=ratio(notional),
                           fee_period_index=period_index, fee_rate=ratio(rate), fee=ratio(fee),
                           realized_pnl=ratio(pnl), cumulative_realized_pnl=ratio(realized),
                           cumulative_fees=ratio(fees), net_base_exposure=ratio(position),
                           average_entry_price=ratio(average) if position else None,
                           collateral_balance=ratio(initial + realized - fees),
                           policy_sha256=policy_sha256))
    if ratio(position) != replayed["net_base_exposure"]:
        raise ValueError("Accounting exposure does not reconcile with replay")
    if replay(archive, notice_sha256, scenario, scenario_sha256,
              allow_scenario=allow_scenario) != replayed:
        raise ValueError("Replay evidence changed during accounting")
    return dict(version=VERSION, scope="DECLARED_LINEAR_USDT_FEE_AND_REALIZED_PNL_ONLY",
                engineering_status="PASSED", acceptance_status="NOT_VALIDATED",
                costs_verified=False, risk_budget_enforced=False,
                funding_included=False, unrealized_pnl=None, equity=None,
                initial_collateral=ratio(initial), total_fees=ratio(fees),
                realized_pnl=ratio(realized), net_realized_pnl=ratio(realized - fees),
                collateral_balance=ratio(initial + realized - fees),
                average_entry_price=ratio(average) if position else None,
                policy_sha256=policy_sha256, scenario_sha256=scenario_sha256,
                ledger=ledger, replay=replayed,
                source_sha256=digest(Path(__file__).read_bytes()))
