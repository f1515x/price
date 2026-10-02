# 多资产一分钟覆盖采集与复核

`intraday_batch.py` 使用已有一分钟原始归档通路，为明确的资产清单采集同一
UTC 半开窗口。所有资产共享采集开始时的 `as_of`，逐页原始响应和子清单哈希
保留在各资产目录，顶层 `batch.json` 固定资产清单、子清单哈希及覆盖报告。
已有目录拒绝覆盖；失败资产的原始响应与已完成资产保留，但不会生成顶层清单。
缺失或未收盘仍可归档，报告为 `INCOMPLETE_OR_ISSUES`，不能通过完整覆盖验收。

```powershell
python intraday_batch.py BTC ETH --start 1790553600 --end 1790726400 --output new-batch
python intraday_batch.py BTC ETH --start 1790553600 --end 1790726400 --output new-batch --verify-sha256 <独立固定的batch.json哈希>
python audit_intraday_batch.py --archive new-batch --batch-sha256 <固定哈希> --registration ../1/data/M6-restart-registration.json --registration-sha256 b2bc4ddbf455c86dd53911d3814c27bd61026d89104fe58fffe15a4b005ea6cd --output new-batch-acceptance.json
```

离线复核逐资产从原始字节重建分钟线和覆盖统计，校验资产身份、同一时间窗口、
安全目录名及固定子清单。验收还要求覆盖冻结登记的全部资产并重核冻结源码，
逐资产报告必须无缺失、无问题且全部已收盘。验收 JSON 使用新路径，拒绝覆盖。

覆盖以资产分钟计数，不能用一个资产的完整数据掩盖另一个资产的缺口。
`unclosed_minutes` 与已收盘但缺失的时间戳分开记录。
这是指定窗口的行情证据工程，不能据此认定全历史覆盖、秒级行情、实际成交、
费用或规格认证，也不产生策略检验结果。M6 保持 `NOT_VALIDATED`。
