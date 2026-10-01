"""Pinned field-level historical evidence review; never certifies authenticity."""
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from contract_specs import digest, encoded
from dated_specifications import FIELDS, _keys
from kline import normalize_symbol
from spec_evidence import _json

VERSION = "spec-field-review-v1"
MARKET = "gate_usdt_perpetual"


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Nonempty text required")


def _interval(start, end):
    if any(type(t) is not int or t < 0 for t in (start, end)) or start >= end:
        raise ValueError("Increasing nonnegative UTC Unix boundaries required")


def _number(value):
    if not isinstance(value, str):
        raise ValueError("Decimal string required")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError("Positive finite decimal required")
    return number


def _append(spans, start, end):
    if spans and spans[-1]["end"] == start:
        spans[-1]["end"] = end
    else:
        spans.append(dict(start=start, end=end))


def load(path, expected_sha256, symbols, start, end):
    """Recompute review coverage from pinned documents and explicit claims.

    Review records are human assertions, including their effective boundaries.
    Exact UTF-8 byte excerpts bind those assertions to archived documents; they
    do not establish issuer identity or prove the asserted historical interval.
    """
    _interval(start, end)
    symbols = list(symbols)
    if (not symbols or any(not isinstance(s, str) or normalize_symbol(s) != s for s in symbols)
            or len(set(symbols)) != len(symbols)):
        raise ValueError("Unique canonical symbols required")
    path = Path(path)
    original = path.read_bytes()
    if digest(original) != expected_sha256:
        raise ValueError("Review ledger differs from reviewed SHA-256")
    ledger = _json(original)
    _keys(ledger, ("version", "scope", "market", "documents", "claims"))
    if (ledger["version"] != VERSION or ledger["scope"] != "REVIEW_ASSERTIONS_ONLY"
            or ledger["market"] != MARKET):
        raise ValueError("Unsupported review version, scope or market")
    documents = ledger["documents"]
    if not isinstance(documents, dict):
        raise ValueError("Documents object required")
    root, archived = path.parent.resolve(), {}
    for name, doc in documents.items():
        _text(name)
        _keys(doc, ("file", "sha256", "origin", "kind"))
        for value in doc.values():
            _text(value)
        if doc["kind"] not in ("effective_notice", "observation", "synthetic"):
            raise ValueError("Unknown document kind")
        relative = Path(doc["file"])
        target = (root / relative).resolve()
        if (relative.is_absolute() or relative.drive or ".." in relative.parts
                or ":" in doc["file"] or not target.is_relative_to(root)):
            raise ValueError("Unsafe document path")
        body = target.read_bytes()
        if digest(body) != doc["sha256"]:
            raise ValueError("Document hash mismatch")
        archived[name] = (target, body)
    if not isinstance(ledger["claims"], list):
        raise ValueError("Claims list required")
    ids, used, claims = set(), set(), []
    for claim in ledger["claims"]:
        _keys(claim, ("id", "symbol", "field", "value", "start", "end", "document",
                      "excerpt_start", "excerpt_end", "excerpt", "reviewer", "rationale"))
        for key in ("id", "symbol", "field", "document", "excerpt", "reviewer", "rationale"):
            _text(claim[key])
        if claim["id"] in ids:
            raise ValueError("Duplicate claim ID")
        ids.add(claim["id"])
        if claim["symbol"] not in symbols or claim["field"] not in FIELDS:
            raise ValueError("Unknown asset or specification field")
        _interval(claim["start"], claim["end"])
        number = _number(claim["value"])
        ref = claim["document"]
        if ref not in documents:
            raise ValueError("Unknown document reference")
        a, b = claim["excerpt_start"], claim["excerpt_end"]
        _interval(a, b)
        body = archived[ref][1]
        if b > len(body) or body[a:b] != claim["excerpt"].encode("utf-8"):
            raise ValueError("Excerpt differs from exact archived bytes")
        used.add(ref)
        claims.append(dict(claim, normalized_value=str(number.normalize()),
                           eligible_for_review_coverage=documents[ref]["kind"] == "effective_notice"))
    if used != set(documents):
        raise ValueError("Unreferenced documents")
    assets = []
    for symbol in symbols:
        fields = {}
        for field in FIELDS:
            matching = [c for c in claims if c["symbol"] == symbol and c["field"] == field
                        and c["eligible_for_review_coverage"] and c["start"] < end and c["end"] > start]
            boundaries = sorted({start, end, *(max(start, c["start"]) for c in matching),
                                 *(min(end, c["end"]) for c in matching)})
            covered, gaps, conflicts = [], [], []
            for a, b in zip(boundaries, boundaries[1:]):
                active = [c for c in matching if c["start"] <= a and c["end"] >= b]
                values = {Decimal(c["value"]) for c in active}
                if not values:
                    _append(gaps, a, b)
                elif len(values) > 1:
                    conflicts.append(dict(start=a, end=b, claim_ids=sorted(c["id"] for c in active)))
                else:
                    _append(covered, a, b)
            fields[field] = dict(reviewed_coverage_seconds=sum(p["end"]-p["start"] for p in covered),
                                 reviewed_intervals=covered, missing_intervals=gaps,
                                 conflicting_intervals=conflicts,
                                 verified_coverage_seconds=0,
                                 unverified_intervals=[dict(start=start, end=end)])
        assets.append(dict(symbol=symbol, fields=fields))
    # Check for concurrent changes before releasing the findings.
    if path.read_bytes() != original or any(p.read_bytes() != b for p, b in archived.values()):
        raise ValueError("Evidence changed during review")
    return dict(version=VERSION, scope=ledger["scope"], market=MARKET,
                ledger_sha256=expected_sha256, documents=documents, claims=claims, assets=assets,
                required_window=dict(start=start, end=end, end_exclusive=True),
                historical_specs_verified=False, exact_costs_verified=False,
                used_for_execution_parameters=False, acceptance_status="NOT_VALIDATED",
                reasons=["REVIEW_ASSERTIONS_NOT_AUTHENTICATED", "REALIZED_COST_EVIDENCE_MISSING"],
                source_sha256={name: digest(Path(__file__).with_name(name).read_bytes())
                               for name in ("spec_field_review.py", "dated_specifications.py",
                                            "contract_specs.py", "spec_evidence.py", "kline.py")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = load(args.ledger, args.expected_sha256, args.symbols, args.start, args.end)
    with Path(args.output).open("xb") as target:
        target.write(encoded(report))
    print(json.dumps(dict(status=report["acceptance_status"], ledger_sha256=args.expected_sha256)))


if __name__ == "__main__":
    main()
