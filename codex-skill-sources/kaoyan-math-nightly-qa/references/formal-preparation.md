# 正式范围、冻结与按点编纂

## Outcome

Turn the user-authorized pending math package set into verified formal cards and derived layers with one owning serial writer, then archive every current complete package and already-closed historical legacy evidence set to the verified T9 volume and bind their data-disk-relative locations into Obsidian locator notes. Keep the current user-selected model.

The immutable package and ledger are the fact layer. Semantic findings are formal-intake decisions, not retroactive edits to the raw conversation.

新本地非空批次先核 `数学一回滚复习系统/正式质量合同.json`，启用时读取该项目内 `数学一回滚复习系统/schema/formal_quality_v1.md`，在原 freeze 上用 `math_formal_quality.py begin → requirements → finalize`，随后按 proof 走唯一原生 writer 和 reconcile。已有 proof 或正式 closeout 时按其回执续接。新 `memory_review` 检查真实条件、首个断点、保留的正确动作及提示先后；先逐条回原题、首答、提示、修正及后续独立证据再写 `local_verified: true`。Decisions 检查匿名转述，本机核对完整原件。

Morning warmup and Project C questions now enter this same pending Capture backlog without foreground scores. Their missing score_event_id is expected, not a missing prerequisite. Read the saved actual answer, hints, correction, queue/item and source before adjudicating mastery and scheduling through the formal writer. Preserve a stated score as user evidence until adjudicated. If an older score already exists for the same real attempt, check that exact event and do not advance its schedule a second time. Scorer commands with --formal-intake belong only to an already authorized formal operation, never to a resumed learning turn.

## Authorization

For a cumulative formal-intake request, compute `cutoff_date` in `Asia/Shanghai` and include every capture with original `study_date <= cutoff_date` that has not reached a trusted formal terminal state. A cutoff date alone does not narrow the write scope to that day.

Narrow the backlog when the user gives the daily short command or explicitly limits the run to today, or supplies an exact capture/package subset. For the daily short command use `--only-today --cutoff-date D`; preserve earlier items for the next authorized cumulative run.

`只读`, `只检查`, or `不要修改` forces report-only mode: read pending packages and report gaps without freeze, formal writes, archive, Obsidian locator notes or cleanup.

For a formal-only request with no pending work, stop. For the three-step daily request, check the already accepted records for D and resume any missing deliverable. If D has no recorded learning evidence, state that instead of substituting another day.

## Authoritative Pending Set

First read `references/backlog-through-date.md`, then run the read-only canonical planner. For the short daily command, add `--only-today` and keep that scope for the final readback:

```bash
python3 数学一回滚复习系统/scripts/quick_intake.py backlog-through-date \
  --cutoff-date YYYY-MM-DD
```

Persist the returned immutable `plan` with its `plan_sha256`. Process `date_groups` in ascending original `study_date`. Before each date, replay the ledger and run:

```bash
python3 数学一回滚复习系统/scripts/quick_intake.py pending --date YYYY-MM-DD
```

Use its capture IDs, active freeze IDs, package/manifest hashes, target identity and study date. Reopen `manifest.json`, `conversation.json`, `source.json`, `receipt.json` and every attachment for a current complete package. Follow validated `archive-pointer.json` for a cleaned complete package and `legacy-archive-pointer.json` for cleaned historical source-bundle bytes; never accept a chat-supplied path as authority.

Historical v1/v2 events and source bundles remain valid inputs. Do not rewrite them or invent conversations that were not saved.

An existing trusted closeout must not be frozen or applied again. A committed closeout whose complete package archive is incomplete is `archive_pending`; a historical closeout with no canonical package is `legacy_archive_pending`. Neither is consumed until its matching verified receipt, locator and pointer exist.

## Freeze Before Semantics Or Writes

Read `数学一回滚复习系统/schema/quick_intake_events.md`. Resolve identity and group captures, then create one `math-fast-intake-freeze-v1` payload and run:

```bash
python3 数学一回滚复习系统/scripts/quick_intake.py freeze \
  --payload-file ${MATH_COLD_ROOT}/DATE/BATCH/freeze.json \
  --consume-payload-file
```

Reuse an active freeze; never create a second active freeze for the same capture. A failed freeze means no formal write. New-source missing evidence becomes `needs_user` and remains pending.

An active freeze is a resume target, not a new transaction. If formal state changed after the freeze, or an uncommitted closeout prepare exists, do not repeat the writer apply. Revalidate and resume the partial formal closeout or the closeout commit respectively.

## Prepared Project A content

For an explicitly supplied Project A math v5 package, use kaoyan-math-enhancement-intake. The already completed formal_card, exam_writeup, knowledge_point_reviews and profile_updates are the semantic input. Perform exact source/version/identity checks and resolve only concrete conflicts; do not reassign or repeat whole-batch semantic compilation. Original raw evidence remains immutable. The existing serial writer, archive and closeout below remain authoritative.

After all real closeouts of the exact supplied A batch, accept its prepared profile update through math_learning_profiles.py accept --input PREPARED_PROFILES --event-id CLOSEOUT (repeat --event-id for every batch closeout). For deferred_batch_merge, use the [verified contribution scope](../../kaoyan-math-enhancement-intake/references/profile-consolidation.md) and one consolidated row per concept. Local completion requires reading the actual teaching view, checking short_summary and next_check against the accepted version, and checking the relevant conditions, hint dependence and remaining limit. Report replica publication separately. Missing derived refresh is recovery-only, never another formal apply. A B review-audit uses its dedicated concept-review writer.

只维护已经存在的语义概况时走 `prepare/accept-maintenance`。若概况已落地而结果为 `local_refresh_pending`，用同一份 prepared 文件及完全相同的理由走 `resume-maintenance` 只续刷新，可加 `--refresh-only`。若当天正式 writer 改过来源版本导致准备失效，先核精确所影响证据再重准备，不重放正式学习事件。

## Native Evidence Read Topology

After freeze, read references/native-luna-read-contract.md for the evidence envelope. Delegate only under the active native proactive mode or the user's explicit authorization; otherwise the owning agent reads serially. Use native orchestration when independent reads help, without loading another orchestration Skill merely to enable concurrency. Do not impose a model, leaf count, effort, fork mode or service tier unless the user explicitly requires it for this task.

Every delegated read is bounded, read-only and tied to exact frozen paths/hashes. The parent reopens the cited bytes, resolves identity, mastery and relations, and performs every write serially. A leaf never allocates IDs, decides formal mastery or writes. Failed or ungrounded output is discarded; the parent continues from the raw evidence or records the precise unresolved item.

Do not revive Terra, Provider, MCP resolver/consumer, AnalysisPackage, Dispatcher or background formal-intake routes. Native engineering delegation is separate from the single-agent tutoring entry, which runs on the user-selected model.

## Parent Formal Decisions

按题号、小问、操作从全部数学项目的本地学习会话、原图、题解和已登记归档取历史依据；混合消息用来源项的 `turn_span:[起,止]` 绑定本题字符区间，另附 sequence、role 和该区间逐字 quote。只修订有原话或作答变化支撑的个人判断，保留旧版和仍适用的证据。完整来源用原有归档与定位入口，题目解析仅支撑数学结论。沿同一次正式审阅，在已有读取回执、实际响应与原会话可见回答能回指时填写 `reviewed.memory_use`，按数学运行根的 `数学一回滚复习系统/schema/formal_quality_v1.md` 核对象、条件、同一子问和实际改变的一处讲法。finalize 回传私有采用检查，仅有事后复核或缺原始证据时保留 `not_established`。原生工具输出早于当前可见答句时，可在 `evidence.delivery.tool_output_line` 指定原日志的输出行，按 Capture 固定片段哈希、同次调用、题号、小问及答句摘录核验。缺据留未建立；旧工具回执与原文分开。图解操作及助手自报不登记为独立作答。派生缺失只续原批次的本地检查。

当前冻结批次先读已有 `math_formal_quality.py begin` 返回的精确、标签与同版向量候选、Decisions 及同 Capture 的顺序证据，再决定采纳、按条件分开或保留不确定。候选同形或向量接近不能判同一结论；来源、对象、定义域、量词和推出方向必须对齐。模型回执是冷路径建议，父任务复核、原 writer 串行提交；API 未核验或失败不算完成模型裁决。

The parent independently decides:

- source and target identity, duplicate merge and formal ID allocation;
- confirmed user facts versus assistant teaching;
- first break, later breaks, independently correct steps and hint dependence;
- mastery, taxonomy, methods, traps and relations;
- final formal-card content and required derived-layer actions.

Do not convert assistant explanation into independent mastery or turn missing evidence into a user error. Multiple captures for one real question produce one formal-card write while preserving each event.

正式条目的可迁移公式保留必要条件。提交后检查 `postcommit.formula_projection`：沿已核来源增量生成公式/图形派生，条件、源哈希、阶段与授权一致时可复用。默认参考入口读当前代际；缺条件或坐标记待核。派生暂缺只运行 `math_postcommit.py --formula-only --event-id CLOSEOUT` 补回，不重做 freeze、apply 或学习事件。


## 以教材方法和真实反馈更新每个受影响知识点

每进入一题/主题卡，读取当前完整个人概况、相关历史原话与 problem_solving 方法层，再核对其适用条件和来源；短摘要、计数或hash不能代替这次正式编纂所需的完整阅读。方法目录位于 `错题知识网络/个人知识点索引/做题方法/{catalog,bindings}.json`，四本依据是高数18讲、线性9讲、临门一脚及概率论基础30讲。只读当前相关方法及准确原页；source_refs 的 hash、PDF 1基物理页、来源类型都保留。教材、原卡快照、派生参考要区分；未核读原书不能宣称已核读。可直接调用的性质和需记忆的结论同样属于做题方法，须写清触发、对象与适用条件；不能只抽取步骤而漏掉使该步成立的性质。

把当前题“线索→目标/对象角色→必要与隐含条件→第一动作→公式和步骤→分支/验算”与本人真实步骤逐项对齐，定位首个有据断点。等式归零不自动满足零点定理或罗尔条件；n阶方阵不自动给出可逆性或可对角化。候选方法按题目条件选择，保留本人有效熟悉路线，不能按数组第一项或章节名机械选择。没有展示的步骤保持未验证。

以完整真实对话的首答和提示先后为依据，分别核对概念对象、条件识别、运算动作及步骤之间的连接：已经独立完成、提示后才修复、仅本人自报、尚无证据必须分开。会使用结论不自动等于会证明，会计算不自动等于能识别启动条件；父概念已有摘要、方法目录里存在某技巧或助手已经讲过，都不能证明本人会相应细点。看懂、评价“讲得好”或认可某次短推导的展开量，不构成独立掌握证据。

本人本轮明确说“这一步我会”，可把该步作为当前讲解起点，先简列继续，不强制先测验；正式记录仍为self_reported。一次无提示正确可以支持实际展示的对象、条件与步骤范围内的讲法，不必等到整条方法被认证后才沿用；但不能扩成未展示的整条方法、证明或迁移都已掌握。

正式语义成稿必须为每个受影响已确认concept_key恰好更新一项既有 `math-learning-profile-update-v1`：overview 保留适用方法ID/名称、必要条件与启动、完整历史中的有据能力、当前操作链与首断点、提示后变化和未验证分支；short_summary 在2000 UTF-8字节内给出本点下次“看到什么→先检查/先做什么→个人卡在哪一步→最小帮助”。已独立完成的部分可凝练成结论或带条件的动作，教学展开只落在真实缺口或尚未接通的步骤连接上；未知写未验证，不改写为不会，也不自动增加整套补课。next_check 只检查一个有据断点或需最小核对的具体动作，不要求重教已展示正确的全部前缀。

稳定方法由 problem_solving 保留；个人摘要仍须具体写出“哪一概念或条件未认清、哪一运算不会、哪两步之间未接通”，并保留解决该处所需的最少结论和条件，不能删成纯知识点介绍或通用错误。step_evidence 沿现有状态与精确步骤ID记录原作用域，局部动作不扩大成整步掌握；teaching_preferences 只写有原话支持的讲法或路线依据，不把呈现评价当学习结果。首答、自改、提示后修复、独立正确、复述、理解自报及助手错误分开；progress 只记有前后证据的变化，无则[]。没有本轮本人作答，不制造错误/进步；已有偏好及引用按原合同保留。不得只写“注意条件”“基础薄弱”或建议日后再更新。

教材和已核方法中的可直接调用性质、二级结论，下一次默认给“结论＋必要条件＋本题应用”；未知或忘记该结论本身不触发自动证明。只有当前明确问为何、推导、证明，或题目本身要求证明时，才展开对应局部，保留必要的短连接，不扩成无关理论课。正式卡仍完整完成本题要求的解答或证明；选填题优先评估条件成立的简洁路线，不因摘要变短而省掉合法性检查。

本地普通正式编纂在写入前保存完整 profile_updates 并用 `math_learning_profiles.py prepare` 固定已有概念的来源和基线。新概念必须等原生writer/索引给出真实键后再绑定prepare，不生成伪键。全部相关真实closeout完成后，通过原 `accept --event-id ...` 接受完整成稿；跨日期/分包只合并每点一份，并绑定本批全部相关closeout。实际正式提交与摘要接受是两道事实；摘要或本机验回失败只恢复相应后置步骤。A返回包按其同版method-context来源及准备结果复用，不重写可靠成稿。

每份摘要服务下一次讲解：分别查本人熟悉或受益的解释、本人明确偏向或已自主使用的合法方法、本人作答中可核的具体不足。按 `teaching_preferences_v1` 给新核偏好加 `focus=explanation|method|both`，保留原话、适用范围与证据类型；只自报、提示后和独立执行不得合并。用 `short_summary` 写已做对的前缀、卡住的最早动作和所需的最小提示，用 `next_check` 留一个动作。没有证据的维度标未确认。章节或导航项仅做导向，不作细点个性化命中。

接收完读回本地 `math_teaching_context.py resolve --for-teaching --concept 真实细点 --view after_attempt --max-bytes 12000`，确认方法层的启动、条件与步骤可取，short_summary/next_check保留本轮有据断点与提示依赖，已有偏好未丢。保留同版exam_frequency中的主题、统计范围、真实出现年份、去重题数和频次等级，以及适用的choice_fill_guidance；未单列或来源未就绪按原状态说明，不填成零次或低频，也不把父主题统计当细点掌握。protected不得含这些方法、频率或个人提示。方法新增或绑定更正建议另作有原页和条件依据的定点维护，不能把未应用建议声称为已同步目录；若具体冲突影响本题正确性，先修复该冲突再称该项完整。

编写本批短摘要前，若旧稿已退为“无可归属”，而同键旧版、原题卡或分步记录仍有可定位的作答，回到原题、原角色和提示先后核对。只保留核实的题目与操作范围，区别题卡记录、本人原话、助手给出的动作和教材方法。仅有教材依据时可以写具体的起手条件，个人熟悉程度保持未核。下一检查应能直接在本题作答；同一题关联的多个知识点各查自己的动作。

## Teaching approach in the existing profile

During the authorized semantic pass, also identify the learner’s preferred or familiar explanation for each affected concrete operation. Follow the teaching-preference contract（项目内 `错题知识网络/schema/teaching_preferences_v1.md`）: preserve exact user quotes and scope; distinguish explicit preference, a representation followed by a concrete repair, and an independently used familiar route. Record the preferred method, notation and explanation order, plus evidenced approaches to avoid, in teaching_preferences. The default teaching route is problem cue → justified condition → needed formula → current substitution/action. Place the formula next to the step that uses it. Do not turn missing knowledge or a historical local why into an unsolicited derivation, general-use explanation or theory lesson; solve any proof actually required by the problem. Preserve the full formal solution contract, but keep the teaching approach operational. An assistant’s choice or “I understand” alone proves neither preference nor effectiveness. Retain existing preferences when no new evidence changes them; do not force a global style from one local request. Accept them with the same profile update, verify after_attempt/direct reads, and keep protected views closed. No preference adds a learning event, score or mastery claim.
当前稿合并与精简遵守现有摘要合同的完整性与去重条款（项目内 `错题知识网络/schema/teaching_preferences_v1.md`）：逐项保留有效个人事实，按作用域接入补充证据；旧版本走已有历史归档，不将整份旧稿叠入当前overview，不重复独立方法/考频/选填字段。
