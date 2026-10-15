# 本文档为4象限的任务清单，全文书写大白话

## 想做：
- 完成 issue #12：修复 Actions 提交报告时远端分支有新提交导致推送失败的问题，提交 PR 并用远端 Checks 验证。
- 完成 issue #10：订单展示和入库增加合约乘数、价格步长，提交 PR 并用远端 CI 验证。
- 审阅本次修复 PR；合并前确认凭证表和订单表权限，已有订单附加列允许省略写入。

## 做完：
- 2026-10-15：issue #12 已增加报告提交脚本，每次基于远端最新提交完整替换三个生成文件，保留远端代码，普通推送最多尝试三次；同一分支工作流改为排队。已补充六项临时 Git 仓库回归测试，等待远端 Checks 验证。
- 2026-10-15：issue #10 已完成并关闭，PR #11：https://github.com/f1515x/price/pull/11 保持未合并。提交 6859de8 的远端 Checks 已通过：https://github.com/f1515x/price/actions/runs/38689441552；未进行本地编译或测试，未改动真实数据库。
- 2026-10-15：issue #10 已增加价格步长获取函数，单份合约参数复用于仓位计算和展示；上传解析新增两个参数并保留数字字符串，兼容旧报告和只有时间戳的报告。
- 2026-10-15：订单 SQL 支持首次建表和重复升级，两个新列使用 numeric；README、架构说明和回归测试已更新。30 个 Python 文件 AST 静态语法检查及 git diff --check 通过，未执行本地编译或测试。
- 2026-10-15：PR #9 提交 0938267 的远端 Checks 已通过：https://github.com/f1515x/price/actions/runs/38682623850，PR 说明已同步验证结果。未执行本地编译或测试。
- 2026-10-15：已基于最新 main 提交并推送 fix-remove-contracts-table，创建修复 PR #9：https://github.com/f1515x/price/pull/9。README 已补充 PR #8 版本的升级办法，架构图已补齐订单上传，PR 保持未合并。
- 2026-10-15：按用户要求删除 PR #8 的 contracts 表读写、上传前参数补齐、建表 SQL 和相关测试；凭证 SQL 独立为 docs/supabase_secret.sql，继续保留现有 secret 凭证读取。
- 2026-10-15：精度报告和仓位计算改用 Gate 公开合约接口，保留数字字符串、实际价格步长和多空张数规则。订单恢复直接上传报告中的六个字段，订单 SQL 不再添加乘数和步长列，README 和架构说明已同步。
- 2026-10-15：已调整远端 CI 用的回归测试，覆盖不访问合约数据库、参数校验、真实步长换算、正常订单和仅时间戳上传。38 个 Python 文件的 AST 静态语法检查及 git diff --check 通过；未执行本地编译或测试。
- 2026-10-15：已创建 PR #8：https://github.com/f1515x/price/pull/8；代码提交 0ee8d4a 的远端 Checks 已通过：https://github.com/f1515x/price/actions/runs/38679231902。按 issue 要求关闭 #6，PR 保持未合并。
- 2026-10-15：补齐 orders 的 quanto_multiplier 和 order_price_round 写入；上传前读齐并校验对应合约参数，读取失败保留旧订单。已更新 SQL、README 和远端回归测试，AST 静态语法检查及差异检查通过，未进行本地编译或测试。
- 2026-10-14：按用户要求撤回最近一次 yml 配置集中调整及配套 README 说明，关闭未合并的 PR #7。issue #6 的实现保留在 feature 分支，issue 仍打开；未进行本地编译或测试。

- 2026-10-14：补查迁移脚本，已有 Orders3 secret 表保留原权限，只为新建凭证表设置服务端读取权限，避免影响原有客户端。

- 2026-10-14：代码提交 d5c2d3e 的远端 Checks 已通过：https://github.com/f1515x/price/actions/runs/38677785215。

- 2026-10-14：已推送 feature-issue-6-supabase-contracts 并创建 PR #7：https://github.com/f1515x/price/pull/7。PR 写有 Closes #6，合并后自动关闭 issue；目前保持 issue 打开。

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
- 本次修复尚未合并，未改动真实数据库中的表和列。
- 未执行真实 Supabase 迁移、账户查询或通知；上线前按需执行 docs/supabase_sizes.sql 和 docs/supabase_secret.sql，准备唯一凭证记录和服务端权限。

- 按仓库约定，不做本地构建、编译或会触发编译的测试，也不连接真实数据库做删除验证。
- 未合并 PR。

## 在做：
- 2026-10-15：已读取 issue #12 的失败日志，业务步骤均成功，最后 git push 因 main 已更新而被拒绝。正在修改报告提交步骤并补充并发更新回归测试；不做本地编译或测试。
