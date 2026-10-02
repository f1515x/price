# M6-R18 日内声明手续费与已实现盈亏对账验收

日期：2026-10-01（America/La_Paz）。完成 plan.md 4.1 M6 剩余“费用/风险执行”中的
日内声明手续费及已实现盈亏对账工程子项。工程 `PASSED`，M6 策略仍 `NOT_VALIDATED`。

新增 [对账模块](../source/intraday_accounting.py)、
[验收命令](../source/audit_intraday_accounting.py)、
[使用说明](../source/INTRADAY_ACCOUNTING.md)及
[测试](../source/tests/test_intraday_accounting.py)。复用现有日内订单回放，未修改冻结源码。

## 交付与验证

- 公告、订单情景和费用政策分别固定哈希。按 UTC 成交秒选择完整连续的费用区间，
  部分成交按当时乘数和毛成交额收费，撤销余量与乘数换算不收取成交费用。
- 使用基础资产敞口计算平均入场成本、部分平仓和反向开仓盈亏；多空均精确核算，
  乘数换算保持基础资产成本，非终止小数用 numerator/denominator 保存。
- 每笔台账保留费率区间、政策哈希、毛成交额、费用、累计费用/盈亏及保证金余额。
  期末敞口与原回放一致，余额等于初始保证金加已实现盈亏减费用。
- `python -m unittest discover -s tests -q`：398 项通过，新增 13 项涵盖多空对账、
  平均成本、部分平仓、反向开仓、精确分数、秒级费率边界、部分成交与撤销、
  乘数/换算、零成本、负余额、不完整区间、非法费率、固定哈希及显式启用。
- 25 项机器检查通过：两份真实公告的生效时点上回放合成部分成交，费用由
  0.001 切换为 0.002；每份情景手续费 0.21 USDT、已实现盈亏 0、保证金余额
  999.79 USDT。费用、订单及成交都是声明，无真实账户成本或成交认证。
- 37 个冻结源码与登记哈希不变；旧整单/部分成交验收重核一致。

[机器验收 JSON](data/M6-intraday-accounting-acceptance.json) SHA-256：
`032218dddbc15b9c7999ba9fa43d3f660cf7801dd25f5ccf86f7b99bce513db1`。

## 复现

在 `../source` 运行，输出必须使用新路径：

```powershell
python audit_intraday_accounting.py --previous ../1/data/M6-notice-execution-acceptance.json --expected-prior-sha256 8d2222ec57fe46a803ab7db37873ad3c1e5f902c8c4f910301419723f45612fc --registration ../1/data/M6-restart-registration.json --archive ../1/data/M6-historical-notices --output new-accounting-acceptance.json
python -m unittest discover -s tests -q
```

## 保留依赖

本次从零持仓开始，单资产线性合约，费用区间声明单一有效费率，不推定 maker/taker
身份、账户等级、返佣或实际滑点。未核算资金费、保证金占用、风险预算和强平。
保证金余额允许负值，不充当风险执行器。未提供标记价格，未实现盈亏与权益为 null。
剩余：真实费用/滑点/结算价认证、资金费及风险执行、实际成交认证、完整历史规格及
认证未来执行器接入、足量未来独立验证。M7/M8/M9 依赖不解除。

最初尝试补采两份公告附近分钟数据，公开接口均返回 HTTP 400，消息为
`Candlestick too long ago. Maximum 10000 points recently are allowed`；未取得行情，
未将该尝试标为覆盖完成。本次转而完成上述费用声明工程。

通过用户指定 GitHub 插件核对目标仓库 `huan00000/price`。
计划、报告和验收 JSON 保存在仓库外 `../1`。
代码提交：`feature@4154a24c3ae4d32f25617111ee6158869a24c8ee`（本地提交，未推送）。
提交前 `git diff --cached --check` 通过，提交后源码工作区干净。
