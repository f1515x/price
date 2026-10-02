# M6-R17 多资产统一窗口分钟行情采集与覆盖复核验收

日期：2026-10-01。原任务：plan.md 4.1 M6 多资产精细行情覆盖中的批量采集与指定窗口覆盖复核子项。

工程结果 `PASSED`；M6 策略仍 `NOT_VALIDATED`。

## 交付与真实数据

新增批量采集器与离线验收命令，复用 M6-R16 原始一分钟归档通路。
资产共用 UTC 半开窗口及收盘判断时点，逐资产保存原始响应与固定清单哈希，
顶层清单固定完整资产库存及覆盖报告。复核重新读取原始响应，逐资产重建分钟线和
质量统计；完整覆盖验收还核对冻结登记资产库存与源码。失败保留原始证据，
不生成顶层清单；缺失/未收盘归档明确报告不完整。使用方式见
[INTRADAY_BATCH.md](../source/INTRADAY_BATCH.md)。

真实公开 API 采集范围为 2026-09-28 00:00 至 2026-09-30 00:00 UTC：

| 资产 | 原始响应页数 | 已收盘分钟线 | 缺失 | 未收盘 | 质量问题 |
|---|---:|---:|---:|---:|---:|
| BTC_USDT | 3 | 2,880 | 0 | 0 | 0 |
| ETH_USDT | 3 | 2,880 | 0 | 0 | 0 |

合计 5,760 个资产分钟，`quality_status=COMPLETE`。
[真实归档清单](data/M6-intraday-batch-20260928-30/batch.json) SHA-256：
`265b9cd30f35d596246874c1d9a4c8d9b85b5cc0117d5d9f06e5b2701a2e6333`。

## 验证

- `python -m unittest discover -s tests -q`：385 项通过，新增 11 项覆盖逐资产完整性、规范化重复资产、缺失、未收盘、失败证据保留、拒绝覆盖、顶层/子归档改写、重新固定哈希后的库存/窗口/统计伪造、登记资产缺项、登记改写和不完整覆盖验收拒绝。
- 9 项批量与 20 项逐资产机器检查通过；37 个冻结源码哈希保持不变，登记固定哈希保持不变。重复离线复核一致。
- [机器验收 JSON](data/M6-intraday-batch-acceptance.json) SHA-256：`b75087a99f5b2c3aa86138701c09caca771164a7b8dbb85c0096b0744d8adfe8`。
- `git diff --check` 与暂存检查通过。

## 复现

在 `../source` 运行，验收输出须使用新路径：

```powershell
python audit_intraday_batch.py --archive ../1/data/M6-intraday-batch-20260928-30 --batch-sha256 265b9cd30f35d596246874c1d9a4c8d9b85b5cc0117d5d9f06e5b2701a2e6333 --registration ../1/data/M6-restart-registration.json --registration-sha256 b2bc4ddbf455c86dd53911d3814c27bd61026d89104fe58fffe15a4b005ea6cd --output new-batch-acceptance.json
python -m unittest discover -s tests -q
```

## 保留依赖

仅证明指定两天的 BTC/ETH 分钟观察覆盖与归档完整性，不代表多资产全历史覆盖。
该窗口未补齐两份历史公告的精确秒行情。OHLCV 无法证明分钟内路径、队列、
实际成交、滑点、账户费用、持仓换算或历史规格真实性，哈希也不构成交易所签名。
未修改冻结未来执行器，未将已暴露窗口用作新假设测试；未来独立验证和 M7/M8/M9
依赖继续保留。

通过 GitHub 插件核对目标仓库 `huan00000/price`；计划、报告、真实归档及验收 JSON
保存于仓库外的 `../1`。代码提交：`feature@33435e9702b92ff18c96ce0e270a8c4c223e3233`（本地提交，未推送）；提交后源码工作区干净。
