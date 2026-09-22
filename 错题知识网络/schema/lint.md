# lint 流程

lint 用于检查数学 wiki 是否存在结构问题。默认只输出报告；只有用户明确要求保存报告时，才写入 `错题知识网络/wiki/lint_reports/YYYY-MM-DD.md`。

## 预读

每次 lint 前读取：

1. `错题知识网络/schema/lint.md`
2. `错题知识网络/schema/karpathy_llm_wiki.md`
3. `错题知识网络/schema/decision_matrix.md`
4. `错题知识网络/wiki/index.md`
5. `错题知识网络/wiki/log.md`
6. 全部 `错题知识网络/wiki/**/*.md`
7. `错题知识网络/生成/wrong_questions.json`
8. 必要的 `错题卡/*.md` frontmatter
9. `错题知识网络/方法论库/method_gap_schema.md`
10. `错题知识网络/方法论库/错因分类/考研数学错因分类_动作断点表.md`

## index/log 检索式访问

- `wiki/index.md` 不通读：新条目写在文件头部；常规 lint 先读头部最近约 100 行，再按 `wiki_id`、path、错题编号、关键词用 `rg` 定向检索。全量 index 解析只在专项全量 lint 时执行。
- `wiki/log.md` 不通读：新条目写在文件尾部；常规 lint 先读尾部最近约 200 行。更早历史按月份读取 `wiki/log_archive/YYYY-MM.md`。

## 检查项

- 孤立概念：没有 `wiki_refs`、`wrongnet_refs`、`method_card_ids` 的页面。
- 重复方法页：标题、触发条件、方法链高度相似。
- 知识点断链：`knowledge` 不在 `知识点库.md`、知识树或已有错题卡中出现。
- 错因描述不一致：与 method_gap 允许值或错因分类表冲突。
- `wiki_refs` 断链：引用不存在的 wiki ID。
- `wrongnet_refs` 断链：引用不存在的错题卡 ID。
- `method_card_ids` 断链：引用未登记的方法卡 ID。
- raw source 未处理：`index.md` 中 `status: unprocessed` 或 `needs_card_decision` 的来源。
- index/log 不一致：log 记录了创建或更新，但 index 没登记。
- 派生目录风险：发现 `错题知识网络/生成/` 被手工当源数据加工时，只报告，不继续加工。
- Karpathy 对齐：检查是否存在 source summary、overview、synthesis、question queue 和可反链导航；如果只有报告没有双链，标记为结构不足。
- 全量错题覆盖：检查每一张 `错题卡/*.md` 是否有 `wiki/sources/wrong_cards/SRC-WQ-{ID}.md`，并且是否登记到 `SRC-WRONGCARDS-INDEX_全量错题卡覆盖索引.md`。
- 知识点簇覆盖：`wiki/topics/knowledge_clusters/MATHWIKI-KNOWLEDGE-*.md` 属于索引型 topic 层，不要求逐条写入总 `wiki/index.md`，但必须被 `MATHWIKI-KNOWLEDGE-INDEX_知识点簇索引.md` 链接覆盖；缺子索引或子索引断链才算问题。
- 方法簇覆盖：`wiki/methods/method_clusters/MATHWIKI-METHOD-CLUSTER-*.md` 属于索引型 method 层，不要求逐条写入总 `wiki/index.md`，但必须被 `MATHWIKI-METHOD-INDEX_方法簇索引.md` 链接覆盖。
- 错因簇覆盖：`wiki/error_patterns/error_clusters/MATHWIKI-ERROR-CLUSTER-*.md` 属于索引型 error 层，不要求逐条写入总 `wiki/index.md`，但必须被 `MATHWIKI-ERROR-INDEX_错因簇索引.md` 链接覆盖。
- method_gap 动作断点覆盖：`wiki/methods/action_gap_clusters/MATHWIKI-ACTION-GAP-*.md` 属于索引型 action gap 层，不要求逐条写入总 `wiki/index.md`，但必须被 `MATHWIKI-ACTION-GAP-INDEX_method_gap动作断点索引.md` 链接覆盖。
- 多维矩阵覆盖：检查 `MATHWIKI-COVERAGE-MATRIX_错题卡多维编译矩阵.md` 是否按每张正式错题卡登记 source、knowledge、method、error、method_gap 状态。
- source summary 分层：检查 `SRC-WQ-{ID}` 是否区分覆盖入口、索引型簇页和深度编译页；`cluster_wiki` 不得被当作 `deep_wiki` 完成。

## 可复制操作单

1. 读取本文件、`decision_matrix.md`，按检索式访问 `wiki/index.md` 和 `wiki/log.md`。
2. 列出全部 `wiki/**/*.md`，跳过 `lint_reports/` 中旧报告。
3. 从 `wiki/index.md` 抽取所有 `wiki_id`、`path`、`wrongnet_refs`、`method_card_ids`、`source_id`。
4. 检查每个 index 路径是否存在，每个稳定 wiki 页是否被总 index 登记；`topics/knowledge_clusters/MATHWIKI-KNOWLEDGE-*.md` 只检查是否被 `MATHWIKI-KNOWLEDGE-INDEX_知识点簇索引.md` 登记。
5. 检查每个 `wiki_refs` 是否能在 index 或页面 frontmatter 中找到。
6. 检查 `wrongnet_refs` 是否存在对应 `错题卡/{ID}_*.md`，但不打开完整长解析。
7. 检查 `method_card_ids` 是否在 `方法论库/method_card_registry.md` 中登记；`待匹配` 不算断链，只算待补。
8. 检查 raw source 状态是否为允许值，`unprocessed` 和 `needs_card_decision` 输出为待处理。
9. 检查 `生成/` 是否被本次任务修改；若有，只报告为风险，不手改。
10. 对索引型簇页采用“index of indexes”规则：总 index 登记 `MATHWIKI-KNOWLEDGE-INDEX`、`MATHWIKI-METHOD-CLUSTER-INDEX`、`MATHWIKI-ERROR-CLUSTER-INDEX`、`MATHWIKI-ACTION-GAP-INDEX`，具体簇页由各自子索引登记。
11. 检查 `MATHWIKI-COVERAGE-MATRIX` 是否存在，并与 source summary、知识点簇、方法簇、错因簇、动作断点簇数量一致。
12. 检查全量覆盖索引是否同时有 `cluster_wiki` 和 `deep_wiki` 列，并且剩余深度编译数没有被索引型簇页冲掉。
13. 默认只在回复中输出报告；用户明确要求保存时才写 `wiki/lint_reports/YYYY-MM-DD.md`。

## wrongnet 边界检查

- `错题卡/*.md` 有改动时，必须确认是否运行 `wrongnet.py rebuild`。
- `生成/` 有改动但没有对应 rebuild 记录时，标记为高风险。
- `wiki/`、`schema/`、`operation_center/` 的修改不要求 rebuild。
- 回滚 JSON 有改动时，必须确认来自 `scheduler.py` 或用户授权；否则标记为高风险。

## method_gap 检查

- `action_gap_type` 只能来自 `method_gap_schema.md` 的允许值。
- `related_method_card_id` 必须能在 `method_card_registry.md` 中找到，或明确写 `待匹配`。
- 错因模式页不能把 `方法调取失败`、`条件检查遗漏`、`动作链断裂` 混写成互相替代的同义词。
- 若 wiki 页引用错因分类表，必须保留“动作断点”含义，不改成空泛学习建议。

## 只读样本测试

- 样本范围：`wiki/index.md`、`wiki/log.md`、`schema/*.md`、`wiki/operation_center/数学学习看板.base`。
- 预期：能发现未处理 raw source、候选专题、operation center 是否登记。
- 禁止：不写 `生成/`，不改错题卡，不更新回滚 JSON。

## 输出格式

```markdown
# YYYY-MM-DD wiki lint

## 高风险

- 待补充。

## 中风险

- 待补充。

## 低风险

- 待补充。

## 建议动作

- 待补充。
```
