"""Pure ATR and ratio calculations."""
import numpy as np
import pandas as pd

def ratio(weak, strong, o):
    """计算 weak 相对 strong 的有向比例：(weak - strong) / o。"""
    weak = float(weak)
    strong = float(strong)
    o = float(o)
    if o == 0:
        raise ValueError("开盘价 o 不能为 0")
    return (weak - strong) / o


def classify_ratio(value):
    """按 r 值判断当前是否存在潜在交易机会。"""
    value = float(value)
    if value > 0.10:
        return "涨势过猛，有潜在开空交易机会。"
    if value < -0.10:
        return "跌势太猛，有潜在开多交易机会。"
    return "波动较小，没有潜在交易机会。"


def atr14(ohlc):
    """计算 Wilder ATR(14)，返回与 ``ohlc`` 同索引的 Series。"""
    period = 14
    if len(ohlc) < period:
        raise ValueError(f"K线数量不足：计算 ATR14 至少需要 {period} 根")

    previous_close = ohlc["close"].shift(1)
    true_range = pd.concat(
        [
            ohlc["high"] - ohlc["low"],
            (ohlc["high"] - previous_close).abs(),
            (ohlc["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    values = np.full(len(true_range), np.nan, dtype=float)
    values[period - 1] = float(true_range.iloc[:period].mean())
    for position in range(period, len(true_range)):
        values[position] = (
            values[position - 1] * (period - 1) + float(true_range.iloc[position])
        ) / period
    return pd.Series(values, index=ohlc.index, name="ATR14")

