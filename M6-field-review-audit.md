# M6-R8：逐字段历史规格证据审阅与覆盖缺口检查验收

日期：2026-10-01。完成 plan.md 4.1 M6 的证据审阅与缺口检查工程子项。
通过用户指定 GitHub 插件核对 `huan00000/price`，在本地 `feature` 分支开发。
代码提交：`61cc253a02a08f34eacd41fe9345d7859aecd7ff`，未推送。

工程验收 **PASSED**；M6 策略保持 **NOT_VALIDATED**。
真实历史规格逐字段真实性认证尚未完成；本次交付可追溯的人工审阅记录和覆盖计算。

交付：[模块](../source/spec_field_review.py)、[说明](../source/SPEC_FIELD_REVIEW.md)、
[14 项新增测试](../source/tests/test_spec_field_review.py)、
[复核工具](../source/audit_spec_field_review.py)、
[机器验收](data/M6-field-review-acceptance.json)、
[保留输入](data/M6-field-review-acceptance/real-review.json)。

每条主张固定资产、规格字段、正有限十进制值、UTC 秒有效区间、引用文档、
原文精确字节偏移和片段、审阅者与理由。原文哈希和片段校验保证引用可追溯，
不证明发行方、值与原文的语义关系或有效期间真实。`effective_notice` 标签
也是主张，不能认证文件。观察快照及 synthetic 类型不能提供历史有效期审阅覆盖。

按资产和五个字段分别裁切请求窗口，合并同值覆盖，定位异值冲突和没有主张的
区间。冲突不计入 reviewed_coverage_seconds，单列冲突 claim ID；
verified_coverage_seconds 始终为 0，整个窗口仍列为未认证。
支持记录日内证据边界，但不生成执行参数，也不改变日线执行器的限制。

验证结果：

- 全量 270 项测试通过，新增 14 项，覆盖范围裁切、同值十进制等价、冲突隔离、
  多资产/字段隔离、空证据、日内记录、原文偏移、哈希/路径/值/键/ID 等非法输入。
- 机器验收 9 项全部通过，合成 BTC tick 在第 2 日冲突，冲突日不计覆盖；
  ETH 的 `1` 与 `1.00` 重叠主张合并为完整三日覆盖。
- 将合成审阅输入的文档类型改为 observation 后，所有字段覆盖归零。
- 复核真实规格观察台账，现有观察仍不能补足历史有效期；真实审阅清单为空，
  BTC/ETH 五个字段均报告整个真实窗口缺口，未制造审阅者或历史生效日期。
- 原登记字节与全部 37 个冻结源码哈希不变，未接入冻结未来执行器。
- 合成输入、空的真实审阅输入和对应哈希全部保留；输出报告和输入目录拒绝覆盖。

复现（在 source 目录）：

```powershell
$acceptance = Get-Content ..\1\data\M6-field-review-acceptance.json -Raw | ConvertFrom-Json
python audit_spec_field_review.py ..\1\data\M6-restart-registration.json `
  ..\1\data\M6-spec-evidence-20261001 `
  --expected-registration-sha256 $acceptance.registration_sha256 `
  --expected-ledger-sha256 $acceptance.ledger_sha256 `
  --output ..\1\data\M6-field-review-new.json
python -m unittest discover -s tests -q
```

真实历史文档获取、逐字段真实性认证、多个字段联合执行合法性审查、认证规格
执行集成、真实账户费用/滑点/精确结算价及未来独立验证仍待完成。
即使审阅覆盖完整，也不解除 M6 验证及 M7/M8/M9 依赖。
