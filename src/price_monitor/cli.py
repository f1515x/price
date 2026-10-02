"""Dispatch existing commands without mixing their argument parsers."""
import argparse
import importlib
import sys

COMMANDS = {
    "candles": "market.candles",
    "performance": "market.performance",
    "structure": "analysis.structure",
    "signals": "strategy.signals",
    "allocation": "risk.allocation",
    "sizes": "risk.sizing",
    "precision": "market.precision",
    "notify": "clients.telegram",
}


def main():
    parser = argparse.ArgumentParser(description="行情分析、信号与仓位监控")
    parser.add_argument("command", choices=COMMANDS)
    args = parser.parse_args(sys.argv[1:2])
    module = importlib.import_module(f"price_monitor.{COMMANDS[args.command]}")
    old_argv = sys.argv
    try:
        sys.argv = [old_argv[0], *old_argv[2:]]
        if args.command == "performance":
            result = module.main(module.parse_args().base_asset)
            return 0 if result is not None else 1
        return module.main()
    finally:
        sys.argv = old_argv
