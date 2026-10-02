# M6-R6：日期费用/滑点声明与跨日执行集成验收

日期：2026-10-01。完成 plan.md 4.1 M6 成本执行集成中的声明情景工程子项。
通过用户指定的 GitHub 插件确认 `huan00000/price`，在本地 `feature` 分支提交。
代码提交：`df7529577da8e17e8ee0a0e8d43548724b3561a2`，未推送。

工程验收 **PASSED**，策略仍 **NOT_VALIDATED**。真实账户手续费、实际滑点及
精确结算价证据尚未取得；本次不认证真实历史成本，不改动冻结未来执行器。

交付：[模块](../source/dated_costs.py)、[说明](../source/DATED_COSTS.md)、
[15 项测试](../source/tests/test_dated_costs.py)、[复核工具](../source/audit_dated_costs.py)、
[机器验收](data/M6-dated-costs-acceptance.json)。

固定哈希的清单和原始引用文档先核验，再按资产校验连续 UTC 日区间。
仅接受十进制字符串费率和滑点比例，不允许覆盖风险、资金费或规格字段。
零成本对照可用；非法数值、浮点下溢/舍入越界、日内变化、缺口/重叠、
资产覆盖不完整、坏哈希、危险路径、重复键及伪造认证字段均拒绝。

独立包装模块使用既有共享账户组合模拟器。可同时加载 M6-R5 规格清单，
按规格与成本的边界并集形成完整执行区间。入场和退出采用各自执行日成本，
保留逐笔参数及日期。退出时间为日线结束标记，采用 `exit_time - DAY`
对应日线的配置，避免在日界误用次日费率。历史资金费仍要求完整结算序列，
缺失拒绝，不填零；日线的保守所有权和 mark 模型继续保留。

验证：

- `python -m unittest discover -s tests -q`：241 项全部通过，新增 15 项。
- 合成 BTC/ETH 原生多资产模拟，规格在第 1 日、费用在第 2 日独立切换，
  两资产均成交 3 张。BTC 净损益 -3.894，ETH（乘数 0.01）净损益 -0.03894，
  与独立计算一致，期末资金 9996.06706 与账户资金对账一致。
- 多空方向不利滑点、退出日界、静态零成本等价、历史资金费与缺失拒绝、
  清单坏哈希/非法区间/路径/字段/数值均有测试。
- 原登记文件及全部 37 个冻结源码哈希不变；机器验收全部 8 项检查通过。
- 暂存差异格式检查通过；本地工作分支为 `feature`。

复现（输出必须为新文件；登记哈希保存于机器验收）：

```powershell
$registrationHash = (Get-Content ..\1\data\M6-dated-costs-acceptance.json -Raw | ConvertFrom-Json).registration_sha256
python audit_dated_costs.py ..\1\data\M6-restart-registration.json `
  --expected-registration-sha256 $registrationHash `
  --output ..\1\data\M6-dated-costs-new.json
python -m unittest discover -s tests -q
```

声明费率不是逐笔 maker/taker 账单；声明滑点不是实际盘口成交证据。
入场风险预算仅按入场成本估计，后续费用变化不重设已持仓数量及初始止损风险，
实际损失可能超过预算。合成数据只验证工程，不证明策略效果或真实成本。
哈希只证明字节未变；历史规格与精确成本认证始终 false。

真实历史规格有效期和逐字段认证、真实账户成本/精确结算价证据及认证执行集成、
未来独立结果仍待完成。M6 保持 `NOT_VALIDATED`，旧基础假设保持 `TERMINATED`，
M7/M8/M9 依赖不变。
