# 离线候选样本量与数据可信度

只读审计 E4 数据库中显式指定的单资产、运行版本、规则和 UTC 日桶范围。

```powershell
python candidate_quality.py --database ..\1\data\E4-candidates.sqlite BTC --run-id RUN_ID --output quality.json
python candidate_report.py --database ..\1\data\E4-candidates.sqlite BTC --run-id RUN_ID --format quality-json --output quality.json
```

`--start` 包含起始日，`--end` 不包含结束日。范围裁剪到源快照的已收盘期间，空范围输出零计数，历史样本量 min/max 输出 null。候选表格命令自动附带样本摘要；CSV 保留 E6 原格式。

报告分别列出日历覆盖天数、有效日线观测数、缺失日桶、共同可用/不可用观测数、未触发数、原始候选日线数、指标历史观测数量范围、质量问题及去重事件起点数。无时间戳的原始数据问题只能报告整个源快照的数量，不能假装归属于查询区间；预热不足与缺失 K 线分别统计。

默认去重间隔 30 日，与 M4 的最大事件观察期限一致，可通过独立命令的 `--dedup-days` 显式调整。按整个运行版本时间顺序贪心保留首个候选，之后所有方向候选至少相隔该间隔，再过滤报告范围。查询起点之前的事件继续影响去重，不能因裁剪报告而制造新事件。返回保留事件的时间戳和方向，便于审计；不同资产、规则和重叠版本的计数不能直接相加。

去重事件数仅是间隔约束下的信号起点数量，不证明统计独立性，不评估前向标签是否完整，不是成交数或业绩。`independent_sample_count` 和 `trades` 为 null。M6 的 `NOT_VALIDATED` 与执行未授权状态继续保留。

生成摘要前重新校验原始历史文件哈希、质量计算、源快照身份、SQLite 历史数据和完整候选 payload 哈希。输出保存输入、候选输出及实现哈希。数据库以只读模式访问；输出文件拒绝覆盖。审计需要原始快照文件仍在原位置，读取整个运行版本及原始文件有相应时间和内存成本。
