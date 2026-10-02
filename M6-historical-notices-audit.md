# M6-R11：官方历史规格公告取证与变更事件复核

日期：2026-10-01（America/La_Paz）。完成 plan.md 4.1 M6 中历史规格证据获取的
**两份官方公告短摘录取证子项**。不表示完整历史有效规格或真实性认证已完成。

通过用户指定 GitHub 插件确认 `huan00000/price` 仓库可访问；本地 `feature` 开发，提交 `c158d7cb0ed798a30b7c2b6277effa6e312eb161`，未推送。
工程验收 **PASSED**，M6 策略验收仍 **NOT_VALIDATED**。

实际取得的变更信息：

| 来源 | 字段 | 生效时间 UTC | 变更 |
|---|---|---|---|
| [Gate 公告 47661](https://www.gate.com/announcements/article/47661) | ETH price_tick | 2025-10-18 08:00 | 0.05 → 0.01 |
| [Gate 公告 50325](https://www.gate.com/announcements/article/50325) | ETH min_quantity | 2026-03-24 02:00 | 1 → 0.1 |

直接下载及多语言路径均返回 HTTP 403；网页工具成功打开官方页面并核对公告。
保存的是标明传输方式的少量原文摘录，不是完整 HTML、原始 HTTP 响应或搜索摘要。
归档时间为 2026-10-02 01:39:39 UTC，即本地 2026-10-01 21:39:39。
每个事件保存原文日期、表头及 ETH 行的精确 UTF-8 字节位置，字段映射和理由由审阅者记录。

交付：[模块](../source/historical_notices.py)、[说明](../source/HISTORICAL_NOTICES.md)、
[复核工具](../source/audit_historical_notices.py)、[测试](../source/tests/test_historical_notices.py)、
[机器验收](data/M6-historical-notices-acceptance.json)、
[真实短摘录清单](data/M6-historical-notices/notices.json)。

验证：新增 **12 项测试通过**；**9 项机器检查通过**，两份真实公告事件、
摘录字节绑定、日内边界、未推定有效期终点、零认证覆盖、未生成执行参数、
NOT_VALIDATED、37 个冻结源码与原登记不变均通过。
全量 **313 项测试通过**（运行 20.893 秒）。

这次取得了先前真实空审阅清单之外的实际公告证据。公告表达一次变更，不能据此
证明此前从何时起有效、之后无修订/撤销，或未来测试窗口仍适用。尤其最小张数
不能自动充当数量步长。没有把短摘录注入旧审阅清单，没有制造日界有效区间，
没有运行模拟或调整既有冻结假设。

剩余：完整原文与发行方/语义认证、BTC 与其他规格字段、完整有效期间、日内调整
执行政策、认证执行接入、真实账户成本与独立未来策略验证。M6、M7/M8/M9 依赖不变。
