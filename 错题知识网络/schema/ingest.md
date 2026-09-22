# ingest 流程

ingest 用于导入一份数学资料，提取知识点、方法、错因、触发条件，并决定是否只写 wiki、先记候选，或进入两阶段正式错题流程。学习中的当前单题入库不执行本 schema 的全量预读；它直接路由到 `kaoyan-math-wrong-intake` 的 fast capture，成功后立即返回学习。

## 预读

资料型 `wiki-only` / `candidate-card` ingest 和夜间正式收口前读取：

1. `错题知识网络/schema/decision_matrix.md`
2. `错题知识网络/schema/karpathy_llm_wiki.md`
3. `错题知识网络/schema/page_template.md`
4. `错题知识网络/wiki/index.md`
5. `错题知识网络/wiki/log.md`
6. `错题知识网络/README.md`
7. `错题知识网络/AI维护规则.md`
8. 相关 raw source 或错题卡

## index/log 检索式访问

- `wiki/index.md` 不通读：新条目写在文件头部；日常先读头部最近约 100 行，再按 `wiki_id`、错题编号、来源 ID、关键词用 `rg` 定向检索。
- `wiki/log.md` 不通读：新条目写在文件尾部；日常先读尾部最近约 200 行。更早历史按月份进入 `wiki/log_archive/YYYY-MM.md`，需要时再按日期或关键词检索。

## 抽取内容

从输入中抽取：

- 概念：定义、适用条件、易混点。
- 方法：题面触发、应想到的方法、第一动作、检查点。
- 错因模式：知识缺口、触发遗漏、方法调取失败、动作链断裂、条件检查遗漏、收尾验证遗漏。
- 易错触发条件：看到什么结构时容易误判。
- 关联：知识点标签、错题 ID、方法卡 ID、原始来源。

## 资料类型路由

| 输入类型 | 默认处理 | 需要升级的条件 |
|---|---|---|
| 讲义、截图说明、视频笔记、NotebookLM 导出 | `wiki-only`，沉淀概念、方法、触发条件 | 出现具体用户错题且用户要求复做召回 |
| ChatGPT/Codex 讨论 | `wiki-only` 或 `candidate-card` | 讨论中包含题目摘要、明确错点、可确定知识点 |
| 旧错题批量原始资料 | `candidate-card`，先登记来源和缺失信息 | 单题字段足够且用户确认正式入库 |
| 已有错题卡复盘 | 只更新 wiki 总结或候选页 | 用户明确要求改卡，且改动不编造事实 |
| 学习中的当前新错题入库请求 | `fast-capture` | 夜间批次收口，或用户明确要求“立即完整正式入库” |

## 决策

按 `decision_matrix.md` 判断：

- `wiki-only`：只更新 wiki/index/log，不运行 `wrongnet.py rebuild`。
- `candidate-card`：记录候选错题，不擅自建卡。
- `fast-capture`：由 `kaoyan-math-wrong-intake` 只追加不可变快速事件，返回 `pending_nightly`。不查读全套 wiki，不分配正式 ID，不改卡，不运行 rebuild、回滚或 Wiki 同步。
- `formal-card`：只由夜间批次或用户明确要求“立即完整正式入库”触发。必须基于已有 capture，通过 `pending` 和 freeze 固定证据，再查重、判断复发或合并、改写正式卡。多题批次完成全部卡后只做一次成功 rebuild，然后统一完成 bridge、回滚、必需的 Wiki、visual 和每目标答案安全教学切片，最后提交 closeout-v3；Tutor 只在适用时可选同步，不属于 closeout 门禁。明确的立即完整入库使用同一合同的 batch-size-one，不得绕过 capture、freeze 或 teaching context。单题处理后不默认输出同类旧题；旧题由用户在学习结束后显式触发统一筛选。
- `rollback-unit`：只有用户明确要求或符合回滚规则时，才对当前正式 ID 使用 `scheduler.py upsert-wrongnet --id`；正式复发必须加 `--expect-recurrence`。`add` 只处理非错题型手工 D0 单元，`sync-wrongnet` 只处理显式历史批量补建。
- `method_gap.evidence_origin`：只能写 `user_confirmed`、`model_inferred_from_solution` 或 `pending_user_confirmation`。缺少用户作答、第一错步或明确复发证据时，不得写 `user_confirmed`；仅有解析路线时必须保留为模型推导或待确认。

## 可复制操作单

1. 确认输入来源：写出 `source_refs`，不要改 raw source。
2. 确认当前任务是 `wiki-only`、`candidate-card`、`fast-capture`、`formal-card` 还是 `rollback-unit`。只有资料 ingest 和正式收口读取本页的预读集；`fast-capture` 不做全量预读。
3. 先判断是否需要 source summary；新来源默认需要，已有来源则更新已有 summary。
4. 抽取概念、方法、错因模式、触发条件、知识点标签、错题 ID、方法卡 ID。
5. 把抽取结果接入已有 wiki 页；能更新旧页时优先更新旧页，不为同一概念重复建页。
6. 若是 `wiki-only`：新建或更新 `wiki/` 页面，按检索式访问规则更新 `wiki/index.md`，追加 `wiki/log.md`，结束。
7. 若是 `candidate-card`：只在 `wiki/index.md` 的 `candidate_card` 或相关 wiki 页中登记，不建正式卡。
8. 若是 `fast-capture`：仅核对当前题的来源、真实作答、第一断点与已有评分引用，通过稳定临时 JSON 调用 `quick_intake.py record`；收到 `pending_nightly` 后立即结束，用户可继续下一题。
9. 若是 `formal-card`：从 `pending` 取权威目标，在正式写入前复用或创建 freeze，再读 `录入模板.md`、相关旧卡、`知识点库.md` 和方法论库；按真实题目聚合 capture，查重命中时更新旧卡，不重复建卡。
10. 按录入模板完成本批全部正式卡，然后只运行一次成功的 `python3 错题知识网络/scripts/wrongnet.py rebuild`，再完成 bridge、定点回滚、必需的 Wiki、visual 和每目标 teaching context 校验，最后提交 closeout-v3。Tutor 仅在适用且不会阻塞收口时可选同步，不属于 closeout 门禁。回滚先对对应 ID 运行 `upsert-wrongnet --dry-run`，核对后再实际执行；复发时加 `--expect-recurrence`。任何正式目标缺少、过期或错误绑定的教学切片都必须阻止 closeout；失败不得改用全库同步绕过，capture 保持 pending 并按原 freeze 重试。

## 正式错题卡的 wiki 覆盖

每一张 `错题卡/*.md` 都必须被视为 LLM Wiki 的 raw source，并生成轻量 source summary：

- 位置：`错题知识网络/wiki/sources/wrong_cards/SRC-WQ-{ID}.md`
- 总索引：`错题知识网络/wiki/sources/SRC-WRONGCARDS-INDEX_全量错题卡覆盖索引.md`
- 覆盖表：`错题知识网络/wiki/coverage/MATHWIKI-COVERAGE-001_错题卡全量覆盖索引.md`
- 多维矩阵：`错题知识网络/wiki/coverage/MATHWIKI-COVERAGE-MATRIX_错题卡多维编译矩阵.md`
- 知识点簇：`错题知识网络/wiki/topics/knowledge_clusters/MATHWIKI-KNOWLEDGE-INDEX_知识点簇索引.md`
- 方法簇、错因簇、动作断点簇：分别由 `methods`、`error_causes`、`method_gap.action_gap_type` 生成，用来暴露可继续深度编译的模式。
- source summary 只抽取标题、科目、章节、知识点、错因、方法、陷阱、method_gap、关联 wiki 和待编译去向。
- 不复制完整题干和长解析。
- 新增或更新正式错题卡后，必须同步新增或更新对应 source summary，并刷新全量覆盖索引、知识点簇、方法簇、错因簇、动作断点簇和多维矩阵。

## 写入规则

- raw source 只读，不改写。
- wiki 页只写综合结论，不保存完整长解析。
- 夜间或明确立即完整收口修改 `错题卡/*.md` 后，必须在本批全部卡完成后只运行一次成功的：

```bash
python3 错题知识网络/scripts/wrongnet.py rebuild
```

- 只修改 `wiki/`、`schema/`、`wiki/index.md`、`wiki/log.md` 时，不运行 rebuild。

## 只读样本测试

- 样本来源：`错题知识网络/知识树/高等数学18讲第16讲_无穷级数.md`。
- 判断：既有知识树是 wiki 种子内容，没有新增用户做错的一道题。
- 决策：`wiki-only`。
- 允许动作：登记到 `wiki/index.md`，在 `wiki/log.md` 记录 ingest。
- 禁止动作：不新建错题卡，不修改知识树原文，不运行 rebuild。

## 日志

每次 ingest 在 `wiki/log.md` 追加：

```markdown
## YYYY-MM-DD ingest SOURCE_ID

- input:
- source_refs:
- wiki_created:
- wiki_updated:
- card_decision:
- wrongnet_rebuild:
- rollback_action:
- missing_info:
```
