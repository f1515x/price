# 离线候选表格与 CSV 输出（E6）

`candidate_report.py` 读取 E4/E5 数据库中的既有日志，完成计划 4.2 的研究候选输出项。必须指定运行版本和标的；默认展示 `percentile_structure`，可用 `--rule` 选择七条 M4 规则中的任意一条。不会重新生成信号。

在源码目录运行：

```powershell
python candidate_store.py --database ..\1\data\E4-candidates.sqlite list
python candidate_report.py --database ..\1\data\E4-candidates.sqlite BTC --run-id <run_id> --start 2025-02-01 --end 2025-03-01
python candidate_report.py --database ..\1\data\E4-candidates.sqlite BTC --run-id <run_id> --rule move --format csv --output candidates-new.csv
```

时间过滤针对 UTC 日桶 `[start,end)`，`bar_time_utc` 是日线起点，`signal_time_utc` 是收盘后信号时间。CSV 另存最早执行及结构确认时间。`ret_30d_pct` 已乘以 100，收益分位保持 0～100，Move、Stretch 是倍数。表格数字显示六位有效数字；CSV 保留 Python 浮点完整表示，供后续处理。

每根日线一行，包含价格、收益、分位、Move、Stretch、趋势、weak/strong 价格、共同可用状态、候选方向及原因。保留 `UNAVAILABLE` 和 `NO_CANDIDATE` 行；方向 `NONE` 不代表数据可用，需同时看状态及原因。CSV 包含历史收益观测数、指标/结构缺失原因、输入哈希、源码哈希及三组参数 JSON；观测数不是独立事件数。表格标题记录标的、规则、运行及快照版本、参数和研究验证状态。

缺失数值、未实现评分和结构分位显示 `N/A`。分数不能从异常度推算；当前日志仍为 `NOT_VALIDATED`，没有执行授权。查询仅展示既有研究数据，未接入原交易入口，不构成 M8 影子运行，也不解除 M6/M7/M8/M9 依赖。

输出文件使用 UTF-8，已有路径拒绝覆盖；数据库按已有只读查询通路打开，不创建缺失数据库。查询沿用 E4 限制：不重验原始文件，也不为数据库增加防篡改签名。空区间输出表头（表格额外说明无数据），错误版本/标的/规则及倒置区间报错。

复核工具读取全部快照和全部七条规则，核对原始字段、方向与原因、CSV 往返、预热 N/A、28 日边界及数据库文件哈希，并生成新目录中的审计记录与示例：

```powershell
python audit_candidate_report.py --database ..\1\data\E4-candidates.sqlite --output ..\1\data\E6-recheck
python -m unittest discover -s tests -v
```

正式验收文件在 `../1/data/E6-report/acceptance.json`，说明在 `../1/E6-audit.md`。新增测试覆盖百分比单位、UTC 信号时间、不可用记录、规则方向、CSV 精度及版本追溯、空区间、查询边界、只读与拒绝覆盖。
