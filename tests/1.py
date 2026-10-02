"""查询1个月涨跌幅与振幅的算术平均值，简称「1个月综合均值」。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from price_monitor.market import quarterly as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
