# 历史规格官方公告短摘录与变更事件

M6-R11 完成历史官方公告的检索、短摘录归档与变更事件复核。两份实际来源：

- [Gate ETH 价格步长公告 47661](https://www.gate.com/announcements/article/47661)：
  2025-10-18 08:00 UTC，ETH_USDT 价格步长从 0.05 改为 0.01。
- [Gate 最小下单张数公告 50325](https://www.gate.com/announcements/article/50325)：
  2026-03-24 02:00 UTC，ETHUSDT 最小下单张数从 1 改为 0.1。

直接 HTTPS 下载返回 403；已通过网页工具打开官方公告并核对日期、表头和 ETH 行。
归档每份最多 25 个词的短摘录，标为 `WEB_TOOL_SHORT_EXCERPT`，保留官方 URL、
查看时间（UTC）、来源行位置、UTF-8 字节定位及 SHA-256。摘录由不同原文行组成，
不是完整网页，也不是交易所原始 HTTP 响应。`retrieved_at` 是本次来源查看记录时间；
验收工具只从已核对的摘录重建归档，不重新访问网站。

`historical_notices.build(manifest, blobs, destination)` 拒绝覆盖已有目录。
`verify(destination, expected_sha256)` 固定清单哈希后重核摘录和字段映射，拒绝路径逃逸、
域名伪装、重复 JSON 键、无变化事件、同资产同字段同时间冲突、无时区/无效日期、
未来事件、伪造完整覆盖或认证字段。字段含义和时间解析仍是明确记录的审阅判断，
精确摘录匹配仅证明字节绑定，不能机器认证网页发行者或语义。

事件保留 `effective_timestamp` 和 `intraday_boundary`，不推定前后完整有效区间，
不延展新值直到未来测试末日，不把 `min_quantity` 自动认定为 `quantity_step`。
两次生效时间都在日内；不能静默取整为 UTC 日界后交给日线模拟。
不生成执行参数；`historical_specs_verified=false`、`verified_coverage_seconds=0`、
`acceptance_status=NOT_VALIDATED`。完整原文、后续修订/撤销、BTC 证据、其他字段、
真实性认证、账户费用及未来独立验证仍有缺口。

复核已有归档（输出文件不得已存在）：

```powershell
$noticeHash = (Get-FileHash ..\1\data\M6-historical-notices\notices.json -Algorithm SHA256).Hash.ToLower()
python historical_notices.py ..\1\data\M6-historical-notices --expected-sha256 $noticeHash --output notice-verification.json
```

重建独立验收到新目录，登记哈希从已固定的 M6-R10 验收读取：

```powershell
$registrationHash = (Get-Content -Raw ..\1\data\M6-joint-execution-acceptance.json | ConvertFrom-Json).registration_sha256
python audit_historical_notices.py --destination new-notice-archive --registration ..\1\data\M6-restart-registration.json --expected-registration-sha256 $registrationHash --output new-notice-acceptance.json
python -m unittest discover -s tests -q
```

固定哈希应独立保存；从同一可能被改动的清单重新计算哈希不能证明该清单可信。
原登记、冻结执行器与 M7/M8/M9 依赖保持原状态。
