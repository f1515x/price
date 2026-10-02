"""Exact declared funding settlements over pinned intraday fill accounting."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

from contract_specs import digest, encoded
from dated_specifications import _keys
from intraday_accounting import account
from intraday_orders import number, ratio
from spec_evidence import _json

VERSION = "declared-intraday-funding-v1"
ORDERING = "SETTLEMENT_BEFORE_SAME_SECOND_FILLS"


def exact(value):
    return Fraction(value["numerator"], value["denominator"])


def signed_rate(value):
    if not isinstance(value, str):
        raise ValueError("Funding rate requires decimal string")
    try:
        rate = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid funding rate") from exc
    if not rate.is_finite() or abs(Fraction(rate)) >= 1:
        raise ValueError("Finite funding rate with magnitude below one required")
    return Fraction(rate)


def settle(archive, notice_sha256, scenario, scenario_sha256, fee_policy,
           fee_policy_sha256, funding_policy, funding_policy_sha256, *, allow_scenario=False):
    """Positive rate debits longs; settle on exposure strictly before the second.

    The complete schedule is declared, never inferred or exchange-certified.
    """
    body = encoded(funding_policy)
    if digest(body) != funding_policy_sha256:
        raise ValueError("Funding policy differs from pinned SHA-256")
    policy = _json(body)
    _keys(policy, ("symbol", "start", "end", "ordering", "scheduled_timestamps", "settlements"))
    baseline = account(archive, notice_sha256, scenario, scenario_sha256, fee_policy,
                       fee_policy_sha256, allow_scenario=allow_scenario)
    # Use a pinned snapshot rather than mutable caller inputs after validation.
    scenario = _json(encoded(scenario))
    if digest(encoded(scenario)) != scenario_sha256:
        raise ValueError("Scenario differs from pinned SHA-256")
    if (policy["symbol"] != scenario["symbol"]
            or type(policy["start"]) is not int or type(policy["end"]) is not int
            or policy["start"] != scenario["start"] or policy["end"] != scenario["end"]
            or policy["ordering"] != ORDERING):
        raise ValueError("Funding symbol, window and explicit ordering must match")
    schedule, settlements = policy["scheduled_timestamps"], policy["settlements"]
    if not isinstance(schedule, list) or not isinstance(settlements, list):
        raise ValueError("Declared schedule and settlements must be lists")
    if any(type(t) is not int or not scenario["start"] <= t < scenario["end"] for t in schedule):
        raise ValueError("Settlement timestamps must be exact UTC seconds inside window")
    if schedule != sorted(set(schedule)):
        raise ValueError("Strictly increasing unique settlement schedule required")
    parsed = []
    for item in settlements:
        _keys(item, ("timestamp", "rate", "settlement_price"))
        if type(item["timestamp"]) is not int:
            raise ValueError("Exact settlement timestamp required")
        parsed.append((item["timestamp"], signed_rate(item["rate"]),
                       Fraction(number(item["settlement_price"]))))
    if [t for t, _, _ in parsed] != schedule:
        raise ValueError("Exactly one settlement per declared schedule timestamp required")
    fills = baseline["ledger"]
    cursor = 0
    position = realized = fees = funding = Fraction(0)
    initial = exact(baseline["initial_collateral"])
    ledger = []
    for index, (stamp, rate, price) in enumerate(parsed):
        while cursor < len(fills) and fills[cursor]["timestamp"] < stamp:
            fill = fills[cursor]
            position = exact(fill["net_base_exposure"])
            realized = exact(fill["cumulative_realized_pnl"])
            fees = exact(fill["cumulative_fees"])
            cursor += 1
        cashflow = -position * price * rate
        funding += cashflow
        ledger.append(dict(timestamp=stamp, schedule_index=index, rate=ratio(rate),
                           settlement_price=ratio(price), net_base_exposure=ratio(position),
                           funding_cashflow=ratio(cashflow), cumulative_funding=ratio(funding),
                           collateral_balance=ratio(initial + realized - fees + funding),
                           funding_policy_sha256=funding_policy_sha256))
    fill_ledger = []
    settled = 0
    accrued = Fraction(0)
    for fill in fills:
        while settled < len(ledger) and ledger[settled]["timestamp"] <= fill["timestamp"]:
            accrued = exact(ledger[settled]["cumulative_funding"])
            settled += 1
        fill_ledger.append(dict(fill, cumulative_funding=ratio(accrued),
                               collateral_balance=ratio(exact(fill["collateral_balance"]) + accrued)))
    if account(archive, notice_sha256, scenario, scenario_sha256, fee_policy,
               fee_policy_sha256, allow_scenario=allow_scenario) != baseline:
        raise ValueError("Accounting evidence changed during funding settlement")
    return dict(version=VERSION, scope="DECLARED_LINEAR_USDT_FUNDING_ACCOUNTING",
                engineering_status="PASSED", acceptance_status="NOT_VALIDATED",
                costs_verified=False, funding_schedule_verified=False,
                risk_budget_enforced=False, funding_included=True,
                ordering=ORDERING, unrealized_pnl=None, equity=None,
                total_funding_cashflow=ratio(funding),
                net_realized_pnl=ratio(exact(baseline["net_realized_pnl"]) + funding),
                collateral_balance=ratio(exact(baseline["collateral_balance"]) + funding),
                funding_policy_sha256=funding_policy_sha256,
                settlement_ledger=ledger, fill_ledger=fill_ledger, accounting=baseline,
                source_sha256=digest(Path(__file__).read_bytes()))
