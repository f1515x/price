# SQLite SMC 结构历史

`structure_store.py` 完成计划 4.2 的 SMC 结构持久化子项（E3）。在 E1/E2 历史库中增加 `structure_runs` 和 `structure_rows`，保持原历史与指标表兼容；没有结构记录时 `list` 返回空数组。

```powershell
python history_store.py --database ..\1\data\E3-structures.sqlite list
python structure_store.py --database ..\1\data\E3-structures.sqlite build <snapshot_id> --swing-length 50
python structure_store.py --database ..\1\data\E3-structures.sqlite list
python structure_store.py --database ..\1\data\E3-structures.sqlite query BTC --run-id <run_id> --start 2025-02-01 --end 2025-03-01
```

`build` 接收一个或多个快照 ID，先重新校验原始快照证据并逐行核对 SQLite 日线，再使用 M3 `replay` 生成结构。运行 ID 绑定输入快照、参数、版本、`structure_history.py`/`smc.py`/`indicators.py` 源码哈希及输出摘要。不同参数和输入保留独立版本；重复构建仍会验证和回放，但不新增行。任何输入校验或 SQL 写入失败都不会留下部分批次。

每行完整保留原 M3 输出：标的、市场、周期、时间、价格、趋势、weak/strong 原价及调整价、ratio、swing_atr、ATR14、pivot 位置及确认时间、结构整体确认时间、信号时间和最早执行时间、连续根数、缺口、状态及缺失原因。未确认结构保持 `null`；不会提前使用 pivot，也不会生成交易候选。

查询必须指定运行版本和匹配的标的，时间区间为 UTC 日桶 `[start,end)`，按时间递增返回完整 JSON。主键 `(run_id,timestamp)` 提供时间查询索引。只读操作不会创建新库。附加表沿用 E1 的 `user_version=1`，不改变原历史数据定义。

本模块采用 M3 的逐前缀参考回放，时间复杂度为平方级；长历史构建可能较慢，适用于离线研究。构建时原快照目录必须存在，且不应并发修改证据或历史表。数据库是可重建索引，无防篡改签名；查询不会重验原始文件。

测试：`python -m unittest discover -s tests`。新增 7 项覆盖多标的往返、确认时间及缺口、与 E2 共存、参数隔离及幂等、原始/库内篡改拒绝、整批 SQL 回滚、查询边界和 CLI。

真实验收记录位于 `../1/data/E3-structure-store.json`，数据库为 E2 独立副本 `../1/data/E3-structures.sqlite`。候选日志及持续采集调度仍待实施；M6 `NOT_VALIDATED`、基础假设 `TERMINATED` 和 M7/M8/M9 依赖不变。
