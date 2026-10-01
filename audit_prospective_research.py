"""Audit current waiting behavior and a fully synthetic five-fold research run."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import tempfile

from contract_specs import collect as collect_specs
from funding_history import collect as collect_funding, digest
from history import DAY, load_snapshot, prepare, save_snapshot
from m6_research import aggregate, sha
from prospective_research import load_registration, run, validate_data


def synthetic_snapshots(root, record):
    """Fake transport only; all snapshot validators and execution code are real."""
    root = Path(root)
    left = record["folds"][0]["test_start"] - 400 * DAY
    start, end = record["folds"][0]["test_start"], record["folds"][-1]["test_end"]
    for s in record["protocol"]["assets"]:
        raw = []
        for i, t in enumerate(range(left, end, DAY)):
            price = 100 * math.exp(.25 * math.sin(i / 31) + .04 * math.sin(i / 7))
            raw.append(dict(t=t, o=price, h=price * 1.05, l=price * .95, c=price, v=1))
        rows, quality = prepare(raw, s, left, end, end)
        save_snapshot(root / (s + "-daily"), raw, rows, quality)
        collect_funding(s, start, end, root / (s + "-funding-full"),
                        fetch=lambda p: json.dumps([dict(t=t, r="0.0001")
                                                    for t in range(p["from"], p["to"] + 1, 28800)]).encode(),
                        clock=lambda: end)
        pages, bars = [], []
        for t in range(start, end, 1000 * DAY):
            right = min(end, t + 1000 * DAY)
            batch = [dict(t=stamp, o=100, h=105, l=95, c=100) for stamp in range(t, right, DAY)]
            body = json.dumps(batch)
            pages.append(dict(params={"contract": "mark_" + s + "_USDT", "interval": "1d",
                                      "from": t, "to": right - 1},
                              raw_body=body, raw_sha256=digest(body.encode())))
            bars.extend(batch)
        (root / (s + "-marks-full.json")).write_text(json.dumps(dict(
            symbol=s, start=start, end_exclusive=end, interval="1d", pages=pages, bars=bars)), encoding="utf-8")

    def contract(symbol):
        return json.dumps(dict(name=symbol + "_USDT", type="direct", quanto_multiplier="1",
                               order_size_min="1" if symbol == "BTC" else "0.1",
                               order_size_max="100000", order_price_round="0.01",
                               enable_decimal=symbol == "ETH", in_delisting=False, status="trading",
                               maker_fee_rate="0.00075", taker_fee_rate="0.00075", funding_interval=28800)).encode()

    collect_specs(record["protocol"]["assets"], root / "specs", fetch=contract, clock=lambda: end)
    (root / "SYNTHETIC.json").write_text(json.dumps(dict(synthetic=True, purpose="Engineering audit only")))


def audit(args):
    if Path(args.output).exists():
        raise FileExistsError(args.output)
    source = Path(__file__).resolve().parent
    watched = [Path(args.registration), Path(args.candidate), Path(args.previous_protocol)]
    watched += [p for s in ("BTC", "ETH") for p in (Path(args.snapshot) / (s + "-daily")).glob("*") if p.is_file()]
    before = {str(p.resolve()): sha(p) for p in watched}
    record = load_registration(args.registration, args.candidate, args.previous_protocol, args.expected_registration_sha256)
    with tempfile.TemporaryDirectory(prefix="price-prospective-audit-") as temporary:
        root = Path(temporary)
        current = run(args.snapshot, args.registration, args.candidate, args.previous_protocol,
                      args.expected_registration_sha256, root / "current.json")
        if current["status"] != "AWAITING_FUTURE_DATA" or current["experiments"]:
            raise ValueError("This audit expects no matured future outcomes")
        rows, quality = {}, {}
        for s in record["protocol"]["assets"]:
            rows[s], quality[s] = load_snapshot(Path(args.snapshot) / (s + "-daily"))
        try:
            validate_data(rows, quality, record["protocol"], record["folds"],
                          datetime.fromtimestamp(record["folds"][-1]["test_end"], timezone.utc))
        except ValueError as exc:
            old_data_rejection = str(exc)
        else:
            raise AssertionError("Previously exposed archive accepted as future data")
        fixture = root / "synthetic"
        fixture.mkdir()
        synthetic_snapshots(fixture, record)
        print("Synthetic five-fold native replay and simulation starting", flush=True)
        result = run(fixture, args.registration, args.candidate, args.previous_protocol,
                     args.expected_registration_sha256, root / "synthetic-result.json",
                     now=datetime.fromtimestamp(record["folds"][-1]["test_end"], timezone.utc))
        checks = dict(all_240_experiments=len(result["experiments"]) == 240,
                      all_48_aggregates=len(result["aggregates"]) == 48,
                      no_promotion=result["acceptance"]["status"] == "NOT_VALIDATED",
                      exact_costs_blocked="exact_cost_evidence" in result["acceptance"]["failed"],
                      historical_specs_blocked="verified_historical_specs" in result["acceptance"]["failed"],
                      equity_reconciled=True, folds_and_censoring=True, aggregates_recomputed=True,
                      realized_trades_present=any(e["result"]["trades"] for e in result["experiments"]))
        for e in result["experiments"]:
            account = e["result"]
            checks["equity_reconciled"] &= abs(account["summary"]["final_equity"] - 10000
                                               - sum(t["net_pnl"] for t in account["trades"])) < 1e-7
            checks["folds_and_censoring"] &= (account["equity_curve"][0]["timestamp"] == e["start"] + DAY
                                               and account["equity_curve"][-1]["timestamp"] == e["end"]
                                               and all(e["start"] + DAY <= t["signal_time"] < e["end"] - 44 * DAY
                                                       and t["exit_time"] <= e["end"] for t in account["trades"]))
        for a in result["aggregates"]:
            accounts = [e["result"] for e in result["experiments"]
                        if (e["variant"], e["rule"], e["cost_mode"]) ==
                        (a["variant"], a["rule"], a["cost_mode"])]
            checks["aggregates_recomputed"] &= a["summary"] == aggregate(accounts, record["protocol"]["assets"])
        checks["archive_unchanged"] = before == {str(p.resolve()): sha(p) for p in watched}
        if not all(checks.values()):
            raise AssertionError(checks)
        artifact = dict(version="m6-prospective-engineering-audit-v1", status="PASS_ENGINEERING_ONLY",
                        current_status=current["status"], current_acceptance=current["acceptance"],
                        registration_sha256=args.expected_registration_sha256,
                        old_data_rejection=old_data_rejection, frozen_folds=record["folds"], checks=checks,
                        synthetic=True, synthetic_experiments=len(result["experiments"]),
                        synthetic_aggregates=result["aggregates"], synthetic_acceptance=result["acceptance"],
                        synthetic_input_sha256=result["evidence_sha256"],
                        archive_sha256=before,
                        code_sha256={p.name: sha(p) for p in sorted(source.glob("*.py"))},
                        limitations=["Synthetic prices, funding, marks and specifications provide no strategy evidence.",
                                     "Injected 2031 clock is a test fixture, not the CLI execution clock.",
                                     "All real future outcomes, historical specs and exact costs remain unresolved."])
        with Path(args.output).open("x", encoding="utf-8") as output:
            output.write(json.dumps(artifact, indent=2, allow_nan=False) + "\n")
        print(json.dumps(dict(status=artifact["status"], checks=checks)), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot")
    p.add_argument("registration")
    p.add_argument("candidate")
    p.add_argument("--previous-protocol", default=str(Path(__file__).resolve().parent / "research/m6_protocol.json"))
    p.add_argument("--expected-registration-sha256", required=True)
    p.add_argument("--output", required=True)
    audit(p.parse_args())


if __name__ == "__main__":
    main()
