# 架构与迁移说明

## 调用树

```text
cli / 根目录兼容脚本
├── market.precision → Gate.io 公开合约接口 → data/price_steps.json
├── strategy.signals
│   ├── market.performance → TradingView
│   └── analysis.structure
│       ├── market.candles → Gate.io → data/candles/<SYMBOL>.json
│       └── analysis.indicators → ATR14 / r 值
├── risk.sizing
│   ├── strategy.signals → 当次分析的价格和方向
│   ├── risk.allocation → clients.gate → 杠杆与账户保证金
│   ├── Gate.io 公开合约信息 → quanto_multiplier
│   ├── data/price_steps.json
│   └── reporting.text → 仓位报告
└── clients.telegram → 报告 + config/chat_ids.txt → Telegram
```

`settings` 统一解析运行路径与凭据。纯信号公式、SMC、ATR 和报告格式均可独立使用；部分外部请求仍位于市场模块和仓位编排模块，未额外引入无实现的抽象层。

## 迁移映射

| 原模块/文件 | 当前实现/文件 |
| --- | --- |
| kline.py | market/candles.py |
| month.py | market/performance.py |
| smc.py | analysis/structure.py + indicators.py |
| price.py | strategy/signals.py |
| amount.py | risk/allocation.py + clients/gate.py |
| size.py | risk/sizing.py + reporting/text.py |
| float.py | market/precision.py |
| tele_gate.py | clients/telegram.py |
| symbol.txt / id.txt | config/symbols.txt / chat_ids.txt |
| float.js | data/price_steps.json |
| size.txt / price.txt | reports/sizes.txt / signals.txt |
| <SYMBOL>_data.js | 新缓存默认 data/candles/<SYMBOL>.json |

根目录 Python 文件只是兼容层。旧缓存不会自动读取，可将其 JSON 内容复制到新的对应缓存文件；已有 JSON/JS 行情仍可显式传给 structure 命令。仓库外依赖旧数据 URL 或文件路径的消费者需要同步使用新路径。

## 保持的计算行为

月涨跌幅百分数与结构 r 值小数的单位不变；信号条件仍为严格超过 ±15% 和 ±0.10；信号价格仍为调整后的 weak 价格乘 1.01 或 0.99。仓位价值仍为最大可开仓价值的 1%，张数向零取整，做空负数、做多正数。报告价格继续 ROUND_DOWN 量化。

SMC/ATR/r 值使用 200 根合成 K 线与迁移前实现逐项核对，预期结果保存在测试 fixture 中。

## 行为调整

- 密钥读取由模块导入阶段延后到签名请求；环境变量优先于可选 .env。
- 账户保证金请求增加 15 秒超时。
- 移除 TradingView 源码内嵌会话 cookie；保留原 URL、请求字段和 headers。尚未验证真实匿名请求响应。
- 工作流先更新当次精度映射，再计算仓位。
- 数据使用 JSON 扩展名，输入配置和报告分目录保存。
- 统一 CLI 的 performance 命令在查询失败时返回非零退出码。

## 后续工程边界

当前精度映射来自价格文本小数位，不代表交易所的实际下单步长；迁移没有替换这套公式。K 线更新仍采用末尾 8 条替换，长时间停机时未自动补齐断档。生成报告依然追加时间戳并提交，因此仍可能每次运行产生提交。

依赖已集中声明在 pyproject.toml，尚未锁定版本。部署前可在选定 Python 和操作系统上生成依赖锁文件。生产定时任务仍遵循 GitHub 默认分支上的 schedule 行为，迁移分支上的 CI 会独立执行。
