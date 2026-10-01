# Windows 每日研究采集任务

安装后每日 UTC 00:05（America/La_Paz 前一天 20:05）及当前用户登录时运行 E5，BTC/ETH 起点固定为 2024-01-01。隐藏窗口、最低权限，不保存密码；**仅在该用户登录期间执行**。错过运行后允许补跑，登录触发也会补采停机期间日线。

```powershell
.\install_daily_collection.ps1 -Python (Get-Command python).Source -Root E:\git\0AAimportant\price\1\data\daily-collection
schtasks.exe /Run /TN Price-Research-Daily
schtasks.exe /Query /TN Price-Research-Daily /V /FO LIST
```

安装器拒绝覆盖同名任务。任务失败每 15 分钟重试，最多 3 次；同一任务不重叠运行，最多运行 2 小时。采集器还使用目录锁；强制终止可能遗留锁，确认对应进程已结束后再处理。根目录必须独立且固定。源码升级会产生新的研究版本。

`deployment.json` 和 `scheduled-task.xml` 保存安装配置，`task-output.log` 保存每次开始、采集结果及退出码，`state.json`、`cycles.jsonl` 和 SQLite 保存管道审计记录。任务退出码 0 及状态 `COMPLETE` 只证明一次管道运行成功。完整数据口径和存储增长限制见 [E5 使用说明](COLLECTION_SCHEDULER.md)。

停用或删除任务：

```powershell
schtasks.exe /Change /TN Price-Research-Daily /Disable
schtasks.exe /Delete /TN Price-Research-Daily /F
```

删除任务保留研究数据。不要在采集运行时删除数据或锁。部署不构成 M8 影子运行，策略仍为 `NOT_VALIDATED`，基础假设仍为 `TERMINATED`，不执行交易。
