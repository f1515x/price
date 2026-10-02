"""
结合月涨跌幅与 SMC 结构计算潜在挂单价格。

示例：
    python price.py BTC
    python price.py BTC ETH HYPE SOL
    python price.py HYPE
    python price.py SPX500
    python price.py ETH

输出内容格式:
===== HYPE =====
HYPE_data.js 更新完成：本次请求 8 条，当前共 501 条
本次监测到HYPE的1个月涨跌幅为：+52.34%
当前r值为+12.51%
weak high，weak price = 87.58
open short FINAL_PRICE = 88.46
"""

import argparse
import math
import re

from price_monitor.market.quarterly import get_monthly_metrics, parse_base_asset
from price_monitor.analysis.structure import get_structure


def price(perf_1m, structure, combined_average):
    """按月度综合均值阈值、r 值和 weak 类型计算 FINAL_PRICE。

    ``perf_1m`` 和 ``structure['ratio']`` 分别使用百分数（如 21.21）和
    小数（如 0.12）。最终价格以 SMC 输出中的 ``weak price``，即
    ``adjusted_weak_price`` 为基准。
    ``combined_average`` 使用百分数；保留其符号及完整精度，低位判断
    使用其相反数。格式化为两位小数仅用于展示，不参与比较。
    """
    perf_1m = float(perf_1m)
    threshold_percent = float(combined_average)
    if not math.isfinite(threshold_percent):
        raise ValueError("月度综合均值阈值必须是有限数值")
    threshold_ratio = threshold_percent / 100
    ratio = float(structure["ratio"])
    weak_type = str(structure["weak_type"]).lower()
    weak_price = float(structure["adjusted_weak_price"])

    if perf_1m > threshold_percent and ratio > threshold_ratio and weak_type == "high":
        return 1.01 * weak_price
    if perf_1m < -threshold_percent and ratio < -threshold_ratio and weak_type == "low":
        return 0.99 * weak_price
    return None


def analyze(base_asset, swing_length=50):
    """用同一个币种参数获取月度指标与 SMC 结果并执行判断。"""
    base_asset = parse_base_asset(base_asset)
    result = get_monthly_metrics(base_asset)
    perf_1m = result.performance_1m
    structure = get_structure(base_asset, swing_length)
    final_price = price(perf_1m, structure, result.combined_average)

    print(f"本次监测到{base_asset}的1个月涨跌幅为：{perf_1m:+.2f}%")
    print(f"1 个月综合均值（判断阈值）：{result.combined_average:+.2f}%")
    print(f"当前r值为{structure['ratio'] * 100:+.2f}%")
    print(
        f"weak {structure['weak_type']}，"
        f"weak price = {structure['adjusted_weak_price']:.2f}"
    )
    if final_price is None:
        print("暂无潜在交易机会")
    else:
        action = "open short" if str(structure["weak_type"]).lower() == "high" else "open long"
        print(f"{action} FINAL_PRICE = {final_price:.2f}")

    return final_price


def parse_assets(values):
    """同时支持空格、英文句点和中英文逗号分隔多个币种。"""
    assets = []
    for value in values:
        assets.extend(item for item in re.split(r"[.,，、]+", value) if item)
    return [parse_base_asset(asset) for asset in assets]


def main(argv=None):
    parser = argparse.ArgumentParser(description="结合 month 与 SMC 计算 FINAL_PRICE")
    parser.add_argument(
        "base_assets",
        nargs="+",
        help="币种，例如 BTC，或 BTC ETH HYPE SOL",
    )
    parser.add_argument(
        "-s", "--swing-length", type=int, default=50,
        help="SMC 摆动高低点周期，默认 50",
    )
    args = parser.parse_args(argv)
    if args.swing_length < 1:
        parser.error("--swing-length 必须大于 0")

    assets = parse_assets(args.base_assets)
    failed = False
    for index, asset in enumerate(assets):
        if index:
            print()
        print(f"===== {asset} =====")
        try:
            analyze(asset, args.swing_length)
        except Exception as exc:
            failed = True
            print(f"处理失败：{exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
