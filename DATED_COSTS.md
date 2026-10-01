# 日期费用与滑点声明情景

`dated_costs.py` 为 M6-R6 工程子项。离线组合模拟按每根 UTC 日线所属日
应用费用和滑点，可同时加载 M6-R5 日期规格清单；独立边界取并集。
不改动冻结源码或未来执行协议，不认证真实账户费用、实际滑点或结算价。

清单包含 `version: dated-cost-scenario-v1`、`scope: DECLARED_SCENARIO_ONLY`、
`sources` 与 `assets`。源文档声明与 M6-R5 一致：清单目录内相对 `file`、
原字节 `sha256`、`description`。每个资产的连续左闭右开区间包含整数 UTC
Unix 秒 `start`、`end`、唯一已知源名称数组 `sources`，以及
`costs: {"fee_rate": "0.001", "slippage": "0.0005"}`。
两个成本字段都必须为有限、非负且小于 1 的十进制字符串。
拒绝浮点下溢、舍入为 1、日内边界、缺口、重叠、未引用文档、非法路径、
重复 JSON 键、坏哈希、额外字段及不完整资产覆盖。允许显式零成本对照。

```python
from dated_costs import simulate_manifest
result = simulate_manifest(
    asset_rows, candidates, portfolio_config, groups,
    "costs.json", reviewed_cost_sha256,
    specification_path="specs.json",          # 两个规格参数同时提供或同时省略
    specification_sha256=reviewed_spec_sha256,
    allow_declared_scenario=True,
)
```

费用与滑点采用现有模拟器模型：每个成交均用当日同一个手续费率；滑点为
方向不利的价格比例，入场限价仍约束成交价。它们不是逐笔 maker/taker
账单或实际盘口滑点。入场预算计入入场日费率/滑点下的止损估计；未来成本
改变不会调整已有持仓数量或已记录止损风险，真实损失仍可能超过初始预算。

入场时间为成交日桶起点。退出时间标记日线结束，退出参数使用退出那根
日线所属日期，即 `exit_time - DAY`，不会误用次日参数。每笔交易的
`cost_application` 记录实际应用日期、入场/退出费率与滑点。
日线仍无法确定真实日内成交时刻或资金费所有权，继承保守结算规则。

资金费独立保留原配置代理或传入的完整历史结算序列；成本声明不能覆盖
资金费、风险参数或规格。即使传入历史资金费，也不自动认证精确成本。
结果记录清单/文档/执行源码哈希、完整合并区间及未认证状态。
`historical_specs_verified` 与 `exact_costs_verified` 始终 false，
`acceptance_status` 始终 `NOT_VALIDATED`。哈希只证明字节未变。

命令行只校验费用清单并输出范围报告，拒绝覆盖已有报告：

```powershell
python dated_costs.py costs.json --expected-sha256 <固定哈希> --base-config base.json `
  --symbols BTC ETH --start <UTC日桶秒> --end <UTC日桶秒> `
  --allow-declared-scenario --output new-cost-report.json
python -m unittest discover -s tests -q
```

真实历史规格逐字段认证、账户费用/实际滑点/精确结算价的完整证据及认证
执行集成仍待完成；不解除 M6、M7、M8 或 M9 验证依赖。
