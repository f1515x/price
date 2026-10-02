# 日内声明手续费与已实现盈亏对账

`intraday_accounting.account` 复用日内订单声明回放，增加线性 USDT 合约的
逐笔手续费和平均成本已实现盈亏。必须独立固定公告、订单情景及费用政策哈希，
显式传入 `allow_scenario=True`；不更改旧回放或冻结未来研究源码。

费用政策格式：

```json
{
  "initial_collateral": "1000",
  "fee_periods": [
    {"start": 0, "end": 10, "rate": "0.001"},
    {"start": 10, "end": 20, "rate": "0.002"}
  ]
}
```

政策哈希为 `digest(encoded(policy))`。从零持仓开始，费用区间为 UTC 秒半开窗口，
必须完整、连续覆盖情景窗口，拒绝缺口、重叠、乱序和布尔时间戳。
金额与费率使用十进制字符串，初始保证金和费率非负，费率小于 1，允许字符串 `"0"`。
每个区间声明单一有效费率；不推定账户等级、maker/taker 身份或返佣。

每笔手续费 = 成交张数 × 当时乘数 × 声明成交价 × 成交秒费率。
使用毛成交额，不以净持仓抵消买卖费用。挂单未成交量、撤销及乘数换算不产生费用。
同方向加仓更新加权平均入场价；反方向成交仅对平仓基础资产量核算盈亏，
越过零持仓的剩余部分以该笔成交价开仓。多空、部分平仓、反向开仓均使用精确有理数，
不依赖 Decimal 上下文精度；乘数换算保持基础资产成本和敞口。

每笔台账包含费率区间索引、费用政策哈希、毛成交额、手续费、已实现盈亏、
累计手续费/盈亏、持仓平均价格及保证金余额。完整订单回放保留规格、公告和情景追溯。
对账公式：`collateral_balance = initial_collateral + realized_pnl - total_fees`。
期末基础资产敞口须与订单回放完全一致，返回前再次核验回放和公告证据。
输出均为 `numerator/denominator`，平仓后平均入场价为 null。

余额可为负数，不隐式拒绝成交或截断损失。余额仅为初始保证金加已实现盈亏减费用，
不是账户权益；未提供标记价格时 `unrealized_pnl` 和 `equity` 均为 null。
资金费、实际滑点、保证金占用、风险预算及强平未纳入。成交价已由情景声明，
不会再次叠加滑点。真实成本认证、风险执行及冻结未来执行器接入继续待办。
`engineering_status=PASSED` 只表示声明对账完成，`costs_verified=false`、
`risk_budget_enforced=false`，M6 策略继续 `NOT_VALIDATED`。

以下验收使用两份真实公告的时间和值，订单、成交和费用均为合成声明，输出须为新文件：

```powershell
python audit_intraday_accounting.py --previous ../1/data/M6-notice-execution-acceptance.json --expected-prior-sha256 8d2222ec57fe46a803ab7db37873ad3c1e5f902c8c4f910301419723f45612fc --registration ../1/data/M6-restart-registration.json --archive ../1/data/M6-historical-notices --output new-accounting-acceptance.json
python -m unittest discover -s tests -q
```
