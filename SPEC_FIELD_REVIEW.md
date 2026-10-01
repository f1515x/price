# 逐字段历史规格证据审阅

`spec_field_review.py` 是 M6-R8 的证据审阅与缺口检查工程子项。
为五个执行规格字段分别关联十进制值、资产、左闭右开的 UTC Unix 秒有效区间、
原始文档、精确 UTF-8 字节片段、审阅者与理由。审阅信息是显式人工主张；
哈希、来源文字、审阅者名称及 `effective_notice` 标签均不认证发行方或历史真实性。
本模块不产生执行参数，不修改冻结协议，不解除 M6/M7/M8/M9 的依赖。

清单严格包含 `version: spec-field-review-v1`、`scope: REVIEW_ASSERTIONS_ONLY`、
`market: gate_usdt_perpetual`、`documents` 和 `claims`。
每个 document 包含目录内相对 `file`、原始字节 `sha256`、`origin` 和 `kind`。
kind 为 `effective_notice`、`observation` 或 `synthetic`；后两者不能提供有效期间覆盖。
每条 claim 包含 `id`、`symbol`、`field`、`value`、`start`、`end`、`document`、
`excerpt_start`、`excerpt_end`、`excerpt`、`reviewer`、`rationale`。
片段偏移是字节偏移，不能用字符索引；片段必须与固定哈希文档原始字节严格相等。
value 为正有限十进制字符串，field 为 `multiplier`、`quantity_step`、
`min_quantity`、`max_quantity` 或 `price_tick`，资产必须是请求的规范名称。
没有历史有效期文档时 documents 和 claims 均可为空，输出整个窗口的缺口。

以请求窗口裁切各字段的主张；同值重叠区间做并集，按 Decimal 比较等价数值。
不同值重叠区间单列冲突及 claim ID，不计入审阅覆盖；没有有效期主张的区间
单列 missing_intervals。不同资产和字段互不补足。覆盖只统计原文关联完整且
标为 effective_notice 的审阅主张，不验证数值与原文语义，也不检查多个字段的
联合执行合法性。日内区间可记录，不能据此声称日线模拟能处理日内生效变更。

报告保存全部主张、原文来源、清单及相关源码哈希，并在返回前重新核对输入字节。
拒绝坏哈希、重复 JSON 键、重复 ID、危险路径、无效范围/值、伪造额外认证字段、
未知引用与未使用文档。`verified_coverage_seconds` 固定 0，完整窗口仍列为
unverified_intervals；`historical_specs_verified`、`exact_costs_verified` 和
`used_for_execution_parameters` 固定 false，策略状态为 `NOT_VALIDATED`。

```powershell
python spec_field_review.py review.json --expected-sha256 <固定哈希> `
  --symbols BTC ETH --start <UTC秒> --end <UTC秒> --output new-report.json
python -m unittest discover -s tests -q
```

CLI 校验后写入报告，拒绝覆盖。验收工具 `audit_spec_field_review.py` 同时固定
真实观察台账及预登记哈希，核验冻结源码，并保存空的真实审阅清单以及明确标注
为合成的覆盖/冲突/观察输入。合成 effective_notice 标签只用于测试审阅主张计算。
真实历史文档获取、逐字段真实性认证、成本证据和认证执行集成仍待完成。
