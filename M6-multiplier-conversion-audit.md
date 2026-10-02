# M6-R15 持仓乘数精确换算声明政策验收

日期：2026-10-01。原任务：plan.md 4.1 M6 的持仓乘数换算剩余工程。

结果：工程 `PASSED`；M6 策略仍 `NOT_VALIDATED`。

## 交付行为

`intraday_orders.replay` 升级为 v3。情景显式设置
`multiplier_conversion_policy="PRESERVE_BASE_EXPOSURE_EXACT"` 后，公告生效时按
`旧张数 × 旧乘数 / 新乘数` 精确换算多空持仓。默认或显式
`REJECT_HELD_POSITION` 仍拒绝带持仓的乘数变更，未知政策拒绝；政策受情景哈希固定。

同秒公告全部字段联合变更后检查新数量步长；不能精确对齐时拒绝，不取整、不合成成交。
订单最小/最大尺寸限制不用于强平或削减既有持仓。变更撤销旧挂单余量；
同秒新订单与成交按新规格执行。重复相同公告只转换一次，窗口结束前无后续动作的公告也处理。

日志记录换算前后张数、乘数、政策与不变的基础资产敞口。每笔成交记录 signed_base_exposure，
最终报告返回 net_base_exposure；全部使用 Fraction 与分子/分母，避免上下文精度或舍入损失。
跨乘数期间按基础资产敞口对账，原始成交张数之和不能直接当作期末持仓。

## 验证证据

- `python -m unittest discover -s tests -q`：365 项通过；新增 12 项专项测试覆盖多空、默认拒绝、政策非法值、同秒部分成交与平仓、联合新步长、无法精确换算拒绝、低 Decimal 精度、多次变更与重复公告、订单尺寸边界、半开窗口、输入不可变及认证状态。
- `audit_multiplier_conversion.py`：29 项机器检查全部通过，见 [固定验收 JSON](data/M6-multiplier-conversion-acceptance.json)。
- 合成多空情景：旧乘数 2、成交 ±0.1 张，对应敞口 ±0.2；乘数变为 2.5、步长变为 0.01 后持仓精确为 ±0.08 张。公告撤销旧挂单余量 0.9；同秒反向成交 0.08 张后持仓与敞口均为零；后续乘数变为 1 的公告仍处理。
- 未显式启用政策以及新步长 0.03 无法对齐的情景均拒绝。
- 乘数事件、订单与成交全部为合成声明，保存在 [合成验收输入](data/M6-multiplier-conversion/synthetic-notices/notices.json)，不是新取得的真实公告。原两份真实 ETH 公告及整单/部分成交回放作为独立回归基线复核。
- 本次独立固定公告与情景哈希；前序证据、预登记及 37 个冻结源码在验收前后均复核不变。原归档验收文件未覆盖。
- `git diff --check` 与暂存检查通过；本地工作区干净。

机器验收 SHA-256：`7568e36efc74d93949699b2db093da2d4c0fd856af0b32d39669129daefa7f9f`。

## 复现

在 `../source` 运行，R12 固定输入哈希取自机器验收的 baseline.baseline.prior_acceptance_sha256。
输出目录与输出文件均须使用尚不存在的新路径。

```powershell
python audit_multiplier_conversion.py --destination new-multiplier-fixtures --previous ..\1\data\M6-notice-execution-acceptance.json --expected-prior-sha256 <baseline.baseline.prior_acceptance_sha256> --registration ..\1\data\M6-restart-registration.json --archive ..\1\data\M6-historical-notices --output new-multiplier-acceptance.json
python -m unittest discover -s tests -q
```

## 验收边界

此交付仅证明显式声明政策下基础资产敞口守恒，不认证交易所实际历史换算规则，
不证明盈亏/保证金守恒、实际成交、完整有效规格、费用或风险约束。
未取得真实乘数公告，未接入冻结未来执行器。真实精细行情与成交、实际换算认证、
完整历史规格及成本/风险执行、未来独立验证仍待完成，M7/M8/M9 依赖不变。

代码提交：`feature@b97c9e5eccb5b2364d39e8b6042e669396e0de3e`（本地提交，未推送）。
计划、报告及机器验收位于仓库外的 `../1`。
