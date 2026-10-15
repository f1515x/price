# 本文档为4象限的任务清单，全文书写大白话

## 想做：
- 完成 issue #6：从 Supabase 读取 Gate 凭证，保存每个合约的乘数和下单价格步长，调整脚本、文档和远端测试。
- 完成 issue #4：只有时间戳的报告也先清空旧数据，再写入时间戳，其他订单字段填 null。

## 做完：
- 2026-10-14：已同步 price，远端已有名为 feature 的分支，改用 feature-issue-6-supabase-contracts 避免 Git 分支路径冲突。
- 2026-10-14：按 Orders3 的 secret 表和带等号的列名读取 Gate 凭证，不再读取 Gate 环境变量或 Actions Secrets；读取失败立即终止，错误信息不包含凭证内容。
- 2026-10-14：precision 按合约名保存乘数、下单价格步长和最大杠杆，原样保存数字字符串；仓位计算改读数据库，按实际步长处理价格后换算张数。
- 2026-10-14：已补充数据库脚本、迁移说明和离线回归测试；feature push 不发布真实报告，保留 main 和手动运行的完整业务流程。
- 2026-10-14：Python AST 静态语法检查和 git diff --check 通过，未运行本地编译或测试，也未连接真实数据库、账户或发送通知。

- 已从 GitHub 同步 price 仓库，并创建 feature/issue-4-timestamp-only 分支。
- 已确认旧代码会跳过只有时间戳的报告，这是旧订单残留的原因。
- 已修改解析逻辑：只有时间戳时生成一条订单字段全部为 null 的记录，沿用先删除、后插入的流程。
- 已补充只有时间戳、带 none 的时间戳、空报告、错误报告以及命令行先删除再插入的回归测试。
- 已更新 README，说明没有订单时如何替换旧记录，以及订单字段需要允许 NULL。
- 已通过 Python AST 静态语法检查和 git diff --check，未运行项目代码。
- 首次推送因远端已有 feature 分支而命名冲突，改用 feature-issue-4-timestamp-only 分支继续推送。
- 已推送 feature-issue-4-timestamp-only 分支。
- 已创建 PR #5：https://github.com/f1515x/price/pull/5，尚未合并。
- 已按用户要求关闭 issue #4：https://github.com/f1515x/price/issues/4。
- 远端 Checks 已通过，包含新增回归测试：https://github.com/f1515x/price/actions/runs/38012403632（代码提交 9ba8ec7）。

## 没做：
- 按仓库约定，不做本地构建、编译或会触发编译的测试，也不连接真实数据库做删除验证。
- 未合并 PR。

## 在做：
- 2026-10-14：issue #6 代码和文档已完成，正在提交 PR 并等待远端 CI；合并后再关闭 issue。
- 无，推送、创建 PR、关闭 issue 和远端测试结果记录均已完成。
