"""Replay confirmed daily SMC from verified M1 snapshots, without future bars."""
import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

import pandas as pd

from history import DAY, load_snapshot
from indicators import calculate
from smc import pine_weak_strong, ratio

VERSION = "daily-structure-v1"


@dataclass(frozen=True)
class Config:
    swing_length: int = 50

    def __post_init__(self):
        if type(self.swing_length) is not int or self.swing_length < 1:
            raise ValueError("swing_length must be a positive integer")


def replay(rows, config=Config()):
    """Use closed, quality-checked prepare/load_snapshot rows.

    Recompute each contiguous prefix through the existing SMC implementation.
    This reference replay is quadratic; it deliberately preserves legacy logic.
    A missing day resets both structure and ATR. No trading signals are emitted.
    """
    rows = list(rows)
    indicators = calculate(rows)  # validates identity/order/OHLCV; Wilder ATR14
    output, segment = [], []
    for row, indicator in zip(rows, indicators):
        if indicator["gap_before"]:
            segment = []
        segment.append(row)
        result = {k: row[k] for k in ("timestamp", "symbol", "market", "interval", "source", "close")}
        result.update(version=VERSION, parameters=asdict(config), signal_time=row["timestamp"] + DAY,
                      earliest_execution_time=row["timestamp"] + DAY,
                      gap_before=indicator["gap_before"], contiguous_bars=len(segment),
                      atr14=indicator["atr"], trend="UNSET", trend_bias=0,
                      weak_type=None, raw_weak_price=None, adjusted_weak_price=None,
                      strong_price=None, ratio=None, swing_atr=None,
                      structure_confirmed_at=None, structure=None)
        reasons = []
        if len(segment) <= config.swing_length:
            reasons.append("INSUFFICIENT_STRUCTURE_HISTORY")
        else:
            frame = pd.DataFrame(segment).set_index("timestamp")
            try:
                state = pine_weak_strong(frame, config.swing_length)
            except ValueError as exc:
                if str(exc) != "数据中尚未确认完整的 Swing High 和 Swing Low":
                    raise
                reasons.append("UNCONFIRMED_STRUCTURE")
            else:
                structure = asdict(state)
                for key in ("top_index", "bottom_index", "swing_high_index", "swing_low_index"):
                    structure[key] = int(structure[key])
                for side in ("high", "low"):
                    pivot = frame.index.get_loc(structure[f"swing_{side}_index"])
                    structure[f"swing_{side}_confirmed_at"] = int(frame.index[pivot + config.swing_length]) + DAY
                result.update(structure=structure, trend=state.trend, trend_bias=state.trend_bias,
                              structure_confirmed_at=max(structure["swing_high_confirmed_at"],
                                                         structure["swing_low_confirmed_at"]))
                if state.trend_bias == 0:
                    # Legacy labels both ends weak in UNSET; there is no strong side.
                    reasons.append("TREND_UNSET")
                else:
                    bullish = state.trend_bias == 1
                    weak = state.top_price if bullish else state.bottom_price
                    strong = state.bottom_price if bullish else state.top_price
                    atr = indicator["atr"]
                    result.update(weak_type="high" if bullish else "low", raw_weak_price=weak,
                                  strong_price=strong, ratio=ratio(weak, strong, row["open"]))
                    if atr is None:
                        reasons.append("ATR_WARMUP")
                    else:
                        result["adjusted_weak_price"] = weak + atr if bullish else weak - atr
                        if atr == 0:
                            reasons.append("ZERO_ATR")
                        else:
                            result["swing_atr"] = abs(weak - strong) / atr
        for key, value in result.items():
            if isinstance(value, float) and not math.isfinite(value):
                result[key] = None
                reasons.append("NONFINITE_" + key.upper())
        result.update(status="UNAVAILABLE" if reasons else "OK", reasons=reasons)
        output.append(result)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot")
    parser.add_argument("--output", required=True)
    parser.add_argument("--swing-length", type=int, default=50)
    args = parser.parse_args()
    config = Config(args.swing_length)
    rows, quality = load_snapshot(args.snapshot)
    results = replay(rows, config)
    payload = dict(version=VERSION, parameters=asdict(config), input_sha256=quality["sha256"],
                   input_quality=quality, rows=results)
    content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with Path(args.output).open("x", encoding="utf-8") as target:
        target.write(content)
    print(json.dumps(dict(rows=len(results), ready=sum(r["status"] == "OK" for r in results))))


if __name__ == "__main__":
    main()
