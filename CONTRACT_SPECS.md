# Gate 合约规格快照

`contract_specs.py` 采集 Gate USDT 永续合约的**当前**公开规格，保存原始响应、SHA-256、UTC 请求与接收时间、来源 URL、规范化字段及采集器源码哈希。字段口径来自 [Gate 官方文档](https://www.gate.com/docs/developers/apiv4/en/futures/)。不需要账户或 API key。

```powershell
python contract_specs.py BTC ETH --output ..\1\data\M6-contract-specs-new
python -m unittest discover -s tests -v
```

输出目录必须不存在。采集/校验全部成功后才创建目录；已有快照不覆盖。`load_snapshot(path)` 离线核对原始响应哈希和规范化字段，拒绝资产错配、非法数值、反向合约、报告与原始数据不一致。

数量以合约张数计，`quanto_multiplier` 是每张对应的标的数量；`order_price_round` 是价格步长。整数张合约映射数量步长为 1。小数张的 `enable_decimal` 仅说明支持小数，不能据此确定步长，也不能把最小数量当作步长。小数张快照正常保存，但标记 `UNSUPPORTED_DECIMAL_STEP`，禁止自动映射；接口最小数量为 0 时保留原值，不能作为可下单的有效最小数量。退市或非 trading 状态标记 `NOT_TRADING`。

研究场景可显式映射乘数、最小张数、数量步长、价格 tick 和最大张数：

```python
from contract_specs import scenario_config
from trade_simulation import Config

base = Config(initial_equity=10000, risk_fraction=.005,
              max_exposure=1, max_drawdown=.15)
config = scenario_config("../1/data/M6-contract-specs-20261001", "BTC", base,
                         assume_current_specs=True)
# config.multiplier / quantity_step / min_quantity / price_tick / max_quantity 使用快照值。
# 可传给 simulate(rows, candidates, config)。
```

必须显式声明 `assume_current_specs=True`。这是“假定当前规格适用于研究区间”的场景，不能当作历史真实规格回测。映射不改变费用、资金费率、风险预算等参数；返回配置需与快照及这一假设一起归档。BTC 和 ETH 分开查询、分别映射，不能复用 BTC 参数替代 ETH。组合模拟器通过 `execution_by_asset` 接收每资产 Config，也可通过 `execution_periods` 接收连续日期版本，见 [M6 研究说明](M6_RESEARCH.md)。

采集器已加入 `X-Gate-Size-Decimal: 1`，避免 ETH 小数最小数量被旧响应格式显示为 0。小数步长仍不自动从最小数量推导；映射须另传 `decimal_step` 和非空 `precision_source`，使用者负责证据可靠性。例如 ETH 使用 `decimal_step="0.1"` 与 [官方数量精度公告](https://www.gate.com/zh/announcements/article/50325)。老快照的零最小数量仍拒绝映射，不追写历史证据。

价格 tick 与最大张数已接入执行；公开 maker/taker 费率及资金结算间隔仍只是公开快照字段。公开费率不代表账户实际成交费率，当前 funding rate 不代表历史结算序列。模拟器没有保证金或强平约束；当前配置变更时间也不能证明此前全部规格。映射后的结果仍是研究场景，不能宣称完整重现交易所执行。完整历史资金费率及滚动实验见 M6 说明，真实历史规格的其余字段仍需证据。
