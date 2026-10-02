# M3：已确认 SMC 结构回放验收

完成日期：2026-09-30。在 `../source` 的 `feature` 分支开发；通过 GitHub 插件核对仓库为 `huan00000/price`，本次未推送。

## 交付与口径

- [structure_history.py](../source/structure_history.py) 从 M1 已校验日线快照生成逐日结构，版本 `daily-structure-v1`，默认 `swing_length=50`，ATR 固定使用 M2 的 Wilder ATR14。
- 每个连续日线前缀调用既有 `pine_weak_strong`，只传入当前及过去数据，保留旧 pivot、趋势突破与 trailing extrema 规则。未改动旧交易入口与 SMC 实现。
- 每行保存资产、市场、周期、来源、收盘价、参数、状态、缺失原因、连续根数、raw/adjusted weak、strong、trend、ratio、ATR14、swing_atr，以及完整原始结构字段。文件保存输入哈希和质量报告。
- `timestamp` 为日桶起点；`signal_time` 与 `earliest_execution_time` 为该日收盘时间 `timestamp+86400`，代表下一日桶最早可执行边界，不代表已经生成交易候选或成交。
- `swing_high_index / swing_low_index` 是 pivot 发生日桶起点；对应 `*_confirmed_at` 为其右侧第 swing_length 根日线收盘时间。`structure_confirmed_at` 为当前两侧 pivot 确认时间的较晚者。最新 trailing 价格和趋势必须到当前 `signal_time` 才可知，不能用 pivot 确认时间提前使用当前快照。
- `top_index / bottom_index` 是 trailing 极值发生日，不是 pivot 确认时间。trailing 价格在确认后的逐日更新沿用旧实现。
- BULLISH 使用 weak high / strong low，BEARISH 使用 weak low / strong high。旧实现 UNSET 时两端都标 weak，新回放保留原结构并标记 `TREND_UNSET`，配对与 ratio 返回 null。
- `ratio=(raw_weak-strong)/当前开盘价`；adjusted weak 为 raw weak 加/减一次 ATR；`swing_atr=abs(raw_weak-strong)/ATR`。ATR 预热或为零均明确记录；不生成无穷值。
- 缺失或被 M1 排除的异常日导致连续段中断，结构和 ATR 从新段重新预热。CLI 校验输入哈希并重建质量报告；输出存在时拒绝覆盖。API 要求使用 M1 prepare/load_snapshot 的已收盘结果。

## 验证

在 `E:\git\0AAimportant\price\source` 执行：

```powershell
python -m unittest discover -s tests -v
python structure_history.py ..\1\data\BTC-20240101-20250301 --output ..\1\data\BTC-M3-new.json
```

21 项测试全部通过：原 M1/M2 15 项，新增 [M3 测试](../source/tests/test_structure_history.py) 6 项。覆盖手工 pivot 确认延迟、趋势未定、双向价格和有符号 ratio、旧接口数值一致、未来追加/修改不改变既有结果、缺口后重新预热、非法参数/混合资产/乱序、未收盘及异常行排除。

实际离线运行已生成 [BTC-M3-structures.json](data/BTC-M3-structures.json)：425 行，237 行结构就绪。无需重新下载行情，原始快照未修改。

## 边界

本次交付是研究用结构回放，不包含 M4 事件研究、候选规则、收益验证或自动下单。日线默认 50 根结构窗口不能直接等同原小时线窗口。参考实现逐前缀重算，复杂度约 O(N²×swing_length)，适用于当前小规模验收；大规模多资产研究前可另行改为增量状态机，并以本实现做一致性对照。
