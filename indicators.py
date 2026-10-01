"""Causal daily research indicators; consumes verified M1 snapshots only."""
import argparse
from collections import deque
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from statistics import median

from history import DAY, load_snapshot

VERSION = "daily-indicators-v1"


@dataclass(frozen=True)
class Config:
    window: int = 365
    ema_period: int = 50
    atr_period: int = 14

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in asdict(self).values()):
            raise ValueError("Indicator periods must be positive integers")


def calculate(rows, config=Config()):
    """Rows must come from history.prepare/load_snapshot (closed, valid, sorted).

    Distribution uses the last W valid returns, even across historical gaps.
    EMA and Wilder ATR reset after gaps; both seed with a period-length SMA.
    First segment TR is high-low. Current return enters history AFTER output.
    """
    past = deque(maxlen=config.window)
    closes, trs = deque(maxlen=31), deque(maxlen=config.atr_period)
    seed = []
    ema = atr = previous = previous_close = None
    output = []
    identity = None
    for row in rows:
        current_identity = tuple(row[k] for k in ("symbol", "market", "interval", "source"))
        if row["interval"] != "1d" or (identity is not None and identity != current_identity):
            raise ValueError("Expected one daily asset/source per calculation")
        identity = current_identity
        stamp = row["timestamp"]
        if type(stamp) is not int or stamp % DAY or (previous is not None and stamp <= previous):
            raise ValueError("Expected strictly increasing UTC daily timestamps")
        o, h, l, c, v = (row[k] for k in ("open", "high", "low", "close", "volume"))
        if not all(math.isfinite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0 or v < 0 or not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("Expected quality-checked OHLCV")
        gap = previous is not None and stamp != previous + DAY
        if gap:
            closes.clear()
            trs.clear()
            seed.clear()
            ema = atr = previous_close = None
        closes.append(c)
        tr = h - l if previous_close is None else max(h - l, abs(h - previous_close), abs(l - previous_close))
        trs.append(tr)
        if atr is not None:
            atr += (tr - atr) / config.atr_period
        elif len(trs) == config.atr_period:
            atr = sum(trs) / config.atr_period
        if ema is not None:
            ema += 2 / (config.ema_period + 1) * (c - ema)
        else:
            seed.append(c)
            if len(seed) == config.ema_period:
                ema = sum(seed) / config.ema_period
        ret = c / closes[0] - 1 if len(closes) == 31 else None
        reasons = {}
        result = {k: row[k] for k in ("timestamp", "symbol", "market", "interval", "source", "close")}
        result.update(signal_time=stamp + DAY, version=VERSION, parameters=asdict(config),
                      ret_30d=ret, history_count=len(past),
                      history_start=past[0][0] if past else None,
                      history_end=past[-1][0] if past else None,
                      ema=ema, atr=atr, return_percentile=None, typical_move=None,
                      signed_move=None, robust_z=None, stretch_atr=None)
        if ret is None:
            reasons["ret_30d"] = "INSUFFICIENT_CONTIGUOUS_DATA"
        if len(past) == config.window:
            values = [value for _, value in past]
            typical = median(abs(x) for x in values)
            center = median(values)
            mad = median(abs(x - center) for x in values)
            result["typical_move"] = typical
            if ret is not None:
                result["return_percentile"] = 100 * (sum(x < ret for x in values) + 0.5 * sum(x == ret for x in values)) / len(values)
                for key, divisor, numerator in (("signed_move", typical, ret), ("robust_z", 1.4826 * mad, ret - center)):
                    if divisor == 0:
                        reasons[key] = "ZERO_TYPICAL_MOVE" if key == "signed_move" else "ZERO_MAD"
                    else:
                        result[key] = numerator / divisor
            else:
                for key in ("return_percentile", "signed_move", "robust_z"):
                    reasons[key] = "CURRENT_RETURN_UNAVAILABLE"
        else:
            for key in ("return_percentile", "typical_move", "signed_move", "robust_z"):
                reasons[key] = "INSUFFICIENT_HISTORY"
        if ema is None:
            reasons["ema"] = "INSUFFICIENT_CONTIGUOUS_DATA"
        if atr is None:
            reasons["atr"] = "INSUFFICIENT_CONTIGUOUS_DATA"
        if ema is None or atr is None:
            reasons["stretch_atr"] = "INDICATOR_WARMUP"
        elif atr == 0:
            reasons["stretch_atr"] = "ZERO_ATR"
        else:
            result["stretch_atr"] = (c - ema) / atr
        for key, value in result.items():
            if isinstance(value, float) and not math.isfinite(value):
                result[key] = None
                reasons[key] = "NONFINITE_RESULT"
        result.update(status="OK" if not reasons else "UNAVAILABLE", reasons=reasons, gap_before=gap)
        output.append(result)
        if ret is not None and math.isfinite(ret):
            past.append((stamp, ret))
        previous, previous_close = stamp, c
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot")
    parser.add_argument("--output", required=True)
    parser.add_argument("--window", type=int, default=365)
    parser.add_argument("--ema-period", type=int, default=50)
    parser.add_argument("--atr-period", type=int, default=14)
    args = parser.parse_args()
    config = Config(args.window, args.ema_period, args.atr_period)
    rows, quality = load_snapshot(args.snapshot)
    results = calculate(rows, config)
    payload = {"version": VERSION, "parameters": asdict(config), "input_sha256": quality["sha256"],
               "input_quality": quality, "rows": results}
    content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with Path(args.output).open("x", encoding="utf-8") as target:
        target.write(content)
    print(json.dumps({"rows": len(results), "ready": sum(r["status"] == "OK" for r in results)}))


if __name__ == "__main__":
    main()
