# E1：SQLite 多标的历史数据存储验收

日期：2026-10-01。完成 plan.md 第四象限 4.2 的 SQLite 历史数据存储实施项；在 `../source` 的 `feature` 分支开发，GitHub 插件确认项目为 `huan00000/price`。

产物：[存储代码](../source/history_store.py)、[使用说明](../source/HISTORY_STORE.md)、[8 项新增测试](../source/tests/test_history_store.py)、[本地数据库](data/E1-history.sqlite)、[机器验收记录](data/E1-history-store.json)。

## 实现与范围

- 校验 M1 原始响应及 CSV 哈希，重算质量与 30 日收益后导入；保留完整质量报告和来源目录。
- 用质量报告内容哈希区分快照版本；相同证据重复导入不新增记录，重叠或修订版本分别保存，查询显式选择版本和标的。
- 支持多标的批量导入和 UTC `[start,end)` 时间查询，返回字段与 `history.load_snapshot` 一致，包括缺失收益的空字符串及数据状态。
- 全批输入先验证，SQL 写入使用单个事务；异常整批回滚。只读查询不创建数据库，拒绝未知结构。主键为 `(snapshot_id,timestamp)`。

## 验证

`python -m unittest discover -s tests`：121 项全部通过（原有 113 项，新增 8 项）。新增覆盖多标的往返及边界、重复导入、修订版本隔离、损坏输入整批拒绝、SQL 写入失败回滚、缺口及质量保留、错误标的/版本/区间拒绝、只读与外来结构保护。首次测试的两处测试连接未关闭问题已修复，完整重跑通过。

实际导入 BTC/ETH 各两版：原 M1/M6 早期样本各 425 行，以及 M6 完整历史各 2,465 行，共 4 个快照、5,780 行（不同版本分别计数，不能当作独立行情样本数）。完整历史覆盖 2020-01-01～2026-09-30。

逐字段核对四个快照的全部读取结果，与原加载器完全一致；四版各查询 2025-02-01～2025-03-01，均准确返回 28 行。再次导入全部快照新增 0 行。`PRAGMA integrity_check` 为 `ok`，外键错误为 0；数据库、源码和各版输入哈希保存在机器记录中。

复现：

```powershell
python history_store.py --database ..\1\data\E1-history.sqlite list
python history_store.py --database ..\1\data\E1-history.sqlite query BTC --snapshot-id 8a23caf94005d64b4ef105368bb7e94527e588cd8a186c8106ffd7cba6534646 --start 2025-02-01 --end 2025-03-01
```

## 验收边界

E1 工程验收 `PASS`。SQLite 是可重建索引，原始快照仍是校验依据；没有数据库签名或通用秘密扫描。此次仅存储历史 OHLCV/收益，不迁移 SMC、动态指标或候选日志，不增加调度任务。当前交易入口未改变；M6 仍为 `NOT_VALIDATED`、基础假设仍为 `TERMINATED`，M7/M8/M9 依赖不变。

代码提交见 plan.md 3.18；仅本地提交，未推送。
