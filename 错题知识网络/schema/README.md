# 数学一 LLM Wiki Schema

本目录规定 AI 如何在数学一系统中维护三层结构：

1. raw sources：原始资料层，只读，不由 AI 修改。
2. wiki：AI 维护的 Markdown 综合知识层。
3. schema：本目录规则层，规定 ingest、query、lint 的流程和边界。

## 与现有 wrongnet 的关系

- `错题知识网络/错题卡/*.md` 仍是错题源数据。
- `错题知识网络/生成/` 仍是 `wrongnet.py rebuild` 的派生输出，不手改。
- wiki 层只沉淀概念、方法、专题、错因模式、易错触发条件，不替代正式错题卡。
- 方法卡 ID 仍以 `错题知识网络/方法论库/method_card_registry.md` 为准。
- 回滚复习仍以 `数学一回滚复习系统/复习单元.json` 和 `scheduler.py` 为准。

## 入口文件

- `karpathy_llm_wiki.md`：Karpathy LLM Wiki 模式在数学错题系统中的落地规则。
- `page_template.md`：wiki 页 frontmatter 和正文模板。
- `decision_matrix.md`：什么时候只写 wiki、什么时候需要错题卡、什么时候需要 rebuild。
- `ingest.md`：导入资料流程。
- `query.md`：基于 wiki 回答并沉淀高价值分析的流程。
- `lint.md`：wiki 体检流程。
- `relationship_signal_policy.json`：关系评分中的粗/泛信号、证据边界、推断知识点和执行模式机器可读策略。
- `marginnote_visual_import.md`：MarginNote 4 题图、解析图和解析文字迁移到 Obsidian 可视化错题详情层的流程。
- `../../数学一回滚复习系统/schema/wrongnet_targeted_upsert.md`：正式错题卡按当前 ID 定点创建或更新长期复习单元的证据、幂等、调度和原子写入合同。

## 默认维护原则

以后数学资料整理默认不是一次性总结，而是 LLM Wiki 增量维护：先确认 raw source，只读；再更新 source summary、概念、方法、专题、错因、触发、综合或待调查页面；最后更新 `wiki/index.md` 和 `wiki/log.md`。正式错题卡仍按 wrongnet 规则单独处理。

正式错题卡也要进入 LLM Wiki 覆盖层：每一张 `错题卡/*.md` 都应有轻量 source summary，并在 `wiki/sources/SRC-WRONGCARDS-INDEX_全量错题卡覆盖索引.md` 中登记处理状态。

正式卡需要进入长期回滚时，先对当前 ID 运行 `upsert-wrongnet --dry-run`，再实际执行；复发加 `--expect-recurrence`。不得为当前题使用全库 `sync-wrongnet`，也不得把当天即时纠错通过记成长期延迟成功。

同时，每张正式错题卡应进入多维 wiki 投影：

- knowledge：`wiki/topics/knowledge_clusters/MATHWIKI-KNOWLEDGE-INDEX_知识点簇索引.md`
- methods：`wiki/methods/method_clusters/MATHWIKI-METHOD-INDEX_方法簇索引.md`
- error_causes：`wiki/error_patterns/error_clusters/MATHWIKI-ERROR-INDEX_错因簇索引.md`
- method_gap：`wiki/methods/action_gap_clusters/MATHWIKI-ACTION-GAP-INDEX_method_gap动作断点索引.md`

`method_gap.evidence_origin` 是个人错因回流的来源门禁：`user_confirmed` 表示用户作答证据直接确认，`model_inferred_from_solution` 表示仅从题面或解析推导复做入口，`pending_user_confirmation` 表示仍待用户确认。正确解析路线、宽泛知识点和占位文本不得冒充个人真实错因。历史卡缺少该字段时由读取层标记为 `legacy_unclassified`，不批量猜测迁移。
- coverage matrix：`wiki/coverage/MATHWIKI-COVERAGE-MATRIX_错题卡多维编译矩阵.md`

这些索引型页面让 Obsidian 能看到全量错题被编译到哪些维度；它们不替代人工沉淀的正式概念页、方法页、专题页、错因模式页和触发页。

## MarginNote 可视化详情层

`错题知识网络/可视化错题详情/` 是独立视觉层，用于把 MarginNote 4 导出的题图、解析图和解析文字转成 Obsidian 可直接查看的单题详情页。该层可以保存完整视觉材料，但不得替代或污染 `错题卡/*.md`。

默认格式优先级：

1. `.oo3`：主结构源。
2. `docx`：辅助校验源。
3. 脑图 PDF：可选视觉校验。

只更新视觉详情层、`wiki/index.md` 或 `wiki/log.md` 时，不运行 `wrongnet.py rebuild`。
