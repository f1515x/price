# M2：逐日动态指标验收

完成日期：2026-09-30。实现：[indicators.py](../source/indicators.py)，测试：[test_indicators.py](../source/tests/test_indicators.py)。GitHub 插件已确认仓库 `huan00000/price`；本次成果保存在本地，未推送。

## 已交付与口径

- 收益分位（严格小于计 1、相等计 0.5）、Median Move、signed_move、Robust Z、EMA、Wilder ATR、Stretch。遵循 plan.md 的收益与分母公式，收益使用小数。
- 版本 `daily-indicators-v1`，集中配置默认 W=365、EMA=50、ATR=14；CLI 可调整三个参数。30 日收益固定要求 31 根连续有效日线。
- 分布仅使用当前时点之前最近 W 个有效收益；先计算后加入当前收益。历史有效收益可跨缺口保留，并记录数量和首尾时间。数量不足 W 时分布指标缺失。396 根连续日线首次具备默认完整窗口。
- EMA 以首 50 根收盘价的简单平均初始化，之后 alpha=2/51；ATR 以首 14 个 TR 的简单平均初始化，之后采用 Wilder alpha=1/14。连续段首根 TR=high-low，其后取 high-low、abs(high-prev_close)、abs(low-prev_close) 的最大值。数据缺口使 ATR/EMA 和当前收益重新预热。
- 输入 CLI 必须经过 M1 快照哈希校验与原始质量重建。未收盘、错误、冲突和缺失日不会生成指标行，原因保留于输出 input_quality；缺口后的首个有效时点标记 gap_before。calculate API 要求传入 prepare/load_snapshot 返回的已收盘数据，不接受混合标的、乱序或非法 OHLCV。
- 零 typical_move、MAD、ATR 对应指标输出 JSON null 和具体原因；预热与历史不足分别记录原因，非有限计算结果转为 null。status=OK 仅表示指标齐备，不表示策略或结构就绪。
- 每行记录时间、收盘后可知时间 signal_time=t+86400、资产来源、价格、收益、历史数量/范围、参数、版本、指标与原因。文件附输入哈希和完整质量报告，可离线重现；输出路径已存在时拒绝覆盖。

## 可复现验收

在 `E:\git\0AAimportant\price\source` 执行：

```powershell
python -m unittest discover -s tests -v
python indicators.py ..\1\data\BTC-20240101-20250301 --output ..\1\data\BTC-M2-new.json
```

15 项测试全部通过（原 M1 8 项、新 M2 7 项）。覆盖完整窗口边界、当前值排除、未来数据追加不改变过去、手算分位与 MAD/Move、EMA/ATR 初始化和递推、零分母与重复值、异常和未收盘数据排除、缺口重新预热、无效参数与混合资产拒绝。

已使用 M1 保存的 BTC 数据实际运行 CLI：[BTC-M2-indicators.json](data/BTC-M2-indicators.json)。425 行中 30 行指标全部就绪，其余 395 行处于预热/历史不足阶段。无需下载或修改原快照。

本任务完成指标工程与计算验收，未进行收益有效性回测；SMC 接入、候选信号与评分仍属于后续任务。旧交易入口未改动。
