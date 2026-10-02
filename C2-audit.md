# C2：Git 历史 cookie 本地脱敏副本验收

日期：2026-10-01（America/La_Paz）。来源：`plan.md` 第 4.3 节“会话失效及历史清理”待办。完成其中可独立验收的本地历史清理副本；账户失效、原工作仓库及 GitHub 历史清理继续待办。

通过用户选择的 GitHub 插件读取 `huan00000/price` 元数据，核对 remote 指向同一公开仓库。在 `../source` 的 `feature` 分支提交 `ccd81ae40eb75dc57c7b9aa8bedba83c8d6938d0`，未推送；工作区干净。

## 交付

- [清理工具](../source/sanitize_history.py)、[操作说明](../source/HISTORY_SANITIZATION.md)、[验收测试](../source/tests/test_sanitize_history.py)。清理依赖 `git-filter-repo==2.47.0`，已安装；交易研究运行依赖不变。
- 独立裸仓库：`data/C2-sanitized-20261001.git`，覆盖运行时本地全部 5 个 refs，HEAD 为 `feature`。
- [机器审计](data/C2-sanitized-20261001.git/sanitization-audit.json)、[旧新提交映射](data/C2-sanitized-20261001.git/filter-repo/commit-map)。机器审计记录所有 refs 的原 ID 和脱敏后 ID，不包含 cookie 值。

历史 `month.py` 共 2 个 blob；从旧字典提取 7 个会话/设备/跟踪键、5 个不同敏感字面量（部分键共用值）。不输出原值，不向交易网站验证旧会话，也不把普通短值如主题或 consent 设置作为全局替换规则。

独立 `--mirror --no-local` 克隆后，清理所有导出 blob、提交及 tag 消息中的已知值。保留提交图、提交数量和 refs 名称；移除副本 remote 配置，主动清空 reflog、同步 GC，再扫描副本中全部实际存储对象，包括不可达对象。

## 实际验证

| 检查 | 结果 |
|---|---|
| 原仓库对象扫描 | 304 commit、348 tree、475 blob；1 个 blob 命中已知值 |
| 脱敏副本全部存储对象扫描 | 304 commit、348 tree、475 blob；已知值命中 0 |
| 本地 refs 名称覆盖 | 原/副本均 5 个，集合相同 |
| 提交数量 | 原/副本均 304，不裁剪空提交 |
| 当前 feature tree | 原/副本均 `7d9d0892072f81f9b5cde0358387695f5f1c681a` |
| 原仓库 refs | 清理前后完全一致 |
| 副本完整性 | `git fsck --full --no-reflogs` 通过，无 remote，无 alternates |
| 全套离线测试 | 113 项通过，含 3 项新增历史清理验收测试 |
| 变更检查 | `git diff --cached --check` 通过 |

新增测试使用虚构值，覆盖分支、tag 消息、commit 消息、改名二进制文件、remote-tracking ref、副本零残留、源码未变、报告不含值，以及拒绝已有/嵌套输出、未发现值和过短字面量。

清理后 `feature` 提交为 `9b95b03b6f8fd56d4540d7b3c1a0ab88d19efb9c`。仅提交 ID 改变，当前所有跟踪文件的 Git tree 完全一致；研究输入、报告和源码内容没有因清理改变。

## 保留边界

结论为 `LOCAL_SANITIZED_MIRROR_VERIFIED`，不等同完整凭据事件处置完成。原 `../source` 仍保留旧历史，GitHub 分支、独有 refs/PR refs、缓存和其他克隆均未改写，账户会话未撤销。工具只保证识别出的已知字面量在副本全部 Git 对象中零残留，不证明不存在其他秘密。

没有强制推送或替换原仓库。后续远端改写须核对当时远端状态、账户会话处置与协作者同步，不能直接拿本地 remote-tracking 快照覆盖远端。此子任务不改变 `M6 NOT_VALIDATED` 或当前假设 `TERMINATED`，也不解除 M7/M8 依赖。
