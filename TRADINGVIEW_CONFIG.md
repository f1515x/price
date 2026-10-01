# TradingView 查询配置

`month.get_month_performance(base_asset)` 默认匿名请求公开 scanner 接口。
源码不再包含个人会话、设备或跟踪 cookie，调用方式、15 秒超时与月涨跌幅百分数返回值保持不变。

如运行环境确实需要会话，可通过进程环境变量 `TRADINGVIEW_COOKIES_JSON` 提供 JSON 对象，键和值必须是非空字符串。
每次查询读取当前环境，空值或未设置表示匿名请求；格式错误会在网络请求前失败，错误信息不包含配置内容。
cookie 只发往 HTTPS 的 `scanner.tradingview.com`。

本地 PowerShell 可用以下虚构值示例设置格式，替换为自己的有效配置后运行：

```powershell
$env:TRADINGVIEW_COOKIES_JSON = '{"sessionid":"example-only","sessionid_sign":"example-only"}'
python month.py BTC
Remove-Item Env:TRADINGVIEW_COOKIES_JSON
```

不要把真实值写入源码、命令截图或验收报告。`.env` 与 `.env.*` 已加入忽略规则；
`.env.example` 只提供变量名。`month.py` 不自动加载 `.env`，需要由调用进程注入环境。
现有 Gate API 的 `.env` 加载方式保持不变。

GitHub Actions 的计算步骤已接入同名可选 repository secret `TRADINGVIEW_COOKIES_JSON`。
未配置 secret 时使用匿名请求；不需要创建 secret 才能启动现有流程。

本次迁移只移除当前源码中的凭据。旧提交仍可能包含旧值，原会话失效需要账户所有者在 TradingView 完成，
历史清理需要单独协调 Git 历史重写。不能将本次改动视为已撤销原会话或已清理历史。
