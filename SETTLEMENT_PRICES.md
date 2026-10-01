# 逐结算价格声明与资金费模拟

M6-R7 工程：`settlement_prices.py` 将完整归档资金费率与逐结算时点价格声明
严格关联，再调用现有组合模拟器。只接受显式声明情景，不能认证真实结算价。
不修改冻结研究源码、参数、未来测试区间或未来执行器。

清单结构（全部时间为 UTC Unix 秒，价格为十进制字符串）：

```json
{
  "version": "settlement-price-scenario-v1",
  "scope": "DECLARED_SCENARIO_ONLY",
  "sources": {
    "prices": {"file": "prices-source.txt", "sha256": "<固定文档哈希>", "description": "价格声明"}
  },
  "assets": {
    "BTC": {
      "funding_snapshot": "BTC-funding",
      "funding_sha256": "<固定 funding.json 哈希>",
      "prices": [
        {"timestamp": 0, "mark_price": "100", "sources": ["prices"]},
        {"timestamp": 28800, "mark_price": "110", "sources": ["prices"]},
        {"timestamp": 57600, "mark_price": "120", "sources": ["prices"]}
      ]
    }
  }
}
```

源文档和资金费快照必须在清单目录内。先固定清单哈希，再检查文档、资金费报告
及原始页哈希，并复核原始资金费归档。资产、市场、区间和假设间隔必须完全匹配。
当前模拟器仅支持八小时格点；价格按计划结算时间严格一一匹配，资金费报告时间
允许既有不超过 60 秒延迟并保留原时间。不得将报告延迟时间当作计划结算时间。
价格不得为零、负数、非有限数、浮点下溢/溢出或 JSON 数字；缺失、乱序、重复、
额外记录、非法路径、重复 JSON 键、坏哈希和伪造认证字段均拒绝。
读取前后复核所有证据字节，避免归档在加载中被改动。

```python
from settlement_prices import simulate_manifest
result = simulate_manifest(
    asset_rows, candidates, portfolio_config, groups,
    "settlements.json", reviewed_manifest_sha256,
    allow_declared_scenario=True,
    execution_periods=declared_execution_periods,  # 可省略；兼容已校验的日期规格/成本区间
)
```

价格只用于资金费名义金额：`数量 × 合约乘数 × 方向 × 历史费率 × 声明结算价`。
不使用日线 mark 开盘或高低区间替代缺价。入场日跳过该日开盘结算；入场、止损
或止盈日只能确定日内所有权存在歧义，收取负担、扣留收入；完整持仓日保留正负资金费。
日线仍不能确定真实日内持仓时间，声明价格也不能证明真实交易所结算价格。
资金费八小时间隔是经序列检查的假设，不认证真实历史间隔。

结果保留逐资产资金费报告哈希、全部价格来源与清单哈希、执行源码哈希、价格
模型和所有权规则。`settlement_prices_verified` 和 `exact_costs_verified` 始终
false，认证结算数为 0，`acceptance_status` 保持 `NOT_VALIDATED`。
哈希只证明字节未变，价格文本声明不证明历史真实性。现有费率归档的浮点精度规则沿用。

CLI 只校验并输出证据摘要，拒绝覆盖已有输出：

```powershell
python settlement_prices.py settlements.json --expected-sha256 <固定哈希> `
  --symbols BTC ETH --start <UTC日桶秒> --end <UTC日桶秒> `
  --allow-declared-scenario --output new-evidence.json
python -m unittest discover -s tests -q
```

`audit_settlement_prices.py` 保存合成价格/费用清单、原始资金费归档及多资产多空
模拟结果，核验资金费、手续费、账户对账和冻结源码。真实价格认证、账户费用/
实际滑点证据及认证执行集成、未来独立策略验证仍待完成，不解除 M7/M8/M9 依赖。
