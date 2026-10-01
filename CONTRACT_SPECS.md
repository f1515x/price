# Gate 合约规格快照

`contract_specs.py` 采集 Gate USDT 永续合约的**当前**公开规格，保存原始响应、SHA-256、UTC 请求与接收时间、来源 URL、规范化字段及采集器源码哈希。字段口径来自 [Gate 官方文档](https://www.gate.com/docs/developers/apiv4/en/futures/)。不需要账户或 API key。

```powershell
python contract_specs.py BTC ETH --output ..\1\data\M6-contract-specs-new
python -m unittest discover -s tests -v
```

输出目录必须不存在。采集/校验全部成功后才创建目录；已有快照不覆盖。`load_snapshot(path)` 离线核对原始响应哈希和规范化字段，拒绝资产错配、非法数值、反向合约、报告与原始数据不一致。

数量以合约张数计，`quanto_multiplier` 是每张对应的标的数量；`order_price_round` 是价格步长。整数张合约映射数量步长为 1。小数张的 `enable_decimal` 仅说明支持小数，不能据此确定步长，也不能把最小数量当作步长。小数张快照正常保存，但标记 `UNSUPPORTED_DECIMAL_STEP`，禁止自动映射；接口最小数量为 0 时保留原值，不能作为可下单的有效最小数量。退市或非 trading 状态标记 `NOT_TRADING`。

研究场景可显式映射三个已支持字段：

```python
from contract_specs import scenario_config
from trade_simulation import Config

base = Config(initial_equity=10000, risk_fraction=.005,
              max_exposure=1, max_drawdown=.15)
config = scenario_config("../1/data/M6-contract-specs-20261001", "BTC", base,
                         assume_current_specs=True)
# config.multiplier / quantity_step / min_quantity 使用快照值。
# 可传给 simulate(rows, candidates, config)。
```

必须显式声明 `assume_current_specs=True`。这是“假定当前规格适用于研究区间”的场景，不能当作历史真实规格回测。映射不改变费用、资金费率、风险预算等参数；返回配置需与快照及这一假设一起归档。BTC 和 ETH 分开查询、分别映射，不能复用 BTC 参数替代 ETH；当前组合模拟器只接受统一规格，尚不支持每资产配置。

最大订单张数、价格步长、公开 maker/taker 费率及资金结算间隔保存于快照，尚未接入执行模型。公开费率不代表账户实际成交费率，当前 funding rate 不代表历史结算序列。现有模拟器没有价格 tick 舍入、最大订单数量、保证金或强平约束；映射后的结果仍是研究场景，不能宣称已完整模拟交易所执行或真实历史成本。历史规格版本、ETH 小数张步长确认与上述执行约束继续待办。
