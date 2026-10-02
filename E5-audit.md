# E5 持续研究数据采集调度验收（2026-10-01）

完成计划 4.2 的持续采集调度工程项。代码：[collection_scheduler.py](../source/collection_scheduler.py)，用法：[COLLECTION_SCHEDULER.md](../source/COLLECTION_SCHEDULER.md)，独立复核：[audit_collection_scheduler.py](../source/audit_collection_scheduler.py)。

- 支持单次执行及常驻每日调度，默认 UTC 00:05 后采集已收盘日线；每 60 秒检查，失败重试，成功后等待下一日。固定历史起点覆盖停机漏采日期，收盘前不纳入当前日线。
- 依次写入 E1 历史、E2 指标、E3 结构、E4 离线候选日志；参数/源码/数据版本可追溯。不可变快照重验，重启幂等，阶段失败保留证据并可重试。
- 排他锁阻止同根目录并行执行，状态原子替换，周期日志追加；完成状态只在所有标的、所有阶段成功后写入。数据不足、缺口仍如实记录。
- 7 项新增测试通过；全套 **150 项测试通过**。覆盖多标的完整链路、收盘延迟、缺口、幂等、停机补采、阶段/网络失败恢复、锁、证据篡改拒绝及到期调度重试。
- 使用既有真实 Gate 归档响应重放 BTC/ETH 各 425 根日线，四层记录与独立重算全部一致；每资产共同可用候选日志 30 行。重复运行新增 0 行，原六份证据文件哈希不变，SQLite 完整性 `ok`、外键错误 0。
- 单独执行真实 Gate 公共 HTTP 接口检查：BTC `[2025-02-27,2025-03-01)` 两根日线返回并通过 OHLCV 质量校验，无缺失或质量问题。此检查不等同长期稳定性验证。

验收产物：[机器验收](data/E5-collection/acceptance.json)、[数据库](data/E5-collection/research.sqlite)、[最新周期状态](data/E5-collection/state.json)、[周期日志](data/E5-collection/cycles.jsonl)、[联网检查](data/E5-collection/transport-smoke.json)、[新增测试](../source/tests/test_collection_scheduler.py)。原始快照保存于同目录 `snapshots/`。

完整验收模式为 `VERIFIED_ARCHIVED_RESPONSE_REPLAY_NOT_LIVE`，没有将归档重放当作当前实时信号。没有安装系统任务或启动长期后台服务，运行方式见使用说明。平方级结构回放及每日完整版本会增长耗时和存储，本期没有实现增量计算或保留期清理。强制结束后可能遗留锁，需确认进程退出再移除。四个阶段分别事务提交，失败周期可能留有部分阶段，不能把部分阶段当作完整交付。

本项仅交付研究数据采集调度；`COMPLETE` 表示管道工程成功，日志固定 `NOT_VALIDATED`、`execution_authorized=false`，评分/结构分位 N/A。M6 基础假设仍 `TERMINATED`，策略验收仍 `NOT_VALIDATED`，M7/M8/M9 依赖不变；停机补采不构成实时影子运行证据。

代码提交：`feature@e99e0b0769e2e18b45da00b1c5a10b6ff29ba9d9`（本地提交，未推送）；计划、报告及验收数据保存于 `../1`。
