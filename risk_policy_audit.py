"""Audit recorded M6 research risk controls without rerunning or selecting a strategy."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path

from history import DAY
from research_decision import close_hypothesis, digest

RISK_FIELDS = ("initial_equity", "risk_fraction", "max_exposure", "max_drawdown")


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Invalid numeric risk evidence")
    return value


def equal(actual, expected, label):
    if not math.isclose(number(actual), number(expected), rel_tol=1e-9, abs_tol=1e-8):
        raise ValueError(label)


def audit_run(run, protocol):
    """Check allocation-time caps, close-based halt, group slots and reconciliation.

    Close-mark exposure can grow beyond an entry cap. Realized losses can exceed
    modeled stop risk through gaps/funding. Neither is treated as a hard loss cap.
    """
    params = run["parameters"]
    base = protocol["execution"]
    for key in ("max_total_risk", "max_same_direction"):
        if params[key] != protocol[key]:
            raise ValueError("Portfolio risk policy differs from protocol")
    configs = [params["execution"], *run["execution_by_asset"].values()]
    configs.extend(p["config"] for periods in (run["execution_periods"] or {}).values() for p in periods)
    for cfg in configs:
        if any(cfg[k] != base[k] for k in RISK_FIELDS):
            raise ValueError("Execution risk policy differs from protocol")
    if run["groups"] != protocol["groups"]:
        raise ValueError("Correlation groups differ from protocol")

    for allocation in run["allocations"]:
        equity = number(allocation["equity"])
        if equity <= 0:
            raise ValueError("Allocation with nonpositive equity")
        for key, limit in (("gross_exposure", base["max_exposure"]),
                           ("modeled_stop_risk", protocol["max_total_risk"])):
            value = number(allocation[key])
            if value < 0 or value > equity * limit + 1e-8:
                raise ValueError("Allocation cap exceeded: " + key)

    curve = run["equity_curve"]
    if not curve:
        raise ValueError("Missing equity curve")
    peak = base["initial_equity"]
    halted = False
    first_halt = None
    previous = None
    max_dd = 0
    for point in curve:
        stamp = point["timestamp"]
        if type(stamp) is not int or (previous is not None and stamp != previous + DAY):
            raise ValueError("Invalid equity timeline")
        previous = stamp
        equity = number(point["equity"])
        peak = max(peak, equity)
        dd = max(0, 1 - equity / peak)
        equal(point["drawdown"], dd, "Drawdown differs from equity high water mark")
        max_dd = max(max_dd, dd)
        halted = halted or dd >= base["max_drawdown"]
        if type(point["halted"]) is not bool or point["halted"] != halted:
            raise ValueError("Drawdown halt missing or reset")
        if halted:
            first_halt = stamp if first_halt is None else first_halt
            if point["pending"] != 0:
                raise ValueError("Pending orders remain after halt")

    trades = {}
    for trade in run["trades"]:
        identity = (trade["symbol"], trade["signal_time"])
        if identity in trades:
            raise ValueError("Duplicate trade identity")
        trades[identity] = trade
        if number(trade["modeled_stop_risk"]) > number(trade["risk_budget"]) + 1e-8:
            raise ValueError("Single trade modeled risk exceeds budget")
        if first_halt is not None and trade["entry_time"] >= first_halt:
            raise ValueError("New fill after account halt")

    # An admitted order occupies a group/direction slot until cancellation, or
    # until its filled position exits. End events precede starts at the same open.
    events = []
    filled = set()
    for order in run["orders"]:
        if not order["admitted"]:
            continue
        if first_halt is not None and order["signal_time"] >= first_halt:
            raise ValueError("New order admitted after account halt")
        if order["group"] != protocol["groups"][order["symbol"]]:
            raise ValueError("Order group differs from protocol")
        end = order["end_time"]
        if order["status"] == "FILLED":
            identity = (order["symbol"], order["signal_time"])
            if identity in filled or identity not in trades:
                raise ValueError("Filled order/trade mismatch")
            filled.add(identity)
            trade = trades[identity]
            equal(trade["entry_time"], end, "Trade fill time differs from order")
            equal(trade["quantity"], order["quantity"], "Trade quantity differs from order")
            end = trade["exit_time"]
        if end < order["signal_time"]:
            raise ValueError("Invalid slot interval")
        if end > order["signal_time"]:
            slot = (order["group"], order["direction"])
            events.extend(((order["signal_time"], 1, slot), (end, -1, slot)))
    if filled != set(trades):
        raise ValueError("Trade lacks admitted filled order")
    slots = Counter()
    for _, change, slot in sorted(events):
        slots[slot] += change
        if not 0 <= slots[slot] <= protocol["max_same_direction"]:
            raise ValueError("Same-direction group slot limit exceeded")

    summary = run["summary"]
    equal(summary["max_drawdown"], max_dd, "Maximum drawdown mismatch")
    equal(summary["final_equity"], curve[-1]["equity"], "Final equity mismatch")
    equal(summary["final_equity"], base["initial_equity"] + sum(number(t["net_pnl"]) for t in trades.values()),
          "Trade/equity reconciliation failed")
    return dict(allocations=len(run["allocations"]), trades=len(trades), curve_points=len(curve),
                max_drawdown=max_dd, halted=halted)


def audit(report_path, protocol_path, expected_report_sha256, decision_date):
    decision = close_hypothesis(report_path, protocol_path, expected_report_sha256, decision_date)
    report = json.loads(Path(report_path).read_bytes())
    protocol = json.loads(Path(protocol_path).read_bytes())
    # Bind the reviewed implementation as well as the original report/protocol.
    for name in ("portfolio_simulation.py", "trade_simulation.py", "m6_research.py"):
        if digest(Path(__file__).with_name(name).read_bytes()) != report["code_sha256"][name]:
            raise ValueError("Reviewed execution source differs: " + name)
    if not report["experiments"]:
        raise ValueError("Missing portfolio experiments")
    checks = [dict(variant=e["variant"], rule=e["rule"], partition=e["partition"],
                   fold=e["fold"], cost_mode=e["cost_mode"], **audit_run(e["result"], protocol))
              for e in report["experiments"]]
    return dict(version="research-risk-policy-v1", decision_date=decision_date,
                scope="Retrospective research controls; no live trading authorization",
                evidence=dict(report_sha256=expected_report_sha256,
                              protocol_sha256=decision["evidence"]["protocol_sha256"],
                              audit_code_sha256=digest(Path(__file__).read_bytes())),
                risk={k: protocol["execution"][k] for k in RISK_FIELDS},
                max_total_risk=protocol["max_total_risk"], max_same_direction=protocol["max_same_direction"],
                groups=protocol["groups"], acceptance_thresholds=protocol["acceptance"],
                acceptance=decision["acceptance"], hypothesis_status=decision["decision"],
                audited_runs=len(checks), allocations=sum(c["allocations"] for c in checks),
                halted_runs=sum(c["halted"] for c in checks), runs=checks,
                limitations=["Allocation caps apply at fills, not every subsequent market mark.",
                             "Modeled stop risk excludes funding and cannot cap gap losses.",
                             "Daily close halt cancels pending orders; existing positions continue.",
                             "No margin/liquidation model or live execution approval.",
                             "Original historical specification and exact-cost evidence gaps remain."])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("protocol")
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--decision-date", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(args.report, args.protocol, args.expected_report_sha256, args.decision_date)
    with Path(args.output).open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: result[k] for k in ("audited_runs", "allocations", "halted_runs", "hypothesis_status")}))


if __name__ == "__main__":
    main()
