# E5 持续研究数据采集调度

2026-10-01 后续 E7 已在当前 Windows 主机启用每日系统任务；安装、停用及登录要求见 [每日任务说明](DAILY_COLLECTION_TASK.md)。下文“不自动安装”和归档验收边界描述 E5 采集器本身。

`collection_scheduler.py` 定时获取 Gate USDT 永续已收盘 UTC 日线，依次复用 E1～E4 保存历史、指标、结构及七条既有研究规则的离线候选决策。使用独立根目录，不修改原入口。

```powershell
python collection_scheduler.py --root ..\1\data\daily-collection --start 2024-01-01 --symbols BTC ETH
python collection_scheduler.py --root ..\1\data\daily-collection --start 2024-01-01 --symbols BTC ETH --watch
```

默认每天 UTC 00:05 后采集前一天及之前的日线（America/La_Paz 前一天 20:05），每 60 秒检查到期；失败后下一次检查重试，成功后等待下一日。前台进程 Ctrl+C 退出，不自动安装 Windows 服务或任务。也可由外部任务计划程序每天运行一次第一条命令；单次失败返回非零退出码。进程必须保持运行，或由外部调度启动；本次验收没有开启长期常驻采集。

固定 `--start` 保留完整指标和结构初始化历史；停机多日后一次抓取覆盖遗漏日期，不逐日补造过去的实时决策。Gate 每页不超过 1,000 天，网络请求有 30 秒超时。`--close-delay` 默认 300 秒，范围 0～86399；`--poll-seconds` 范围 1～60。指标窗口、结构长度、tail/move/stretch 可显式配置，默认与 E4 一致。改变参数保留独立版本，不登记新假设。

根目录保存 `research.sqlite`、不可变 `snapshots/`、原子替换的 `state.json` 以及追加的 `cycles.jsonl`。周期绑定 UTC 截止时间、参数及 11 个源码哈希；每阶段保存快照/运行 ID、行数及版本。相同日期复用并重验原始快照，重跑数据库构建不会重复写入；失败保留已完成阶段供重试。阶段各自事务提交，跨阶段不做总事务；失败状态不可当作完整周期。质量不足仍完整保存并标记 `INSUFFICIENT_DATA`，`COMPLETE` 只表示管道全部成功，不能表示数据足够或策略有效。

`collector.lock` 通过排他创建阻止同根目录重叠运行；进程正常退出/异常会删除锁。断电或强制结束可能遗留锁，须确认没有对应进程后手动移除。请始终让同一采集任务使用同一个根目录，并避免其他程序并发修改数据库、证据或源码。不完整/篡改的快照拒绝覆盖，需先保留调查证据再换新根目录恢复。

研究参考结构回放为平方级计算，固定起点的每日完整版本会持续增加耗时与存储；本期没有增量 SMC 算法、保留期删除、服务安装或可用性承诺。停机后的历史采集也不能充当实时影子日志。原始响应及质量报告仍是证据，数据库无防篡改签名。

候选始终保留 `NOT_VALIDATED`、`execution_authorized=false`，评分/结构分位 N/A。基础假设仍 `TERMINATED`，M6 验收及 M7/M8/M9 依赖不变。

运行测试：`python -m unittest discover -s tests`。新增测试验证收盘延迟、多标的全链路、重启幂等、停机补采、阶段/网络失败恢复、锁、篡改拒绝、缺口保留及调度到期重试。

完整可复核验收使用已验证的真实归档响应，经注入网络边界重放；没有冒充当前行情或实时运行。验收目录须为新路径：

```powershell
python audit_collection_scheduler.py --root ..\1\data\E5-recheck ..\1\data\BTC-20240101-20250301 ..\1\data\ETH-20240101-20250301
```

交付 `../1/data/E5-collection/acceptance.json`、同目录数据库、快照、周期日志及状态。另有 `transport-smoke.json` 记录真实公共 HTTP 接口两根历史日线的连接检查；它仅证明本次请求成功，不证明长期在线运行。
