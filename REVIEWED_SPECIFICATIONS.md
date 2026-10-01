# 逐字段审阅主张接入日期规格模拟

M6-R9 完成五个规格字段联合合法性检查及审阅主张到执行参数的离线情景通路。
`reviewed_specifications.py` 读取 M6-R8 固定哈希清单及原文字节，不接受未校验报告
作为输入。必须显式设置 `allow_reviewed_scenario=True`。API `load` 返回日期配置和
来源报告；`simulate_review` 接入既有共享账户模拟，并在每笔成交的
`entry_specification_review` 保存成交日区间、逐字段 claim ID、十进制值和清单哈希。
报告保留完整审阅记录、文档哈希与相关执行源码哈希。

每个资产每个字段必须覆盖整个请求窗口且没有异值冲突；不会用默认规格补缺口。
同值 Decimal 主张可重叠，保留所有关联 ID；观察及 synthetic 文档不能贡献覆盖。
合并五个字段全部边界后生成左闭右开日期区间，不跨资产补值。
日内主张边界拒绝进入日线模拟，即使同值；窗口外边界裁切。
数量上限/下限必须与步长整除，最大值不得小于最小值。拒绝浮点溢出、下溢及
十进制值转模拟浮点再转文本后的数值丢失。合约乘数在样本内改变仍不支持。
风险、成本、资金费等非规格参数保持基础配置，资金费 API 参数沿用原引擎。
解析结束及模拟返回前重新核对原文；冻结的未来协议及执行器没有修改。

这是 **REVIEWED_SCENARIO_ONLY**。人工主张及 effective_notice 类型标签不认证发行方、
语义或历史有效期；`verified_fields=[]`，`historical_specs_verified=false`，
`exact_costs_verified=false`，`acceptance_status=NOT_VALIDATED`。
`used_for_execution_parameters` 仅在执行模拟后为 true；嵌套原始审阅报告仍是原有
证据分析报告。真实历史证据为空时严格拒绝模拟。不能用于认证未来研究或上线。

```powershell
python reviewed_specifications.py review.json --expected-sha256 <固定哈希> `
  --base-config config.json --symbols BTC ETH --start <UTC日界秒> --end <UTC日界秒> `
  --allow-reviewed-scenario --output new-report.json
python -m unittest discover -s tests -q
```

CLI 只解析配置并写来源报告，拒绝覆盖；模拟通过 Python API 调用。
验收工具 `audit_reviewed_specifications.py` 固定原登记及真实审阅哈希，检查冻结源码，
保存合成 BTC 多/ETH 空案例、独立费用/滑点算术、账户资金与真实缺口拒绝结果。
合成 effective_notice 标签只用于测试通路，不是新取得的历史证据。
