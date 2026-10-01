# M6 新协议执行器

`prospective_research.py` 执行已冻结的 `m6-move-filter-prospective-20261001-v1`。
研究范围为 BTC/ETH、收益分位 + Move ≥ 2、方向一致的已确认结构，以及原始 weak 价格挂单。
旧规则使用本地 30 日收益代理，仍不同于 TradingView `Perf.1M`。

```powershell
python prospective_research.py ..\1\data\M6-full-20261001 `
  ..\1\data\M6-restart-registration.json research\m6_restart_protocol.json `
  --expected-registration-sha256 b2bc4ddbf455c86dd53911d3814c27bd61026d89104fe58fffe15a4b005ea6cd `
  --output ..\1\data\M6-prospective-status.json
```

输出文件必须尚不存在；后续状态检查请使用新文件名。运行器不会覆盖报告或改写输入。
登记、候选协议、旧协议、五个固定分区、12 组执行版本和全部已登记 Python 文件必须通过校验。
源码变化会拒绝执行，应保留登记时源码和新执行器的独立 checkout；不得改登记哈希绕过校验。
新执行器及审计工具的哈希另记在报告中，不修改已有登记证据。

当前日期只产生 `AWAITING_FUTURE_DATA`、`NOT_VALIDATED`，不会读取行情或生成收益。
五个连续 365 日区间从 2026-11-15 UTC 开始，最后于 2031-11-14 00:00 UTC 结束（不含）。
最终最早评估时间对应 America/La_Paz 的 **2031-11-13 20:00**。
执行器不提供修改日期、分区、规则、风险、阈值或选择盈利版本的 CLI 参数。
即使已结束四个区间，也不评估中途收益或提前通过验证。

全部区间收盘后，输入目录须包含每个标的的：

- `BTC-daily/`、`ETH-daily/`：既有 `history.py` 的 raw/CSV/质量报告格式；
  至少 395 个测试前完整日线作为因果预热，随后覆盖全部固定测试日，两个标的时间网格一致。
- `BTC-funding-full/`、`ETH-funding-full/`：既有 `funding_history.py` 的分页原始证据及完整资金费率。
- `BTC-marks-full.json`、`ETH-marks-full.json`：带分页原文和哈希的 1d mark 报告，覆盖结算日。
- `specs/`：既有 `contract_specs.py` 的合约快照。该通路沿用原 M6 当前规格外推模型，
  不认证完整历史规格；ETH 数量精度沿用原证据约定。

旧历史只参与因果指标/结构预热。日线起点和信号收盘时间都须落在所属区间内，
排除测试前一天收盘恰好位于边界的信号。每个区间末尾固定截断 44 日信号，
12 组敏感性版本使用同一信号样本。区间独立本金、共享账户、相关组/敞口/风险约束沿用原实现。
两条规则 × 12 组版本 × 5 个区间 × 两种费用口径，产生 240 次模拟及 48 份汇总。
真实费率 + 日线 mark 保守边界与固定代理费用分开报告，只有前者进入研究门槛计算。
缺失/错误/未收盘数据、缺失结算或损坏哈希会拒绝整轮研究，不填零、不缩短测试区间。

结果可以是 `COMPLETED_RESEARCH_ONLY`，验收仍为 `NOT_VALIDATED`：
当前规格快照不认证历史有效性，配置的手续费/滑点和日线 mark 不认证精确成本。
代码固定保留这两个证据失败项，没有外部布尔开关将其标记通过。
后续历史规格和精确成本证据集成须单独交付；当前执行器完成不解除 M7/M8/M9 依赖。

工程复核：

```powershell
python -m unittest discover -s tests -q
python audit_prospective_research.py ..\1\data\M6-full-20261001 `
  ..\1\data\M6-restart-registration.json research\m6_restart_protocol.json `
  --expected-registration-sha256 b2bc4ddbf455c86dd53911d3814c27bd61026d89104fe58fffe15a4b005ea6cd `
  --output ..\1\data\M6-prospective-audit-new.json
```

审计在临时目录生成**合成行情/资金费率/mark/规格**，注入 2031 年测试时钟，
使用真实加载、指标、结构回放、候选、组合执行和汇总代码跑完全部区间。
只保存工程检查、输入哈希和明确标记的合成结果；临时完整报告随目录清理。
这不是未来市场数据或策略有效性证据。登记、原归档及其哈希保持不变。
