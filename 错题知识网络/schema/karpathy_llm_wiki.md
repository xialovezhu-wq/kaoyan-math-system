# Karpathy LLM Wiki 对齐规则

本文件把 Karpathy 的 LLM Wiki 模式落到数学一错题系统中。以后凡是数学系统里的资料整理、错因综合、方法沉淀、专题复盘、Obsidian 导航和 Dashboard 数据整理，都默认按本规则执行，除非用户明确要求正式错题入库。

参考来源：<https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f>

## 核心差异

传统 RAG 是每次提问时从 raw sources 重新检索和拼接。数学一 LLM Wiki 的目标不是临时检索，而是把每次导入、查询和复盘都编译成可持续维护的 Markdown 知识库。

因此，AI 每次工作后要判断是否留下可复用痕迹：

- source summary：这份来源说了什么、可信度和边界是什么。
- concept page：一个数学概念、条件或定义如何复用。
- method page：看到什么题面信号，应触发什么第一动作。
- topic page：一组错题或知识点如何形成专题。
- knowledge cluster page：按正式错题卡 `knowledge` 字段自动聚合的索引型 topic，用于覆盖全量错题，但不等于深度概念页。
- method cluster page：按正式错题卡 `methods` 字段自动聚合的索引型 method，用于发现高频方法入口，但不等于深度方法页。
- error cluster page：按正式错题卡 `error_causes` 字段自动聚合的索引型 error，用于发现高频错因模式，但不等于深度错因页。
- action gap cluster page：按正式错题卡 `method_gap.action_gap_type` 自动聚合的索引型动作断点，用于发现方法链缺口，但不等于完整错因判断。
- coverage matrix：逐题检查 source、knowledge、method、error、method_gap 是否都有可追踪 wiki 入口。
- error pattern page：反复出现的错因模式是什么。
- trigger page：哪些题面信号容易诱发错误。
- synthesis page：跨来源、跨错题、跨专题的稳定综合结论。
- question page：尚未解决、需要继续查证或补资料的问题。

## 数学系统三层

### raw sources

只读证据层，包括：

- `错题知识网络/错题卡/*.md`
- `错题知识网络/知识树/*.md`
- `错题知识网络/方法论库/`
- `高数讲义/`
- `线代讲义/`
- `概率论讲义/`
- `kaoyan_math_project_v2/`
- `错题知识网络/批量导入/原始文件/`
- 用户提供的截图说明、视频笔记、ChatGPT/Codex 讨论、NotebookLM 导出

raw sources 不由 AI 修改。正式错题卡虽然是 wrongnet 源数据，但对 LLM Wiki 来说也属于只读证据；只有用户明确进入错题入库或更新卡片流程时，才按 wrongnet 规则修改。

### wiki

AI 维护的 Markdown 编译层，位置为 `错题知识网络/wiki/`。

wiki 不是报告归档，也不是错题卡替代品。它必须具备可浏览、可反链、可持续更新的结构。每个稳定页面都应尽量包含：

- frontmatter：`wiki_id`、`type`、`title`、`status`、`last_updated`
- 来源引用：只写路径、页码、链接或错题 ID
- 双链：使用 Obsidian `[[...]]` 指向相关 source summary、概念页、方法页、专题页
- 可复用结论：避免只写一次性总结
- 待确认项：缺信息时写 `待确认`，不编造

索引型簇页采用子索引规则：总 `wiki/index.md` 只登记这些入口索引，具体簇页由对应子索引托管。

- `MATHWIKI-KNOWLEDGE-INDEX_知识点簇索引.md` 托管 `MATHWIKI-KNOWLEDGE-###`。
- `MATHWIKI-METHOD-INDEX_方法簇索引.md` 托管 `MATHWIKI-METHOD-CLUSTER-###`。
- `MATHWIKI-ERROR-INDEX_错因簇索引.md` 托管 `MATHWIKI-ERROR-CLUSTER-###`。
- `MATHWIKI-ACTION-GAP-INDEX_method_gap动作断点索引.md` 托管 `MATHWIKI-ACTION-GAP-###`。

lint 时不要把这些自动簇页逐条缺总 index 视为错误，但要检查它们是否被对应子索引覆盖，并检查 `MATHWIKI-COVERAGE-MATRIX_错题卡多维编译矩阵.md` 是否存在。

正式错题卡 source summary 和覆盖表要区分两类链接：

- `cluster_wiki`：知识点簇、方法簇、错因簇、action_gap 簇，表示该题已经进入全量索引型知识图谱。
- `deep_wiki`：正式概念页、方法页、专题页、错因模式页、触发页或综合页，表示该题已经进一步沉淀为可复用知识。

不要把 `cluster_wiki` 误报为深度编译完成；它只证明没有漏题，不能替代人工或半人工的高层综合页。

### schema

规则层，位置为 `错题知识网络/schema/`。每次操作前先读对应 schema：

- ingest：`ingest.md`、`decision_matrix.md`、本文件
- query：`query.md`、`decision_matrix.md`、本文件
- lint：`lint.md`、本文件

## 默认操作模式

### ingest

1. 先创建或更新 source summary。
2. 再更新相关概念、方法、专题、错因、触发页。
3. 如果出现新矛盾或旧结论被推翻，要在相关页写出冲突说明。
4. 更新 `wiki/index.md`。
5. 追加 `wiki/log.md`。

一个来源可以触达多个 wiki 页。不要只生成一个孤立摘要。

### query

1. 先读 `wiki/index.md`，再读相关 wiki 页。
2. 用 raw sources 作证据补充，不从 raw sources 每次重新发散。
3. 高价值答案要沉淀回 wiki：比较、方法总结、错因模式、专题综合、待调查问题。
4. 只要没有修改正式错题卡，就不运行 `wrongnet.py rebuild`。

### lint

定期检查：

- 是否有孤立页。
- 是否有 source summary 没有链接到概念/方法/专题。
- 是否有重要概念被反复提到但没有页面。
- 是否有断开的 `[[wikilink]]`。
- 是否有 index/log 不一致。
- 是否有 raw source 长期 `unprocessed`。
- 是否有 wiki 页面越界复制完整题干或长解析。
- 是否每张正式错题卡都有 `SRC-WQ-{ID}`、coverage 表、知识点簇入口和多维矩阵行。
- 是否方法簇、错因簇、动作断点簇有子索引托管；缺失标签只能标记为缺口，不允许由 AI 编造。

## 完成标准

数学一 LLM Wiki 不是一次性建完，而是进入可持续运行状态。当前阶段的完成标准是：

1. Obsidian 中存在清晰入口页。
2. index/log 可读、可维护、可被 AI 预读。
3. 至少有 source summary、overview、concept、method、topic、error pattern、trigger、synthesis、question/queue 类型页面。
4. 核心页面之间有双链，不是孤立报告。
5. raw/wiki/schema 边界清楚。
6. 正式错题卡、`生成/`、回滚 JSON 的保护规则清楚。
7. 后续每次 ingest/query/lint 都能沿着本规则继续增量维护。

满足以上条件后，系统才算从“兼容 LLM Wiki”进入“开始按 LLM Wiki 运行”。
