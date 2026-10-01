# SQLite 历史数据存储

`history_store.py` 使用 Python 标准库 SQLite，为 4.2 的多标的历史存储提供可追溯版本及 UTC 时间查询。仅导入 M1 `history.save_snapshot` 产物；先校验原始响应、CSV 哈希并重算质量与收益，不导入任意 CSV。

```powershell
python history_store.py --database ..\1\data\history.sqlite import ..\1\data\BTC-20240101-20250301 ..\1\data\ETH-20240101-20250301
python history_store.py --database ..\1\data\history.sqlite list
python history_store.py --database ..\1\data\history.sqlite query BTC --snapshot-id <list输出的snapshot_id> --start 2025-02-01 --end 2025-03-01
```

`list` 保存完整质量报告、原始/CSV SHA-256、来源目录及行数；快照 ID 是排序后的完整质量报告 JSON 的 SHA-256。同一证据重复导入不增加行数，时间重叠或修订的数据另存版本，不覆盖旧值。查询必须显式给出版本与匹配的标的，区间为 `[start,end)`；返回字段与 M1 加载器完全兼容，缺失收益保留空字符串及原状态。缺失日线不补齐，未收盘线仍由原质量校验排除。

多快照导入在校验全部输入后执行单个事务，任何 SQL 写入失败回滚整个批次。主键 `(snapshot_id,timestamp)` 支持按版本查询时间段。只读操作不创建数据库，未知或其他应用数据库结构拒绝使用。数据库是可重建的本地索引；原始快照继续保留作为证据。数据库本身没有防篡改签名，不能替代原始证据校验。

本模块范围为历史 OHLCV/30 日收益存储；指标持久化由 E2 [indicator_store.py](INDICATOR_STORE.md) 扩展。SMC、候选日志及持续采集调度仍待实施。未接入交易入口，未启动 M7/M8/M9，也不改变策略验收结论。
