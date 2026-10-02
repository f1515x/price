# M6-R14 部分成交与剩余订单撤销声明回放验收

日期：2026-10-01。原任务：plan.md 4.1 M6 的“支持日内成交”剩余部分成交政策工程。

结果：工程 `PASSED`；M6 策略仍 `NOT_VALIDATED`。

## 交付行为

`intraday_orders.replay` 升级为 v2。fill 可明确声明本次 quantity，同一订单允许多次成交；省略 quantity 时只成交当前剩余数量，兼容既有整单调用。每笔成交记录原始数量、本次数量、剩余数量、规格和固定输入哈希。

成交数量必须有限、为正、符合当前数量步长且不超过余量；价格满足步长和买卖限价。提交时仍核对最小/最大张数。最小下单张数不约束成交片段或残余，这是明确的声明情景政策，未认证为交易所实际历史规则。

公告先于同秒动作，撤销全部订单余量并记录数量；已成交持仓保留。手动撤销记录未成交余量。完成/撤销订单不能继续成交或复用 ID。余量和净持仓使用 Fraction 精确运算、十进制字符串精确输出，不依赖 Decimal 上下文精度。

## 验证证据

- `python -m unittest discover -s tests -q`：353 项通过，新增 10 项覆盖部分成交守恒、超额/非法片段、同秒公告阻断、撤销余量、卖单限价、低精度精确运算及整单兼容。
- `audit_partial_orders.py`：17 项机器检查全部通过，见 [固定验收 JSON](data/M6-partial-orders-acceptance.json)。
- 两份已归档真实 ETH 公告的准确生效秒用于合成情景：旧买单 1 张先成交 0.1，公告撤销剩余 0.9；新卖单 1 张先成交 0.1，再通过旧接口成交剩余 0.9。最终净持仓精确为 -0.9，无剩余挂单。
- 固定情景/公告/前序验收哈希；全部情景完成后再次核对公告、前序证据、登记和 37 个冻结源码。原归档验收文件不覆盖。
- `git diff --check` 通过。

机器验收 SHA-256：`60d27b169cff392c570264f2bdf4ab21d50192042bc70d8d1b3d31c5d512fdfe`。

## 复现

在 `../source` 中运行，R12 固定输入哈希已保存在机器验收的 baseline.prior_acceptance_sha256。

```powershell
python audit_partial_orders.py --previous ..\1\data\M6-notice-execution-acceptance.json --expected-prior-sha256 <baseline.prior_acceptance_sha256> --registration ..\1\data\M6-restart-registration.json --archive ..\1\data\M6-historical-notices --output new-partial-acceptance.json
python -m unittest discover -s tests -q
```

## 验收边界

初始规格、订单和成交全部为声明。此报告不证明实际成交、完整历史规格、费用、盈亏或风险，不接入冻结未来执行器；持仓乘数变化仍拒绝无换算回放。真实精细行情、真实成交与政策认证、持仓换算、完整规格及成本/风险执行、未来独立验证仍待完成。M7/M8/M9 依赖保持。

代码提交：`feature@d9b8d60599a0648394fda4a4116d0210e3de799a`（本地提交，未推送）。计划与报告位于仓库外的 `../1`。
