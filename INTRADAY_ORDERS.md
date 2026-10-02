# 日内公告与订单政策声明回放

M6-R13 提供 `intraday_orders.replay`，只回放明确声明的 UTC 秒级订单与整单成交。
调用必须传入公告清单哈希、独立固定的情景哈希及 `allow_scenario=True`。
情景哈希计算为 `digest(encoded(scenario))`；报告中的情景可据此独立复现。

情景含 `symbol/start/end/initial_specification/actions`。五字段初始规格必须是
窗口起点**之前**的明确声明，不从公告或当前快照推定。窗口为半开 `[start,end)`，
允许非日界时间；动作按时间排序。同秒动作按输入顺序，公告先于所有同秒动作。
同秒多字段变更联合核对前值并验证后值，重复同字段相同公告只应用一次。

每次规格变更撤销全部未成交挂单；需用全新 ID 明确重新提交。不会自动改价或改数量。
已持仓遇到 multiplier 变化拒绝回放，必须另行定义持仓换算政策。
其余规格变化保留既有持仓数量，新提交订单按新规格检查。净持仓采用精确有理数记录。

动作格式：

- `submit`：kind、timestamp、order_id、direction（整数 ±1）、quantity、limit_price。
- `fill`：kind、timestamp、order_id、price。仅整单成交，不能重复成交或成交已撤销订单。
- `cancel`：kind、timestamp、order_id。只允许撤销当前挂单。

数量和价格必须是有限正十进制字符串。独立检查数量步长、最小/最大张数和价格步长；
买单成交价不高于限价、卖单不低于限价。禁止 OHLC 推断成交、部分成交、隐式订单、
浮点精度取整。没有手续费、资金费、盈亏及风险预算模拟，不构成交易执行器。

返回前重核公告原文摘录与清单。每笔成交保存当时五字段规格和两个输入哈希，
审计日志保存准确变更秒、全部公告 ID、撤销 ID 和动作。
`PASSED` 只表示声明符合该政策；报告仍为 `NOT_VALIDATED`、零认证覆盖，
规格和市场成交均未认证。真实逐笔/精细行情、完整有效规格、认证未来执行接入仍待完成。
既有日线政策继续拒绝日内变更；冻结登记和源码不修改。

复现到新文件：

```powershell
python audit_intraday_orders.py --previous ..\1\data\M6-notice-execution-acceptance.json --expected-prior-sha256 <独立固定的R12验收哈希> --registration ..\1\data\M6-restart-registration.json --archive ..\1\data\M6-historical-notices --output new-intraday-acceptance.json
python -m unittest discover -s tests -q
```

真实公告验收只使用公告的生效秒及变更值。初始规格、订单和成交均是合成声明，
不证明历史完整有效期或真实成交。
