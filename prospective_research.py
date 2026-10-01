"""Execute the frozen M6 restart after all five future folds close; no orders."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from event_study import Config as EventConfig
from funding_history import load_snapshot as load_funding, execution_funding, load_marks
from history import DAY, load_snapshot
from indicators import Config as IndicatorConfig, calculate
from m6_research import aggregate, acceptance, periods_for, restrict, sha, variants
from portfolio_simulation import PortfolioConfig, simulate
from prospective_evidence import assess as assess_evidence
from research_registration import VERSION as REGISTRATION_VERSION, read_json, validate
from structure_history import Config as StructureConfig, replay
from trade_simulation import Config, proposals

VERSION = "m6-prospective-runner-v2"
SOURCE = Path(__file__).resolve().parent


def canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


def load_registration(registration_path, candidate_path, previous_path, expected_sha256):
    """Bind the reviewed record, original protocol, variants and frozen code."""
    if sha(registration_path) != expected_sha256:
        raise ValueError("Registration SHA-256 differs from reviewed evidence")
    _, record = read_json(registration_path)
    _, candidate = read_json(candidate_path)
    _, previous = read_json(previous_path)
    if (record.get("version") != REGISTRATION_VERSION
            or record.get("status") != "REGISTERED_AWAITING_FUTURE_DATA"):
        raise ValueError("Expected frozen prospective registration")
    if (record["candidate_sha256"] != sha(candidate_path)
            or canonical(record["protocol"]) != canonical(candidate)):
        raise ValueError("Candidate differs from frozen registration")
    predecessor = record["predecessor"]
    if (predecessor["decision"] != "TERMINATED"
            or predecessor["evidence"]["protocol_sha256"] != sha(previous_path)
            or canonical(predecessor["preserved_acceptance_thresholds"]) != canonical(previous["acceptance"])):
        raise ValueError("Original terminated protocol differs from registration")
    registered = datetime.fromisoformat(record["registered_at"])
    if registered.tzinfo is None or registered.utcoffset() is None:
        raise ValueError("Registration clock must be timezone-aware")
    bounds = validate(candidate, previous, predecessor["exposed_history_end_exclusive"], registered)
    expected_variants = [dict(name=name, execution=asdict(cfg))
                         for name, cfg in variants(Config(**candidate["execution"]))]
    if canonical(record["folds"]) != canonical(bounds):
        raise ValueError("Frozen fold boundaries differ")
    if canonical(record["variants"]) != canonical(expected_variants):
        raise ValueError("Frozen execution variants differ")
    policy = dict(fixed_parameters=True, test_selection=False, early_promotion=False,
                  development_history_end_exclusive=predecessor["exposed_history_end_exclusive"],
                  warmup_only_before_test=True, partition_capital="independent_equal_capital",
                  censor_days=candidate["embargo_days"], signal_bars_must_start_within_fold=True,
                  historical_specs_required=True, exact_cost_evidence_required=True,
                  missing_evidence_status="NOT_VALIDATED", no_orders=True)
    if any(canonical(record["evaluation_policy"].get(k)) != canonical(v) for k, v in policy.items()):
        raise ValueError("Frozen evaluation policy differs")
    # A dedicated checkout preserves all registered modules, including indirect
    # imports. New executor files are separately hashed in every output.
    frozen = record["source_sha256"]
    required = {"research_registration.py", "research_decision.py", "m6_research.py",
                "trade_simulation.py", "portfolio_simulation.py", "event_study.py",
                "history.py", "indicators.py", "structure_history.py", "smc.py",
                "funding_history.py", "contract_specs.py", "execution_history.py",
                "research_config.py", "kline.py"}
    if not required <= frozen.keys():
        raise ValueError("Frozen source manifest is incomplete")
    for name, digest in frozen.items():
        if Path(name).name != name or not name.endswith(".py") or sha(SOURCE / name) != digest:
            raise ValueError("Frozen source differs: " + name)
    return record


def validate_data(rows, quality, protocol, bounds, now):
    """Reject gaps, substituted assets, unclosed bars and truncated future folds."""
    names = protocol["assets"]
    if set(rows) != set(names) or set(quality) != set(names):
        raise ValueError("Every registered asset is required")
    left, right = bounds[0]["test_start"], bounds[-1]["test_end"]
    warmup = max(30 + protocol["indicators"]["window"],
                 protocol["indicators"]["ema_period"], protocol["indicators"]["atr_period"])
    grids = []
    for symbol in names:
        bars, report = rows[symbol], quality[symbol]
        if not bars or report["symbol"] != symbol or any(b["symbol"] != symbol for b in bars):
            raise ValueError("Snapshot asset identity differs: " + symbol)
        if report["issues"] or report["missing_timestamps"]:
            raise ValueError("Snapshot quality issues or missing bars: " + symbol)
        if (report["as_of"] > now.timestamp()
                or any(b["timestamp"] + DAY > now.timestamp() for b in bars)):
            raise ValueError("Snapshot contains future or unclosed observations")
        grid = [b["timestamp"] for b in bars]
        if (grid[0] > left - warmup * DAY or grid[-1] + DAY < right
                or any(b != a + DAY for a, b in zip(grid, grid[1:]))):
            raise ValueError("Complete future folds and causal warmup required: " + symbol)
        if any(b["market"] != "gate_usdt_perpetual" for b in bars):
            raise ValueError("Registered Gate USDT perpetual market required")
        grids.append(grid)
    if any(grid != grids[0] for grid in grids[1:]):
        raise ValueError("Identical verified asset grids required")


def partition(rows, candidates, structures, fold, censor_days):
    """Exclude pre-fold signal bars, even when their close is at the boundary."""
    left, right = fold["test_start"], fold["test_end"]
    eligible = [c for c in candidates if left <= rows[c["index"]]["timestamp"] < right
                and left <= c["signal_time"] < right - censor_days * DAY]
    return restrict(rows, eligible, structures, left, right, censor_days)


def evaluate(root, record, now):
    """All variants/rules share complete data, features and independent fold capital."""
    root = Path(root)
    protocol, bounds = record["protocol"], record["folds"]
    names = protocol["assets"]
    rows, quality = {}, {}
    for symbol in names:
        rows[symbol], quality[symbol] = load_snapshot(root / (symbol + "-daily"))
    validate_data(rows, quality, protocol, bounds, now)
    # Never let bars after the final registered test influence any feature.
    end = bounds[-1]["test_end"]
    rows = {s: [r for r in bars if r["timestamp"] < end] for s, bars in rows.items()}
    features, structures = {}, {}
    for s in names:
        features[s] = calculate(rows[s], IndicatorConfig(**protocol["indicators"]))
        structures[s] = replay(rows[s], StructureConfig(**protocol["structures"]))
    rules = (protocol["primary_rule"], protocol["baseline_rule"])
    candidates = {rule: {} for rule in rules}
    for rule in rules:
        for s in names:
            cs = proposals(rows[s], rule, indicators=features[s], structures=structures[s],
                           event_config=EventConfig(**protocol["events"]))
            candidates[rule][s] = [c for c in cs if all(features[s][c["index"]][k] is not None
                                      for k in ("ret_30d", "return_percentile", "signed_move", "stretch_atr"))]
    reports = {s: load_funding(root / (s + "-funding-full")) for s in names}
    funding = {}
    for s in names:
        report = reports[s]
        marks = load_marks(root / (s + "-marks-full.json"))
        if (report["symbol"] != s or marks["symbol"] != s
                or report["start"] > bounds[0]["test_start"] or report["end_exclusive"] < end
                or report["end_exclusive"] > now.timestamp()
                or marks["end_exclusive"] > now.timestamp()
                or marks.get("interval", "1h") != "1d"):
            raise ValueError("Future funding/mark identity or coverage differs")
        funding[s] = execution_funding(report, marks["bars"], daily_bounds=True)
    experiments = []
    for name, cfg in variants(Config(**protocol["execution"])):
        periods = periods_for(root, names, cfg, bounds[0]["test_start"], end)
        pc = PortfolioConfig(cfg, protocol["max_total_risk"], protocol["max_same_direction"])
        settlements = ({s: {t: [dict(e, rate=e["rate"] * 2) for e in events]
                                 for t, events in days.items()} for s, days in funding.items()}
                       if name.startswith("funding_daily=") else funding)
        for rule in rules:
            for fold_id, fold in enumerate(bounds):
                pr, cs, ss = {}, {}, {}
                for s in names:
                    pr[s], cs[s], ss[s] = partition(rows[s], candidates[rule][s], structures[s],
                                                   fold, protocol["embargo_days"])
                for mode in ("historical_funding", "proxy"):
                    result = simulate(pr, cs, pc, protocol["groups"], ss, execution_periods=periods,
                                      funding=settlements if mode == "historical_funding" else None)
                    experiments.append(dict(variant=name, rule=rule, fold=fold_id, partition="test",
                                            cost_mode=mode, start=fold["test_start"], end=fold["test_end"],
                                            result=result))
    summaries = [dict(variant=name, rule=rule, cost_mode=mode,
                      summary=aggregate([e["result"] for e in experiments
                                         if (e["variant"], e["rule"], e["cost_mode"]) == (name, rule, mode)], names))
                 for name, _ in variants(Config(**protocol["execution"]))
                 for rule in rules for mode in ("historical_funding", "proxy")]
    historical = {(a["variant"], a["rule"]): a["summary"] for a in summaries
                  if a["cost_mode"] == "historical_funding"}
    verdict = acceptance(historical[("base", rules[0])], historical[("base", rules[1])],
                         [s for (name, rule), s in historical.items() if name != "base" and rule == rules[0]],
                         protocol["acceptance"], dict(historical_funding=True, historical_specs=False))
    # No caller-supplied boolean, present-day specs or daily price bounds may
    # certify the unresolved exact-cost/historical-specification evidence.
    verdict["checks"]["exact_cost_evidence"] = False
    verdict["failed"].append("exact_cost_evidence")
    verdict["status"] = "NOT_VALIDATED"
    return dict(status="COMPLETED_RESEARCH_ONLY", input_quality=quality, funding_quality=reports,
                experiments=experiments, aggregates=summaries, acceptance=verdict,
                evidence_sha256={str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*"))
                                 if p.is_file() and p.suffix in (".json", ".csv")})


def run(root, registration_path, candidate_path, previous_path, expected_sha256, output, *, now=None,
        evidence_ledger=None, expected_evidence_sha256=None):
    if Path(output).exists():
        raise FileExistsError(output)
    now = datetime.now(timezone.utc) if now is None else now
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Execution clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    record = load_registration(registration_path, candidate_path, previous_path, expected_sha256)
    if now < datetime.fromisoformat(record["registered_at"]):
        raise ValueError("Execution cannot predate registration")
    evidence = assess_evidence(record, evidence_ledger, expected_evidence_sha256, now=now)
    report = dict(version=VERSION, hypothesis_id=record["protocol"]["hypothesis_id"],
                  evaluated_at=now.isoformat(), registration_sha256=expected_sha256,
                  candidate_sha256=record["candidate_sha256"], protocol=record["protocol"], folds=record["folds"],
                  registered_source_sha256=record["source_sha256"],
                  code_sha256={p.name: sha(p) for p in sorted(SOURCE.glob("*.py"))},
                  specification_evidence=evidence,
                  no_orders=True,
                  limitations=["Local clock and hashes are not an external trusted timestamp.",
                               "No interim evaluation or promotion before all five registered folds close.",
                               "Previously exposed bars are causal warmup only; signal bars must be within a fold.",
                               "Fixed 44-day tail censoring; independent equal capital in every fold.",
                               "Current specifications are extrapolated assumptions, not verified historical specs.",
                               "Daily mark bounds and configured fees/slippage are not exact realized costs.",
                               "44-day clusters are independence proxies; BTC/ETH excludes delisted universe.",
                               "Legacy proxy differs from TradingView Perf.1M; no profitability claim."])
    if now.timestamp() < record["folds"][-1]["test_end"]:
        report.update(status="AWAITING_FUTURE_DATA", experiments=[], aggregates=[],
                      complete_folds=sum(f["test_end"] <= now.timestamp() for f in record["folds"]),
                      earliest_final_evaluation=record["folds"][-1]["test_end"],
                      acceptance=dict(status="NOT_VALIDATED", checks={},
                                      failed=["complete_future_folds", "verified_historical_specs", "exact_cost_evidence"]))
    else:
        report.update(evaluate(root, record, now))
    # Observation ledgers cannot certify historical validity or realized costs.
    # Keep explicit failures in both waiting and completed research reports.
    for check in ("verified_historical_specs", "exact_cost_evidence"):
        report["acceptance"]["checks"][check] = False
        if check not in report["acceptance"]["failed"]:
            report["acceptance"]["failed"].append(check)
    report["acceptance"]["status"] = "NOT_VALIDATED"
    with Path(output).open("x", encoding="utf-8") as target:
        target.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", help="M6 layout: SYMBOL-daily, -funding-full, -marks-full.json, specs/")
    parser.add_argument("registration")
    parser.add_argument("candidate")
    parser.add_argument("--previous-protocol", default=str(SOURCE / "research/m6_protocol.json"))
    parser.add_argument("--expected-registration-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence-ledger", help="Optional immutable specification observation ledger")
    parser.add_argument("--expected-evidence-sha256", help="Reviewed ledger.json SHA-256; required with ledger")
    args = parser.parse_args()
    result = run(args.snapshot, args.registration, args.candidate, args.previous_protocol,
                 args.expected_registration_sha256, args.output,
                 evidence_ledger=args.evidence_ledger, expected_evidence_sha256=args.expected_evidence_sha256)
    print(json.dumps(dict(status=result["status"], acceptance=result["acceptance"])))


if __name__ == "__main__":
    main()
