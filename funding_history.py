"""Auditable funding-rate snapshots and conservative daily settlement accounting."""
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import time
from concurrent.futures import ThreadPoolExecutor

from history import DAY
from kline import normalize_symbol

VERSION = "gate-funding-history-v1"
ENDPOINT = "https://api.gateio.ws/api/v4/futures/usdt/funding_rate"


def encoded(value):
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def request(params):
    with urlopen(Request(ENDPOINT + "?" + urlencode(params), headers={"Accept": "application/json"}), timeout=30) as r:
        return r.read()


def normalize(raw, start, end, interval):
    """A settlement grid is an explicit assumption, checked against every record."""
    if (type(start) is not int or type(end) is not int or start % DAY or end % DAY or start >= end
            or type(interval) is not int or interval < 1 or DAY % interval):
        raise ValueError("Invalid funding interval/range")
    records = {}
    for item in raw:
        t, rate = item.get("t"), item.get("r")
        if type(t) is not int or not start <= t < end or t % interval > 60:
            raise ValueError("Off-grid funding timestamp")
        if type(rate) not in (str, float, int):
            raise ValueError("Invalid funding rate")
        rate = float(rate)
        if not math.isfinite(rate):
            raise ValueError("Nonfinite funding rate")
        scheduled = t//interval*interval
        record = dict(timestamp=scheduled, reported_timestamp=t, rate=rate)
        if scheduled in records and records[scheduled] != record:
            raise ValueError("Conflicting funding duplicate")
        records[scheduled] = record
    missing = [t for t in range(start, end, interval) if t not in records]
    return ([records[t] for t in sorted(records)], missing)


def collect(symbol, start, end, destination, fetch=request, interval=28800, clock=time.time,
            to_only=False):
    """Persist API error bodies as availability evidence; never treat them as zero."""
    symbol = normalize_symbol(symbol)
    normalize([], start, end, interval)
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    raw, pages, blobs = [], [], {}
    page_days=30 if to_only else 100
    tasks=[]
    for left in range(start, end, page_days*DAY):
        right = min(end, left+page_days*DAY)
        params = dict(contract=symbol+"_USDT", **{"to": right-1}, limit=1000)
        if not to_only:
            params["from"] = left
        tasks.append(params)
    with ThreadPoolExecutor(max_workers=4 if to_only else 1) as pool:
        responses=list(pool.map(fetch,tasks))
    for params,body in zip(tasks,responses):
        value = json.loads(body)
        name = f"page-{len(pages):04d}.json"
        if not isinstance(value, (dict, list)):
            raise ValueError("Invalid funding response")
        if isinstance(value, list):
            if len(value) >= 1000:
                raise ValueError("Funding page may be truncated; reduce page size")
            raw.extend(item for item in value if start <= item.get("t",-1) < end)
        elif not isinstance(value.get("label"), str):
            raise ValueError("Unrecognized funding error response")
        pages.append(dict(params=params, raw_file=name, sha256=digest(body),
                          observed_at=int(clock()), status="OK" if isinstance(value,list) else "API_ERROR"))
        blobs[name] = body
    records, missing = normalize(raw, start, end, interval)
    report = dict(version=VERSION, symbol=symbol, market="gate_usdt_perpetual", source_url=ENDPOINT,
                  start=start, end_exclusive=end, assumed_interval=interval, pages=pages,
                  records=records, missing=missing,
                  status="COMPLETE_ASSUMED_GRID" if not missing else "INCOMPLETE_DO_NOT_SIMULATE",
                  source_sha256=digest(Path(__file__).read_bytes()))
    report["pagination"] = "to_only_30_days" if to_only else "from_to_100_days"
    report["timestamp_protocol"] = "scheduled grid with <=60s report delay; original timestamp retained"
    destination.mkdir(parents=True)
    for name, body in blobs.items():
        (destination/name).write_bytes(body)
    (destination/"funding.json").write_bytes(encoded(report))
    return report


def load_snapshot(destination):
    destination = Path(destination)
    report = json.loads((destination/"funding.json").read_bytes())
    if report.get("version") != VERSION or report.get("source_url") != ENDPOINT:
        raise ValueError("Unsupported funding snapshot")
    normalize_symbol(report["symbol"])
    raw = []
    left = report["start"]
    to_only=report.get("pagination","from_to_100_days")=="to_only_30_days"
    page_days=30 if to_only else 100
    for i, p in enumerate(report["pages"]):
        if p["raw_file"] != f"page-{i:04d}.json":
            raise ValueError("Invalid funding raw path")
        expected = dict(contract=report["symbol"]+"_USDT", **{
                        "to": min(report["end_exclusive"],left+page_days*DAY)-1}, limit=1000)
        if not to_only:
            expected["from"] = left
        if p["params"] != expected:
            raise ValueError("Funding page range mismatch")
        left = expected["to"]+1
        body = (destination/p["raw_file"]).read_bytes()
        if digest(body) != p["sha256"]:
            raise ValueError("Funding raw hash mismatch")
        value = json.loads(body)
        if p["status"] != ("OK" if isinstance(value,list) else "API_ERROR"):
            raise ValueError("Funding page status mismatch")
        if isinstance(value,list):
            raw.extend(item for item in value if report["start"] <= item.get("t",-1) < report["end_exclusive"])
    if left != report["end_exclusive"]:
        raise ValueError("Incomplete funding page manifest")
    records, missing = normalize(raw, report["start"], report["end_exclusive"], report["assumed_interval"])
    status = "COMPLETE_ASSUMED_GRID" if not missing else "INCOMPLETE_DO_NOT_SIMULATE"
    if (report["records"],report["missing"],report["status"]) != (records,missing,status):
        raise ValueError("Funding report mismatch")
    return report


def execution_funding(report, mark_bars, daily_bounds=False):
    """Use mark-price hourly open at each settlement, never a later hourly close."""
    if report["status"] != "COMPLETE_ASSUMED_GRID":
        raise ValueError("Incomplete historical funding")
    marks = {}
    for b in mark_bars:
        t, price = b.get("t"), float(b["o"])
        if type(t) is not int or not math.isfinite(price) or price <= 0:
            raise ValueError("Invalid mark bar")
        if t in marks and marks[t] != price:
            raise ValueError("Conflicting mark prices")
        if daily_bounds:
            low,high=float(b["l"]),float(b["h"])
            if not all(math.isfinite(v) for v in (low,high)) or not 0<low<=price<=high:
                raise ValueError("Invalid mark price bounds")
            marks[t] = dict(mark_price=price,mark_low=low,mark_high=high)
        else:
            marks[t] = price
    daily = {}
    for r in report["records"]:
        t = r["timestamp"]
        key=t//DAY*DAY if daily_bounds else t
        if key not in marks:
            raise ValueError("Missing settlement mark price")
        values=marks[key] if daily_bounds else dict(mark_price=marks[key])
        daily.setdefault(t//DAY*DAY, []).append(dict(r,**values))
    return daily


def load_marks(path):
    """Rebuild mark bars from hashed original page bodies and bounded ranges."""
    report = json.loads(Path(path).read_bytes())
    symbol = normalize_symbol(report["symbol"])
    left, end = report["start"], report["end_exclusive"]
    interval=report.get("interval","1h")
    if interval not in ("1h","1d"):
        raise ValueError("Unsupported mark interval")
    seconds=DAY if interval=="1d" else 3600
    bars = []
    for page in report["pages"]:
        expected = dict(contract="mark_"+symbol+"_USDT",interval=interval,
                        **{"from":left,"to":min(end,left+1000*seconds)-1})
        if page["params"] != expected:
            raise ValueError("Mark page range mismatch")
        body = page["raw_body"].encode()
        if digest(body) != page["raw_sha256"]:
            raise ValueError("Mark raw hash mismatch")
        batch = json.loads(body)
        if not isinstance(batch,list) or len(batch)>1000:
            raise ValueError("Invalid mark page")
        bars.extend(batch)
        left = expected["to"]+1
    if left != end or bars != report["bars"]:
        raise ValueError("Mark series mismatch")
    return report


def validate_execution_funding(rows, funding, interval=28800):
    if set(rows) != set(funding):
        raise ValueError("Funding must cover every asset")
    for s, bars in rows.items():
        for b in bars:
            stamp = b["timestamp"]
            events = funding[s].get(stamp)
            if not isinstance(events, list) or not events:
                raise ValueError("Missing daily funding; zero substitution is forbidden")
            times = []
            for e in events:
                t = e["timestamp"]
                if type(t) is not int or not stamp <= t < stamp+DAY:
                    raise ValueError("Funding outside execution day")
                for key in ("rate", "mark_price"):
                    if type(e[key]) not in (int,float) or not math.isfinite(e[key]):
                        raise ValueError("Invalid settlement number")
                if e["mark_price"] <= 0:
                    raise ValueError("Invalid settlement mark")
                if "mark_high" in e or "mark_low" in e:
                    if (any(type(e.get(k)) not in (int,float) or not math.isfinite(e[k]) for k in ("mark_low","mark_high"))
                            or not 0 < e["mark_low"] <= e["mark_price"] <= e["mark_high"]):
                        raise ValueError("Invalid settlement mark bounds")
                times.append(t)
            if times != list(range(stamp,stamp+DAY,interval)):
                raise ValueError("Incomplete/duplicate/unsorted settlement grid")


def funding_charge(events, direction, units, *, ambiguous, new_position, stamp):
    amount = 0
    for e in events:
        if new_position and e["timestamp"] == stamp:
            continue  # an order submitted at this open cannot earn prior settlement
        signed_rate=direction*e["rate"]
        mark=e.get("mark_high" if signed_rate>=0 else "mark_low",e["mark_price"])
        charge = units*signed_rate*mark
        # Daily OHLC cannot prove intraday ownership. Charge debits and withhold
        # credits on entry/stop/target days; this is a declared conservative bound.
        amount += max(0,charge) if ambiguous else charge
    return amount
