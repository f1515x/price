"""Inventory pinned M6 specification evidence; never infer validity or certify it."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import re

from contract_specs import digest, encoded
from dated_specifications import FIELDS
import historical_notices
from spec_evidence import _json, verify as verify_observations
from spec_field_review import load as load_review


PINS = {
    "data/M6-evidence-scope.json": "5842d41fc76998ee7884e645e3ad90c33c25a3deedd118a7f7ba796357345c8b",
    "data/M6-restart-registration.json": "b2bc4ddbf455c86dd53911d3814c27bd61026d89104fe58fffe15a4b005ea6cd",
    "data/M6-spec-evidence-20261001/ledger.json": "845d22b74e248c7cf08a441125879007c092e4f44a706e05bbf3b72ef1ed5408",
    "data/M6-field-review-acceptance/real-review.json": "e3f7a684aa643c88a4e77ab2e848c749dcb9e4399189503e83d14038389d0cf5",
    "data/M6-historical-notices/notices.json": "e05867d17b1c461875f97b3c329aaad6a2b1b721483f2b195ae74eb9113d94e6",
}
RAW_KEYS = {"multiplier": "quanto_multiplier", "quantity_step": "enable_decimal",
            "min_quantity": "order_size_min", "max_quantity": "order_size_max",
            "price_tick": "order_price_round"}
LABELS = {"multiplier": "乘数", "quantity_step": "数量步长", "min_quantity": "最小张数",
          "max_quantity": "最大张数", "price_tick": "价格 tick"}


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def window(start, end):
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError("Increasing nonnegative UTC second boundaries required")
    return dict(start=start, end_exclusive=end, start_utc=utc(start), end_exclusive_utc=utc(end))


def scalar_binding(body, key):
    """Retain a scalar member's exact UTF-8 bytes, not a reserialized quotation."""
    pattern = (rb'"' + key.encode("ascii") + rb'"\s*:\s*'
               rb'("(?:\\.|[^"\\])*"|true|false|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)')
    matches = list(re.finditer(pattern, body))
    if len(matches) != 1:
        raise ValueError("Expected one scalar source member: " + key)
    match = matches[0]
    text = match.group().decode("utf-8")
    if _json("{" + text + "}")[key] != _json(body)[key]:
        raise ValueError("Scalar byte binding differs from JSON member")
    return dict(start=match.start(), end=match.end(), text=text, json_pointer="/" + key)


def period_rows(scope, symbol, events, claims, observation_refs, issue_refs):
    """Partition required windows at evidence boundaries, never assign notice values."""
    targets = [("historical", scope["historical_data"][symbol])]
    targets += [("future-" + str(f["index"]), f["test"]) for f in scope["future_folds"]]
    rows = []
    for target, required in targets:
        start, end = required["start"], required["end_exclusive"]
        window(start, end)
        matching_events = [e for e in events if e["symbol"] == symbol]
        matching_claims = [c for c in claims if c["symbol"] == symbol
                           and c["eligible_for_review_coverage"] and c["start"] < end and c["end"] > start]
        boundaries = {start, end}
        boundaries.update(e["effective_timestamp"] for e in matching_events
                          if start < e["effective_timestamp"] < end)
        for c in matching_claims:
            boundaries.update((max(start, c["start"]), min(end, c["end"])))
        boundaries = sorted(boundaries)
        for i, (a, b) in enumerate(zip(boundaries, boundaries[1:])):
            for field in FIELDS:
                active = [c for c in matching_claims if c["field"] == field
                          and c["start"] <= a and c["end"] >= b]
                values = {Decimal(c["value"]) for c in active}
                status = "CONFLICTING_REVIEW_ASSERTIONS" if len(values) > 1 else (
                    "REVIEW_ASSERTIONS_ONLY" if values else "NO_VALIDITY_ASSERTION")
                gaps = ["ISSUER_FIELD_SEMANTICS_AND_EFFECTIVE_PERIOD_NOT_AUTHENTICATED"]
                if not values:
                    gaps += ["FULL_EFFECTIVE_PERIOD_EVIDENCE_MISSING"]
                if len(values) > 1:
                    gaps += ["CONFLICTING_VALUES_REQUIRE_RESOLUTION"]
                if target.startswith("future-"):
                    gaps += ["FUTURE_VALIDITY_UNKNOWN_UNTIL_OBSERVED"]
                if symbol == "ETH" and field == "quantity_step":
                    gaps += ["EXPLICIT_DECIMAL_QUANTITY_STEP_MISSING"]
                rows.append(dict(
                    id=f"{symbol}-{target}-{i}-{field}", symbol=symbol, field=field,
                    target=target, required_window=window(a, b),
                    period_semantics="COVERAGE_PARTITION_NOT_PROVEN_EFFECTIVE_PERIOD",
                    certified_value=None, certified_effective_period=None,
                    certified_coverage_seconds=0, certification_status="NOT_CERTIFIED",
                    review_status=status, review_claim_ids=sorted(c["id"] for c in active),
                    conflicting_claim_ids=sorted(c["id"] for c in active) if len(values) > 1 else [],
                    observation_refs=observation_refs[field],
                    notice_context_refs=[e["id"] for e in matching_events if e["field"] == field],
                    notice_context_is_period_proof=False, issue_context_refs=issue_refs[field], gaps=gaps))
    return rows


def build(root):
    root = Path(root).resolve()
    inputs = {}

    def track(relative, expected=None):
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Evidence path escapes root")
        body = path.read_bytes()
        sha = digest(body)
        if expected is not None and sha != expected:
            raise ValueError("Pinned evidence differs: " + relative)
        if relative in inputs and inputs[relative] != sha:
            raise ValueError("Evidence changed during inventory: " + relative)
        inputs[relative] = sha
        return body

    loaded = {name: _json(track(name, sha)) for name, sha in PINS.items()}
    scope = loaded["data/M6-evidence-scope.json"]
    registration = loaded["data/M6-restart-registration.json"]
    if scope["assets"] != registration["protocol"]["assets"] or scope["assets"] != ["BTC", "ETH"]:
        raise ValueError("Scope assets differ from registration")
    for name, sha in scope["input_sha256"].items():
        track(name, sha)
    source_dir = Path(__file__).resolve().parent
    code_hashes = {name: digest((source_dir / name).read_bytes()) for name in (
        Path(__file__).name, "contract_specs.py", "dated_specifications.py", "historical_notices.py",
        "spec_evidence.py", "spec_field_review.py", "kline.py")}
    frozen = registration["source_sha256"]
    if len(frozen) != 37 or any(digest((source_dir / name).read_bytes()) != sha for name, sha in frozen.items()):
        raise ValueError("Frozen source constraint failed")
    if [{"index": f["index"], "test_start": f["test"]["start"], "test_end": f["test"]["end_exclusive"]}
            for f in scope["future_folds"]] != [
                {"index": i, "test_start": f["test_start"], "test_end": f["test_end"]}
                for i, f in enumerate(registration["folds"])]:
        raise ValueError("Future windows differ from frozen registration")

    ledger_name = "data/M6-spec-evidence-20261001/ledger.json"
    ledger = loaded[ledger_name]
    for snapshot in ledger["snapshots"]:
        for name, sha in snapshot["files"].items():
            track(str(Path(ledger_name).parent / "snapshots" / snapshot["snapshot_sha256"] / name).replace("\\", "/"), sha)
    verify_observations(root / Path(ledger_name).parent, PINS[ledger_name])
    expected_window = scope["historical_data"]["BTC"]
    if any(scope["historical_data"][s] != expected_window for s in scope["assets"]) or (
        ledger["required_window"]["start"], ledger["required_window"]["end"]) != (
            expected_window["start"], expected_window["end_exclusive"]):
        raise ValueError("Observation ledger and scope windows differ")

    notice_name = "data/M6-historical-notices/notices.json"
    manifest = loaded[notice_name]
    for doc in manifest["documents"].values():
        track((Path(notice_name).parent / doc["file"]).as_posix(), doc["sha256"])
    notices = historical_notices.verify(root / Path(notice_name).parent, PINS[notice_name])
    if notices["events"] != _json(track("data/M6-historical-notices-acceptance.json"))["evidence"]["events"]:
        raise ValueError("Recomputed notices differ from fixed scope evidence")
    review_name = "data/M6-field-review-acceptance/real-review.json"
    for doc in loaded[review_name]["documents"].values():
        track((Path(review_name).parent / doc["file"]).as_posix(), doc["sha256"])
    review = load_review(root / review_name, PINS[review_name], scope["assets"],
                       expected_window["start"], expected_window["end_exclusive"])

    sources, observations, issues, rows = {}, [], [], []
    for event_index, event in enumerate(notices["events"]):
        doc = notices["documents"][event["document"]]
        sources[event["id"]] = dict(
            kind="NOTICE_CHANGE_EVENT_SHORT_EXCERPT", manifest=notice_name,
            manifest_pointer=f"/events/{event_index}",
            file=(Path(notice_name).parent / doc["file"]).as_posix(), sha256=doc["sha256"],
            url=doc["url"], capture_method=doc["capture_method"], retrieved_at=doc["retrieved_at"],
            original_excerpt=(root / Path(notice_name).parent / doc["file"]).read_text(encoding="utf-8"),
            bindings=event["bindings"], symbol=event["symbol"], field=event["field"],
            before=event["before"], after=event["after"], effective_timestamp=event["effective_timestamp"],
            publication_time=None, publication_time_status="NOT_SEPARATELY_ARCHIVED",
            effective_period_start=None, effective_period_end=None, authenticated=False)
    for asset in ledger["assets"]:
        symbol = asset["symbol"]
        refs, issue_refs = {f: [] for f in FIELDS}, {f: [] for f in FIELDS}
        for i, observation in enumerate(asset["observations"]):
            relative = (Path(ledger_name).parent / "snapshots" / observation["snapshot_sha256"] / observation["raw_file"]).as_posix()
            body = track(relative, observation["raw_sha256"])
            oid = f"{symbol}-observation-{i}"
            observations.append(dict(id=oid, symbol=symbol, observed_at=observation["observed_at"],
                                     observed_utc=utc(observation["observed_at"]), snapshot_sha256=observation["snapshot_sha256"],
                                     source_url=observation["source_url"], values={f: observation[f] for f in FIELDS},
                                     effective_period=None, historical_validity_established=False))
            for field in FIELDS:
                sid = oid + "-" + field
                refs[field].append(sid)
                sources[sid] = dict(kind="CURRENT_API_RESPONSE_ONLY", file=relative,
                                    sha256=observation["raw_sha256"], url=observation["source_url"],
                                    observed_at=observation["observed_at"], normalized_value=observation[field],
                                    byte_binding=scalar_binding(body, RAW_KEYS[field]),
                                    mapping="FLAG_BASED_CURRENT_ASSUMPTION_NOT_EXPLICIT_STEP" if field == "quantity_step" else "DIRECT_SCALAR_MAPPING",
                                    effective_period_start=None, effective_period_end=None, authenticated=False)
        for field in FIELDS:
            values = {Decimal(o["values"][field]) for o in observations
                      if o["symbol"] == symbol and o["values"][field] is not None}
            if len(values) > 1:
                iid = symbol + "-" + field + "-observed-difference"
                issue_refs[field].append(iid)
                issues.append(dict(id=iid, symbol=symbol, field=field,
                                   kind="OBSERVED_VALUE_DISCREPANCY_NOT_PROVEN_PERIOD_CONFLICT",
                                   source_refs=refs[field], certified_interval_conflict=False,
                                   affected_effective_period=None, resolution="UNRESOLVED",
                                   reason="Different response times/request context do not establish an effective change time."))
        rows += period_rows(scope, symbol, notices["events"], review["claims"], refs, issue_refs)
    report = dict(version="m6-spec-evidence-matrix-v1", task="plan.md 4.2 second checkbox",
                  owner="Codex", started_on="2026-10-02", expected_completed_on="2026-10-02",
                  completed_on="2026-10-02", date_timezone="America/La_Paz",
                  matrix_status="DELIVERED", strategy_status="NOT_VALIDATED",
                  historical_specs_verified=False, used_for_execution_parameters=False,
                  period_policy="Half-open UTC seconds; partitions show coverage requests, not certified effective periods.",
                  observation_policy="Every observation/notice is context only; no forward/backward validity extrapolation.",
                  scope_ref="data/M6-evidence-scope.json", fields=list(FIELDS), assets=scope["assets"],
                  sources=sources, observations=observations, issues=issues, rows=rows,
                  real_review=dict(file=review_name, claims=review["claims"], documents=review["documents"]),
                  summary=dict(rows=len(rows), historical_rows=sum(r["target"] == "historical" for r in rows),
                               future_rows=sum(r["target"].startswith("future-") for r in rows),
                               certified_coverage_seconds=0, rows_missing_certification=len(rows),
                               rows_with_review_conflicts=sum(bool(r["conflicting_claim_ids"]) for r in rows),
                               observed_discrepancies=len(issues), notice_events=len(notices["events"])),
                  input_sha256=inputs, code_sha256=code_hashes, frozen_sources_verified=len(frozen),
                  excluded_evidence="R5/R8/R9/R10/R12-R19 synthetic declarations and replay fixtures verify engineering only; no effective coverage credit.",
                  blockers=["Full original notices and issuer/field/effective-period authentication are missing.",
                            "BTC complete change history and ETH decimal quantity step are missing.",
                            "ETH observed minimum-size discrepancy is unresolved; future validity is unknown."],
                  next_step="Complete the market/fill evidence matrix (4.2 third checkbox); authenticating specifications remains 4.3.")
    if any(digest((root / name).read_bytes()) != sha for name, sha in inputs.items()):
        raise ValueError("Evidence changed during matrix build")
    if any(digest((source_dir / name).read_bytes()) != sha for name, sha in {**code_hashes, **frozen}.items()):
        raise ValueError("Source changed during matrix build")
    return report


def markdown(report):
    lines = ["# M6 规格证据矩阵", "", "日期：2026-10-02（America/La_Paz）。负责人：Codex。", "",
             "覆盖分区仅表示所需证据期间；每行认证值和认证有效期间均为未知，认证覆盖为 0。",
             "快照及公告引用仅供查证，不把公告前/后值外推到表中期间，也不把当前快照外推到未来。", "",
             "BTC 历史窗口未发现已归档公告边界；ETH 按两份公告的精确秒拆成三个证据分区。",
             "没有发现已登记区间主张冲突，原因是实际区间主张为空；不能认定实际规格没有冲突。", "",
             "## 逐资产、字段和期间", "",
             "O0/O1 为该资产两次观察；N47661/N50325 为 ETH 公告。引用是上下文，不是有效期证明。", "",
             "| 资产 | 覆盖窗口 UTC [起点, 终点) | 字段 | 现有来源 | 认证状态 | 缺口 / 差异 |", "|---|---|---|---|---|---|"]
    for row in report["rows"]:
        w = row["required_window"]
        refs = "O0、O1"
        if row["notice_context_refs"]:
            refs += "；" + "、".join("N" + ref.split("-")[-1] for ref in row["notice_context_refs"])
        gap = "真实有效期间、发行方与语义认证缺失"
        if row["target"].startswith("future-"):
            gap += "；未来待观察"
        if row["field"] == "quantity_step":
            gap += "；小数步长未知" if row["symbol"] == "ETH" else "；1 为整数模式映射假设"
        if row["issue_context_refs"]:
            gap += "；观察值 0/0.1 差异待解"
        lines.append(f"| {row['symbol']} | {w['start_utc']} → {w['end_exclusive_utc']} | {LABELS[row['field']]} | {refs} | 未认证 / 0 秒 | {gap} |")
    lines += ["", "## 观察来源与原文字节定位", "",
              "下表原文来自保存的 API 响应；quantity_step 仅引用 enable_decimal 标志，原响应没有明确步长字段。",
              "归档字节、SHA-256、来源 URL、JSON 指针及 UTF-8 字节偏移完整保存在机器矩阵中。", "",
              "| 资产/观察 | 接收时间 UTC | 字段 | 观察值 | 原文 |", "|---|---|---|---|---|"]
    for o in report["observations"]:
        for field in FIELDS:
            source = report["sources"][o["id"] + "-" + field]
            value = o["values"][field] if o["values"][field] is not None else "未知"
            lines.append(f"| {o['id']} | {o['observed_utc']} | {LABELS[field]} | {value} | `{source['byte_binding']['text']}` |")
    lines += ["", "ETH 最小张数 0 → 0.1 是不同响应的观察差异。差异的真实生效时间和请求口径关系未证实，",
              "保留未解决项，不认定两次接收之间发生了实际变更。0 也不能作为合法正张数执行参数。", "",
              "## 公告短摘录", "", "这里只保留两个已归档短摘录，完整原文、独立发布时间与有效期终点缺失。", ""]
    for sid, source in report["sources"].items():
        if source["kind"] == "NOTICE_CHANGE_EVENT_SHORT_EXCERPT":
            lines += [f"### {sid}", "", f"来源：[{sid}]({source['url']})。生效时点 UTC：{utc(source['effective_timestamp'])}。",
                      f"字段：{LABELS[source['field']]}；{source['before']} → {source['after']}；未认证。", "",
                      "```text", source["original_excerpt"].rstrip(), "```", ""]
    lines += ["## 缺口与边界", "", "两资产五字段的历史和五个未来区间全部保留未认证缺口。",
              "真实审阅清单为空，合成声明与订单回放不提供认证覆盖；最小张数不充当数量步长。",
              "保证金、成本、成交和执行政策不在本矩阵范围。M6 保持 NOT_VALIDATED。", ""]
    return "\n".join(lines).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; never overwritten")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    report = build(args.evidence_root)
    json_body, md_body = encoded(report), markdown(report)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "matrix.json").write_bytes(json_body)
    (args.output_dir / "matrix.md").write_bytes(md_body)
    print(encoded(dict(report["summary"], matrix_sha256=digest(json_body))).decode("utf-8"))


if __name__ == "__main__":
    main()
