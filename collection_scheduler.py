"""UTC daily collection scheduler for offline research; never sends orders."""
import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import time

from candidate_store import Config as CandidateConfig, build_candidates
from history import DAY, date_timestamp, fetch_daily, load_snapshot, prepare, save_snapshot
from history_store import import_snapshots
from indicator_store import build_indicators
from indicators import Config as IndicatorConfig
from kline import normalize_symbol
from structure_history import Config as StructureConfig
from structure_store import build_structures


@dataclass(frozen=True)
class Config:
    symbols: tuple = ("BTC", "ETH")
    start: int = date_timestamp("2024-01-01")
    close_delay: int = 300
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)
    structures: StructureConfig = field(default_factory=StructureConfig)
    candidates: CandidateConfig = field(default_factory=CandidateConfig)
    parameter_profile: dict = None

    def __post_init__(self):
        normalized = tuple(normalize_symbol(s) for s in self.symbols)
        if not normalized or len(set(normalized)) != len(normalized):
            raise ValueError("Expected distinct nonempty symbols")
        if type(self.start) is not int or self.start < 0 or self.start % DAY:
            raise ValueError("start must be a UTC midnight timestamp")
        if type(self.close_delay) is not int or not 0 <= self.close_delay < DAY:
            raise ValueError("close_delay must be seconds in [0,86400)")
        object.__setattr__(self, "symbols", normalized)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _identity(config):
    names = ("collection_scheduler.py", "history.py", "history_store.py", "kline.py",
             "indicators.py", "indicator_store.py", "structure_history.py",
             "structure_store.py", "candidate_store.py", "event_study.py", "smc.py", "research_config.py",
             "trade_simulation.py")
    evidence = dict(parameters=asdict(config), implementation_sha256={
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in names})
    return hashlib.sha256(_json(evidence).encode()).hexdigest(), evidence


@contextmanager
def _lock(root):
    path = root / "collector.lock"
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError:
        raise RuntimeError("Collector lock exists; check running process before removing it") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
            handle.flush()
            yield
    finally:
        path.unlink()


def _write_state(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(_json(value) + "\n", encoding="utf-8")
    temporary.replace(path)


def collect(root, config=Config(), now=None, fetch=None):
    """One due cycle, resumable per acquisition and stage under a root lock.

    A fixed start preserves EMA/SMC history; missing days stay explicit. Each
    acquisition is immutable. A failed stage leaves evidence for the next retry.
    Completed cycles are replayed idempotently through all stores to revalidate
    evidence; success is recorded only after every asset and stage completes.
    """
    now = int(time.time()) if now is None else int(now)
    end = (now - config.close_delay) // DAY * DAY
    if end <= config.start:
        raise ValueError("No closed daily range available")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _lock(root):
        identity, evidence = _identity(config)
        cycle = f"{end}-{identity}"
        state_path = root / "state.json"
        state = dict(version="daily-collection-v1", cycle=cycle, as_of=now,
                     end_exclusive=end, status="RUNNING", stages={}, evidence=evidence,
                     validation="NOT_VALIDATED", execution_authorized=False)
        _write_state(state_path, state)
        try:
            directories = []
            for symbol in config.symbols:
                directory = root / "snapshots" / f"{symbol}-{config.start}-{end}"
                if directory.exists():
                    _, report = load_snapshot(directory)
                    if (report["symbol"], report["start"], report["end_exclusive"]) != (
                            symbol, config.start, end):
                        raise ValueError("Acquisition range differs from requested cycle")
                else:
                    kwargs = {} if fetch is None else {"fetch": fetch}
                    raw, pages = fetch_daily(symbol, config.start, end, **kwargs)
                    rows, report = prepare(raw, symbol, config.start, end, now)
                    report["pages"] = pages
                    save_snapshot(directory, raw, rows, report)
                    load_snapshot(directory)
                directories.append(directory)
            database = root / "research.sqlite"
            state["stages"]["history"] = import_snapshots(database, directories)
            _write_state(state_path, state)
            ids = [r["snapshot_id"] for r in state["stages"]["history"]]
            state["stages"]["indicators"] = build_indicators(database, ids, config.indicators)
            _write_state(state_path, state)
            state["stages"]["structures"] = build_structures(database, ids, config.structures)
            _write_state(state_path, state)
            state["stages"]["candidates"] = build_candidates(
                database, ids, config.candidates, config.indicators, config.structures)
            state["quality"] = {symbol: load_snapshot(directory)[1]
                                for symbol, directory in zip(config.symbols, directories)}
            state["status"] = "COMPLETE"
        except Exception as exc:
            state["status"] = "FAILED"
            state["error"] = dict(type=type(exc).__name__, message=str(exc))
            _write_state(state_path, state)
            with (root / "cycles.jsonl").open("a", encoding="utf-8") as log:
                log.write(_json(state) + "\n")
            raise
        _write_state(state_path, state)
        with (root / "cycles.jsonl").open("a", encoding="utf-8") as log:
            log.write(_json(state) + "\n")
        return state


def watch(root, config, poll_seconds=60, clock=time.time, sleep=time.sleep, run=collect):
    """Retry failures each poll; after success wait for the next UTC due day.

    Restarting safely revalidates today's data once. Ctrl+C stops cleanly.
    No backlog loop: the fixed-start next acquisition covers missed days.
    """
    if type(poll_seconds) is not int or not 1 <= poll_seconds <= 60:
        raise ValueError("poll_seconds must be an integer in [1,60]")
    completed_end = None
    while True:
        now = int(clock())
        end = (now - config.close_delay) // DAY * DAY
        if end > config.start and end != completed_end:
            try:
                state = run(root, config, now=now)
                completed_end = state["end_exclusive"]
                print(_json(dict(status=state["status"], end_exclusive=completed_end)), flush=True)
            except Exception as exc:
                print(_json(dict(status="FAILED", error=str(exc))), flush=True)
        sleep(poll_seconds)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Dedicated persistent collection directory")
    parser.add_argument("--research-config", help="Shared research parameter JSON")
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--start", type=date_timestamp)
    parser.add_argument("--close-delay", type=int)
    parser.add_argument("--window", type=int)
    parser.add_argument("--swing-length", type=int)
    parser.add_argument("--tail", type=float)
    parser.add_argument("--move", type=float)
    parser.add_argument("--stretch", type=float)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    overrides = (args.symbols, args.start, args.close_delay, args.window, args.swing_length,
                 args.tail, args.move, args.stretch)
    if args.research_config:
        if any(v is not None for v in overrides):
            parser.error("--research-config cannot be combined with parameter overrides")
        from research_config import load_profile
        config = load_profile(args.research_config).collector()
    else:
        config = Config(tuple(args.symbols) if args.symbols is not None else ("BTC", "ETH"),
                        args.start if args.start is not None else date_timestamp("2024-01-01"),
                        args.close_delay if args.close_delay is not None else 300,
                        IndicatorConfig(window=args.window if args.window is not None else 365),
                        StructureConfig(args.swing_length if args.swing_length is not None else 50),
                        CandidateConfig(args.tail if args.tail is not None else 10,
                                        args.move if args.move is not None else 2,
                                        args.stretch if args.stretch is not None else 2))
    if args.watch:
        try:
            watch(args.root, config, args.poll_seconds)
        except KeyboardInterrupt:
            return 0
    else:
        state = collect(args.root, config)
        print(_json(dict(status=state["status"], cycle=state["cycle"],
                        database=str(Path(args.root).resolve() / "research.sqlite"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
