"""Offline, next-open event research; no orders, costs or portfolio returns."""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import random
from statistics import mean, median

from history import DAY, load_snapshot
from indicators import Config as IndicatorConfig, calculate
from structure_history import Config as StructureConfig, replay

VERSION = "daily-events-v1"
HORIZONS = (1, 3, 7, 14, 30)
RULES = ("legacy_proxy", "percentile", "move", "stretch", "percentile_move",
         "percentile_stretch", "percentile_structure")


@dataclass(frozen=True)
class Config:
    tail: float = 10
    move: float = 2
    stretch: float = 2
    train_fraction: float = 0.7
    seed: int = 20260930
    min_events: int = 30

    def __post_init__(self):
        if not 0 < self.tail < 50 or not 0 < self.move < float("inf") or not 0 < self.stretch < float("inf"):
            raise ValueError("Invalid research thresholds")
        if not 0 < self.train_fraction < 1:
            raise ValueError("train_fraction must be between zero and one")
        if type(self.seed) is not int or type(self.min_events) is not int or self.min_events < 1:
            raise ValueError("Invalid seed/min_events")


def signals(indicator, structure, config=Config()):
    """Direction +1 = long, -1 = short; thresholds fixed before labels."""
    ret = indicator["ret_30d"]
    p, m, s = (indicator[k] for k in ("return_percentile", "signed_move", "stretch_atr"))
    direction = 1 if ret is not None and ret < 0 else -1 if ret is not None and ret > 0 else 0
    percentile = direction if p is not None and ((direction == 1 and p <= config.tail) or
                                                (direction == -1 and p >= 100-config.tail)) else 0
    move = direction if m is not None and direction and -direction*m >= config.move else 0
    stretch = direction if s is not None and direction and -direction*s >= config.stretch else 0
    aligned = structure["status"] == "OK" and structure["weak_type"] == ("low" if direction == 1 else "high")
    ratio = structure["ratio"]
    legacy = direction if aligned and ret is not None and abs(ret) > .15 and ratio is not None and -direction*ratio > .10 else 0
    return dict(legacy_proxy=legacy, percentile=percentile, move=move, stretch=stretch,
                percentile_move=percentile if move else 0,
                percentile_stretch=percentile if stretch else 0,
                percentile_structure=percentile if aligned else 0)


def label(rows, index, direction, horizon):
    """Signal at t close; enter t+1 open, exit t+h close. Gaps censor labels."""
    future = rows[index+1:index+horizon+1]
    if len(future) != horizon or any(r["timestamp"] != rows[index]["timestamp"]+(j+1)*DAY for j, r in enumerate(future)):
        return None
    entry = future[0]["open"]
    extrema = [direction*(r[key]/entry-1) for r in future for key in ("high", "low")]
    return dict(return_=direction*(future[-1]["close"]/entry-1),
                mae=min(0, *extrema), mfe=max(0, *extrema),
                entry_time=future[0]["timestamp"], exit_time=future[-1]["timestamp"]+DAY)


def summarize(events):
    if not events:
        return dict(n=0, mean=None, median=None, p10=None, p90=None, positive_rate=None,
                    mean_mae=None, mean_mfe=None)
    values = sorted(e["return_"] for e in events)
    def quantile(q):
        pos = (len(values)-1)*q
        lo = int(pos)
        return values[lo] + (values[min(lo+1, len(values)-1)]-values[lo])*(pos-lo)
    return dict(n=len(events), mean=mean(values), median=median(values), p10=quantile(.1),
                p90=quantile(.9), positive_rate=mean(v > 0 for v in values),
                mean_mae=mean(e["mae"] for e in events), mean_mfe=mean(e["mfe"] for e in events))


def study(rows, config=Config(), indicator_config=IndicatorConfig(), structure_config=StructureConfig()):
    rows = list(rows)
    indicators = calculate(rows, indicator_config)
    structures = replay(rows, structure_config)
    if not rows:
        raise ValueError("Empty snapshot")
    # Compare on common availability, not different warmup periods.
    eligible = [i for i, (a, b) in enumerate(zip(indicators, structures))
                if all(a[k] is not None for k in ("ret_30d", "return_percentile", "signed_move", "stretch_atr"))
                and b["status"] == "OK"]
    split = rows[eligible[min(int(len(eligible)*config.train_fraction), len(eligible)-1)]]["timestamp"]+DAY if eligible else None
    candidates = []
    for i in eligible:
        a, b = indicators[i], structures[i]
        candidates.append(dict(index=i, timestamp=rows[i]["timestamp"], signal_time=a["signal_time"],
                               ret_30d=a["ret_30d"], percentile=a["return_percentile"],
                               move=a["signed_move"], stretch=a["stretch_atr"], trend=b["trend"],
                               signals=signals(a, b, config)))
    summaries, events = [], []
    for rule in RULES:
        for partition in ("train", "test"):
            last_signal = None
            selected = []
            pool = [c for c in candidates if (c["signal_time"] < split if partition == "train" else c["signal_time"] >= split)]
            for c in pool:
                d = c["signals"][rule]
                if d and (last_signal is None or c["signal_time"]-last_signal >= max(HORIZONS)*DAY):
                    selected.append((c, d))
                    last_signal = c["signal_time"]
            for horizon in HORIZONS:
                def outcome(c, d):
                    value = label(rows, c["index"], d, horizon)
                    # All train labels end before test's earliest possible entry.
                    if value is None or (partition == "train" and value["exit_time"] > split):
                        return None
                    return dict(value, timestamp=c["timestamp"], direction=d, trend=c["trend"])
                valid = [e for c, d in selected if (e := outcome(c, d)) is not None]
                # Uniform random times, same valid count and direction mix, fixed seed.
                # Control samples can overlap: descriptive baseline, not independent trials.
                control_pool = [c for c in pool if outcome(c, 1) is not None]
                rng = random.Random(config.seed)
                sampled = rng.sample(control_pool, len(valid))
                random_events = [outcome(c, e["direction"]) for c, e in zip(sampled, valid)]
                unconditional = [outcome(c, d) for c in control_pool for d in (1, -1)]
                groups = {name: summarize([e for e in valid if e["direction"] == d]) for name, d in (("long", 1), ("short", -1))}
                groups.update({trend: summarize([e for e in valid if e["trend"] == trend]) for trend in ("BULLISH", "BEARISH")})
                summaries.append(dict(rule=rule, partition=partition, horizon=horizon,
                                      selected=len(selected), censored=len(selected)-len(valid),
                                      status="DESCRIPTIVE_ONLY" if len(valid) >= config.min_events else "INSUFFICIENT_EVENTS",
                                      result=summarize(valid), groups=groups,
                                      random_control=summarize(random_events),
                                      unconditional={name: summarize([e for e in unconditional if e["direction"] == d]) for name, d in (("long", 1), ("short", -1))}))
                for kind, values in (("signal", valid), ("random_control", random_events)):
                    events.extend(dict(e, rule=rule, partition=partition, horizon=horizon, kind=kind) for e in values)
    return dict(version=VERSION, parameters=asdict(config), indicator_parameters=asdict(indicator_config),
                structure_parameters=asdict(structure_config), horizons=HORIZONS, split_time=split,
                bars=len(rows), eligible=len(eligible), excluded=len(rows)-len(eligible),
                conclusion="DESCRIPTIVE_ONLY_NOT_VALIDATED", candidates=candidates, summaries=summaries, events=events)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot")
    parser.add_argument("--output", required=True)
    parser.add_argument("--window", type=int, default=365)
    parser.add_argument("--swing-length", type=int, default=50)
    args = parser.parse_args()
    rows, quality = load_snapshot(args.snapshot)
    result = study(rows, indicator_config=IndicatorConfig(window=args.window),
                   structure_config=StructureConfig(args.swing_length))
    result.update(input_sha256=quality["sha256"], input_quality=quality)
    result["code_sha256"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                             for name in ("event_study.py", "history.py", "indicators.py", "structure_history.py", "smc.py")}
    result["protocol"] = dict(entry="next_day_open", exit="horizon_day_close", units="fraction",
                              dedup_days=30, split="chronological_common_eligible_70_30",
                              purge="train_exit_time_lte_test_first_entry", costs_included=False,
                              random_control="uniform_times_same_count_and_direction_mix_may_overlap",
                              legacy="daily_local_30d_proxy_no_limit_fill_simulation")
    with Path(args.output).open("x", encoding="utf-8") as target:
        target.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps({k: result[k] for k in ("bars", "eligible", "split_time", "conclusion")}))


if __name__ == "__main__":
    main()
