# 历史规格证据台账与缺口检查

`spec_evidence.py` 将 `contract_specs.py` 的已验证快照打包保存，按资产和观察时间排序，
检查规格字段差异，并输出所需研究区间的证据缺口。它是 M6 历史规格证据管理子任务，
不认证历史规格或精确成本，也不连接账户或下单。

```powershell
python spec_evidence.py build ..\1\data\M6-contract-specs-20261001 `
  ..\1\data\M6-full-20261001\specs --symbols BTC ETH `
  --start 2020-01-01 --end 2026-10-01 --output ..\1\data\spec-ledger-new
python spec_evidence.py verify ..\1\data\spec-ledger-new --expected-sha256 <build输出的ledger_sha256>
python -m unittest discover -s tests -q
```

日期为 UTC，研究区间左闭右开。输出目录必须不存在；所有输入校验后才开始写入。
原 `specs.json` 和 API 响应逐字节保留在 `snapshots/<规格报告SHA-256>/`；
同一规格报告重复导入只保留一次。`ledger.json` 记录输入文件、台账代码及规格校验器哈希。
复核必须提供审阅时保存的台账 SHA-256，并重新读取所有原始证据和重算全部结论。
校验可检测损坏和篡改；文件哈希不能自行证明文件来自交易所。

台账区分以下含义：

- `observed_at`：采集器接收该响应的时间，不是参数生效时间。
- `observed_changes`：相邻观察中执行相关字段的差异；数值相等的字符串格式差异不计为变化。
  差异可能来自接口精度或请求口径，不能直接认定交易所发生了规格变更。
  `effective_time` 始终为 null；同一秒的冲突规格拒绝入库，要求先查明证据。
- `observations_in_window`：研究区间内的观察次数；数量不等于覆盖时长。
- `uncovered_intervals`：当前快照没有历史有效区间证据，因此整个请求区间仍未获认证。
  即使快照落在研究期内，或两次规格相同，也不能据此插值、向前或向后外推。
- ETH 等小数张的步长未知或最小张数为零时，保留 `UNRESOLVED_QUANTITY_PRECISION`。
  本工具不自动采用公告或其它配置补足精度。

`historical_specs_verified` 和 `exact_costs_verified` 始终为 false，
`verified_coverage_seconds` 为 0，验收为 `NOT_VALIDATED`。
公开 maker/taker 费率保留为观察数据，不能冒充账户成交费用、滑点或资金结算价。
缺少所需资产仍输出缺口，不能通过省略 ETH 将 BTC 的证据当作完整覆盖。

本工具没有接入已冻结的 M6 新协议执行器；登记中原有源码保持不变。
获得独立、可核验的历史生效区间及精确成本后，仍须单独交付证据加载、
执行时点映射和模拟集成。M6 策略验收及 M7/M8/M9 依赖保持原结论。
