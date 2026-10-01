"""Acquire M6 public research evidence, retaining HTTP errors and resumable responses."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor

import contract_specs
import funding_history
import history


class PublicArchive:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, url, *, decimal=False):
        key = hashlib.sha256((url+str(decimal)).encode()).hexdigest()
        path = self.root/(key+".json")
        if path.exists():
            envelope = json.loads(path.read_bytes())
            return envelope["body"].encode()
        cmd = ["curl.exe", "-4", "-sS", "--connect-timeout", "8", "--max-time", "25",
               "--retry", "2", "--retry-all-errors", "--retry-delay", "1"]
        if decimal:
            cmd += ["-H", "X-Gate-Size-Decimal: 1"]
        result = subprocess.run(cmd+[url], capture_output=True, timeout=100)
        if result.returncode:
            raise RuntimeError("Public GET transport failed: " + url)
        body = result.stdout.decode()
        json.loads(body)  # never cache a HTML/proxy error as an exchange response
        path.write_text(json.dumps(dict(url=url, decimal_header=decimal,
                                       observed_at=int(time.time()), body=body), indent=2), encoding="utf-8")
        return result.stdout


def acquire(root, symbols, start, end, funding_start, full_funding=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    archive = PublicArchive(root/"responses")
    specs = root/"specs"
    if not specs.exists():
        contract_specs.collect(symbols, specs, fetch=lambda s: archive.get(
            contract_specs.ENDPOINT+s+"_USDT", decimal=True))
    print("contract specifications saved", flush=True)
    for s in symbols:
        destination = root/(s+"-daily")
        if not destination.exists():
            raw, pages = history.fetch_daily(s, start, end, fetch=lambda p: json.loads(
                archive.get(history.ENDPOINT+"?"+urlencode(p))))
            rows, quality = history.prepare(raw, s, start, end, int(time.time()))
            quality["pages"] = pages
            history.save_snapshot(destination, raw, rows, quality)
        rows, quality = history.load_snapshot(destination)
        print(s, "daily", len(rows), "status", quality["research_status"], flush=True)
        destination = root/(s+"-funding-full" if full_funding else s+"-funding")
        if not destination.exists():
            funding_history.collect(s, funding_start, end, destination, fetch=lambda p: archive.get(
                funding_history.ENDPOINT+"?"+urlencode(p)),to_only=full_funding)
        report = funding_history.load_snapshot(destination)
        print(s, "funding", len(report["records"]), report["status"], flush=True)
        # Independently preserve an old-history query's availability response.
        archive.get(funding_history.ENDPOINT+"?"+urlencode(dict(contract=s+"_USDT",
                    **{"from":start,"to":start+history.DAY-1},limit=1000)))
        destination = root/(s+"-marks-full.json" if full_funding else s+"-marks-v2.json")
        if not destination.exists():
            bars, pages = [], []
            seconds=history.DAY if full_funding else 3600
            tasks=[dict(contract="mark_"+s+"_USDT",interval="1d" if full_funding else "1h",
                        **{"from":left,"to":min(end,left+1000*seconds)-1})
                   for left in range(funding_start,end,1000*seconds)]
            with ThreadPoolExecutor(max_workers=4) as pool:
                bodies=list(pool.map(lambda p:archive.get(history.ENDPOINT+"?"+urlencode(p)),tasks))
            for params,body in zip(tasks,bodies):
                batch = json.loads(body)
                if not isinstance(batch,list):
                    raise ValueError("Mark candle request rejected: " + str(batch))
                bars.extend(batch)
                pages.append(dict(params=params, raw_body=body.decode(),raw_sha256=hashlib.sha256(body).hexdigest()))
            destination.write_bytes(funding_history.encoded(dict(symbol=s,start=funding_start,
                                    end_exclusive=end,interval="1d" if full_funding else "1h",bars=bars,pages=pages)))
        marks = funding_history.load_marks(destination)
        if report["status"] == "COMPLETE_ASSUMED_GRID":
            funding_history.execution_funding(report, marks["bars"],daily_bounds=full_funding)
        print(s,"mark candles",len(marks["bars"]),flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output")
    p.add_argument("--symbols", nargs="+", default=["BTC","ETH"])
    p.add_argument("--start", type=history.date_timestamp, default=history.date_timestamp("2020-01-01"))
    p.add_argument("--end", type=history.date_timestamp, default=history.date_timestamp("2026-10-01"))
    p.add_argument("--funding-start", type=history.date_timestamp, default=history.date_timestamp("2026-04-06"))
    p.add_argument("--full-funding",action="store_true")
    a=p.parse_args()
    acquire(a.output,a.symbols,a.start,a.end,a.start if a.full_funding else a.funding_start,a.full_funding)


if __name__ == "__main__":
    main()
