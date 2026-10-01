# SQLite 动态指标历史

`indicator_store.py` 完成计划 4.2 的指标持久化子项（E2）。在 E1 历史库中增加 `indicator_runs`、`indicator_rows` 两张附加表，保持原历史表及 `user_version=1` 兼容；未生成指标的 E1 库可直接使用，`list` 返回空数组。

```powershell
python history_store.py --database ..\1\data\E2-indicators.sqlite list
python indicator_store.py --database ..\1\data\E2-indicators.sqlite build <snapshot_id> --window 365 --ema-period 50 --atr-period 14
python indicator_store.py --database ..\1\data\E2-indicators.sqlite list
python indicator_store.py --database ..\1\data\E2-indicators.sqlite query BTC --run-id <run_id> --start 2025-02-01 --end 2025-03-01
```

`build` 接收一个或多个快照 ID。先通过原快照目录重新校验 CSV、原始证据及质量报告，逐行核对数据库历史，再调用已有 M2 `calculate`；原目录丢失或证据不一致时拒绝构建。运行 ID 绑定输入快照、指标版本、完整参数、指标源码 SHA-256 和输出摘要。改参数或改源码产生独立运行，重复构建不增加行数。全批写入使用单个事务，失败全部回滚。

完整 JSON 行保留标的、市场、周期、时间、价格、收益分位、Move、Stretch、Robust Z、EMA/ATR、样本量及历史覆盖、参数版本、缺失原因和数据状态。预热及缺失值保持 `null`，不会伪造数值或交易信号。主键 `(run_id,timestamp)` 支持显式版本的 UTC `[start,end)` 查询，标的不匹配时报错。查询只读且不会因路径写错创建空库。

数据库是可重建索引，不是防篡改证据库；查询不重新核验原始文件。构建期间应避免其他程序改动原始证据或直接修改历史表。完整原始证据需继续保留。

E2 实际验收在 E1 库的独立副本 `../1/data/E2-indicators.sqlite` 上运行，原 E1 文件不变。BTC/ETH 四个快照共 5,780 行，与 M2 逐行一致，4,200 行状态 OK；各版本 2025 年 2 月查询返回 28 行，重复构建新增 0 行，SQLite 完整性与外键检查通过。完整记录见 `../1/data/E2-indicator-store.json`。

测试：`python -m unittest discover -s tests`，128 项通过，其中新增 7 项覆盖多标的往返、缺口/预热、查询边界、幂等、参数隔离、原文件/数据库篡改拒绝、批量 SQL 回滚及 CLI。

SMC 结构、候选日志和持续采集调度仍待实施。未接入交易入口；M6 `NOT_VALIDATED`、基础假设 `TERMINATED` 及 M7/M8/M9 依赖保持不变。
