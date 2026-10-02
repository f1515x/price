"""Compatibility entry point; implementation: price_monitor.market.performance."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from price_monitor.market import performance as _implementation

if __name__ == "__main__":
    _implementation.main(_implementation.parse_args().base_asset)
else:
    sys.modules[__name__] = _implementation
