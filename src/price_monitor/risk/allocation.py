# coding: utf-8
"""建议仓位公式与 CLI；账户请求由 clients.gate 提供。"""
import sys
import requests
import argparse

# =========================== 配置区 ===========================

FEE_RATE = 0.00075          # 交易费率（如 0.075%）
HOST = "https://api.gateio.ws"
PREFIX = "/api/v4"
DEFAULT_CONTRACT = "CL_USDT"
# =============================================================

from price_monitor.settings import load_env, credentials
from price_monitor.clients.gate import gen_sign, get_max_leverage, get_total_available_margin, parse_max_leverage_from_q_multiplier


def compute_max_open(available_margin, max_leverage, fee_rate):
    """使用从错误信息中提取的最大杠杆计算最大可开仓价值（USDT）"""
    denominator = 1.0 / max_leverage + 2 * fee_rate
    if denominator <= 0:
        raise ValueError("分母无效，请检查最大杠杆和费率")
    return available_margin / denominator


def amount(max_open):
    """计算仓位价值，取最大开仓价值的 1%"""
    return round(0.01 * max_open, 2)


def main():
    parser = argparse.ArgumentParser(
        description="从 Gate.io 杠杆限制错误中提取最大杠杆，计算最大可开仓位（USDT价值）并输出1%仓位建议"
    )
    parser.add_argument(
        '-c', '--contract',
        default=DEFAULT_CONTRACT,
        help=f"合约名称，默认 {DEFAULT_CONTRACT}"
    )
    args = parser.parse_args()

    session = requests.Session()
    try:
        print(f"=== 正在获取合约 {args.contract} 的最大杠杆限制 ===")
        max_leverage = get_max_leverage(session, args.contract)
        print(f"合约信息中的最大杠杆: {max_leverage}\n")

        print("正在获取可用保证金...")
        margin = get_total_available_margin(session)
        print(f"可用保证金: {margin:.8f} USDT\n")

        max_open = compute_max_open(margin, max_leverage, FEE_RATE)
        formula = f"{margin:.4f} / (1/{max_leverage} + 2*{FEE_RATE})"

        print(f"{'最大杠杆':>8} | {'最大开仓(USDT)':>20} | 计算公式")
        print("-" * 70)
        print(f"{max_leverage:>8} | {max_open:>20.8f} | {formula}")

        suggested_position = amount(max_open)
        print(f"\n建议仓位价值 (max_open 的 1%): {suggested_position:.2f} USDT\n")

    except Exception as e:
        print(f"执行失败: {e}")
        sys.exit(1)
    finally:
        session.close()
        print("\n[信息] requests 会话已关闭（连接已断开）")


if __name__ == "__main__":
    main()
