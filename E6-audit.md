# E6：离线研究候选可读输出验收

日期：2026-10-01。对应 `plan.md` 4.2「输出至少包含……未完成的评分和历史分位明确显示 N/A」的离线研究输出工程项。

代码提交：`feature@c74fa4c74e40e71874b5287215ae058422192112`（本地提交，未推送）；计划、验收报告和数据位于仓库外 `../1`。

## 交付

- [输出工具](../source/candidate_report.py)：指定 SQLite 数据库、运行 ID、标的、规则和 UTC 日桶范围，输出可读表格或 UTF-8 CSV。
- [使用说明](../source/CANDIDATE_REPORT.md)、[复核工具](../source/audit_candidate_report.py)、[5 项新增测试](../source/tests/test_candidate_report.py)。
- [机器验收](data/E6-report/acceptance.json)：保存原库哈希、源码哈希、每版本/规则状态计数及示例文件摘要；同目录保存各快照 28 日 CSV 和 3 日预热表格，共 8 个示例。

输出包含日线时间、信号时间、价格、30 日收益百分比、收益分位、Move、Stretch、SMC 趋势和 weak/strong、数据状态、规则方向及触发/过滤原因。CSV 另存结构确认和最早执行时间、历史观测数、指标与结构缺失原因、参数、输入和源码哈希；表格标题保留运行、快照及参数版本。

未实现评分及结构分位显示 `N/A`；预热及未触发行保留。表格浮点显示六位有效数字，CSV 保留完整浮点表示；UTC 日桶范围为 `[start,end)`，日线时间与信号时间分别展示。查询不会创建缺失数据库，输出文件拒绝覆盖。

## 验证结果

在 `../source` 运行：

```powershell
python audit_candidate_report.py --database ..\1\data\E4-candidates.sqlite --output ..\1\data\E6-report
python -m unittest discover -s tests
git diff --check
```

- BTC/ETH 共 4 个快照、5,780 根日线，七条既有规则共 40,460 条决策全部复核通过。CSV 所有导出字段完整往返一致，收益单位、指标、结构、方向、状态和原因与存储记录一致。
- 每个版本 2025-02-01 至 2025-03-01 导出恰好 28 行，总计 112 行；每个预热示例显示 `UNAVAILABLE`、`N/A` 和 `NOT_VALIDATED`。
- 全部 155 项测试通过（原 150 项及新增 5 项），覆盖空范围、错误版本/标的/规则、时间边界、CSV 精度、参数追溯、文件拒绝覆盖及数据库只读。
- E4 原数据库 SHA-256 前后相同；工具不运行采集、不重算信号。`git diff --check` 通过。

## 边界

本项完成离线研究输出，不构成 M8 原入口并排输出或实时影子运行；原入口仍受 M6 依赖约束。每根日线的规则计数没有去重，不是独立事件或成交数量。当前策略仍为 `NOT_VALIDATED`，基础假设仍为 `TERMINATED`，没有执行授权。

读取沿用 E4 只读接口，不重验原始证据，也不提供数据库防篡改签名。候选阈值、评分验证、原入口接入及 M6 历史规格/精确成本缺口均未因本项解除。
