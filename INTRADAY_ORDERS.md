# 日内公告与订单政策声明回放

M6-R13 提供 `intraday_orders.replay`；M6-R14（v2）增加部分成交与剩余数量跟踪。
M6-R15（v3）增加显式持仓乘数换算与逐笔基础资产敞口。
只回放明确声明的 UTC 秒级订单和成交。
调用必须传入公告清单哈希、独立固定的情景哈希及 `allow_scenario=True`。
情景哈希计算为 `digest(encoded(scenario))`；报告中的情景可据此独立复现。

情景含 `symbol/start/end/initial_specification/actions`。五字段初始规格必须是
窗口起点**之前**的明确声明，不从公告或当前快照推定。窗口为半开 `[start,end)`，
允许非日界时间；动作按时间排序。同秒动作按输入顺序，公告先于所有同秒动作。
同秒多字段变更联合核对前值并验证后值，重复同字段相同公告只应用一次。

每次规格变更撤销全部挂单的剩余数量；已经成交的持仓保留。
日志记录撤销 ID 与剩余数量。需用全新 ID 明确重新提交。不会自动改价或改数量。
默认已持仓遇到 multiplier 变化拒绝回放。情景可显式添加
`multiplier_conversion_policy: "PRESERVE_BASE_EXPOSURE_EXACT"`，此字段也受情景哈希固定。
该声明政策精确计算 `新张数 = 旧张数 × 旧乘数 / 新乘数`，保留多空基础资产敞口。
换算结果必须符合同秒全部变更完成后的数量步长，否则拒绝，不取整或生成隐式成交。
订单最小/最大张数不限制已持仓换算，也不自动强平或核算风险。
可显式选择 `REJECT_HELD_POSITION`；其他政策值拒绝。
变更日志中的 `multiplier_conversion` 保存前后张数、乘数、政策及守恒敞口。
成交的 `signed_base_exposure` 和最终 `net_base_exposure` 均以 numerator/denominator 精确返回；
有乘数变更时按基础资产敞口对账，不能直接把不同规格时期的成交张数相加。
其余规格变化保留既有持仓数量，新提交订单按新规格检查。净持仓采用精确有理数记录。

动作格式：

- `submit`：kind、timestamp、order_id、direction（整数 ±1）、quantity、limit_price。
- `fill`：kind、timestamp、order_id、price，可选 quantity（正十进制字符串）。
  quantity 指本次成交张数；省略则成交全部剩余数量，兼容原整单接口。
  同一订单可多次成交，累计不得超过提交数量，已完成或已撤销订单不能再成交。
- `cancel`：kind、timestamp、order_id。只允许撤销当前挂单。

数量和价格必须是有限正十进制字符串。提交时检查数量步长、最小/最大张数和价格步长；
成交片段检查步长与剩余数量，最小下单张数不用于限制成交片段或余量。
这是明确的声明情景政策，未认证为交易所历史实际政策。
买单成交价不高于限价、卖单不低于限价。禁止 OHLC 推断成交、隐式订单、
浮点精度取整。没有手续费、资金费、盈亏及风险预算模拟，不构成交易执行器。

返回前重核公告原文摘录与清单。每笔成交保存当时五字段规格和两个输入哈希，
每笔成交记录原始数量、本次成交数量与剩余数量；返回 pending_quantities。
审计日志保存准确变更秒、全部公告 ID、撤销 ID、撤销余量和动作。
剩余数量与净持仓使用精确有理数计算，不依赖 Decimal 上下文精度。
`PASSED` 只表示声明符合该政策；报告仍为 `NOT_VALIDATED`、零认证覆盖，
规格和市场成交均未认证。真实逐笔/精细行情、完整有效规格、认证未来执行接入仍待完成。
既有日线政策继续拒绝日内变更；冻结登记和源码不修改。

复现到新文件：

```powershell
python audit_intraday_orders.py --previous ..\1\data\M6-notice-execution-acceptance.json --expected-prior-sha256 <独立固定的R12验收哈希> --registration ..\1\data\M6-restart-registration.json --archive ..\1\data\M6-historical-notices --output new-intraday-acceptance.json
python -m unittest discover -s tests -q
```

部分成交验收使用相同固定 R12 输入，输出到新文件：

```powershell
python audit_partial_orders.py --previous ..\1\data\M6-notice-execution-acceptance.json --expected-prior-sha256 <独立固定的R12验收哈希> --registration ..\1\data\M6-restart-registration.json --archive ..\1\data\M6-historical-notices --output new-partial-acceptance.json
```

真实公告验收只使用公告的生效秒及变更值。初始规格、订单和成交均是合成声明，
不证明历史完整有效期或真实成交。

乘数政策验收使用单独保存的合成乘数事件，同时复核既有真实公告回放；
不宣称真实乘数公告、交易所实际换算规则或盈亏守恒。输出目录及文件必须不存在：

```powershell
python audit_multiplier_conversion.py --destination new-multiplier-fixtures --previous ..\1\data\M6-notice-execution-acceptance.json --expected-prior-sha256 <独立固定的R12验收哈希> --registration ..\1\data\M6-restart-registration.json --archive ..\1\data\M6-historical-notices --output new-multiplier-acceptance.json
```
