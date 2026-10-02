# M1：历史日线、质量检查与 30 日收益

完成日期：2026-09-30。代码位于 [history.py](../source/history.py)，测试位于 [test_history.py](../source/tests/test_history.py)。通过 GitHub 插件确认项目为 huan00000/price；本次交付保存于本地，未推送远端。

## 数据口径与实现

使用 Gate USDT 永续普通成交价日线，显式指定 `1d / utc0`。请求按最多 1000 日分页，采用 `[start, end)` 日期区间，不混用 limit 和 from/to。来源：[Gate 官方合约行情文档](https://www.gate.com/docs/developers/apiv4/en/futures/)。该文档定义时间戳为 Unix 秒，v 为合约张数，OHLC 为报价货币价格。当前实现不覆盖股票、现货及传统市场交易日历。

时间戳按 UTC 日桶起点处理，只有 `t + 86400 <= as_of` 才保留。所有数据必须对齐 UTC 午夜。原始响应和获取时点保存在快照中，便于检查供应商修订。

现场验证：在 Unix 秒 1790818597 查询当日日线，返回 t=1790812800，恰为当日 UTC 午夜且该日尚未结束，支持桶起点解释；这根数据将被未收盘检查排除。

- 保存 raw.json、daily.csv、quality.json，包含市场、标的、周期、来源、参数版本、请求分页、采集时点和 SHA256。
- 每次获取写入新目录，拒绝覆盖旧快照；失败请求直接报错，不冒充成功或替换旧数据。落盘中途失败的目录若缺少完整报告不能加载。
- 同值重复保留一条；数值冲突重复使该日失效。异常时间戳、非有限值、非正价格、负成交量、非法高低价及未收盘线均记录原因。
- 按请求范围报告缺失日；不插值、不前填，不删除真实极端行情。
- 收益为 `Close(t)/Close(t-30)-1`，以小数保存。要求 31 个连续有效日线；缺口后重新预热，未就绪输出空值及 INSUFFICIENT_DATA。
- 最近连续且覆盖截至时点的有效日线达到 396 根才标记研究数据 READY；这只说明 M2 的基础样本数量就绪，不代表结构、信号或策略有效。
- `load_snapshot()` 校验文件哈希并使用原获取时点重建，加载不依赖网络，也不受以后当前时间变化影响。

## 可复现操作

在 `E:\git\0AAimportant\price\source` 执行：

```powershell
python -m unittest discover -s tests -v
python history.py BTC --start 2024-01-01 --end 2025-03-01 --output ..\1\data\BTC-new-snapshot
python -c "from history import load_snapshot; rows, report = load_snapshot('../1/data/BTC-20240101-20250301'); print(len(rows), report['research_status'])"
```

输出目录必须尚不存在。更长窗口或补齐缺口时重新指定完整日期范围并写新快照；当前没有增量数据库合并和自动重试。

## 验收结果

实际样本：[BTC 日线 CSV](data/BTC-20240101-20250301/daily.csv)、[质量报告](data/BTC-20240101-20250301/quality.json)、[原始响应](data/BTC-20240101-20250301/raw.json)。范围 2024-01-01 至 2025-02-28（含），425 根连续已收盘日线，395 个有效 30 日收益；缺失 0、质量问题 0，研究数据状态 READY。CLI 已执行落盘后的校验和重建加载。

8 项 unittest 全部通过，覆盖分页和空页、非法时间戳及排序、重复与冲突、异常 OHLCV、未收盘边界、缺失后预热、收益公式与未来数据独立性、重复加载及文件损坏检测。运行环境 Python 3.14.4，只使用标准库。旧交易模块未改动。

仅验证 BTC 样本和采集通路，不声称已完成整个历史币池、下架资产覆盖、M2 指标或回测；真实事件研究仍需扩充数据并处理幸存者偏差。30 日收益是本地代理口径，不等同 TradingView Perf.1M。
