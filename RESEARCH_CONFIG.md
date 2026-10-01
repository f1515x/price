# E9 统一离线研究参数

`research_config.py` 为采集器和单资产离线模拟提供统一 JSON 配置；示例为
[`research/offline_config.example.json`](research/offline_config.example.json)。

```powershell
python collection_scheduler.py --root ..\1\data\configured-collection --research-config research\offline_config.example.json
python trade_simulation.py ..\1\data\BTC-20240101-20250301 --research-config research\offline_config.example.json --output ..\1\data\configured-simulation.json
```

六个顶层字段必须齐全：`schema_version=1`、`collection`、`indicators`、`structures`、`events`、`execution`。
采集部分要求 symbols、UTC 起始日期 start、收盘等待秒数 close_delay；其他部分按现有 Config 校验。
执行部分必须显式提供 initial_equity、risk_fraction、max_exposure、max_drawdown；其余字段可省略，实际默认值会展开记录。
未知字段、重复 JSON 键、NaN/Infinity、布尔数值、错误整数类型和非法区间均拒绝。

采集器使用 indicators、structures 和 events 中的 tail/move/stretch；不模拟或执行交易。
单资产模拟使用指标、结构、完整 events 和 execution 参数；collection 只用于共享配置追溯，模拟输入由 snapshot 路径决定。
events 的 train_fraction、seed、min_events 属于事件研究；execution.min_events 属于模拟描述门槛，两者职责不同。
旧命令行仍可使用；采集器的 --research-config 禁止与 --window、--tail 等参数覆盖组合，
模拟器的 --config 与 --research-config 互斥。输出仍拒绝覆盖已有文件。

每个配置同时具有原文件 `file_sha256` 和展开默认值、规范化标的后的 `parameter_version`。
后者为排序 JSON 的 SHA-256，只改缩进、键序或 UTF-8 BOM 不改变参数版本。
采集 state.json/cycles.jsonl 的 evidence.parameters.parameter_profile 保存完整参数及两个哈希，
同一周期的 stages 链接 SQLite 候选 run_id；候选自身仍保留实际指标、结构和阈值参数版本。
模拟报告的 parameter_profile 保存同一证据，event_parameters 记录实际事件参数。
采集和模拟记录配置加载器源码哈希。改变源码会产生新的采集周期身份；历史证据不重写。

示例 execution 是明确的代理成本/数量场景，乘数、tick 和数量约束并非真实历史合约证据。
该文件没有接入组合/滚动 M6 预登记协议、原交易入口或已部署的 Windows 任务；那些路径继续使用既有配置。
统一配置不登记新假设，不解除 M6/M7/M8/M9 依赖。基础假设保持 TERMINATED，策略保持 NOT_VALIDATED。
事件研究仍为已有 M4 描述性切分，参数调整不是新的独立样本外验证。

归档响应验收可用新目录重放（不是实时行情）：

```powershell
python audit_collection_scheduler.py --root ..\1\data\E9-recheck --research-config research\offline_config.example.json ..\1\data\BTC-20240101-20250301 ..\1\data\ETH-20240101-20250301
python -m unittest discover -s tests
```
