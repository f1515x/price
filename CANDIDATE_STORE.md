# SQLite 离线研究候选日志

`candidate_store.py` 完成计划 4.2 的候选日志持久化子项（E4），在 E1/E2/E3 兼容库中增加 `candidate_runs` 和 `candidate_rows`。复用 M4 的七条规则和共同可用样本口径，不修改原入口或策略。

```powershell
python history_store.py --database ..\1\data\E4-candidates.sqlite list
python candidate_store.py --database ..\1\data\E4-candidates.sqlite build <snapshot_id> --window 365 --swing-length 50 --tail 10 --move 2 --stretch 2
python candidate_store.py --database ..\1\data\E4-candidates.sqlite list
python candidate_store.py --database ..\1\data\E4-candidates.sqlite query BTC --run-id <run_id> --start 2025-02-01 --end 2025-03-01
```

`build` 接收多个快照 ID，重新验证原始证据并核对库内日线，从 M2/M3 重算指标、结构，再调用 M4 `signals`。完整保存每根已收盘日线，包括预热、缺口及未触发时点。与 M4 一样，只有收益、收益分位、Move、Stretch 均可用且结构状态 OK 时，才计算七条规则；不能将单项可用的观察值冒充共同可用候选。因而这是 M4 研究比较口径，并非计划最终上线规则。

每行保存时间、标的、市场、周期、来源、价格、完整指标及其样本量/缺失原因、完整结构及确认时间、信号时间和最早执行时间。每条规则包含方向（1 多、-1 空、0 无候选）、状态及原因：

- `UNAVAILABLE`：缺少必要指标或结构不可用；保留具体缺失字段以及原指标/结构原因。
- `NO_CANDIDATE`：数据可用，但收益方向为零、阈值未达到或结构方向冲突。
- `RESEARCH_CANDIDATE`：触发既有研究规则，仅描述原始研究信号。

日志不使用未来收益标签，不去重、不模拟成交，也不登记新策略假设；连续多日触发的计数不是独立事件数或成交数。固定 `validation=NOT_VALIDATED`、`execution_authorized=false`，评分和结构分位为 `null`（展示为 N/A）。没有挂单、风控审批、线上输出或影子调度；M6 基础假设仍为 `TERMINATED`，M7/M8/M9 的依赖不变。

运行 ID 绑定原快照、三组参数、规则名、输入文件摘要、实现版本与六个源码文件哈希及输出摘要。不同参数/输入保留独立版本；相同构建验证并重算后不新增行。整批校验失败或 SQL 失败会回滚；兼容原表及 E1 `user_version=1`。

查询必须指定运行 ID 及匹配标的，时间按 UTC 日桶 `[start,end)` 筛选，返回完整 JSON 并按时间递增排序。查询键 `(run_id,timestamp)` 提供索引；只读查询不会创建缺失数据库。源码/原始目录必须保留；查询不会重验文件，数据库无防篡改签名。结构参考回放是平方级离线实现；构建期间应避免并发改动证据和日线。

完整测试：`python -m unittest discover -s tests`。新增 8 项覆盖 M4 一致性、缺失记录、前缀因果性/缺口、多标的往返、原结构共存、版本隔离/幂等、输入篡改、事务回滚及 CLI/查询边界。

真实验收工具从 E3 创建独立副本，拒绝覆盖既有产物；验收使用默认参数的 E2/E3 记录逐行独立比对。重新验收请指定新输出路径：

```powershell
python audit_candidate_store.py --baseline ..\1\data\E3-structures.sqlite --database ..\1\data\E4-recheck.sqlite --output ..\1\data\E4-recheck.json
```

交付数据库为 `../1/data/E4-candidates.sqlite`，机器记录为 `../1/data/E4-candidate-store.json`。持续采集调度仍待实施。
