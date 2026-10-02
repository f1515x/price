# M6 子任务：每资产当前合约规格采集与配置映射

日期：2026-10-01。在 `../source` 仓库 `feature` 分支开发；通过 GitHub 插件核对远端 `feature@7a037803fb0ef09ab93f43cba0d95dd6b97bc9ad`。

已交付 [采集与映射代码](../source/contract_specs.py)、[使用说明](../source/CONTRACT_SPECS.md)、[8 项新增测试](../source/tests/test_contract_specs.py) 和 [BTC/ETH 真实规格快照](data/M6-contract-specs-20261001/specs.json)。本次完成当前规格的数据采集、质量校验和受限配置映射子任务；M6 整体与真实历史成本回测仍未完成。

代码提交：`feature@4b8b9b3317889693e16851c2b653dbaa22a055af`（本地提交，未推送）。计划、验收报告及真实快照位于仓库外的 `../1`，已本地保存。

## 在线采集结果

使用 `GET /api/v4/futures/usdt/contracts/{contract}`；口径参照 [Gate 官方合约文档](https://www.gate.com/docs/developers/apiv4/en/futures/)。原始响应逐资产保留，报告包含 SHA-256、UTC Unix 请求/接收时间、采集器源码哈希。`CURRENT_SNAPSHOT_ONLY` 明确没有历史有效期间。

| 字段 | BTC_USDT | ETH_USDT |
|---|---|---|
| 类型 | direct | direct |
| 每张标的乘数 | 0.0001 BTC | 0.01 ETH |
| 接口最小张数 | 1 | 0（不能确认可下单最小数量） |
| enable_decimal | false | true |
| 可确认的张数步长 | 1 | N/A |
| 最大订单张数 | 12000000 | 10000000 |
| 价格 tick | 0.1 | 0.01 |
| 公开 maker / taker 费率 | -0.0001 / 0.00075 | -0.0001 / 0.00075 |
| 当前资金结算间隔 | 28800 秒 | 28800 秒 |
| 映射状态 | MAPPABLE_CURRENT_ASSUMPTION | UNSUPPORTED_DECIMAL_STEP |

真实 ETH 响应 `order_size_min=0`、`enable_decimal=true`。保留原值并拒绝推测数量步长。BTC 场景仅映射乘数、最小张数和整数张步长；必须显式 `assume_current_specs=True`，否则失败。保持风险、费用、资金费率等配置由调用方明确提供。

## 验证与复现

在 `../source` 执行：

```powershell
python -m unittest discover -s tests -v
python contract_specs.py BTC ETH --output ..\1\data\M6-contract-specs-new
python -c "from contract_specs import load_snapshot; r=load_snapshot('../1/data/M6-contract-specs-20261001'); print(r['temporal_scope'], len(r['contracts']))"
```

76 项离线测试全部通过（原有 68 项、新增 8 项）。覆盖快照往返与禁止覆盖、原始/规范化数据篡改、身份/类型/标志/数量校验、非有限值、小数张与退市拒绝映射、显式场景与配置保留、合约张数手算、采集失败不产生部分输出。手算用 0.0001 BTC/张、100 USDT 风险和每 BTC 10 USDT 止损距离，验证 100000 张对应 10 BTC、亏损 100 USDT；这是工程案例，不是策略业绩。在线 BTC/ETH 采集及离线重载成功。

## 剩余边界

- 当前规格不能追溯证明 2024～2025 研究区间的历史规格；响应中的配置变更时间也不证明此前参数。
- ETH 的有效最小张数与小数步长需要可靠的额外来源；未借用 BTC 或猜测精度。
- 价格 tick、最大订单数量尚未接入模拟器；组合模拟器的每资产配置尚未接入。
- 公开费率不是账户实际费用，结算间隔不是历史资金费率。真实历史资金费率、历史规格版本与实际成本仍待完成。
- 本次未新增策略成交或运行有效性回测；足量成交、滚动样本外、敏感性验证及 M7/M8 的依赖仍未解除。
