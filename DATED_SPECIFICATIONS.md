# 日期规格声明加载与离线模拟

`dated_specifications.py` 是 M6-R5 工程子项。它把固定哈希的日期规格声明转换为
现有组合模拟器的 `execution_periods`，按成交日应用规格。声明只用于显式同意的
离线情景研究，不认证历史有效期或真实成本，不接入 M6 冻结未来协议。

每个清单必须包含 `version: dated-specification-scenario-v1`、
`scope: DECLARED_SCENARIO_ONLY`、`sources` 和 `assets`。
`sources` 的每个条目包含清单目录内的相对 `file`、原始字节 `sha256` 和 `description`。
每个资产的区间包含 UTC Unix 秒 `start`、`end`、引用源名称列表 `sources` 及
`specification`；规格完整包含以下五个正数十进制字符串：
`multiplier`、`quantity_step`、`min_quantity`、`max_quantity`、`price_tick`。
步长须显式提供，最小/最大数量须与步长对齐；不从最小张数猜测精度。

区间左闭右开，按时间排序，连续覆盖请求窗口；边界必须为 UTC 日桶起点。
日线不能确定日内生效/成交顺序，故日内变更直接拒绝；合约乘数变化因缺少
持仓转换逻辑而拒绝。缺资产、多余资产、缺口、重叠、坏哈希、危险路径、
重复 JSON 键及额外字段同样拒绝。不支持从观察快照自动推断有效期间。

Python 接口：

```python
from dated_specifications import simulate_manifest
result = simulate_manifest(
    asset_rows, candidates, portfolio_config, groups,
    "manifest.json", reviewed_sha256,
    allow_declared_scenario=True,
)
```

使用已有组合账户模拟器，数量规格按成交日应用；挂单不满足新价格刻度时沿用
`EXECUTION_SPEC_CHANGED` 撤销规则。费用、滑点、资金费代理、风险预算及策略参数
保持传入基准配置。可传 `structures` 及 `funding`，仍沿用原有完整性校验。
结果保留完整执行区间、引用源、清单哈希、执行相关源码哈希和未认证状态。
`verified_fields` 固定为空，`historical_specs_verified`、`exact_costs_verified`
固定为 false，`acceptance_status` 为 `NOT_VALIDATED`。
哈希仅证明字节完整性，文档名称或描述不证明内容真实、交易所来源或时间范围。

命令行只校验并输出范围报告，不运行策略。基准配置为 `trade_simulation.Config`
参数 JSON；输出拒绝覆盖：

```powershell
python dated_specifications.py manifest.json --expected-sha256 <审阅时保存的哈希> `
  --base-config base.json --symbols BTC ETH --start <UTC日桶秒> --end <UTC日桶秒> `
  --allow-declared-scenario --output new-report.json
python -m unittest discover -s tests -q
```

真实历史生效区间、逐字段可核验认证、真实费用/滑点/结算价及冻结执行器集成
仍待完成；本模块不能解除 M6 验证及 M7/M8/M9 依赖。
