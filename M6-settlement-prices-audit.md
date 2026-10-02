# M6-R7：逐结算价格声明加载与资金费模拟接入验收

日期：2026-10-01。完成 plan.md 4.1 M6 精确结算价执行集成的声明情景工程子项。
使用用户指定 GitHub 插件确认 `huan00000/price`，在本地 `feature` 分支开发。
代码提交：`a757fc2fcb70004cba516d0c3d6a512ddd47550d`，未推送。

工程验收 **PASSED**，策略保持 **NOT_VALIDATED**。本次交付逐时点加载、校验
与模拟接口；真实交易所精确结算价证据尚未取得，认证结算数仍为 0。

交付：[模块](../source/settlement_prices.py)、[说明](../source/SETTLEMENT_PRICES.md)、
[15 项测试](../source/tests/test_settlement_prices.py)、[复核工具](../source/audit_settlement_prices.py)、
[机器验收](data/M6-settlement-prices-acceptance.json)、
[保留的合成输入清单](data/M6-settlement-prices-acceptance/prices.json)。

先固定清单、价格文档与资金费报告哈希，逐页复核资金费原始响应，并核验资产、
市场、完整范围和八小时间隔。按计划结算时间一一关联价格，保留原始费率报告
时间；缺失、乱序、重复、格点错位和额外价格拒绝，不按日线开盘/高低区间补价。
源路径限制在清单目录内，加载结束复核全部原始字节。数字、非法十进制价格、
下溢/溢出、危险路径、坏哈希、重复 JSON 键、未知/重复/未引用来源和伪造认证均拒绝。

独立包装现有组合执行器，可传入已校验的日期规格/费用执行区间。只更换资金费
估值价格，不改变订单成交、止损、风控或历史费率；日线持仓归属的保守处理沿用。
入场日开盘结算跳过，入场/止损/止盈日收取负担、扣留收入，完整持仓日保留正负值。
结果明确标记声明价格模型，并保存清单/文档/资金费报告和相关源码哈希。

验证：

- 完整测试：256 项通过，新增 15 项。
- BTC/ETH 合成价格每次结算依次变化，费率 0.001，成交各 2 张，持仓跨三日。
  做多资金费各 2.32；做空资金费各 -1.86，入场日收入扣留，符合独立逐项算术。
- 同时应用声明费率 0.001，每笔往返手续费 0.4。多头账户期末 9994.56，
  空头账户期末 10002.92，与逐笔净损益对账一致；机器验收全部 9 项检查通过。
- 负费率方向反转、止损日扣留收入、真实不完整归档拒绝、原报告 1 秒延迟保留、
  非法价格/时间/字段/路径/来源与哈希损坏均覆盖。
- 原登记字节与全部 37 个冻结源码哈希不变；未改动冻结未来执行器或协议。
- 合成价格、费用清单、资金费报告和原始响应保存于机器验收同名目录，均明确
  为合成数据，复现时不调用外部行情 API。输出与输入目录拒绝覆盖。

复现：

```powershell
$registrationHash = (Get-Content ..\1\data\M6-settlement-prices-acceptance.json -Raw | ConvertFrom-Json).registration_sha256
python audit_settlement_prices.py ..\1\data\M6-restart-registration.json `
  --expected-registration-sha256 $registrationHash `
  --output ..\1\data\M6-settlement-prices-new.json
python -m unittest discover -s tests -q
```

价格声明文本和哈希不能认证历史真实结算价；资金费间隔仍为经检查的八小时格点
假设，日线仍不能确定日内持仓所有权。`settlement_prices_verified` 与
`exact_costs_verified` 始终 false，不证明真实账户成本。历史费率归档沿用既有
浮点精度规则。完整历史规格逐字段认证、真实结算价/账户费用/实际滑点证据及
认证执行集成、未来独立有效验证仍待完成。M6 保持 `NOT_VALIDATED`，
旧基础假设保持 `TERMINATED`，M7/M8/M9 依赖不变。
