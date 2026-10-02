"""Fail closed on known notice changes in daily offline execution scenarios."""
import argparse
from decimal import Decimal
from pathlib import Path

from contract_specs import digest, encoded
from execution_history import at_time, validate_periods
from historical_notices import verify
from history import DAY
from joint_execution import load, simulate_joint
from kline import normalize_symbol

VERSION = "daily-notice-policy-v1"


class NoticePolicyError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__("Daily notice policy blocked: " + ", ".join(
            f"{b['event_id']}:{b['reason']}" for b in report["blockers"]))


def inspect(archive, expected_sha256, symbols, start, end, periods=None):
    """Check event-local constraints only; absence of events proves no coverage."""
    if any(type(t) is not int or t < 0 or t % DAY for t in (start, end)) or start >= end:
        raise ValueError("Increasing UTC daily boundaries required")
    symbols = list(symbols)
    if (not symbols or any(not isinstance(s, str) or normalize_symbol(s) != s for s in symbols)
            or len(set(symbols)) != len(symbols)):
        raise ValueError("Unique canonical symbols required")
    evidence = verify(archive, expected_sha256)
    if periods is not None:
        if set(periods) != set(symbols):
            raise ValueError("Execution periods must match requested symbols")
        for ps in periods.values():
            validate_periods(ps, start, end)
    blockers, checked, outside = [], [], []
    for event in evidence["events"]:
        t = event["effective_timestamp"]
        if event["symbol"] not in symbols or not start <= t < end:
            outside.append(event["id"])
            continue
        check = dict(event_id=event["id"], symbol=event["symbol"], field=event["field"],
                     effective_timestamp=t, before=event["before"], after=event["after"])
        checked.append(check)
        if t % DAY:
            blockers.append(dict(check, reason="INTRADAY_CHANGE_UNRESOLVABLE_WITH_DAILY_BARS",
                                 bar_start=t - t % DAY, bar_end=t - t % DAY + DAY))
        elif periods is None:
            blockers.append(dict(check, reason="DAILY_SPECIFICATION_MAPPING_REQUIRED"))
        else:
            # Validate only the immediate sides of an event, never extend its validity.
            sides = [("after", t)] + ([("before", t - 1)] if t > start else [])
            for side, stamp in sides:
                value = Decimal(str(getattr(at_time(periods[event["symbol"]], stamp), event["field"])))
                if value != Decimal(event[side]):
                    blockers.append(dict(check, reason="NOTICE_SPECIFICATION_CONFLICT", side=side,
                                         declared_value=str(value), notice_value=event[side]))
    return dict(version=VERSION, scope="DAILY_NOTICE_SCENARIO_GATE_ONLY", start=start, end=end,
                symbols=symbols, policy_status="BLOCKED" if blockers else "PASSED",
                checked_events=checked, ignored_event_ids=outside, blockers=blockers,
                notice_evidence=evidence, historical_specs_verified=False,
                verified_coverage_seconds=0, acceptance_status="NOT_VALIDATED",
                source_sha256=digest(Path(__file__).read_bytes()))


def simulate_notice_joint(asset_rows, candidates, config, groups, *, notice_archive,
                          notice_sha256, structures=None, **inputs):
    """Gate the joint scenario and recheck notice bytes before returning trades."""
    rows = {s: list(bars) for s, bars in asset_rows.items()}
    if not rows or any(not bars for bars in rows.values()):
        raise ValueError("Nonempty bars required for every asset")
    first = next(iter(rows.values()))
    start, end = first[0]["timestamp"], first[-1]["timestamp"] + DAY
    # Resolve intraday uncertainty before reading executable declarations.
    preliminary = inspect(notice_archive, notice_sha256, rows, start, end)
    if any(b["reason"] == "INTRADAY_CHANGE_UNRESOLVABLE_WITH_DAILY_BARS"
           for b in preliminary["blockers"]):
        raise NoticePolicyError(preliminary)
    periods, _, _ = load(config.execution, rows, start, end, **inputs)
    report = inspect(notice_archive, notice_sha256, rows, start, end, periods)
    if report["blockers"]:
        raise NoticePolicyError(report)
    result = simulate_joint(rows, candidates, config, groups, structures, **inputs)
    if inspect(notice_archive, notice_sha256, rows, start, end, periods) != report:
        raise ValueError("Notice evidence changed during simulation")
    result["daily_notice_policy"] = report
    for trade in result["trades"]:
        trade["notice_manifest_sha256"] = notice_sha256
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = inspect(args.archive, args.expected_sha256, args.symbols, args.start, args.end)
    with Path(args.output).open("xb") as target:
        target.write(encoded(report))
    print(report["policy_status"])
    return 2 if report["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
