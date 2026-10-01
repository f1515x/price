"""Offline shared-account daily simulation; no exchange orders or margin model."""
import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

from history import DAY, load_snapshot
from indicators import calculate
from structure_history import replay
from trade_simulation import Config, proposals

VERSION = "daily-shared-account-v1"


@dataclass(frozen=True)
class PortfolioConfig:
    execution: Config
    max_total_risk: float
    max_same_direction: int

    def __post_init__(self):
        if not isinstance(self.execution, Config):
            raise ValueError("Explicit execution Config required")
        if (type(self.max_total_risk) not in (int, float)
                or not math.isfinite(self.max_total_risk) or not 0 < self.max_total_risk <= 1):
            raise ValueError("Total stop-risk fraction must be in (0, 1]")
        if type(self.max_same_direction) is not int or self.max_same_direction < 1:
            raise ValueError("Same-direction group limit must be a positive integer")


def simulate(asset_rows, candidates, config, groups, structures=None):
    """Requires an identical continuous UTC grid and explicit correlation groups.

    Alphabetical symbol priority is fixed before inspecting bars. All new fills
    precede all daily exits, so intraday exit proceeds cannot finance other fills.
    Existing positions are valued at today's open when allocating new risk.
    Pending orders reserve group slots; risk/exposure are rechecked on every fill.
    Contract multiplier/steps and signed funding are uniform research assumptions.
    """
    cfg = config.execution
    names = sorted(asset_rows)
    if not names or set(candidates) != set(names) or set(groups) != set(names):
        raise ValueError("Rows, candidates and explicit groups must cover the same assets")
    if any(not isinstance(groups[s], str) or not groups[s].strip() for s in names):
        raise ValueError("Nonempty correlation group required for every asset")
    if structures is not None and set(structures) != set(names):
        raise ValueError("Structures must cover every asset")
    rows = {s: list(asset_rows[s]) for s in names}
    timeline = [r["timestamp"] for r in rows[names[0]]]
    if not timeline or any(b != a+DAY for a, b in zip(timeline, timeline[1:])):
        raise ValueError("Continuous nonempty daily grid required; gaps are not interpolated")
    schedule = {}
    for s in names:
        calculate(rows[s])
        if any(r["symbol"] != s for r in rows[s]):
            raise ValueError("Asset key must match bar symbol")
        if rows[s] and rows[s][0]["market"] != rows[names[0]][0]["market"]:
            raise ValueError("Shared account requires one market/settlement convention")
        if [r["timestamp"] for r in rows[s]] != timeline:
            raise ValueError("Identical daily grids required; align verified snapshots explicitly")
        if structures is not None and len(structures[s]) != len(timeline):
            raise ValueError("Structure/bar length mismatch")
        for c in candidates[s]:
            idx = c["index"]
            if (type(idx) is not int or not 0 <= idx < len(timeline)
                    or type(c["direction"]) is not int or c["direction"] not in (1, -1)
                    or type(c["signal_time"]) is not int or c["signal_time"] != timeline[idx]+DAY
                    or not all(type(c[k]) in (int, float) and math.isfinite(c[k]) and c[k] > 0
                               for k in ("raw_weak_price", "strong_price", "atr"))):
                raise ValueError("Invalid candidate or signal before indexed daily close")
            schedule.setdefault((s, c["signal_time"]), []).append(dict(c))
    cash = peak = cfg.initial_equity
    halted = False
    pending, positions = {}, {}
    orders, trades, curve, allocations = [], [], [], []

    def finish(s, price, stamp, reason):
        nonlocal cash
        p = positions.pop(s)
        exit_price = price*(1-p["direction"]*cfg.slippage)
        units = p["quantity"]*cfg.multiplier
        gross = p["direction"]*units*(exit_price-p["entry_price"])
        exit_fee = units*exit_price*cfg.fee_rate
        net = gross-p["entry_fee"]-exit_fee-p["funding"]
        cash += gross-exit_fee
        trades.append(dict(p, symbol=s, exit_price=exit_price, exit_time=stamp, reason=reason,
                           gross_pnl=gross, exit_fee=exit_fee, net_pnl=net,
                           net_r=net/p["risk_budget"], holding_days=(stamp-p["entry_time"])/DAY))

    for i, stamp in enumerate(timeline):
        bars = {s: rows[s][i] for s in names}
        # Only information known at this open controls order admission/cancellation.
        for s in list(pending):
            o = pending[s]
            reason = None
            if stamp >= o["expires_at"]:
                reason = "EXPIRED"
            elif structures is not None and i:
                b = structures[s][i-1]
                if (b["status"] != "OK" or b["weak_type"] != ("low" if o["direction"] == 1 else "high")
                        or b["raw_weak_price"] != o["raw_weak_price"] or b["strong_price"] != o["strong_price"]):
                    reason = "STRUCTURE_INVALIDATED"
            if reason:
                pending.pop(s).update(status=reason, end_time=stamp)
        for s in names:
            for c in schedule.get((s, stamp), []):
                d = c["direction"]
                entry = c["raw_weak_price"]-d*cfg.entry_atr*c["atr"]
                stop = entry-d*cfg.stop_atr*c["atr"]
                target = entry+d*cfg.target_r*cfg.stop_atr*c["atr"]
                o = dict(c, symbol=s, group=groups[s], entry=entry, stop=stop, target=target,
                         expires_at=stamp+cfg.expiry_days*DAY, status="PENDING", admitted=False)
                orders.append(o)
                count = sum(groups[k] == groups[s] and v["direction"] == d
                            for pool in (pending, positions) for k, v in pool.items())
                reason = ("INVALID_PRICE" if min(entry, stop, target) <= 0 else
                          "RISK_HALTED" if halted or cash <= 0 else
                          "ASSET_BUSY" if s in pending or s in positions else
                          "CORRELATION_BLOCKED" if count >= config.max_same_direction else None)
                if reason:
                    o.update(status=reason, end_time=stamp)
                else:
                    o["admitted"] = True
                    pending[s] = o
        # Freeze open marks. Do not use other assets' future close or intraday exits.
        open_equity = cash + sum(p["direction"]*p["quantity"]*cfg.multiplier*
                                 (bars[s]["open"]-p["entry_price"]) for s, p in positions.items())
        gross_open = sum(p["quantity"]*cfg.multiplier*bars[s]["open"] for s, p in positions.items())
        used_risk = sum(p["modeled_stop_risk"] for p in positions.values())
        new_fees = 0
        filled = set()
        for s in names:
            if s not in pending:
                continue
            o, row = pending[s], bars[s]
            d, limit = o["direction"], o["entry"]
            if d*(row["open"]-o["stop"]) <= 0:
                pending.pop(s).update(status="PRICE_INVALIDATED", end_time=stamp)
                continue
            if not (row["low"] <= limit if d == 1 else row["high"] >= limit):
                continue
            base = min(row["open"], limit) if d == 1 else max(row["open"], limit)
            fill = min(limit, base*(1+cfg.slippage)) if d == 1 else max(limit, base*(1-cfg.slippage))
            stop_fill = o["stop"]*(1-d*cfg.slippage)
            unit_risk = (abs(fill-stop_fill)+cfg.fee_rate*(fill+stop_fill))*cfg.multiplier
            equity = max(0, open_equity-new_fees)
            budget = equity*cfg.risk_fraction
            risk_left = max(0, equity*config.max_total_risk-used_risk)
            exposure_left = max(0, equity*cfg.max_exposure-gross_open)
            # Allow for this fill's fee reducing equity and hence both caps.
            unit_fee = fill*cfg.multiplier*cfg.fee_rate
            qty = min(budget/unit_risk, risk_left/(unit_risk+unit_fee*config.max_total_risk),
                      exposure_left/(fill*cfg.multiplier+unit_fee*cfg.max_exposure))
            qty = math.floor(qty/cfg.quantity_step)*cfg.quantity_step
            pending.pop(s)
            if qty < cfg.min_quantity or qty <= 0:
                reason = "TOTAL_RISK_BLOCKED" if risk_left <= 0 else "TOTAL_EXPOSURE_BLOCKED" if exposure_left <= 0 else "QUANTITY_BLOCKED"
                o.update(status=reason, end_time=stamp)
                continue
            fee = qty*unit_fee
            positions[s] = dict(direction=d, entry_price=fill, stop=o["stop"], target=o["target"],
                                quantity=qty, risk_budget=budget, modeled_stop_risk=qty*unit_risk,
                                entry_fee=fee, funding=0, signal_time=o["signal_time"], entry_time=stamp)
            cash -= fee
            new_fees += fee
            gross_open += qty*fill*cfg.multiplier
            used_risk += qty*unit_risk
            o.update(status="FILLED", fill_price=fill, quantity=qty, end_time=stamp)
            filled.add(s)
            allocations.append(dict(timestamp=stamp, symbol=s, equity=open_equity-new_fees,
                                    gross_exposure=gross_open, modeled_stop_risk=used_risk))
        for s in list(positions):
            p, row = positions[s], bars[s]
            d = p["direction"]
            funding = d*p["quantity"]*cfg.multiplier*p["entry_price"]*cfg.funding_daily
            cash -= funding
            p["funding"] += funding
            stopped = row["low"] <= p["stop"] if d == 1 else row["high"] >= p["stop"]
            targeted = row["high"] >= p["target"] if d == 1 else row["low"] <= p["target"]
            if stopped:
                price = min(row["open"], p["stop"]) if d == 1 else max(row["open"], p["stop"])
                finish(s, price, stamp+DAY, "STOP")
            elif targeted and s not in filled:
                finish(s, p["target"], stamp+DAY, "TARGET")
            elif stamp+DAY >= p["entry_time"]+cfg.holding_days*DAY:
                finish(s, row["close"], stamp+DAY, "TIME_EXIT")
        if i == len(timeline)-1:
            for s in list(positions):
                finish(s, bars[s]["close"], stamp+DAY, "END_OF_SAMPLE")
            for o in pending.values():
                o.update(status="END_OF_SAMPLE", end_time=stamp+DAY)
            pending.clear()
        equity = cash+sum(p["direction"]*p["quantity"]*cfg.multiplier*(bars[s]["close"]-p["entry_price"])
                          for s, p in positions.items())
        peak = max(peak, equity)
        dd = max(0, 1-equity/peak)
        if dd >= cfg.max_drawdown:
            halted = True
            for o in pending.values():
                o.update(status="RISK_HALTED", end_time=stamp+DAY)
            pending.clear()
        curve.append(dict(timestamp=stamp+DAY, cash=cash, equity=equity, drawdown=dd, halted=halted,
                          gross_exposure=sum(p["quantity"]*cfg.multiplier*bars[s]["close"] for s, p in positions.items()),
                          positions=len(positions), pending=len(pending)))
    counts = dict(Counter(o["status"] for o in orders))
    admitted = sum(o["admitted"] for o in orders)
    return dict(version=VERSION, parameters=asdict(config), groups=dict(groups), orders=orders,
                trades=trades, equity_curve=curve, allocations=allocations,
                conclusion="DESCRIPTIVE_ONLY_NOT_VALIDATED",
                status="DESCRIPTIVE_ONLY" if len(trades) >= cfg.min_events else "INSUFFICIENT_TRADES",
                protocol=dict(priority="alphabetical_symbol_then_input_candidate_order",
                              accounting="shared_cash_open_marks_fills_before_all_daily_exits",
                              caps="fill_time_gross_not_net_and_sum_initial_modeled_stop_risk",
                              correlation="explicit_groups_same_direction_pending_and_positions",
                              gaps="reject_nonidentical_or_discontinuous_grids",
                              costs="uniform_contract_assumptions_signed_daily_funding_proxy",
                              drawdown="close_mark_halt_new_orders_existing_positions_continue"),
                summary=dict(candidates=len(orders), admitted=admitted, outcomes=counts, trades=len(trades),
                             fill_rate=counts.get("FILLED", 0)/admitted if admitted else None,
                             expiry_rate=counts.get("EXPIRED", 0)/admitted if admitted else None,
                             mean_net_pnl=mean(t["net_pnl"] for t in trades) if trades else None,
                             mean_net_r=mean(t["net_r"] for t in trades) if trades else None,
                             final_equity=cash, net_pnl=cash-cfg.initial_equity,
                             max_drawdown=max(p["drawdown"] for p in curve)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="JSON with execution, caps and assets: {symbol: {snapshot, group}}")
    parser.add_argument("--rule", choices=("legacy_proxy", "percentile_structure"), default="percentile_structure")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    path = Path(args.manifest).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    config = PortfolioConfig(Config(**manifest["execution"]), manifest["max_total_risk"], manifest["max_same_direction"])
    rows, candidates, structures, groups, quality = {}, {}, {}, {}, {}
    for s, asset in manifest["assets"].items():
        rows[s], quality[s] = load_snapshot(path.parent/asset["snapshot"])
        candidates[s] = proposals(rows[s], args.rule)
        structures[s] = replay(rows[s])
        groups[s] = asset["group"]
    result = simulate(rows, candidates, config, groups, structures)
    result.update(rule=args.rule, input_quality=quality,
                  manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  code_sha256={n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                               for n in ("portfolio_simulation.py", "trade_simulation.py", "event_study.py",
                                         "history.py", "indicators.py", "structure_history.py", "smc.py")})
    with Path(args.output).open("x", encoding="utf-8") as target:
        target.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
