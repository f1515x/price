# M6-R16 真实一分钟行情采集与固定哈希归档验收

日期：2026-10-01。原任务：plan.md 4.1 M6 的真实精细行情剩余任务中的采集与质量复核子项。

结果：本子项工程 `PASSED`；M6 策略仍 `NOT_VALIDATED`。

## 已交付

新增独立一分钟交易价 OHLCV 采集命令；按 UTC 半开窗口分页，原始 HTTP 响应字节、URL、
参数和逐页哈希不可覆盖归档。价格保留精确小数字符串，排除非法数据、未收盘及页外数据，
相同重复标记，冲突重复使对应分钟失效；空页输出真实缺失。
独立固定清单哈希后，复核器重读原始响应、重建全部分钟数据与质量报告，拒绝改写。
错误响应保留原始字节，失败采集不会产出可验收清单；重试使用新目录。

实现及调用见 [INTRADAY_HISTORY.md](../source/INTRADAY_HISTORY.md)。
接口范围依据 [Gate 官方期货 API 文档](https://www.gate.com/docs/developers/apiv4/en/futures/)。

## 实际数据与验收

- 真实公开 API 采集：ETH_USDT，2026-09-29 00:00 至 2026-09-30 00:00 UTC，2 页，1,440 根已收盘一分钟 K 线，缺失 0、质量问题 0，`quality_status=COMPLETE`。
- [真实归档清单](data/M6-intraday-history-ETH-20260929/manifest.json) SHA-256：`67a7c7f9925695260be857f4289d5b3b80ef0ae0f39ba1662e186310090b88b8`。
- `python -m unittest discover -s tests -q`：374 项通过；其中 9 项新增专项测试覆盖精度、非法数据、重复冲突、收盘、缺失、分页、覆盖拒绝、原始/派生/清单改写、质量报告重算、错误响应和认证边界。
- `audit_intraday_history.audit`：10 项机器检查通过，37 个冻结源码哈希全部保持不变；归档重复复核一致。见 [机器验收 JSON](data/M6-intraday-history-acceptance.json)。
- 机器验收 SHA-256：`66288c3d8370ef3e2a6c41c7c080b32bdc8c18ea603ef084b6657c55ee18d22f`。
- `git diff --check` 与暂存检查通过，提交后工作区干净。

## 复现

在 `../source` 运行以下离线验收命令；输出文件必须使用新路径。

```powershell
python audit_intraday_history.py --archive ../1/data/M6-intraday-history-ETH-20260929 --manifest-sha256 67a7c7f9925695260be857f4289d5b3b80ef0ae0f39ba1662e186310090b88b8 --registration ../1/data/M6-restart-registration.json --registration-sha256 b2bc4ddbf455c86dd53911d3814c27bd61026d89104fe58fffe15a4b005ea6cd --output new-minute-acceptance.json
python -m unittest discover -s tests -q
```

## 保留依赖

此次采集仅覆盖 ETH 的一天交易价分钟行情，未补齐历史公告时点或多资产全期间覆盖。
OHLCV 不提供一分钟内路径、公告精确秒行情、队列或真实成交；不认证部分成交、滑点、费用、
实际持仓换算或历史规格。哈希证明采集后字节完整性，不构成交易所历史真实性签名。
未接入冻结未来执行器，未产生新假设测试结果，未来独立验证及 M7/M8/M9 依赖保留。

代码提交：`feature@2cf1243baeead4a470711efc988f530e247a1d1b`（本地提交，未推送）。
通过 GitHub 插件核对目标仓库 `huan00000/price`；计划、报告和真实归档位于仓库外的 `../1`。
