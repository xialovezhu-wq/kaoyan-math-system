# query 流程

query 用于基于数学 wiki 和现有错题网络回答问题，并把高价值分析沉淀为 wiki 页。

## 预读

每次 query 前读取：

1. `错题知识网络/schema/query.md`
2. `错题知识网络/schema/karpathy_llm_wiki.md`
3. `错题知识网络/schema/decision_matrix.md`
4. `错题知识网络/wiki/index.md`
5. 相关 wiki 页或种子页
6. 必要时读取 `错题知识网络/生成/wrong_questions.json`
7. 必要时运行只读查询：`wrongnet.py related` 或 `wrongnet.py knowledge`

## index/log 检索式访问

- `wiki/index.md` 不通读：新条目写在文件头部；先读头部最近约 100 行，再按 `wiki_id`、错题编号、来源 ID、关键词用 `rg` 定向检索。
- `wiki/log.md` 不作为 query 默认预读全文；如需操作历史，先读尾部最近约 200 行，更早历史查 `wiki/log_archive/YYYY-MM.md`。

## 回答规则

- 优先基于 wiki、知识树、方法论库和错题卡轻量信息回答。
- raw source 只作依据，不复制长解析。
- 如果回答只是一次解释，不默认入错题卡。
- 输出错题、相似题、复做题、可视化详情或 wiki/source 索引时，优先输出能从 Codex 直接跳到 Obsidian 的链接。对已有 `GS/LA/PR/MX-*` 编号且桥服务可用的题，优先使用 `http://127.0.0.1:8765/open/{编号}`；没有桥映射但能定位 vault 内 Markdown 时，使用 `obsidian://open?vault=kaoyan-math&file=...`；不能定位到 Obsidian note 时，才使用本地文件链接并标明只能本地查看。
- 如果回答形成稳定方法、专题或错因模式，更新对应 wiki 页并记录 log。
- 如果回答形成跨多个来源的稳定判断，优先更新 `wiki/synthesis/` 或 `wiki/questions/`，让探索结果继续积累。
- 如果发现具体错题需要入库但缺少用户错因、日期、题目摘要或知识点，记录为 `candidate-card`。
- 学习结束统一筛题只在用户显式触发时运行，例如用户说“学习结束”“今天错题复盘”“根据今天输入的题筛题”“筛今天最值得复做的题”；单题入库后不默认输出同类旧题复做推荐。数据入口：`python3 错题知识网络/scripts/intake_recommend.py --date YYYY-MM-DD --seed-id GS-902 --seed-id LA-910`；seed 只来自用户指定集或本次学习中已经完成入库的 formal IDs，不扫描全库 touched 卡。筛选标准与输出格式以 `AI维护规则.md` 的「学习结束统一筛题」和「复做推荐输出格式」为准。

## 查询路由

| 问题类型 | 优先读取 | 可选动作 | 禁止动作 |
|---|---|---|---|
| 概念解释 | `wiki/concepts/`、知识树、`知识点库.md` | 沉淀概念页 | 复制讲义长段落 |
| 方法比较 | `wiki/methods/`、方法论库、`method_card_registry.md` | 沉淀方法页或专题页 | 伪造方法卡 ID |
| 按方法模式查题 | `wiki/methods/method_clusters/MATHWIKI-METHOD-INDEX_方法簇索引.md`、相关方法簇页 | 输出轻量错题清单，必要时升级正式方法页 | 把自动方法簇当成完整方法论 |
| 相似题召回 | `wrongnet.py related`、`wrongnet.py knowledge`、`wrong_questions.json` | 输出轻量旧题回顾 | 修改 `生成/` 或绕过 wrongnet |
| 学习结束统一筛题（显式触发） | 本次学习中已完成入库或用户指定的 formal IDs、`intake_recommend.py --date ... --seed-id ...`（单题补查用 `--id`）、`wrongnet.py related`/`knowledge`、`wrong_questions.json` | 跨指定 seed 综合筛出最值得复做的旧题，每道带日期/次数/来源号/原因 | 未显式触发时主动输出复做清单；扫描全库 touched 卡推测 seed；修改 `生成/` 或运行 rebuild |
| 错因模式 | `wiki/error_patterns/`、`method_gap_schema.md`、错因分类表 | 沉淀错因模式页 | 把未确认错因写进正式卡 |
| 按错因或动作断点查题 | `wiki/error_patterns/error_clusters/MATHWIKI-ERROR-INDEX_错因簇索引.md`、`wiki/methods/action_gap_clusters/MATHWIKI-ACTION-GAP-INDEX_method_gap动作断点索引.md` | 输出错因簇或动作断点簇，必要时升级正式错因/触发页 | 用 action_gap_type 替代具体 wrong_point |
| 知识树挂载 | `知识树/*.md`、`wiki/index.md` | 记录 wiki 链接或候选挂载 | 移动或重命名知识树 |

## 可复制操作单

1. 先把用户问题归类为概念、方法、相似题、错因模式、知识树挂载或混合问题。
2. 读取 `query.md`、`decision_matrix.md`，按检索式访问 `wiki/index.md`，并读取相关 wiki/种子页。
3. 若需要相似题，先查 wiki 覆盖层、知识点簇、方法簇、错因簇和动作断点簇；必要时再运行只读查询：`wrongnet.py related ID` 或 `wrongnet.py knowledge 知识点`。
4. 回答时区分“已由 wiki/错题卡支持”和“推断/待确认”。
5. 如果形成稳定结论，写入对应 wiki 页，并同步 `index.md` 与 `log.md`。
6. 若发现应入正式错题卡但信息不足，记为 `candidate-card`，向用户列出缺失字段。
7. query 不运行 rebuild，除非实际修改了 `错题卡/*.md`。

## 沉淀规则

高价值分析满足以下任一条件，可以沉淀到 wiki：

- 能复用到多个错题。
- 能转化为“看到什么，先做什么”的考场动作句。
- 能统一解释一组错因模式。
- 能连接已有知识树、方法卡和多个 `GS/LA/PR` 错题。

query 本身不运行 `wrongnet.py rebuild`；只有实际修改 `错题卡/*.md` 时才运行。

## 只读样本测试

- 样本问题：如何处理“条件边界与分类讨论”类错误？
- 读取依据：`method_gap_schema.md`、`知识树/高等数学18讲第16讲_无穷级数.md`、`wiki/index.md`、相关错题卡轻量标签。
- 结论形态：适合沉淀为专题页，不直接建错题卡。
- rebuild：不需要。
