# M6-R9：逐字段审阅主张联合合法性与日期执行接入验收

日期：2026-10-01。完成 plan.md 4.1 M6 的审阅主张到执行参数工程子项。
通过用户指定 GitHub 插件核对远端 feature 分支；在本地 feature 开发，提交
`4c98b81c8fe372df143796fd405971d7ebe1ece2`，未推送。

工程验收 **PASSED**，M6 策略状态仍为 **NOT_VALIDATED**。
真实历史规格认证及认证未来执行集成尚未完成。

交付：[模块](../source/reviewed_specifications.py)、
[说明](../source/REVIEWED_SPECIFICATIONS.md)、
[17 项新增测试](../source/tests/test_reviewed_specifications.py)、
[复核工具](../source/audit_reviewed_specifications.py)、
[机器验收](data/M6-reviewed-specifications-acceptance.json)、
[保留合成输入](data/M6-reviewed-specifications-acceptance/synthetic-review.json)。

直接从固定清单哈希与原文字节重算 M6-R8 审阅结果。每个资产的五字段必须完整
覆盖且无异值冲突；观察快照、synthetic 类型、默认参数不能补足证据。
合并字段边界后逐段验证数量步长、上下限和浮点可表示性。同值重叠保留全部 ID，
不同资产互不补足。日内边界、乘数变化、浮点溢出/下溢/数值精度损失拒绝执行。
成交日规格通过原共享账户引擎应用，成交保存清单哈希、逐字段 ID、十进制值和
有效区间。解析及模拟返回前重核证据。CLI 仅解析配置；模拟通过 API。

验证结果：

- 全量 287 项测试通过，新增 17 项，覆盖异步字段边界、多资产隔离、成交日期、
  资金对账、缺口/冲突、同值重叠、日内主张、数量合法性、精度、证据篡改及显式许可。
- 11 项机器检查全部通过，原登记字节及全部 37 个冻结源码哈希不变。
- 真实审阅清单仍为空；BTC/ETH 每个字段保留完整历史窗口缺口，并明确拒绝模拟。
- 合成 BTC 多/ETH 空在第 2 日成交，采用当日数量上限 2.5；乘数分别 1/0.01。
  基础手续费率 0.001、滑点 0.001、资金费代理 0，入场受原引擎挂单价 100 限制，
  退出价分别 99.9/100.1。独立算术净损益为 -0.74975/-0.0075025，
  期末资金为 9999.2427475；这只验证原引擎情景执行与来源通路。
- 报告保存合成输入、源码及原登记/真实审阅哈希，输出报告及输入目录拒绝覆盖。

复现（在 source 目录）：

```powershell
$a = Get-Content ..\1\data\M6-reviewed-specifications-acceptance.json -Raw | ConvertFrom-Json
python audit_reviewed_specifications.py ..\1\data\M6-restart-registration.json `
  ..\1\data\M6-field-review-acceptance\real-review.json `
  --expected-registration-sha256 $a.registration_sha256 `
  --expected-review-sha256 $a.real_review_sha256 --symbols BTC ETH `
  --start $a.real_review.required_window.start --end $a.real_review.required_window.end `
  --output ..\1\data\M6-reviewed-specifications-new.json
python -m unittest discover -s tests -q
```

`REVIEWED_SCENARIO_ONLY` 与显式 API/CLI 许可是进入情景通路的条件。
`verified_fields` 为空，`historical_specs_verified` 和 `exact_costs_verified` 均为 false。
有效期、数值语义和发行方真实性仍是未认证人工主张；effective_notice 标签与哈希
不认证它们。未改变风险、费用模型、冻结登记或未来执行器，未运行真实未来验证。
真实历史文档、逐字段真实性认证、认证未来执行接入、真实账户费用/滑点/结算价
及足量有效未来成交仍待完成。M7/M8/M9 不解除依赖。
