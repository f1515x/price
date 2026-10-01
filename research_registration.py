"""Freeze a prospective M6 restart; never run or approve a trading strategy."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from event_study import Config as EventConfig
from history import DAY, date_timestamp
from indicators import Config as IndicatorConfig
from m6_research import variants
from research_config import _object, _section
from research_decision import close_hypothesis, digest
from structure_history import Config as StructureConfig
from trade_simulation import Config as ExecutionConfig

VERSION = "m6-prospective-registration-v1"


def read_json(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    return raw, value


def validate(protocol, previous, exposed_end, now):
    keys = {"version", "hypothesis_id", "mechanism", "primary_rule", "baseline_rule",
            "assets", "groups", "execution", "acceptance", "max_total_risk",
            "max_same_direction", "embargo_days", "test_days", "test_folds",
            "test_start", "indicators", "structures", "events"}
    if not isinstance(protocol, dict) or set(protocol) != keys or protocol["version"] != VERSION:
        raise ValueError("Expected prospective registration schema")
    for key in ("hypothesis_id", "mechanism"):
        if not isinstance(protocol[key], str) or not protocol[key].strip():
            raise ValueError("A new hypothesis and mechanism are required")
    if protocol["hypothesis_id"] == previous["version"] + ":percentile_structure:base":
        raise ValueError("Terminated hypothesis cannot be restarted under the same ID")
    if protocol["primary_rule"] != "percentile_move" or protocol["baseline_rule"] != "legacy_proxy":
        raise ValueError("This restart tests percentile_move against the original legacy baseline")
    # Preserve every original threshold and risk/execution value. This is a
    # signal hypothesis, not a search over previously profitable parameters.
    for key in ("assets", "groups", "execution", "acceptance", "max_total_risk",
                "max_same_direction", "embargo_days", "test_days"):
        if json.dumps(protocol[key], sort_keys=True, allow_nan=False) != json.dumps(previous[key], sort_keys=True, allow_nan=False):
            raise ValueError("Original parameters must be preserved: " + key)
    execution = _section(ExecutionConfig, protocol["execution"])
    for key, cls in (("indicators", IndicatorConfig), ("structures", StructureConfig), ("events", EventConfig)):
        parsed = _section(cls, protocol[key])
        if asdict(parsed) != asdict(cls()):
            raise ValueError("Restart preserves original feature defaults: " + key)
    if type(protocol["test_folds"]) is not int or protocol["test_folds"] != 5:
        raise ValueError("Five fixed test folds required; no optional stopping")
    lifetime = max(cfg.expiry_days + cfg.holding_days for _, cfg in variants(execution))
    if type(protocol["embargo_days"]) is not int or protocol["embargo_days"] < lifetime:
        raise ValueError("Embargo must cover every parameter variant")
    start = date_timestamp(protocol["test_start"])
    # Even today's partly observed daily bar is development data. Test signal
    # bars start after both the exposed history and registration-day embargo.
    first_unobserved_day = (int(now.timestamp()) // DAY + 1) * DAY
    if start < max(exposed_end, first_unobserved_day) + protocol["embargo_days"] * DAY:
        raise ValueError("Test data must be future, unexposed and embargoed")
    return [dict(test_start=start + i * protocol["test_days"] * DAY,
                 test_end=start + (i + 1) * protocol["test_days"] * DAY)
            for i in range(protocol["test_folds"])]


def register(candidate_path, report_path, previous_path, expected_hash, output_path, *, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Registration requires a timezone-aware clock")
    now = now.astimezone(timezone.utc)
    decision = close_hypothesis(report_path, previous_path, expected_hash, now.date().isoformat())
    raw, protocol = read_json(candidate_path)
    _, previous = read_json(previous_path)
    bounds = validate(protocol, previous, decision["exposed_history_end_exclusive"], now)
    result = dict(version=VERSION, status="REGISTERED_AWAITING_FUTURE_DATA",
                  registered_at=now.isoformat(), protocol=protocol, folds=bounds,
                  candidate_sha256=digest(raw),
                  predecessor=decision,
                  source_sha256={p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))},
                  variants=[dict(name=name, execution=asdict(cfg))
                            for name, cfg in variants(ExecutionConfig(**protocol["execution"]))],
                  evaluation_policy=dict(
                      fixed_parameters=True, test_selection=False, early_promotion=False,
                      development_history_end_exclusive=decision["exposed_history_end_exclusive"],
                      warmup_only_before_test=True, partition_capital="independent_equal_capital",
                      censor_days=protocol["embargo_days"],
                      signal_bars_must_start_within_fold=True,
                      historical_specs_required=True, exact_cost_evidence_required=True,
                      missing_evidence_status="NOT_VALIDATED",
                      unresolved=["historical specifications", "exact fees/slippage/settlement prices",
                                  "prospective runner and independent future outcomes"],
                      baseline_difference="local 30d legacy proxy; not TradingView Perf.1M",
                      no_orders=True),
                  limitations=["Local timestamp and hashes are not an external trusted timestamp.",
                               "Registration provides no results or strategy validation.",
                               "Previously inspected history may only provide causal warmup/development.",
                               "New primary rule retains aligned confirmed SMC for executable proposals.",
                               "44-day time clusters remain a proxy, not proven statistical independence."])
    with Path(output_path).open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate")
    parser.add_argument("previous_report")
    parser.add_argument("previous_protocol")
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = register(args.candidate, args.previous_report, args.previous_protocol,
                      args.expected_report_sha256, args.output)
    print(json.dumps(dict(status=result["status"], candidate_sha256=result["candidate_sha256"],
                          registered_at=result["registered_at"], folds=result["folds"])))


if __name__ == "__main__":
    main()
