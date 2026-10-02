# E7：Windows 长期研究采集任务部署验收

日期：2026-10-01。完成原计划 4.2 中“部署长期任务尚未启用”这一未完成项。在 `../source` 的 `feature` 分支开发，使用 GitHub 插件核对远端 `feature@ac297797266aec33e6888ae040a69d83498816ae`。本地代码提交 `5ccf6521aada3c67df2812bb30d0dfb3e3b4f9bb`，未推送。

## 已启用配置

- 当前主机 Windows 任务 `Price-Research-Daily` 已启用；每天 UTC 00:05（America/La_Paz 前一天 20:05），另在当前用户登录时触发补采。
- 仅当前用户登录期间执行，最低权限、隐藏窗口，无保存密码。错过日程允许补跑；固定 2024-01-01 起点补采停机遗漏日线。并非无人登录时也运行的 Windows 服务。
- 使用明确的 Python 绝对路径及源码工作目录；BTC、ETH 写入独立 [采集根目录](data/daily-collection)。失败每 15 分钟重试，最多 3 次；不重叠执行，运行上限 2 小时。安装器拒绝覆盖同名任务。
- [安装器](../source/install_daily_collection.ps1)、[执行器](../source/run_daily_collection.ps1)、[使用/停用说明](../source/DAILY_COLLECTION_TASK.md)、[独立复核](../source/audit_daily_collection.py)。

## 真实执行与核验

通过任务计划程序实际启动两次，均成功退出 0，最终启用且 Ready；任务 XML 与安装快照一致。首次 07:54:53～07:55:11，第二次 07:55:50～07:56:01（America/La_Paz，2026-10-01）。下次定时运行是当日 20:05。

Gate 公共 API 实际取得 BTC/ETH 各 1,004 根已收盘 UTC 日线，覆盖 2024-01-01 至 2026-09-30，缺失和质量问题均为 0。四层查询均与原始快照和独立重算逐行一致；各资产 609 行满足共同研究可用条件。七条规则决策并非独立事件或成交笔数。第二次运行八个资产/阶段版本均 `inserted=false`，新增 0 行；SQLite 完整性 `ok`、外键错误 0。

原有全套 **155 项测试通过**；`git diff --check` 通过。另验证重复安装被拒绝，未覆盖任务。首次日志因 PowerShell 编码差异产生混合编码，原日志保存为 `initial-task-output-mixed-encoding.log`；执行器已统一 UTF-8，第二次实际任务日志可正常读取。

证据：[机器验收](data/daily-collection/deployment-acceptance.json)、[安装配置](data/daily-collection/deployment.json)、[任务状态快照](data/daily-collection/task-status.json)、[实际任务 XML](data/daily-collection/live-task.xml)、[最新周期](data/daily-collection/state.json)、[周期日志](data/daily-collection/cycles.jsonl)、[执行日志](data/daily-collection/task-output.log)、[数据库](data/daily-collection/research.sqlite)。原始 HTTP 响应、日线和质量报告保存于同目录 `snapshots/`；机器验收保留输入及源码 SHA-256。

## 使用与边界

```powershell
schtasks.exe /Query /TN Price-Research-Daily /V /FO LIST
schtasks.exe /Change /TN Price-Research-Daily /Disable
schtasks.exe /Delete /TN Price-Research-Daily /F
```

删除任务保留研究数据。本报告证明部署启用与两次真实运行，不证明未来长期可用性；断电/强制终止可能遗留采集锁，须确认原进程结束后处理。每日完整回放的耗时与存储继续增长，未实现增量 SMC 或自动清理。证据为验收时点快照，后续每日运行会更新状态和日志；复核工具拒绝覆盖已有验收报告。

仅为 E5 研究管道部署，不构成 M8 原入口并排输出或实时影子运行。日志继续保留 `NOT_VALIDATED`、`execution_authorized=false`，评分/结构分位 N/A；基础假设仍 `TERMINATED`，M6 历史成本及有效性缺口不变，M7/M8/M9 依赖未解除。
