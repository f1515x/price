# E2 指标 SQLite 持久化验收（2026-10-01）

完成计划 4.2 尚未实现的指标历史存储子项。实现文件为 [indicator_store.py](../source/indicator_store.py)，命令和范围见 [使用说明](../source/INDICATOR_STORE.md)。

- 在 E1 历史库副本上保存 BTC/ETH 四个分版本快照的 5,780 行指标，逐行与 M2 重算结果一致；其中 4,200 行状态 OK，预热、缺失及其原因完整保留。
- 每个版本的 `[2025-02-01,2025-03-01)` 查询返回 28 行。重复构建新增 0 行；参数、源码和输入版本隔离，输入质量报告及哈希可追溯。
- 构建重新验证原始证据，并核对数据库日线。新增测试确认原文件或数据库被修改时拒绝导入，SQL 失败回滚整个批次。
- 完整测试 128 项通过，新增 7 项。SQLite `integrity_check=ok`，外键错误为 0；E1 原文件 SHA-256 不变。

产物：[数据库](data/E2-indicators.sqlite)、[机器验收记录](data/E2-indicator-store.json)、[测试](../source/tests/test_indicator_store.py)。复核时可按使用说明再次构建各 snapshot_id，确认 inserted=false；用 query 与 `indicators.calculate(history.load_snapshot(...)[0])` 比较。

E2 是本地研究存储工程交付。数据库不提供防篡改签名，查询不重新校验原始证据；构建时需保留原目录，避免并发修改证据及历史表。SMC、候选日志及持续采集调度未实现，M6 仍为 `NOT_VALIDATED`，当前基础假设仍 `TERMINATED`，M7/M8/M9 依赖不变。

代码提交：`feature@930ee185c9c57fc7f8ba67f93d1ad7611fcbe12a`（本地提交，未推送）。
