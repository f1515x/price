# 日线模拟的公告变更执行政策

M6-R12 完成日内规格变更的拒绝执行政策及联合情景模拟接入。
`notice_execution.simulate_notice_joint` 接收原 `simulate_joint` 的输入，另要求
`notice_archive` 和独立固定的 `notice_sha256`。公告、审阅规格、日期成本和
逐结算价格仍须分别固定哈希；没有默认公告清单或自动发现机制。

政策使用 UTC 半开窗口 `[start, end)`，只检查本次标的和窗口内的公告事件：

- 日内变更：返回 `INTRADAY_CHANGE_UNRESOLVABLE_WITH_DAILY_BARS`，包含准确生效秒、
  所在日桶和公告事件 ID。联合参数加载及模拟开始前抛出 `NoticePolicyError`，
  不取整日期、不跳过该日、不删除信号、不根据 OHLC 猜测成交时刻。
- UTC 日界变更：必须有完整的联合执行规格；核对生效时点之后的字段值，
  若生效日不是窗口起点，同时核对前一秒的字段值。冲突阻止模拟；单独检查
  没有规格映射时返回 `DAILY_SPECIFICATION_MAPPING_REQUIRED`。
- 窗口终点或范围外事件不推定有效期间。政策 `PASSED` 只表示给定公告清单
  未发现上述阻断项，不能证明没有遗漏公告、完整历史覆盖或历史真实性。

抛出的 `NoticePolicyError.report` 可审计。成功模拟保存 `daily_notice_policy`，
每笔成交保存 `notice_manifest_sha256`。模拟返回前重核公告清单、摘录和政策，
三类联合声明继续由原联合执行器重核。所有报告保留 `NOT_VALIDATED`、
`historical_specs_verified=false` 和零认证覆盖。

单独检查归档（没有日界规格映射时只输出阻断报告；阻断退出码为 2）：

```powershell
python notice_execution.py ..\1\data\M6-historical-notices --expected-sha256 e05867d17b1c461875f97b3c329aaad6a2b1b721483f2b195ae74eb9113d94e6 --symbols ETH --start 1760745600 --end 1760832000 --output notice-policy.json
```

复现验收到新目录，`--expected-prior-sha256` 使用独立保存的 R11 验收哈希：

```powershell
python audit_notice_execution.py --destination new-policy-inputs --previous ..\1\data\M6-historical-notices-acceptance.json --expected-prior-sha256 <pinned-prior-sha256> --registration ..\1\data\M6-restart-registration.json --archive ..\1\data\M6-historical-notices --output new-policy-acceptance.json
python -m unittest discover -s tests -q
```

该政策只接入新的离线情景包装器。既有联合模拟可独立使用；冻结未来执行器
和 37 份登记源码未改动。支持日内交易需要更细粒度数据、持仓/订单变更政策及
完整认证规格，仍是后续任务。
