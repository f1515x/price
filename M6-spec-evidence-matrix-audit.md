# M6 规格证据矩阵验收

日期：2026-10-02（America/La_Paz）。负责人：Codex。
开始、预期完成、实际完成日期均为 2026-10-02。
完成 plan.md **4.2 第二项**：逐资产、逐覆盖期间列出五类规格字段的现有来源、原文、认证状态、缺口及冲突。

矩阵整理工程 **PASSED**；真实历史规格与 M6 策略均保持 **NOT_VALIDATED**。
覆盖分区不是已经证实的真实有效期间；未知的认证值、有效期起点和终点均保留为 null。

## 交付与范围

- [可读矩阵](data/M6-spec-evidence-matrix/matrix.md)：70 行逐资产、字段、期间记录，并列明 API 原文与公告短摘录。
- [机器矩阵](data/M6-spec-evidence-matrix/matrix.json)：来源 URL、原文 SHA-256、JSON 指针、UTF-8 字节偏移、观察值、缺口及差异。
- [机器复核](data/M6-spec-evidence-matrix-acceptance.json)：13 项检查全部通过。
- [构建工具](../source/build_spec_evidence_matrix.py)、[复核工具](../source/audit_spec_evidence_matrix.py)、[9 项新增测试](../source/tests/test_spec_evidence_matrix.py)。

本轮只读取已经保存的证据，未联网补取交易所资料、运行研究或评估未来收益。
固定依据为 [4.2 第一项范围清单](data/M6-evidence-scope.json)、
[规格观察台账](data/M6-spec-evidence-20261001/ledger.json)、
[真实审阅清单](data/M6-field-review-acceptance/real-review.json)、
[公告清单](data/M6-historical-notices/notices.json)及新登记。
构建工具固定这些输入哈希，重新验证归档快照、原始响应和公告摘录，构建前后复核全部输入。

| 覆盖对象 | 分区与字段 | 行数 | 认证覆盖 |
|---|---|---:|---:|
| BTC 历史 | [2020-01-01, 2026-10-01) × 五字段 | 5 | 0 秒 |
| ETH 历史 | 同一历史窗口按两份公告精确秒拆成三段 × 五字段 | 15 | 0 秒 |
| BTC/ETH 未来 | 原登记五个连续 365 日窗口 × 两资产 × 五字段 | 50 | 0 秒 |

五字段为乘数、数量步长、最小张数、价格 tick、最大张数。
ETH 分区边界为 **2025-10-18 08:00:00 UTC** 和 **2026-03-24 02:00:00 UTC**。
所有区间均为 UTC 秒半开区间，每个资产/字段/目标窗口完整分区且无重叠。
历史训练、隔离与测试都落在固定历史总范围内，不把重复研究分区计为额外证据。
未来日期沿用原登记，未修改协议、参数或评价时点。

## 来源与缺口结论

两资产各有两次 API 响应观察，均晚于历史窗口终点。
矩阵保留接收时点、原始响应、字段原文和字节绑定，不向前或向后推定真实有效期。
BTC 数量步长 `1` 是 `enable_decimal=false` 的当前整数模式映射假设，原响应没有显式数量步长字段；
ETH `enable_decimal=true`，步长仍未知，不能把最小张数 `0.1` 当作数量步长。

两份 ETH 公告只提供 tick `0.05 → 0.01` 与最小张数 `1 → 0.1` 的变更事件。
来源仍为已归档短摘录，完整原文、独立发布时间、发行方/字段语义认证和完整有效区间均未补齐。
公告的生效时点用于拆分补证范围，不将 before/after 值填作整段历史或未来的认证值。
BTC 没有已归档公告边界，不代表 BTC 从未变更规格。

ETH 两次响应的最小张数分别为 `0` 与 `0.1`，保留 **1 项未解决观察差异**。
它们来自不同接收时间及请求口径背景，现有证据未证明真实变更时点或差异原因。
零最小张数不能用于需要正数的执行规格。此差异不是已证实的同一有效期间规格冲突。

真实区间审阅清单仍为空，所以已登记区间主张冲突为 0；
**不能据此宣称实际规格没有冲突**。所有 70 行仍保留认证缺口。
既有合成声明、人工主张标签、订单/部分成交/乘数换算回放及测试通过均不增加真实认证覆盖。

## 验证与复现

新增 9 项测试覆盖公告精确边界、半开端点、资产/字段隔离、未来不外推、
异值审阅冲突、同值十进制等价、合成/观察主张不提供覆盖、输入不变、原文字节绑定和固定输入篡改拒绝。
全量 `python -m unittest discover -s tests -q` **419 项通过**。

13 项机器复核验证重复生成一致、可读与机器矩阵一致、全资产/字段/期间分区完整、
70 行库存、原文哈希/字节绑定、零认证值/期间、真实空审阅、步长不推断、差异保留、
公告不外推、未来未知、原登记与 37 个冻结源码不变、策略与执行不升级。
构建输出为全新目录，验收输出为新文件；拒绝覆盖已有证据。
另以实际命令复核已有输出拒绝覆盖且哈希不变；临时伪造首行认证值/覆盖秒数被机器复核判为 FAILED。
计划与验收报告中的本地链接均已核对存在。

矩阵 JSON SHA-256：`c2f39e24f247992893aa4a0de6be223c57307cabd72d8f6b9c9b2fcb272acc1c`。
在 `../source` 复现，使用不存在的新路径：

```powershell
python build_spec_evidence_matrix.py --evidence-root ../1 --output-dir ../1/data/M6-spec-matrix-new
python audit_spec_evidence_matrix.py --evidence-root ../1 --matrix-dir ../1/data/M6-spec-matrix-new --output ../1/data/M6-spec-matrix-new-acceptance.json
python -m unittest discover -s tests -q
```

通过用户指定 GitHub 插件核对远端 [feature 分支](https://github.com/huan00000/price/tree/feature)，
当时远端提交为 `ac297797266aec33e6888ae040a69d83498816ae`。
开发在本地 `../source` 的 feature 分支完成，源码提交 `68154bcbc47452c067a1275e4d6bd58b5c23cf05`，未推送远端。
此前存在的未跟踪 `build_evidence_scope.py` 原样保留。

## 阻塞与下一步

矩阵整理无阻塞，已交付；真实认证缺完整历史公告/规格原文、有效期间、语义真实性，
ETH 小数数量步长及观察差异解释，未来期间证据须继续观察。
这些缺口仍属于后续补证与认证，不以矩阵完成替代 KR2.1 达成。

下一步为 **4.2 第三项：建立行情与成交证据矩阵**。
仅勾选本项；4.2 其余未交付项、4.3 真实认证、M6 NOT_VALIDATED 和 M7/M8/M9 依赖保持原状态。
