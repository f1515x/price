"""M5 causal structure percentiles and ER ablation, offline research only."""
import argparse
from collections import deque
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

from event_study import Config as EventConfig, HORIZONS, label, signals, summarize
from history import DAY, load_snapshot
from indicators import Config as IndicatorConfig, calculate
from structure_history import Config as StructureConfig, replay

VERSION = "structure-ablation-v1"
RULES = ("baseline", "ratio", "swing", "er")


@dataclass(frozen=True)
class Config:
    window: int = 365
    er_period: int = 30
    structure_tail: float = 20
    er_max: float = 0.5

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in (self.window, self.er_period)):
            raise ValueError("Periods must be positive integers")
        if not 0 < self.structure_tail < 50 or not 0 <= self.er_max <= 1:
            raise ValueError("Invalid structure/ER thresholds")


def features(rows, structures, config=Config()):
    """Daily observations; ratio history is separated by weak direction.

    Current structure enters history after scoring. A data gap resets all
    histories. ER uses N daily changes and needs N+1 contiguous closes.
    """
    if len(rows) != len(structures):
        raise ValueError("Unaligned structures")
    histories = {side: deque(maxlen=config.window) for side in ("high", "low")}
    swings = deque(maxlen=config.window)
    closes = deque(maxlen=config.er_period+1)
    previous = None
    output = []
    for row, structure in zip(rows, structures):
        stamp = row["timestamp"]
        if stamp != structure["timestamp"] or (previous is not None and stamp <= previous):
            raise ValueError("Unaligned or unordered structures")
        if previous is not None and stamp != previous+DAY:
            for history in histories.values():
                history.clear()
            swings.clear()
            closes.clear()
        closes.append(row["close"])
        result = dict(timestamp=stamp, ratio_percentile=None, swing_percentile=None,
                      er=None, ratio_count=0, swing_count=len(swings), reasons={})
        if len(closes) == config.er_period+1:
            values = list(closes)
            path = sum(abs(b-a) for a, b in zip(values, values[1:]))
            if path:
                result["er"] = abs(values[-1]-values[0])/path
            else:
                result["reasons"]["er"] = "ZERO_PRICE_PATH"
        else:
            result["reasons"]["er"] = "ER_WARMUP"
        side = structure["weak_type"]
        valid = (structure["status"] == "OK" and side in histories
                 and all(structure[k] is not None and math.isfinite(structure[k])
                         for k in ("ratio", "swing_atr")))
        if valid:
            history = histories[side]
            result["ratio_count"] = len(history)
            for key, value, past in (("ratio_percentile", structure["ratio"], history),
                                     ("swing_percentile", structure["swing_atr"], swings)):
                if len(past) == config.window:
                    result[key] = 100*(sum(x < value for x in past)+0.5*sum(x == value for x in past))/len(past)
                else:
                    result["reasons"][key] = "INSUFFICIENT_STRUCTURE_HISTORY"
            history.append(structure["ratio"])
            swings.append(structure["swing_atr"])
        else:
            for key in ("ratio_percentile", "swing_percentile"):
                result["reasons"][key] = "STRUCTURE_UNAVAILABLE"
        output.append(result)
        previous = stamp
    return output


def filter_signals(direction, feature, config=Config()):
    p, s, er = (feature[k] for k in ("ratio_percentile", "swing_percentile", "er"))
    ratio_pass = p is not None and ((direction == 1 and p <= config.structure_tail)
                                   or (direction == -1 and p >= 100-config.structure_tail))
    return dict(baseline=direction, ratio=direction if ratio_pass else 0,
                swing=direction if s is not None and s >= 100-config.structure_tail else 0,
                er=direction if er is not None and er <= config.er_max else 0)


def study(rows, config=Config(), event_config=EventConfig(),
          indicator_config=IndicatorConfig(), structure_config=StructureConfig()):
    rows = list(rows)
    if not rows:
        raise ValueError("Empty snapshot")
    indicators, structures = calculate(rows, indicator_config), replay(rows, structure_config)
    values = features(rows, structures, config)
    candidates = []
    for i, (a, b, f) in enumerate(zip(indicators, structures, values)):
        if (b["status"] == "OK" and a["ret_30d"] is not None
                and a["return_percentile"] is not None
                and all(f[k] is not None for k in ("ratio_percentile", "swing_percentile", "er"))):
            direction = signals(a, b, event_config)["percentile_structure"]
            candidates.append(dict(index=i, signal_time=a["signal_time"], trend=b["trend"],
                                   signals=filter_signals(direction, f, config)))
    split = candidates[min(int(len(candidates)*event_config.train_fraction), len(candidates)-1)]["signal_time"] if candidates else None
    summaries, events = [], []
    for partition in ("train", "test"):
        pool = [c for c in candidates if (c["signal_time"] < split if partition == "train" else c["signal_time"] >= split)]
        # Deduplicate baseline first: each ablation filters exactly the same events.
        selected, last = [], None
        for c in pool:
            if c["signals"]["baseline"] and (last is None or c["signal_time"]-last >= max(HORIZONS)*DAY):
                selected.append(c)
                last = c["signal_time"]
        for horizon in HORIZONS:
            valid = []
            for c in selected:
                outcome = label(rows, c["index"], c["signals"]["baseline"], horizon)
                if outcome is not None and (partition == "test" or outcome["exit_time"] <= split):
                    valid.append(dict(outcome, index=c["index"], signal_time=c["signal_time"],
                                      direction=c["signals"]["baseline"], trend=c["trend"], signals=c["signals"]))
            baseline = summarize(valid)
            for rule in RULES:
                kept = [e for e in valid if e["signals"][rule]]
                rejected = [e for e in valid if not e["signals"][rule]]
                stats = summarize(kept)
                enough = len(kept) >= event_config.min_events and (rule == "baseline" or len(rejected) >= event_config.min_events)
                summaries.append(dict(partition=partition, horizon=horizon, rule=rule,
                                      selected=sum(bool(c["signals"][rule]) for c in selected),
                                      censored=sum(bool(c["signals"][rule]) for c in selected)-len(kept),
                                      baseline=baseline, retained=stats, rejected=summarize(rejected),
                                      mean_delta_vs_baseline=stats["mean"]-baseline["mean"] if kept else None,
                                      status="DESCRIPTIVE_ONLY" if enough else "INSUFFICIENT_EVENTS",
                                      groups={name: summarize([e for e in kept if e["direction"] == d])
                                              for name, d in (("long", 1), ("short", -1))}))
            events.extend(dict(e, partition=partition, horizon=horizon) for e in valid)
    return dict(version=VERSION, parameters=asdict(config), event_parameters=asdict(event_config),
                indicator_parameters=asdict(indicator_config), structure_parameters=asdict(structure_config),
                bars=len(rows), eligible=len(candidates), split_time=split, features=values,
                candidates=candidates, summaries=summaries, events=events,
                conclusion="DESCRIPTIVE_ONLY_NOT_VALIDATED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot")
    parser.add_argument("--output", required=True)
    parser.add_argument("--structure-window", type=int, default=365)
    args = parser.parse_args()
    rows, quality = load_snapshot(args.snapshot)
    result = study(rows, Config(window=args.structure_window))
    result.update(input_sha256=quality["sha256"], input_quality=quality)
    result["code_sha256"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                             for name in ("structure_study.py", "event_study.py", "history.py",
                                          "indicators.py", "structure_history.py", "smc.py")}
    result["protocol"] = dict(entry="next_day_open", horizons=HORIZONS, costs_included=False,
                              split="chronological_common_eligible", purge="train_exit_lte_split",
                              dedup="baseline_first_30_days_then_independent_filters",
                              ratio="signed_percentile_by_weak_type", swing="unsigned_all_valid_daily_structures",
                              gaps="reset_all_M5_histories", units="fraction",
                              inference="descriptive_ablation_no_significance_or_causal_claim")
    with Path(args.output).open("x", encoding="utf-8") as target:
        target.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps({k: result[k] for k in ("bars", "eligible", "split_time", "conclusion")}))


if __name__ == "__main__":
    main()
