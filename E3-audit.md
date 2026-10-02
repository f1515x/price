# E3 SMC 结构 SQLite 持久化验收（2026-10-01）

完成计划 4.2 的结构历史存储子项。实现为 [structure_store.py](../source/structure_store.py)，使用方式见 [说明](../source/STRUCTURE_STORE.md)。

- BTC/ETH 四个历史快照共 5,780 行，逐行与 M3 回放一致；其中 5,188 行状态 OK。BTC 短历史版本也与既有 `BTC-M3-structures.json` 完全一致。
- 完整保存 pivot 及结构确认时间、信号和最早执行时间、参数版本、趋势、weak/strong、ratio、swing_atr、缺口及原因。所有非空结构的确认时间均不晚于信号时间。
- 每版本 `[2025-02-01,2025-03-01)` 查询返回 28 行。重复构建新增 0 行；SQLite 完整性检查 `ok`，外键错误 0。
- 在 E2 独立副本上新增结构表，原 E2 文件哈希不变；新库中的已有指标与原库逐行一致，日线与原始快照逐行一致。
- 完整测试 135 项通过，新增 7 项验证多标的、参数隔离、幂等、确认时间、缺口、E2 共存、篡改拒绝、整批 SQL 回滚及 CLI。

产物：[数据库](data/E3-structures.sqlite)、[机器验收记录](data/E3-structure-store.json)、[测试](../source/tests/test_structure_store.py)。复核时按使用说明对各 snapshot_id 再次构建，确认 inserted=false；逐行比较查询结果与 `structure_history.replay(history.load_snapshot(...)[0])`。

回放为平方级离线参考实现，长历史构建耗时较长。原始快照目录必须保留；构建时避免并发修改证据及日线。数据库没有防篡改签名，查询不重验原文件。

仅交付研究存储；候选日志及持续采集调度仍待实施。M6 仍 `NOT_VALIDATED`，基础假设仍 `TERMINATED`，M7/M8/M9 依赖不变。

代码提交：`feature@c11bd89e74a8cdfd0a4581b8d9c6378b721d8ff2`（本地提交，未推送）。
