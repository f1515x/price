"""Close a failed M6 hypothesis using hash-bound, recomputed research evidence."""
import argparse
import hashlib
import json
from pathlib import Path

from m6_research import acceptance, aggregate


def digest(data):
    return hashlib.sha256(data).hexdigest()


def close_hypothesis(report_path, protocol_path, expected_report_sha256, decision_date):
    report_bytes = Path(report_path).read_bytes()
    if digest(report_bytes) != expected_report_sha256:
        raise ValueError("Report SHA-256 does not match the reviewed evidence")
    report = json.loads(report_bytes)
    protocol_bytes = Path(protocol_path).read_bytes()
    protocol = json.loads(protocol_bytes)
    recorded = dict(report["protocol"])
    protocol_hash = recorded.pop("preregistered_file_sha256")
    if protocol_hash != digest(protocol_bytes) or recorded != protocol:
        raise ValueError("Protocol differs from the original preregistration")
    if report["version"] != "m6-rolling-preregistered-v1" or not report["folds"]:
        raise ValueError("Expected a completed rolling M6 report")

    # Rebuild every OOS aggregate from individual portfolio runs, never from
    # isolated accounts, proxy funding, training, or the recent diagnostic.
    summaries = {}
    seen = set()
    for item in report["aggregates"]:
        key = (item["variant"], item["rule"], item["cost_mode"])
        if key in summaries:
            raise ValueError("Duplicate aggregate")
        runs = []
        fold_ids = set()
        for experiment in report["experiments"]:
            if experiment["partition"] != "test":
                continue
            other = (experiment["variant"], experiment["rule"], experiment["cost_mode"])
            if other != key:
                continue
            fold = experiment["fold"]
            identity = (*key, fold)
            if identity in seen or type(fold) is not int or not 0 <= fold < len(report["folds"]):
                raise ValueError("Duplicate or invalid test fold")
            seen.add(identity)
            fold_ids.add(fold)
            bounds = report["folds"][fold]
            if experiment["start"] != bounds["test_start"] or experiment["end"] != bounds["test_end"]:
                raise ValueError("Test partition differs from recorded fold")
            runs.append(experiment["result"])
        if fold_ids != set(range(len(report["folds"]))):
            raise ValueError("Incomplete test fold coverage")
        summary = aggregate(runs, protocol["assets"])
        if summary != item["summary"]:
            raise ValueError("Aggregate differs from individual test runs")
        summaries[key] = summary

    dynamic = summaries[("base", "percentile_structure", "historical_funding")]
    legacy = summaries[("base", "legacy_proxy", "historical_funding")]
    neighbors = [s for (variant, rule, cost), s in summaries.items()
                 if variant != "base" and rule == "percentile_structure" and cost == "historical_funding"]
    # Coverage is the original report's evidence assessment, not a new claim
    # that raw market files or historical specifications were verified here.
    checks = report["acceptance"]["checks"]
    coverage = dict(historical_funding=checks["complete_historical_funding"],
                    historical_specs=checks["verified_historical_specs"])
    if any(type(v) is not bool for v in coverage.values()):
        raise ValueError("Coverage assessments must be booleans")
    result = acceptance(dynamic, legacy, neighbors, protocol["acceptance"], coverage)
    if result != report["acceptance"]:
        raise ValueError("Acceptance differs from recomputed results")
    if result["status"] != "NOT_VALIDATED" or dynamic["mean_net_r"] is None or dynamic["mean_net_r"] >= 0:
        raise ValueError("Termination requires failed acceptance and negative base expectancy")
    return dict(
        version="m6-hypothesis-closure-v1", decision_date=decision_date,
        hypothesis_id=protocol["version"] + ":percentile_structure:base",
        decision="TERMINATED", retrospective=True,
        evidence=dict(report_sha256=digest(report_bytes), protocol_sha256=protocol_hash,
                      decision_code_sha256=digest(Path(__file__).read_bytes()),
                      scope="Recomputed OOS aggregates and acceptance; original coverage assessments retained"),
        acceptance=result, base_oos=dynamic, legacy_oos=legacy,
        neighbors=dict(count=len(neighbors), positive=sum(s["mean_net_r"] is not None and s["mean_net_r"] > 0
                                                        for s in neighbors)),
        exposed_history_end_exclusive=max(q["end_exclusive"] for q in report["input_quality"].values()),
        preserved_acceptance_thresholds=protocol["acceptance"],
        blocked_next_steps=["M7 promotion", "M8 shadow/live integration", "Selecting a profitable tested neighbor"],
        restart_requirements=[
            "New hypothesis and version with a documented mechanism; no best-test parameter selection",
            "Register protocol before inspecting new independent test outcomes",
            "Treat all previously inspected history as development data, not fresh OOS evidence",
            "Preserve acceptance thresholds and resolve historical specification/exact cost evidence gaps",
            "Meet all M6 acceptance gates before advancing M7/M8"],
        limitations=report["limitations"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("protocol")
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--decision-date", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    decision = close_hypothesis(args.report, args.protocol, args.expected_report_sha256, args.decision_date)
    # Exclusive creation preserves an existing decision artifact.
    with Path(args.output).open("x", encoding="utf-8") as output:
        output.write(json.dumps(decision, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(decision=decision["decision"], failed=decision["acceptance"]["failed"])))


if __name__ == "__main__":
    main()
