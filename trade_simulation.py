"""Offline daily limit-order simulation; research only, never places orders."""
import argparse
from collections import Counter
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

from event_study import Config as EventConfig, signals, study
from history import DAY, load_snapshot
from indicators import Config as IndicatorConfig, calculate
from structure_history import Config as StructureConfig, replay
from funding_history import validate_execution_funding, funding_charge

VERSION = "daily-limit-simulation-v1"


@dataclass(frozen=True)
class Config:
    initial_equity: float
    risk_fraction: float
    max_exposure: float
    max_drawdown: float
    entry_atr: float = 0.5
    stop_atr: float = 1.5
    target_r: float = 2
    expiry_days: int = 7
    holding_days: int = 30
    fee_rate: float = 0.0005
    slippage: float = 0.0005
    funding_daily: float = 0.0003
    multiplier: float = 1
    quantity_step: float = 0.000001
    min_quantity: float = 0.000001
    min_events: int = 30
    price_tick: float = 0
    max_quantity: float = 1e30

    def __post_init__(self):
        values = asdict(self)
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values.values()):
            raise ValueError("All simulation parameters must be finite numbers")
        for key in ("initial_equity", "risk_fraction", "max_exposure", "max_drawdown",
                    "stop_atr", "target_r", "multiplier", "quantity_step", "min_quantity", "max_quantity"):
            if values[key] <= 0:
                raise ValueError("Positive parameter required: " + key)
        if self.risk_fraction > 1 or self.max_drawdown >= 1 or self.slippage >= 1:
            raise ValueError("Invalid risk/drawdown/slippage fraction")
        if self.max_quantity < self.min_quantity:
            raise ValueError("Maximum quantity is below minimum")
        if any(values[k] < 0 for k in ("entry_atr", "fee_rate", "slippage", "price_tick")):
            raise ValueError("Negative entry offset or transaction cost")
        for key in ("expiry_days", "holding_days", "min_events"):
            if type(values[key]) is not int or values[key] < 1:
                raise ValueError("Positive integer required: " + key)


def round_step(value, step, up=False):
    if not step:
        return value
    a, b = Decimal(str(value)), Decimal(str(step))
    return float((a / b).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * b)


def order_prices(candidate, config):
    d, atr = candidate["direction"], Decimal(str(candidate["atr"]))
    entry = Decimal(str(candidate["raw_weak_price"])) - d * Decimal(str(config.entry_atr)) * atr
    stop = entry - d * Decimal(str(config.stop_atr)) * atr
    target = entry + d * Decimal(str(config.target_r)) * Decimal(str(config.stop_atr)) * atr
    # Buy limits round down, sell limits up. Stops move away from entry;
    # targets round towards entry. Reject any collapsed stop/target later.
    return (float(round_step(entry, config.price_tick, d == -1)),
            float(round_step(stop, config.price_tick, d == -1)),
            float(round_step(target, config.price_tick, d == -1)))


def proposals(rows, rule, indicator_config=IndicatorConfig(), structure_config=StructureConfig(),
              *, indicators=None, structures=None):
    """Only confirmed, direction-aligned structures; no forward-price inputs."""
    output = []
    indicators = calculate(rows, indicator_config) if indicators is None else indicators
    structures = replay(rows, structure_config) if structures is None else structures
    for i, (a, b) in enumerate(zip(indicators, structures)):
        d = signals(a, b, EventConfig())[rule]
        if (d and b["status"] == "OK" and b["weak_type"] == ("low" if d == 1 else "high")
                and a["atr"] is not None and a["atr"] > 0):
            output.append(dict(index=i, signal_time=a["signal_time"], direction=d,
                               raw_weak_price=b["raw_weak_price"], strong_price=b["strong_price"],
                               atr=a["atr"]))
    return output


def simulate(rows, candidates, config, structures=None, *, funding=None):
    """Single-asset isolated capital. At most one pending order or position.

    All assets in this run share one correlation bucket (one asset only).
    Entry-bar targets are deferred: OHLC cannot prove target happened after fill.
    Entry-bar stops are always applied. Subsequent simultaneous hits use stop first.
    Funding defaults to a constant signed daily proxy. Explicit historical
    events use mark prices/bounds and debit-only ambiguous ownership days.
    """
    rows = list(rows)
    calculate(rows)  # reject invalid identity, timestamps and OHLCV
    if not rows:
        raise ValueError("Empty simulation")
    symbol = rows[0]["symbol"]
    if funding is not None:
        validate_execution_funding({symbol: rows}, {symbol: funding})
    by_time = {}
    for c in candidates:
        if (c["direction"] not in (1, -1) or c["signal_time"] % DAY
                or not all(math.isfinite(c[k]) and c[k] > 0 for k in ("raw_weak_price", "strong_price", "atr"))):
            raise ValueError("Invalid candidate")
        if c["index"] < 0 or c["index"] >= len(rows) or c["signal_time"] != rows[c["index"]]["timestamp"] + DAY:
            raise ValueError("Candidate must be known after its indexed bar closes")
        by_time.setdefault(c["signal_time"], []).append(c)
    if structures is not None and len(structures) != len(rows):
        raise ValueError("Structure/bar length mismatch")
    cash = peak = config.initial_equity
    pending = position = None
    halted = False
    orders, trades, curve = [], [], []

    def finish(price, stamp, reason):
        nonlocal cash, position
        p = position
        exit_price = price * (1 - p["direction"] * config.slippage)
        exposure = p["quantity"] * config.multiplier
        gross = p["direction"] * exposure * (exit_price - p["entry_price"])
        exit_fee = exposure * exit_price * config.fee_rate
        net = gross - p["entry_fee"] - exit_fee - p["funding"]
        cash += gross - exit_fee
        trades.append(dict(p, exit_price=exit_price, exit_time=stamp, reason=reason,
                           gross_pnl=gross, exit_fee=exit_fee, net_pnl=net,
                           net_r=net / p["risk_budget"], holding_days=(stamp-p["entry_time"])/DAY))
        position = None

    for i, row in enumerate(rows):
        stamp = row["timestamp"]
        # Unknown prices are never interpolated; flatten at last observed close.
        if i and stamp != rows[i-1]["timestamp"] + DAY:
            if pending:
                pending.update(status="DATA_GAP", end_time=rows[i-1]["timestamp"]+DAY)
                pending = None
            if position:
                finish(rows[i-1]["close"], rows[i-1]["timestamp"]+DAY, "DATA_GAP")
        # Only yesterday's confirmed structure can cancel today's resting order.
        if pending and structures is not None and i:
            b = structures[i-1]
            c = pending
            if (b["status"] != "OK" or b["weak_type"] != ("low" if c["direction"] == 1 else "high")
                    or b["raw_weak_price"] != c["raw_weak_price"] or b["strong_price"] != c["strong_price"]):
                pending.update(status="STRUCTURE_INVALIDATED", end_time=stamp)
                pending = None
        if pending and stamp >= pending["expires_at"]:
            pending.update(status="EXPIRED", end_time=stamp)
            pending = None
        for candidate in by_time.get(stamp, []):
            d = candidate["direction"]
            entry, stop, target = order_prices(candidate, config)
            order = dict(candidate, entry=entry, stop=stop, target=target,
                         expires_at=stamp+config.expiry_days*DAY, status="PENDING", admitted=False)
            orders.append(order)
            if min(entry, stop, target) <= 0 or d*(entry-stop) <= 0 or d*(target-entry) <= 0:
                order.update(status="INVALID_PRICE", end_time=stamp)
            elif halted or cash <= 0:
                order.update(status="RISK_HALTED", end_time=stamp)
            elif pending or position:
                order.update(status="EXPOSURE_BLOCKED", end_time=stamp)
            else:
                order["admitted"] = True
                pending = order
        filled_today = False
        if pending:
            d, limit = pending["direction"], pending["entry"]
            if d*(row["open"]-pending["stop"]) <= 0:
                pending.update(status="PRICE_INVALIDATED", end_time=stamp)
                pending = None
        if pending:
            d, limit = pending["direction"], pending["entry"]
            touched = row["low"] <= limit if d == 1 else row["high"] >= limit
            if touched:
                # Better open allowed; entry slippage cannot violate the limit.
                base = min(row["open"], limit) if d == 1 else max(row["open"], limit)
                fill = min(limit, base*(1+config.slippage)) if d == 1 else max(limit, base*(1-config.slippage))
                stop_fill = pending["stop"] * (1-d*config.slippage)
                risk_per_unit = (abs(fill-stop_fill) + config.fee_rate*(fill+stop_fill)) * config.multiplier
                budget = cash * config.risk_fraction
                qty = min(budget/risk_per_unit, cash*config.max_exposure/(fill*config.multiplier), config.max_quantity)
                qty = round_step(qty, config.quantity_step)
                if qty < config.min_quantity:
                    pending.update(status="QUANTITY_BLOCKED", end_time=stamp)
                else:
                    fee = qty*config.multiplier*fill*config.fee_rate
                    position = dict(direction=d, entry_price=fill, stop=pending["stop"], target=pending["target"],
                                    quantity=qty, risk_budget=budget, entry_fee=fee, funding=0,
                                    signal_time=pending["signal_time"], entry_time=stamp)
                    cash -= fee
                    pending.update(status="FILLED", fill_price=fill, quantity=qty, end_time=stamp)
                    filled_today = True
                pending = None
        if position:
            p = position
            d = p["direction"]
            stopped = row["low"] <= p["stop"] if d == 1 else row["high"] >= p["stop"]
            targeted = row["high"] >= p["target"] if d == 1 else row["low"] <= p["target"]
            # Charge one whole daily proxy period, including any partial day.
            amount = (funding_charge(funding[stamp], d, p["quantity"]*config.multiplier,
                                    ambiguous=filled_today or stopped or (targeted and not filled_today),
                                    new_position=filled_today, stamp=stamp) if funding is not None else
                      d * p["quantity"] * config.multiplier * p["entry_price"] * config.funding_daily)
            cash -= amount
            p["funding"] += amount
            if stopped:
                price = min(row["open"], p["stop"]) if d == 1 else max(row["open"], p["stop"])
                finish(price, stamp+DAY, "STOP")
            elif targeted and not filled_today:
                finish(p["target"], stamp+DAY, "TARGET")
            elif stamp+DAY >= p["entry_time"]+config.holding_days*DAY:
                finish(row["close"], stamp+DAY, "TIME_EXIT")
        if i == len(rows)-1:
            if position:
                finish(row["close"], stamp+DAY, "END_OF_SAMPLE")
            if pending:
                pending.update(status="END_OF_SAMPLE", end_time=stamp+DAY)
                pending = None
        unrealized = (position["direction"]*position["quantity"]*config.multiplier*(row["close"]-position["entry_price"])) if position else 0
        equity = cash + unrealized
        peak = max(peak, equity)
        dd = max(0, 1-equity/peak)
        if dd >= config.max_drawdown:
            halted = True
            if pending:
                pending.update(status="RISK_HALTED", end_time=stamp+DAY)
                pending = None
        curve.append(dict(timestamp=stamp+DAY, equity=equity, drawdown=dd, halted=halted))
    counts = dict(Counter(o["status"] for o in orders))
    admitted = sum(o["admitted"] for o in orders)
    return dict(parameters=asdict(config), bars=len(rows), orders=orders, trades=trades, equity_curve=curve,
                funding_model=("historical_rates_conservative_daily_mark_bounds" if any("mark_high" in e for events in funding.values() for e in events)
                               else "historical_rates_mark_open_conservative_ambiguous_days") if funding is not None else "signed_daily_proxy",
                status="DESCRIPTIVE_ONLY" if len(trades) >= config.min_events else "INSUFFICIENT_TRADES",
                summary=dict(candidates=len(orders), admitted=admitted, outcomes=counts, trades=len(trades),
                             fill_rate=counts.get("FILLED", 0)/admitted if admitted else None,
                             unfilled_rate=1-counts.get("FILLED", 0)/admitted if admitted else None,
                             expiry_rate=counts.get("EXPIRED", 0)/admitted if admitted else None,
                             mean_net_pnl=mean(t["net_pnl"] for t in trades) if trades else None,
                             mean_net_r=mean(t["net_r"] for t in trades) if trades else None,
                             mean_holding_days=mean(t["holding_days"] for t in trades) if trades else None,
                             net_pnl=cash-config.initial_equity, final_equity=cash,
                             max_drawdown=max(p["drawdown"] for p in curve)))


def research(rows, config, indicator_config=IndicatorConfig(), structure_config=StructureConfig()):
    rows = list(rows)
    events = study(rows, indicator_config=indicator_config, structure_config=structure_config)
    split = events["split_time"]
    eligible = {c["index"] for c in events["candidates"]}
    structures = replay(rows, structure_config)
    experiments = []
    variants = [("base", config)]
    for key, values in (("entry_atr", (0, 1)), ("stop_atr", (1, 2)), ("target_r", (1, 3)),
                        ("expiry_days", (3, 14)), ("fee_rate", (config.fee_rate*2,)),
                        ("slippage", (config.slippage*2,)), ("funding_daily", (config.funding_daily*2,))):
        variants.extend((key+"="+str(v), replace(config, **{key: v})) for v in values)
    for rule in ("legacy_proxy", "percentile_structure"):
        candidates = [c for c in proposals(rows, rule, indicator_config, structure_config) if c["index"] in eligible]
        for partition in ("train", "test"):
            indices = [i for i, r in enumerate(rows) if split is not None and
                       (r["timestamp"] < split if partition == "train" else r["timestamp"] >= split)]
            if not indices:
                continue
            left, right = indices[0], indices[-1]+1
            selected = [dict(c, index=c["index"]-left) for c in candidates
                        if left <= c["index"] < right and
                        (c["signal_time"] < split if partition == "train" else c["signal_time"] >= split)]
            # Test starts with independent capital and no inherited train orders.
            for name, cfg in variants:
                result = simulate(rows[left:right], selected, cfg, structures[left:right])
                experiments.append(dict(rule=rule, partition=partition, variant=name, **result))
    return dict(version=VERSION, parameters=asdict(config), indicator_parameters=asdict(indicator_config),
                structure_parameters=asdict(structure_config), split_time=split, eligible=len(eligible), experiments=experiments,
                conclusion="DESCRIPTIVE_ONLY_NOT_VALIDATED", protocol=dict(
                    entry="limit_from_next_day_no_limit_violation", same_bar="stop_first_entry_bar_target_deferred",
                    stop_gap="open_if_worse_plus_adverse_slippage", funding="constant_signed_daily_entry_notional_proxy",
                    portfolio="single_asset_isolated_capital_one_active_order_or_position",
                    exposure="entry_notional_cap_no_adding_positions", drawdown="daily_close_mark_halts_new_orders",
                    split="M4_common_eligible_70_30_independent_capital_boundary_liquidation",
                    legacy="M4_local_30d_daily_proxy_same_raw_weak_ATR_execution",
                    gaps="last_observed_close_forced_exit_unknown_interval_not_modeled"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot")
    parser.add_argument("--config", required=True, help="Explicit research execution/risk JSON")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = Config(**json.loads(Path(args.config).read_text(encoding="utf-8")))
    rows, quality = load_snapshot(args.snapshot)
    result = research(rows, config)
    result.update(input_sha256=quality["sha256"], input_quality=quality,
                  config_sha256=hashlib.sha256(Path(args.config).read_bytes()).hexdigest())
    result["code_sha256"] = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                             for n in ("trade_simulation.py", "event_study.py", "history.py", "indicators.py", "structure_history.py", "smc.py")}
    with Path(args.output).open("x", encoding="utf-8") as target:
        target.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(experiments=len(result["experiments"]), conclusion=result["conclusion"])))


if __name__ == "__main__":
    main()
