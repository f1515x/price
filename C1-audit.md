# C1 会话凭据配置迁移验收

日期：2026-10-01（America/La_Paz）。来源：`plan.md` 第 4.3 节尚未处理的会话 cookie 事项。

## 交付范围

完成当前源码中的凭据配置迁移，原会话撤销及 Git 历史清理继续作为独立待办。
通过 GitHub 插件核对目标仓库为 `huan00000/price`，本地 remote 一致。
在 `../source` 的 `feature` 分支提交，提交为 `1c2c74ec2be9c99787995eb8d3831a79182c4215`，未推送。

- `month.py` 删除个人会话、设备及跟踪 cookie 常量，默认匿名访问 scanner。
- 可选环境变量 `TRADINGVIEW_COOKIES_JSON` 每次查询时读取，要求合法 cookie 名及非空字符串值。
- 空配置表示匿名；格式错误在请求前抛出不含配置内容的 `ValueError`。
- cookie 通过 CookieJar 设置 scanner 域、根路径及 secure 标记。
- GitHub Actions 计算步骤读取同名可选 repository secret；未配置时为空，不阻止匿名查询。
- 添加 `.env.example`、`.env` 忽略规则、配置说明及 7 项离线测试。
- 原函数签名、标的标准化、15 秒超时、HTTP 错误传播、月涨跌幅返回单位及原阈值输出保留。

## 验证证据

在 `../source` 执行 `python -m unittest discover -s tests -v`：54 项全部通过，包含原有 47 项与新增 7 项。
新增覆盖匿名请求、运行时读取与域限制、非法配置拒绝且错误不含测试值、缺失结果、HTTP 错误、标的校验与 CLI 阈值行为。

移除当前验证进程内的 cookie 环境变量后，实际调用 `month.get_month_performance('BTC')`：
`anonymous_query=PASS; numeric_result=True`。未使用原个人会话，未输出 cookie 值。
这仅证明验收时匿名查询成功，不保证接口永久允许匿名访问。

`git diff --cached --check` 通过；`git check-ignore .env .env.local` 均命中，`.env.example` 未忽略。
代码提交后工作区仅剩此前已有的 `trade_simulation.py` 及 `tests/test_trade_simulation.py` 未跟踪文件，未修改或纳入本次提交。

## 留存边界

本次仅删除当前源码凭据，Git 旧提交仍可能包含原值。
未登录 TradingView 验证或撤销原会话，未重写历史、强制推送、创建 secret 或触发远程流程。
账户侧失效需账户所有者完成，历史清理需单独安排；上述两项继续记录为未完成。
未改动交易规则，不将本次查询验证解释为策略有效性验证。
