# M6 新执行器规格证据接入

`prospective_research.py` v2 可加载 `spec_evidence.py` 的不可覆盖观察台账。
这完成 M6 的观察证据接入与分区缺口输出子任务；历史有效规格映射和精确成本执行集成仍待完成。

```powershell
python prospective_research.py ..\1\data\M6-full-20261001 `
  ..\1\data\M6-restart-registration.json research\m6_restart_protocol.json `
  --expected-registration-sha256 b2bc4ddbf455c86dd53911d3814c27bd61026d89104fe58fffe15a4b005ea6cd `
  --evidence-ledger ..\1\data\M6-spec-evidence-20261001 `
  --expected-evidence-sha256 845d22b74e248c7cf08a441125879007c092e4f44a706e05bbf3b72ef1ed5408 `
  --output ..\1\data\M6-prospective-evidence-status-new.json
```

台账目录和审阅时保存的 `ledger.json` SHA-256 必须同时提供。
执行器复核全部归档报告、API 原始字节哈希和台账结论，再使用已复核的快照记录，
按登记资产和五个固定测试区间重算观察次数、规格差异及未认证区间。
原台账的研究窗口单独保留；旧历史窗口不能代替未来测试窗口。
原台账未请求的资产若在归档内仍参与重算，真正缺失的资产输出 `NO_SPEC_OBSERVATIONS`。
接收时间晚于执行时钟的观察拒绝加载。

`specification_evidence` 保存台账固定哈希、快照数、原研究窗口和五份分区缺口报告。
新增加载器与台账复核器源码哈希由原有 `code_sha256` 字段记录。
不提供台账时保留兼容调用，显式输出 `NO_LEDGER_PROVIDED` 和全部资产/区间缺口。
错误证据在报告写入或行情研究开始前拒绝，不覆盖已有报告。

等待未来数据期间仅读取登记与规格证据，不读取行情或计算收益。
未来全部分区结束后仍沿用固定参数和原模拟通路；观察规格不会映射成有效期间或修改执行参数。
`used_for_execution_parameters=false`，`historical_specs_verified=false`，`exact_costs_verified=false`。
等待和完成研究两条通路都保留 `verified_historical_specs` 与 `exact_cost_evidence` 失败项。
本功能没有认证历史有效期间、账户费用、滑点或精确结算价，不能解除 M6/M7/M8/M9 验证依赖。
登记源码、协议、规则、风险、分区及验收门槛保持冻结。

```powershell
python -m unittest discover -s tests -q
```
