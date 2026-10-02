"""Replay declared exact-time orders across notices; no market fill inference."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

from contract_specs import digest, encoded
from dated_specifications import FIELDS, _keys
from historical_notices import verify
from kline import normalize_symbol
from spec_evidence import _json

VERSION = "intraday-order-scenario-v2"


def decimal_string(value):
    """Serialize a nonnegative finite decimal Fraction without context rounding."""
    scale = 0
    power = 1
    while power % value.denominator:
        power *= 10
        scale += 1
    digits = str(value.numerator * (power // value.denominator)).zfill(scale + 1)
    return digits if not scale else digits[:-scale] + "." + digits[-scale:]


def number(value):
    if not isinstance(value, str):
        raise ValueError("Decimal strings required")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("Finite positive decimal required")
    return result


def specification(raw):
    _keys(raw, FIELDS)
    values = {k: number(v) for k, v in raw.items()}
    if values["min_quantity"] > values["max_quantity"]:
        raise ValueError("Invalid size bounds")
    step = Fraction(values["quantity_step"])
    minimum = Fraction(values["min_quantity"])
    if -(-minimum // step) * step > Fraction(values["max_quantity"]):
        raise ValueError("No legal quantity within bounds")
    return values


def legal(quantity, price, spec):
    q, p = number(quantity), number(price)
    if (not spec["min_quantity"] <= q <= spec["max_quantity"]
            or (Fraction(q) / Fraction(spec["quantity_step"])).denominator != 1
            or (Fraction(p) / Fraction(spec["price_tick"])).denominator != 1):
        raise ValueError("Order violates active specification")
    return q, p


def replay(archive, notice_sha256, scenario, scenario_sha256, *, allow_scenario=False):
    """Inputs are explicit declarations, including fills and the pre-window spec."""
    if allow_scenario is not True:
        raise ValueError("Explicit allow_scenario=True required")
    body = encoded(scenario)
    if digest(body) != scenario_sha256:
        raise ValueError("Scenario differs from pinned SHA-256")
    scenario = _json(body)
    _keys(scenario, ("symbol", "start", "end", "initial_specification", "actions"))
    symbol, start, end = (scenario[k] for k in ("symbol", "start", "end"))
    if not isinstance(symbol, str) or normalize_symbol(symbol) != symbol:
        raise ValueError("Canonical symbol required")
    if any(type(t) is not int or t < 0 for t in (start, end)) or start >= end:
        raise ValueError("Increasing UTC second boundaries required")
    spec = specification(scenario["initial_specification"])
    evidence = verify(archive, notice_sha256)
    events = sorted((e for e in evidence["events"] if e["symbol"] == symbol
                     and start <= e["effective_timestamp"] < end),
                    key=lambda e: (e["effective_timestamp"], e["id"]))
    # Duplicate identical notices are corroboration, not two state transitions.
    unique = {}
    for event in events:
        unique.setdefault(event["effective_timestamp"], []).append(event)
    transitions = list(unique.values())
    actions = scenario["actions"]
    if not isinstance(actions, list):
        raise ValueError("Action list required")
    previous = start
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("Invalid action")
        t = action.get("timestamp")
        if type(t) is not int or not previous <= t < end:
            raise ValueError("Ordered exact action timestamps within window required")
        previous = t
    pending, used, log, fills = {}, set(), [], []
    position = Fraction(0)
    cursor = 0

    def advance(stamp):
        nonlocal cursor, spec
        while cursor < len(transitions) and transitions[cursor][0]["effective_timestamp"] <= stamp:
            group = transitions[cursor]
            event = group[0]
            updated = dict(spec)
            for change in group:
                field = change["field"]
                if spec[field] != number(change["before"]):
                    raise ValueError("Notice before value conflicts with active declaration")
                if field == "multiplier" and position:
                    raise ValueError("Held position requires unsupported multiplier conversion")
                updated[field] = number(change["after"])
            specification({k: str(v) for k, v in updated.items()})
            log.append(dict(kind="notice", timestamp=event["effective_timestamp"],
                            event_ids=[e["id"] for e in group], cancelled_order_ids=sorted(pending),
                            cancelled_quantities={oid: order["remaining_quantity"]
                                                  for oid, order in sorted(pending.items())}))
            pending.clear()
            spec = updated
            cursor += 1

    for action in actions:
        advance(action["timestamp"])
        kind = action.get("kind")
        keys = ("kind", "timestamp", "order_id")
        _keys(action, keys + (("direction", "quantity", "limit_price") if kind == "submit"
                             else (("price", "quantity") if "quantity" in action else ("price",))
                             if kind == "fill" else ()))
        oid = action["order_id"]
        if not isinstance(oid, str) or not oid.strip():
            raise ValueError("Nonempty order ID required")
        if kind == "submit":
            if oid in used or type(action["direction"]) is not int or action["direction"] not in (-1, 1):
                raise ValueError("Unique order ID and signed direction required")
            legal(action["quantity"], action["limit_price"], spec)
            used.add(oid)
            pending[oid] = dict(action, remaining_quantity=action["quantity"])
        elif kind in ("cancel", "fill"):
            if oid not in pending:
                raise ValueError("Order is absent, cancelled or already filled")
            order = pending[oid]
            remaining = Fraction(number(order["remaining_quantity"]))
            if kind == "fill":
                q = number(action.get("quantity", order["remaining_quantity"]))
                price = number(action["price"])
                # Order minimum applies at submission, not to execution fragments.
                if ((Fraction(q) / Fraction(spec["quantity_step"])).denominator != 1
                        or Fraction(q) > remaining
                        or (Fraction(price) / Fraction(spec["price_tick"])).denominator != 1):
                    raise ValueError("Fill violates quantity step, remaining quantity or price tick")
                if ((order["direction"] == 1 and price > number(order["limit_price"]))
                        or (order["direction"] == -1 and price < number(order["limit_price"]))):
                    raise ValueError("Fill exceeds order limit")
                position += order["direction"] * Fraction(q)
                remaining -= Fraction(q)
                order["remaining_quantity"] = decimal_string(remaining)
                fills.append(dict(action, quantity=str(q), direction=order["direction"],
                                  original_quantity=order["quantity"],
                                  remaining_quantity=order["remaining_quantity"],
                                  specification={k: str(v) for k, v in spec.items()},
                                  notice_manifest_sha256=notice_sha256, scenario_sha256=scenario_sha256))
            if kind == "cancel" or not remaining:
                del pending[oid]
        else:
            raise ValueError("Unsupported action; only submit/cancel/fill declarations allowed")
        entry = dict(action)
        if kind in ("cancel", "fill"):
            entry["remaining_quantity"] = decimal_string(remaining)
        log.append(entry)
    advance(end - 1)
    if verify(archive, notice_sha256) != evidence:
        raise ValueError("Notice evidence changed during replay")
    return dict(version=VERSION, scope="DECLARED_INTRADAY_ORDER_POLICY_ONLY",
                policy_status="PASSED", acceptance_status="NOT_VALIDATED",
                historical_specs_verified=False, market_fills_verified=False,
                verified_coverage_seconds=0, notice_evidence=evidence,
                scenario_sha256=scenario_sha256, audit_log=log, fills=fills,
                pending_order_ids=sorted(pending),
                pending_quantities={oid: order["remaining_quantity"]
                                    for oid, order in sorted(pending.items())},
                net_position_contracts=dict(
                    numerator=position.numerator, denominator=position.denominator),
                source_sha256=digest(Path(__file__).read_bytes()))
