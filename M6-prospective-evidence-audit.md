# M6-R4：规格观察台账接入执行器验收

日期：2026-10-01。对应 plan.md 4.1 M6 尚未完成的证据接入，完成其中的
**观察台账接入与登记区间缺口输出**子任务。
已通过 GitHub 插件核对 `huan00000/price`，在本地 `feature` 分支开发和提交，未推送。
代码提交：`3a3044a318a9da0feaf3b7f0a183387f1656a696`；计划和机器验收保存在仓库外的 `../1`。

工程验收 **PASSED**；策略仍 **NOT_VALIDATED**，当前执行状态 **AWAITING_FUTURE_DATA**。
本次没有获得历史生效区间或精确成本证据，也没有计算真实未来收益。

交付 [接入模块](../source/prospective_evidence.py)、[执行器 v2](../source/prospective_research.py)、
[复核工具](../source/audit_prospective_evidence.py)、[使用说明](../source/PROSPECTIVE_EVIDENCE.md)、
[9 项新增测试](../source/tests/test_prospective_evidence.py) 和
[机器验收](data/M6-prospective-evidence-acceptance.json)。

## 完成内容

执行器通过配对参数加载台账目录及审阅时保存的 SHA-256，重新校验全部快照、
原始响应哈希与台账结论。复用内存中已复核快照，按登记 BTC/ETH 和五个固定未来区间
重算观察数量、差异和未认证期间；原台账的历史研究窗口单独保留。
归档内未列入原台账请求的资产仍会重算，真正缺失的资产显示明确缺口。

报告新增 `specification_evidence`：固定台账哈希、快照数、原研究窗口及五份分区报告。
无台账时保留兼容调用，输出 `NO_LEDGER_PROVIDED` 及全部资产/区间缺口。
目录与哈希未配对、固定哈希不符、归档损坏、伪造认证结论及接收时间晚于执行时钟的
观察均在输出或行情研究前拒绝。

等待数据阶段可以检查规格证据，但不读取行情、不运行收益研究。
完成研究阶段也保留 `verified_historical_specs` 与 `exact_cost_evidence` 失败项，
观察台账不能改变挂单、费用、风险等执行参数，不能把观察时间当作生效时间。
`spec_evidence.verify` 默认接口保持兼容，新增可选返回完整已复核快照，避免重复未固定的读取。

## 验证结果

- 212 项 unittest 通过，其中新增 9 项；`git diff --check` 通过。
- 新增测试覆盖五区间重算、输入字节保留、缺台账、缺资产、原台账省略资产、
  参数配对、坏哈希/损坏归档、重新固定哈希的伪造结论、未来观察及最终分支证据门槛。
- 真实台账固定哈希 `845d22b74e248c7cf08a441125879007c092e4f44a706e05bbf3b72ef1ed5408`，
  包含两份快照，BTC/ETH 各两个观察。
- 五个未来区间均按原登记重算；两个资产在区间内的观察数为 0，认证覆盖秒数为 0，
  每个完整区间均未获历史规格认证，精确成本仍未认证。
- 登记、协议、原台账和全部归档哈希不变；原登记全部 37 个源码文件哈希一致。
  新执行器及辅助模块源码哈希单独保存在机器验收中，不改写旧登记。

复现真实证据复核（输出须使用尚不存在的新文件名）：

```powershell
python audit_prospective_evidence.py ..\1\data\M6-full-20261001 `
  ..\1\data\M6-restart-registration.json research\m6_restart_protocol.json `
  --expected-registration-sha256 b2bc4ddbf455c86dd53911d3814c27bd61026d89104fe58fffe15a4b005ea6cd `
  --evidence-ledger ..\1\data\M6-spec-evidence-20261001 `
  --expected-evidence-sha256 845d22b74e248c7cf08a441125879007c092e4f44a706e05bbf3b72ef1ed5408 `
  --output ..\1\data\M6-prospective-evidence-audit-new.json
python -m unittest discover -s tests -q
```

## 剩余边界

本次只完成观察证据接入，尚未交付历史实际生效期间证明、按执行时点映射有效规格、
账户手续费/滑点/精确结算价证据及模拟执行集成。
现有两个公开规格快照不证明未来或历史期间，哈希只能检查完整性，不能认证交易所来源。
五个登记测试区间仍须等待全部结束后进行足量多资产独立验证。
旧基础假设仍 `TERMINATED`，M6 仍 `NOT_VALIDATED`，M7/M8/M9 依赖保持不变。
