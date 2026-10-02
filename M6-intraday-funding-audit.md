# M6-R19 日内资金费声明对账验收

日期：2026-10-01（America/La_Paz）。完成 plan.md 4.1 M6 剩余“日内资金费”中的
声明结算及逐笔余额对账工程子项。工程 `PASSED`，M6 策略仍 `NOT_VALIDATED`。

新增 [资金费模块](../source/intraday_funding.py)、
[验收命令](../source/audit_intraday_funding.py)、
[使用说明](../source/INTRADAY_FUNDING.md)及
[测试](../source/tests/test_intraday_funding.py)。复用原日内手续费与盈亏模块，冻结源码不变。

## 交付与验证

- 公告、订单、手续费政策、资金费政策分别固定哈希。声明结算计划与每条记录精确
  匹配，拒绝缺项、额外项、重复、乱序、窗口外及布尔时间戳，不推定交易所结算计划。
- 按声明结算秒前的基础资产敞口核算，明确结算先于同秒成交。正费率多头支出、
  空头收入，负费率反向；部分成交、撤销及乘数换算后仍保持敞口口径。
- 精确有理数保存每次结算和每次成交后的余额，最终余额等于初始保证金加已实现
  盈亏减手续费加资金费现金流。原对账结果完整保留，返回前重核证据。
- 全量 410 项测试通过（新增 12 项），覆盖多空/正负/零费率、同秒开仓及平仓反向开仓、部分成交撤销、
  多次结算、已平仓、乘数换算、窗口边界/空计划、非法数据、精度、负余额和固定哈希。
- 35 项机器检查通过，两份真实公告时点各回放三次合成结算。每份情景资金费现金流
  为 -0.10 USDT、手续费 0.21 USDT、已实现盈亏 0、最终保证金余额 999.69 USDT。
  公告只提供时点和值，订单、费用、结算计划、费率和结算价全部为声明。
- 登记与 37 个冻结源码哈希不变，旧手续费与订单回放结果重核一致。

[机器验收 JSON](data/M6-intraday-funding-acceptance.json) SHA-256：
`1daf8853b6af5db486539ae81bc00685135359239946fc541609e4b5735361ca`。

## 复现

在 `../source` 运行，输出须使用新路径：

```powershell
python audit_intraday_funding.py --previous ../1/data/M6-notice-execution-acceptance.json --expected-prior-sha256 8d2222ec57fe46a803ab7db37873ad3c1e5f902c8c4f910301419723f45612fc --registration ../1/data/M6-restart-registration.json --archive ../1/data/M6-historical-notices --output new-funding-acceptance.json
python -m unittest discover -s tests -q
```

## 保留依赖

单资产线性 USDT 合约，从零持仓开始。声明结算计划及同秒顺序未获得交易所认证，
允许空声明计划但不证明真实结算缺失；`funding_schedule_verified=false`、
`costs_verified=false`。未实现盈亏及权益为 null，未核算保证金占用、风险预算或强平，
余额可为负，`risk_budget_enforced=false`。真实资金费结算计划/费率/价格及账户费用、
实际滑点和成交认证、完整历史规格、认证未来执行集成及足量独立验证仍待完成。
M6 保持 `NOT_VALIDATED`，M7/M8/M9 依赖保留。

通过用户指定 GitHub 插件核对目标仓库 `huan00000/price`。
计划、报告及验收 JSON 保存在仓库外 `../1`。

代码提交：`feature@03c2f8b90592d643174cf24d4affc3020d2a4707`（本地提交，未推送）。
提交前 `git diff --cached --check` 通过，提交后源码工作区干净。
