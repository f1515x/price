# 历史 cookie 脱敏副本

`sanitize_history.py` 完成 C2 的本地历史清理与可复核副本交付。它不撤销账户会话，也不修改原仓库或 GitHub 历史。仅定位所有本地 refs 可达的历史 `month.py` 中已知会话、设备和跟踪 cookie 字面量；不是通用 secret 扫描器。

```powershell
python -m pip install git-filter-repo==2.47.0
python sanitize_history.py . ..\1\data\C2-new-sanitized.git
python -m unittest discover -s tests -v
```

输出必须是原仓库外的新目录。使用 `git clone --mirror --no-local` 建立独立裸仓库，无硬链接或 alternates。替换所有导出的 blob、提交和 tag 消息中的已知字面量，保持提交图、空提交与退化合并；全部本地 refs（含 remote-tracking refs）参与改写。移除副本的 remote 配置、清空 reflog 并同步 GC，随后扫描全部实际存储对象（包括不可达对象）验证已知值零残留。`git fsck`、refs 覆盖、提交数量与当前 `feature` tree 一致性全部通过后才输出 `sanitization-audit.json`。若当前 feature tree 会被脱敏改变，工具拒绝给出通过报告。

实现使用 [git-filter-repo 官方 API 与历史改写选项](https://github.com/newren/git-filter-repo/blob/main/Documentation/git-filter-repo.txt)。`--partial` 仅用于保留 remote-tracking refs 的名称；显式遍历 `--all`，之后主动清理 reflog/不可达对象并扫描。`--force` 仅作用于本次创建的副本。

敏感值仅在内存和子进程 stdin 中传递，不写规则文件、不进入命令参数或日志。报告只含计数、cookie 键名、对象 ID 与 refs 映射。失败副本不得用于发布；原仓库仍可保留旧值。原始仓库、远端独有 refs、PR refs、缓存、其他克隆与账户会话均不在本地副本清理范围内。

副本内 `filter-repo/commit-map` 保存旧新提交映射。当前 feature tree 保持一致，原有研究输入/源码文件哈希不变，但提交 ID 会变化。后续远端清理须核对届时远端 refs，安排账户会话撤销与协作者同步后另行执行；此工具没有 push 功能，不能用本地 PASS 声称远端已清理。

运行历史清理验收测试需要上述固定版本的工具；日常交易/研究运行不需要它，因此不加入运行时 `requirements.txt`。
