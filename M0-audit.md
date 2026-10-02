# M0：代码现状、数据字典与旧规则基线

核验日期：2026-09-30。核验人：Codex。状态：完成代码现状核验；外部服务可用性及策略参数决策不包含在本次验收中。

证据版本：[huan00000/price，b3e9aab346589061e6a695d7c1879e66be310ea1](https://github.com/huan00000/price/tree/b3e9aab346589061e6a695d7c1879e66be310ea1)。通过 GitHub 插件检索并克隆至 `../source`，以下路径均相对该源码目录。原有策略代码未修改。

## 1. 现状清单

| 核对项 | 代码事实与证据 | 对后续任务的影响 |
|---|---|---|
| 入口 | `price.py:analyze/main` 支持多个标的及 `--swing-length`，默认 50；返回候选价或 None | 保留现有 CLI；50 是 K 线根数 |
| 实际执行链 | `.github/workflows/run.yml` 调用 `size.py` → `price` 的月度与结构接口，再生成张数报告、发送 Telegram | `price.py` 本身仅输出候选；核验未运行发送流程 |
| 交易场所 | `kline.py:update_kline` 请求 Gate `/api/v4/futures/usdt/candlesticks`，合约 `{SYMBOL}_USDT`；`month.py:get_month_performance` 请求 TradingView 的 `GATE:{SYMBOL}USDT.P` | 两个来源分别采样，没有统一信号时间 |
| K 线尺度 | `interval=1h`；首次 limit=501，已有文件 limit=8 | 连续时约 20.875 天的小时区间，首尾时间差 500 小时；不是 501 天，也不足以构成计划所需 396 个日线收盘价 |
| 存储与更新 | `{SYMBOL}_data.js` 实际保存 JSON 数组；已有数据先删末 8 条，再合并新 8 条、按时间去重排序，并按旧数量/新数量较大者截尾 | 非持续历史归档；首次不去重；停更较久可能留缺口，重叠更新也可能使条数减少；无分页补齐 |
| 时间与收盘 | `smc.py:load_ohlcv` 按数量级识别秒/毫秒并转 UTC；采集器不检查收盘状态，结构直接用最后一根 | 源代码未说明供应商时间戳表示开盘还是收盘；未排除未收盘 K 线，不能视为已收盘信号 |
| 质量检查 | 校验列表、时间戳存在、OHLC 列存在及数值转换；排序 | 没有完整的缺失周期、重复索引、非有限值、OHLC 合法性与收盘检查 |
| 标的池 | `symbol.txt`：BTC、ETH、SOL、HYPE、XRP、DOGE、SUI、SPCX、SNDK、CL、XAU、SPX500 | 是配置名单，不是已验证可交易名单；没有历史成员/下架记录，不能默认全部是加密资产现货 |
| 信号频率 | 工作流列出 UTC 00、04、08、12、16、20 时的 cron，另有手动及特定文件 push 触发 | 配置为每 4 小时；不代表实际成功运行频率或持仓时间 |
| 持仓尺度 | 代码没有退出、有效期、止损、止盈或目标持仓时长 | 当前持仓周期未定义；不能将 1h、4h 或 Perf.1M 当作持有期 |
| 仓位 | `amount.py`：可用保证金 / (1/最大杠杆 + 2×0.00075)，再取 1%；`size.py` 除以候选价和 quanto_multiplier，向零取整，空头负数 | 是名义仓位建议，不是基于止损距离的 1% 风险预算；无组合敞口限制 |
| 运行环境 | requirements 仅列 numpy、pandas、requests，未锁版本；CI 使用 Python 3.x；源码含 3.10+ 类型语法 | 复现实验需另行固定环境与参数版本 |

仓库中的 `price.txt`、`size.txt` 为输出示例，不能证明历史表现。当前 Git 跟踪文件中没有 OHLCV 历史数据集、回测或测试套件；工作流仅提交 size.txt 和 float.js，不归档 K 线。

## 2. 数据字典与接口边界

| 字段 / 接口 | 当前定义、单位 | 可用性或限制 |
|---|---|---|
| `t` → `timestamp` | 采集器以 int 排序；加载器转 UTC 索引 | 秒/毫秒为启发式识别；源时间语义需 M1 核对 |
| `o/h/l/c` → `open/high/low/close` | 合约报价价格，加载器转数值 | 没有持久化市场、周期或来源字段 |
| `v` → `volume` | 仅重命名，未强制存在或转换 | 张数/基础资产/计价资产单位无法由源码确认，M1 须按供应商定义确认 |
| `get_month_performance()` / `perf_1m` | TradingView `Perf.1M`，百分数，例如 21.21 表示 21.21% | 实时字段；没有历史快照时间，代码未给出确切起点/收盘公式 |
| `StructureResult.trend / trend_bias` | BULLISH / BEARISH / UNSET；1 / -1 / 0 | 内部存在，`get_structure()` 的字典丢弃此字段 |
| `top_price / bottom_price` | 随结构状态逐根更新的上下沿 | 与已确认 pivot 不完全同义，后续可被当前根极值更新 |
| `swing_high/low`、相关 index | 已确认 swing 价及原始极值位置 | index 是极值所在时间，不是确认时间 |
| `weak_type` | high 或 low | `top_type == Weak High` 时选 high；UNSET 时上下均 weak，却仍选 high，未过滤未定趋势 |
| `weak_price` | 原始 weak 价格，等价于计划的 raw_weak_price | 当前字典名称不是 raw_weak_price |
| `strong_price` | high 方向取 bottom_price；low 方向取 top_price | 仅转换函数局部变量，未返回；UNSET 时该变量并不保证真正 strong |
| `ATR14` | 前 14 根 TR 均值初始化，随后 Wilder 递推；首根 TR=high-low；价格单位 | 默认输入为 1h，所以是 14 根小时线 ATR；不在字典单独返回 |
| `adjusted_weak_price` | high：weak_price + ATR14；low：weak_price - ATR14 | 已经加入一次 ATR，不能重复加 |
| `ratio` | (原始 weak_price - strong_price) / 最后一根 open；小数 | 分母不是 close 或 strong；open=0 抛错；显示时乘 100 |
| `ratio_classification` | ratio >0.10 或 <-0.10 的文字提示 | 不是最终综合信号 |
| `FINAL_PRICE` | `price()` 返回 float 或 None | 无成交时间、止损、费用、数量约束；展示为两位小数不代表交易所合法价格步长 |

`get_structure()` 只返回 weak_type、weak_price、adjusted_weak_price、ratio、ratio_classification。`smc.py --output` 保存的是另一套 StructureResult 字段，也没有完整信号、ATR 与确认时间。新接口应新增字段，同时保留旧字段语义。

结构时序：在处理第 i 根时检测候选 i−swing_length，并比较它右侧的 swing_length 根；只有 leg 改变时更新 pivot。之后收盘穿越结构位更新 trend。算法逐根处理不等于已有历史回放产物；M3 必须记录确认时点、信号时点，并防止把原始 pivot 时间当作可使用时间。

## 3. 冻结的旧规则基线

基线标识：`legacy-b3e9aab-price-v1`，定义以 `price.py:price` 为准：

```text
空头：perf_1m > 15 AND ratio > 0.10 AND weak_type == "high"
      entry = 1.01 × (raw_weak_high + ATR14)
多头：perf_1m < -15 AND ratio < -0.10 AND weak_type == "low"
      entry = 0.99 × (raw_weak_low - ATR14)
其余：None
```

全部为严格不等式；恰好 ±15 或 ±0.10 不触发。函数将 weak_type 转小写，使用 adjusted_weak_price，不独立检查趋势、确认状态、数据质量或正价格。`month.py` 独立运行只判断月涨跌幅，不能拿它替代综合基线。

未来回测分开命名两组：

- **原快照基线**：只有取得当时实际 Perf.1M 和当时可用的 1h 结构才能精确重建；当前仓库缺少这类数据，不能声称已完成原历史回测。
- **本地代理基线**：使用已收盘日线 `100 × (Close(t)/Close(t−30)−1)` 代替 Perf.1M 时，披露收益定义差异；若结构也改日线，另披露结构周期改变，不能把两项改动归因于单一指标。

## 4. 验收与后续交接

已执行离线核验：Python 3.14.4；所有根目录 Python 文件 AST 解析成功；从原 price.py 提取 price() 执行 9 个案例全部通过：正常多空、±15 边界、±0.10 边界、两种方向冲突与中性情形。adjusted_weak_price=100 时正常空头为 101、多头为 99。未导入账户模块、未调用外部行情/账户接口、未发送消息；本次不是服务连通性或策略收益验证。

M0 三项验收产物分别为本文第 1 节现状清单、第 2 节数据字典、第 3 节基线定义。后续任务需处理的已识别缺口：

1. M1：明确日线时区、时间戳与收盘语义，验证标的可用性和 volume 单位，拉取至少 396 个连续日线收盘价，保留足够结构预热；质量检查与历史归档独立于旧小时线缓存。
2. M3：返回原始/调整 weak、strong、trend、ATR、确认时间与信号时间；显式处理 UNSET。
3. M4/M6：预登记持仓/标签窗口、费用、风险预算、敞口及样本外验收门槛；当前没有可沿用的完整定义。
4. 凭据核验：month.py 存在硬编码 cookie 字典及会话相关字段，并用于请求。未验证有效性，报告不复制值；凭据迁移、旧会话失效及历史清理未完成，应另行处理。

以上未定配置如实登记，不代表 M1～M9 已实施。
