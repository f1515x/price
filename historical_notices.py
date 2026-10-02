"""Pinned historical notice excerpts and change events, never validity periods."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import urlsplit

from contract_specs import digest, encoded
from dated_specifications import FIELDS, _keys
from history import DAY
from kline import normalize_symbol
from spec_evidence import _json
from spec_field_review import _number, _text

VERSION = "historical-notice-events-v1"
SCOPE = "NOTICE_CHANGE_EVENTS_ONLY"


def _url(value):
    _text(value)
    u = urlsplit(value)
    if (u.scheme != "https" or u.netloc != "www.gate.com" or u.query or u.fragment
            or not re.fullmatch(r"/(?:[a-z]{2}/)?announcements/article/[0-9]+", u.path)):
        raise ValueError("Canonical Gate HTTPS announcement URL required")


def _file(root, name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+\.txt", name):
        raise ValueError("Flat excerpt filename required")
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Excerpt escapes archive")
    return target


def _stamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError("Explicit UTC second-resolution timestamp required")
    try:
        result = int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    except ValueError as exc:
        raise ValueError("Invalid notice timestamp") from exc
    if result < 0:
        raise ValueError("Nonnegative notice timestamp required")
    return result


def analyze(manifest, blobs):
    """Validate excerpt bindings; reviewer mappings remain explicit assertions."""
    _keys(manifest, ("version", "scope", "market", "documents", "events"))
    if (manifest["version"] != VERSION or manifest["scope"] != SCOPE
            or manifest["market"] != "gate_usdt_perpetual"):
        raise ValueError("Unsupported notice scope/version/market")
    docs = manifest["documents"]
    if not isinstance(docs, dict) or not docs:
        raise ValueError("Notice documents required")
    names = set()
    for key, doc in docs.items():
        _text(key)
        _keys(doc, ("file", "sha256", "url", "retrieved_at", "capture_method", "source_locator"))
        _url(doc["url"])
        _stamp(doc["retrieved_at"])
        _text(doc["source_locator"])
        if doc["capture_method"] != "WEB_TOOL_SHORT_EXCERPT":
            raise ValueError("Explicit short-excerpt capture method required")
        _file(Path.cwd(), doc["file"])
        if doc["file"] in names:
            raise ValueError("Duplicate excerpt filename")
        names.add(doc["file"])
        body = blobs[doc["file"]]
        if digest(body) != doc["sha256"]:
            raise ValueError("Notice excerpt hash mismatch")
        text = body.decode("utf-8")
        _text(text)
        if len(text.split()) > 25:
            raise ValueError("Short notice excerpts limited to 25 words")
    events = manifest["events"]
    if not isinstance(events, list) or not events:
        raise ValueError("Notice change events required")
    ids, used, changes = set(), set(), {}
    findings = []
    for event in events:
        _keys(event, ("id", "symbol", "field", "before", "after", "effective_at",
                      "document", "bindings", "reviewer", "rationale"))
        for k in ("id", "reviewer", "rationale"):
            _text(event[k])
        if event["id"] in ids:
            raise ValueError("Duplicate event ID")
        ids.add(event["id"])
        if not isinstance(event["symbol"], str) or normalize_symbol(event["symbol"]) != event["symbol"]:
            raise ValueError("Canonical symbol required")
        if event["field"] not in FIELDS:
            raise ValueError("Unknown specification field")
        if _number(event["before"]) == _number(event["after"]):
            raise ValueError("Notice event must change the value")
        t = _stamp(event["effective_at"])
        doc_id = event["document"]
        if not isinstance(doc_id, str) or doc_id not in docs:
            raise ValueError("Unknown notice document")
        used.add(doc_id)
        doc = docs[doc_id]
        if t > _stamp(doc["retrieved_at"]):
            raise ValueError("Historical notice event must precede retrieval")
        body = blobs[doc["file"]]
        _keys(event["bindings"], ("effective_time", "table_header", "table_row"))
        for binding in event["bindings"].values():
            _keys(binding, ("start", "end", "text"))
            a, b = binding["start"], binding["end"]
            if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(body):
                raise ValueError("Invalid excerpt byte boundaries")
            _text(binding["text"])
            if body[a:b].decode("utf-8") != binding["text"]:
                raise ValueError("Exact excerpt byte binding mismatch")
        key = (event["symbol"], event["field"], t)
        values = (_number(event["before"]), _number(event["after"]))
        if key in changes and changes[key] != values:
            raise ValueError("Conflicting same-time notice changes")
        changes[key] = values
        findings.append(dict(event, effective_timestamp=t, intraday_boundary=bool(t % DAY),
                             inferred_validity_end=None, authenticated=False))
    if used != set(docs):
        raise ValueError("Unreferenced notice document")
    return dict(version=VERSION, scope=SCOPE, events=findings,
                historical_specs_verified=False, verified_coverage_seconds=0,
                used_for_execution_parameters=False, acceptance_status="NOT_VALIDATED",
                reasons=["SHORT_EXCERPTS_NOT_FULL_ORIGINAL_RESPONSES",
                         "REVIEWER_FIELD_MAPPING_NOT_AUTHENTICATED",
                         "CHANGE_EVENTS_DO_NOT_PROVE_VALIDITY_INTERVALS",
                         "INTRADAY_CHANGES_REQUIRE_EXECUTION_POLICY"])


def build(manifest, blobs, destination):
    """Archive reviewed short excerpts without claiming original HTML capture."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    result = analyze(manifest, blobs)
    if set(blobs) != {d["file"] for d in manifest["documents"].values()}:
        raise ValueError("Unexpected excerpt files")
    destination.mkdir(parents=True, exist_ok=False)
    for name, body in blobs.items():
        (destination / name).write_bytes(body)
    (destination / "notices.json").write_bytes(encoded(manifest))
    return result


def verify(destination, expected_sha256):
    destination = Path(destination).resolve()
    path = destination / "notices.json"
    original = path.read_bytes()
    if digest(original) != expected_sha256:
        raise ValueError("Notice manifest differs from pinned SHA-256")
    manifest = _json(original)
    blobs = {d["file"]: _file(destination, d["file"]).read_bytes()
             for d in manifest["documents"].values()}
    result = analyze(manifest, blobs)
    if path.read_bytes() != original or any(_file(destination, n).read_bytes() != b for n, b in blobs.items()):
        raise ValueError("Notice evidence changed during verification")
    return dict(result, manifest_sha256=expected_sha256, documents=manifest["documents"],
                source_sha256=digest(Path(__file__).read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = verify(args.archive, args.expected_sha256)
    with Path(args.output).open("xb") as target:
        target.write(encoded(report))


if __name__ == "__main__":
    main()
