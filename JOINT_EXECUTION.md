# M6-R10：规格、日期成本与逐结算价格联合执行

`joint_execution.simulate_joint` 将 M6-R9 的逐字段审阅规格、M6-R6 的日期费用/滑点、
M6-R7 的逐结算价格和固定历史资金费归档接入同一次共享账户模拟。
三个输入及其 SHA-256 均为必填，且必须显式设置 `allow_scenario=True`。
不允许用默认配置补齐任何证据缺口。

`load(base, symbols, start, end, **inputs)` 返回 `(periods, funding, report)`。
`simulate_joint(asset_rows, candidates, portfolio_config, groups, structures=None, **inputs)`
返回完整账户结果。`inputs` 包含 `review_path/review_sha256`、`cost_path/cost_sha256`、
`price_path/price_sha256` 与 `allow_scenario`。输入沿用既有模块的文件格式。

联合规格和成本全部日界；规格与成本分别只替换其负责字段，基础风险参数保持原值。
成交日规格决定新持仓数量；后续规格上限或费用变化不重算已有仓位。
入场费用使用日桶起点，退出费用使用 `exit_time - DAY`，因为退出时间标签表示日桶结束。
日线内无法证明结算持有权，沿用保守资金费规则：入场日跳过日初结算；
有歧义的入场/止损/止盈日收取支出且不记收入。不能将此模型称为真实账户对账。

每笔交易保留成交日五字段 claim ID、十进制规格、审阅清单哈希、入场/退出成本及成本清单哈希、
结算价清单哈希。报告保存三个子报告、合并执行区间、相关源码哈希和持有权口径。
模拟返回前重新读取并比对全部加载结果，防止规格、成本、结算价、源文档或资金费归档变化。

这只是 `JOINT_SCENARIO_ONLY`；所有认证标记仍为 false，状态为 `NOT_VALIDATED`。
未改动冻结未来协议与源码，也未接入未来认证执行。真实审阅清单为空时拒绝执行。

复现机器验收（在 source 目录，输出文件及其同名输入目录必须不存在）：

```powershell
$prior = '..\1\data\M6-reviewed-specifications-acceptance.json'
$hash = (Get-FileHash -LiteralPath $prior -Algorithm SHA256).Hash.ToLower()
python audit_joint_execution.py ..\1\data\M6-restart-registration.json $prior `
  ..\1\data\M6-field-review-acceptance\real-review.json `
  --expected-prior-sha256 $hash --output ..\1\data\M6-joint-execution-new.json
python -m unittest discover -s tests -q
```

工具保留合成 BTC 多/ETH 空输入、资金费原始响应和全部文件哈希，核验原登记及冻结源码，
检查真实空审阅输入明确阻止执行。合成 `effective_notice` 标签只用于测试，不能证明真实性。
