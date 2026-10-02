"""查询一个月涨跌幅与一个月振幅的算术平均值。

综合值 = (TradingView Perf.1M + 最近一个已完成自然月的整体振幅) / 2。
振幅 = (区间最高价 - 区间最低价) / 区间开始前一日收盘价 * 100。
自然月按 UTC 划分；Perf.1M 的时间口径由 TradingView 定义，
可能与上述自然月区间不同。导入模块不会发起网络请求。
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
import sys
import time
from typing import Any, Sequence

import requests

TRADINGVIEW_URL = "https://scanner.tradingview.com/symbol"
GATE_CANDLES_URL = "https://api.gateio.ws/api/v4/futures/usdt/candlesticks"
TIMEOUT_SECONDS = 15
DAY_SECONDS = 86_400


@dataclass(frozen=True)
class MonthlyMetrics:
    """各指标的单位均为百分数（例如 21.21 表示 21.21%）。"""

    base_asset: str
    performance_1m: float
    amplitude_1m: float

    @property
    def combined_average(self) -> float:
        return self.performance_1m / 2 + self.amplitude_1m / 2


def parse_base_asset(value: str) -> str:
    """校验 ASCII 币种简称，拒绝标点及非英文字符。"""
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError("币种必须是字符串")
    base_asset = value.strip().upper()
    if not value.isascii() or not re.fullmatch(r"[A-Z0-9]+", base_asset, flags=re.ASCII):
        raise argparse.ArgumentTypeError("币种只能包含英文字母和数字，例如 BTC、1000PEPE")
    return base_asset


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{field} 必须是有限数值")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} 必须是有限数值") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} 必须是有限数值")
    return number


def get_month_performance(
    base_asset: str, *, session: requests.Session | None = None,
) -> float:
    """查询 TradingView 的一个月涨跌幅。"""
    base_asset = parse_base_asset(base_asset)
    if session is None:
        with requests.Session() as owned_session:
            return get_month_performance(base_asset, session=owned_session)
    response = session.get(
        TRADINGVIEW_URL,
        params={
            "symbol": f"GATE:{base_asset}USDT.P",
            "fields": "Perf.1M",
            "no_404": "true",
            "label-product": "right-details",
        },
        headers={
            "Accept": "application/json",
            "Origin": "https://www.tradingview.com",
            "Referer": "https://www.tradingview.com/",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("Perf.1M") is None:
        raise ValueError(f"{base_asset} 未获取到 Perf.1M 数据")
    return _finite_number(data["Perf.1M"], "Perf.1M")


def get_month_window(now: float | None = None) -> tuple[int, int]:
    """返回最近一个完整 UTC 自然月的 [开始, 结束) 时间戳。"""
    current_time = _finite_number(time.time() if now is None else now, "当前时间")
    current = datetime.fromtimestamp(current_time, tz=timezone.utc)
    end = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year, month_index = divmod(end.year * 12 + end.month - 1 - 1, 12)
    start = end.replace(year=year, month=month_index + 1)
    return int(start.timestamp()), int(end.timestamp())


def calculate_month_amplitude(
    candles: Any, *, start_timestamp: int, end_timestamp: int,
) -> float:
    """计算整个区间的振幅；额外前一日仅提供收盘价，不参与高低价。"""
    if (start_timestamp % DAY_SECONDS or end_timestamp % DAY_SECONDS
            or start_timestamp >= end_timestamp):
        raise ValueError("振幅区间必须按 UTC 日界线对齐，且开始时间早于结束时间")
    if not isinstance(candles, list):
        raise ValueError("K 线接口返回的数据不是列表")
    previous_day_timestamp = start_timestamp - DAY_SECONDS
    by_time: dict[int, dict[str, Any]] = {}
    for candle in candles:
        if not isinstance(candle, dict):
            raise ValueError("K 线数据必须是对象")
        timestamp = _finite_number(candle.get("t"), "K 线时间戳 t")
        if not timestamp.is_integer():
            raise ValueError("K 线时间戳必须是整数秒")
        timestamp = int(timestamp)
        if previous_day_timestamp <= timestamp < end_timestamp:
            if timestamp in by_time:
                raise ValueError("K 线存在重复时间戳")
            by_time[timestamp] = candle

    expected = list(range(previous_day_timestamp, end_timestamp, DAY_SECONDS))
    if sorted(by_time) != expected:
        raise ValueError(
            f"需要连续 {len(expected)} 根完整 UTC 日 K 线（含区间前一日）；"
            "当前数据缺失或日界线不匹配"
        )

    period_high = -math.inf
    period_low = math.inf
    previous_close = None
    for timestamp in expected:
        candle = by_time[timestamp]
        high = _finite_number(candle.get("h"), "最高价 h")
        low = _finite_number(candle.get("l"), "最低价 l")
        close = _finite_number(candle.get("c"), "收盘价 c")
        if low <= 0 or high < low or not low <= close <= high:
            raise ValueError("K 线价格必须为正，且满足最低价 <= 收盘价 <= 最高价")
        if timestamp == previous_day_timestamp:
            previous_close = close
        else:
            period_high = max(period_high, high)
            period_low = min(period_low, low)
    amplitude = (period_high - period_low) / previous_close * 100
    if not math.isfinite(amplitude):
        raise ValueError("一个月振幅超出有限数值范围")
    return amplitude


def get_month_amplitude(
    base_asset: str, *, session: requests.Session | None = None,
    now: float | None = None,
) -> float:
    """查询最近一个已完成自然月及区间前一日的 K 线，计算整体振幅。"""
    base_asset = parse_base_asset(base_asset)
    if session is None:
        with requests.Session() as owned_session:
            return get_month_amplitude(base_asset, session=owned_session, now=now)
    start_timestamp, end_timestamp = get_month_window(now)
    response = session.get(
        GATE_CANDLES_URL,
        params={
            "contract": f"{base_asset}_USDT",
            "interval": "1d",
            "timezone": "utc0",
            "from": start_timestamp - DAY_SECONDS,
            "to": end_timestamp - 1,
        },
        headers={"Accept": "application/json"},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return calculate_month_amplitude(
        response.json(), start_timestamp=start_timestamp, end_timestamp=end_timestamp,
    )


def get_monthly_metrics(base_asset: str) -> MonthlyMetrics:
    """共享 HTTP 会话，返回可供其他模块使用的结构化结果。"""
    base_asset = parse_base_asset(base_asset)
    with requests.Session() as session:
        performance = get_month_performance(base_asset, session=session)
        amplitude = get_month_amplitude(base_asset, session=session)
    return MonthlyMetrics(base_asset, performance, amplitude)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="查询一个月涨跌幅与一个月振幅的算术平均值。",
        epilog="振幅区间为最近一个已完成 UTC 自然月；涨跌幅使用 TradingView Perf.1M。",
    )
    parser.add_argument(
        "base_asset", nargs="?", default="BTC", type=parse_base_asset,
        help="基础币种，默认 BTC，例如 ETH、1000PEPE",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = get_monthly_metrics(args.base_asset)
    except requests.RequestException as exc:
        print(f"请求失败：{exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"数据解析失败：{exc}", file=sys.stderr)
        return 1
    print(f"币种：{result.base_asset}")
    print(f"1 个月涨跌幅：{result.performance_1m:+.2f}%")
    print(f"1 个月振幅（最近一个完整 UTC 自然月）：{result.amplitude_1m:.2f}%")
    print(f"1 个月综合均值：{result.combined_average:+.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
