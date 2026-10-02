# 一分钟真实行情归档

`intraday_history.py` 单独采集 Gate USDT 永续的交易价一分钟 OHLCV。
接口依据：https://www.gate.com/docs/developers/apiv4/en/futures/
接口最多返回 2000 点；本通路每页请求 1000 个分钟桶，不混用 limit 和 from/to。

```powershell
python intraday_history.py ETH --start 1790640000 --end 1790726400 --output new-eth-minute-archive
```

时间为 UTC epoch 秒，范围为 `[start,end)`，必须对齐分钟。
默认以采集开始时刻判断收盘，桶在 `t+60` 收盘。成交量为合约张数。
每页保留未经重新序列化的原始响应、请求 URL、参数及 SHA-256。
空页保留并报告缺失；错误响应保留原始字节但不会生成可验收清单。
已有目录拒绝覆盖，失败后重试须使用新目录。

价格保持 Decimal 字符串精度，不使用浮点数或进行舍入。非法 OHLCV、
未收盘、非分钟时间戳、页外数据均排除并输出质量问题。
相同重复只保留一条并标记问题；冲突重复使该分钟失效。

`verify(directory, expected_sha256)` 需要调用者独立固定 manifest.json 的哈希，
核对每页原始字节后重建分钟数据和质量报告；仅修改派生文件及其清单哈希仍不能通过。
清单哈希提供采集后的完整性追溯，不构成交易所签名或历史规格真实性认证。

`audit_intraday_history.py` 复核完整行情窗口及已预登记源码哈希，生成不可覆盖的验收 JSON。
报告继续保留 `NOT_VALIDATED`。一分钟 OHLCV 无法恢复同一分钟内成交顺序、
公告精确秒附近价格、队列、部分成交、实际滑点或账户费用，不能据此合成认证成交。
本通路不接入已冻结的未来执行器，也不使用该窗口作为新假设测试结果。
