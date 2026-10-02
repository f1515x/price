# 日内资金费声明对账

`intraday_funding.settle` 在 `intraday_accounting.account` 的手续费及已实现盈亏
台账上增加精确秒资金费结算。公告、订单、费用政策和资金费政策各自固定 SHA-256，
必须显式传入 `allow_scenario=True`；旧模块和冻结未来执行器保持原版本。

资金费政策示例（与订单情景使用同一资产、UTC 秒半开窗口）：

```json
{
  "symbol": "ETH",
  "start": 0,
  "end": 20,
  "ordering": "SETTLEMENT_BEFORE_SAME_SECOND_FILLS",
  "scheduled_timestamps": [5, 15],
  "settlements": [
    {"timestamp": 5, "rate": "0.01", "settlement_price": "100"},
    {"timestamp": 15, "rate": "-0.005", "settlement_price": "110"}
  ]
}
```

政策哈希为 `digest(encoded(policy))`。计划必须严格递增且不重复，记录与计划逐项
精确对应，拒绝缺项、额外记录、重复、乱序、窗口外及布尔时间戳。空计划可表示声明
窗口无结算，不能证明交易所实际没有结算。计划、费率和价格均由调用方声明。
费率必须是有限十进制字符串且绝对值小于 1；结算价必须为有限正十进制字符串。

从零持仓开始，结算使用该秒之前已成交的基础资产净敞口。
声明顺序为：公告按旧回放处理，资金费结算先于同秒成交；乘数换算保持基础资产
敞口，不改变资金费金额。同秒开仓不计入该次结算，同秒平仓仍按平仓前敞口结算。
不推定此顺序为交易所实际规则。未成交订单和撤销量不产生资金费。

`funding_cashflow = -net_base_exposure * settlement_price * rate`。
正费率多头支出、空头收入，负费率反向；按基础资产敞口避免重复应用合约乘数。
金额使用精确有理数，不受 Decimal 上下文精度影响。

输出包含每次结算的敞口、价格、费率、现金流、累计资金费和当秒结算后的余额，
以及包含已结算资金费的逐成交余额。最终余额等于初始保证金加已实现盈亏减手续费
加资金费现金流；原手续费对账保留在 `accounting` 内。返回前重算原对账并重核证据。

`engineering_status=PASSED`，M6 仍为 `NOT_VALIDATED`。
`funding_schedule_verified=false`、`costs_verified=false`、`risk_budget_enforced=false`。
未核算标记价格、未实现盈亏、保证金占用、风险预算和强平；权益仍为 null，余额可负。
真实结算计划/费率/价格/账户费用及成交认证、认证未来执行集成和独立验证继续待办。

使用两份真实公告时点回放合成资金费及部分成交，输出须使用新路径：

```powershell
python audit_intraday_funding.py --previous ../1/data/M6-notice-execution-acceptance.json --expected-prior-sha256 8d2222ec57fe46a803ab7db37873ad3c1e5f902c8c4f910301419723f45612fc --registration ../1/data/M6-restart-registration.json --archive ../1/data/M6-historical-notices --output new-funding-acceptance.json
python -m unittest discover -s tests -q
```
