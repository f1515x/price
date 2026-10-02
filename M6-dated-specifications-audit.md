# M6-R5：日期规格声明加载与成交时点模拟接入验收

日期：2026-10-01。完成 plan.md 4.1 M6 的一个工程子项：固定哈希的
日期规格声明加载、区间校验与成交日参数映射。通过 GitHub 插件核对
`huan00000/price`，在本地 `feature` 分支提交，未推送。
代码提交：`13006e9e45f3666fbdeffd0dbe3ec6e847f4a0df`。

工程验收 **PASSED**，策略仍 **NOT_VALIDATED**。交付的是声明情景通路；
本次没有获得真实历史生效时间证明，没有认证实际交易成本，未修改冻结未来执行器。

交付：[加载与模拟模块](../source/dated_specifications.py)、
[复核工具](../source/audit_dated_specifications.py)、
[说明](../source/DATED_SPECIFICATIONS.md)、
[14 项测试](../source/tests/test_dated_specifications.py)、
[机器验收](data/M6-dated-specifications-acceptance.json)。

清单和全部引用文档按原始字节核验 SHA-256。规格只允许完整的乘数、
数量步长、最小/最大张数和价格刻度；不推断精度，不接受费用或风险参数混入。
区间必须连续、无重叠并覆盖全部请求资产和日期，UTC 左闭右开。
日内变更无法由日线准确模拟，因此拒绝；乘数变更因未实现持仓转换而拒绝。
路径越界、重复 JSON 键、伪造认证字段、坏哈希和缺资产均拒绝。

独立包装接口将区间传入现有组合模拟器，成交日选择数量规格，
新价格刻度不兼容时撤销挂单。保留清单哈希、文档引用、源码哈希、
完整区间参数和未认证状态。须显式启用 `allow_declared_scenario=True`；
`verified_fields` 始终为空，历史规格与精确成本认证始终 false。
哈希不能认证来源或内容，声明不能证明真实生效时间。

验证结果：

- 226 项 unittest 全部通过，其中新增 14 项；暂存差异检查通过。
- 合成 BTC/ETH 多资产成交日步长从 1 切为 0.1，限额从 2 切为 2.5，
  两资产成交均为 2.5 张，期末资金与净损益对账一致。
- 边界选择、刻度变化撤单、缺口/重叠/顺序、未覆盖窗口、乘数变化、
  非有限数/零值/精度不齐、哈希损坏、路径、资产和认证伪造均有测试。
- 真实观察台账固定哈希
  `845d22b74e248c7cf08a441125879007c092e4f44a706e05bbf3b72ef1ed5408`
  复核通过；它不能作为日期规格声明加载，BTC/ETH 历史认证覆盖仍为零。
- 原登记文件及全部 37 个冻结源码哈希不变，台账保持固定哈希。
  合成数据只验证工程，不构成交易证据。

复现（输出需使用不存在的新文件）：

```powershell
python audit_dated_specifications.py ..\1\data\M6-restart-registration.json `
  ..\1\data\M6-spec-evidence-20261001 `
  --expected-ledger-sha256 845d22b74e248c7cf08a441125879007c092e4f44a706e05bbf3b72ef1ed5408 `
  --output ..\1\data\M6-dated-specifications-new.json
python -m unittest discover -s tests -q
```

真实历史有效期证明、逐字段证据认证、认证规格接入冻结未来执行器、
精确费用/滑点/结算价及模拟集成、未来独立结果仍待完成。
M6 仍 `NOT_VALIDATED`，旧基础假设仍 `TERMINATED`，M7/M8/M9 依赖不变。
