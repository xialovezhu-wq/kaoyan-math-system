---
name: kaoyan-math-nightly-qa
description: "数学正式入库与日终收口。实际执行「提交执行今天的正式入库」等日终指令时，一次完成三步：正式入库并验回服务错题讲解的个性化摘要、按现行 Skill 备次日高频题单、交付全日可交互 HTML 复习页。支持累计截止日、指定日期或精确集合；范围按用户指令。仅修改 Skill、写提示词、预览、快速保存或明确仅做单项时不启动三步。已有正式提交只续缺层，历史 A 回包走 enhancement-intake。"
---

# Kaoyan Math Formal Intake

项目相对路径与迁移后的定位、索引恢复见[当前机器路径](../kaoyan-math-question-worker/references/local-paths.md)。已核验数学工作区时直接使用其根目录和下列相对命令；路径未知或报错时才读取该说明。

数学 A 正常入口由当前 Codex 在本地审核、语义编纂、逐日串行正式写入、更新概况并读回。输入是本地原始证据与真实旧稿；外部分片仅在确实已有或要求时兼容。教材/MCP发布副本不替代本地现行原件。

## 日终短指令

「提交执行今天的正式入库」及明确要求提交今天全部数学快存的等义指令，按 Asia/Shanghai 固定本次学习日 D，只处理 D 的快存，并一次授权下面三步。日终语境中的普通「正式入库」也默认交付三步；未收窄写入范围时按原累计截止合同处理，第 2、3 步只用本次的目标学习日。明确只入库、精确题目/包、单层恢复、只读或其他限定按用户所说范围执行。引用这句来改 Skill、写提示词、讨论流程或预览不是实际执行指令。

1. 正式入库并验回个性化摘要。用下文原生流程处理已授权范围内全部尚未正式完成的快存，保留原学习日、真实首答及提示顺序；完成正式提交、归档及同版向量后置检查。个性化摘要供 [错题讲解 Skill](../kaoyan-math-question-worker/SKILL.md) 使用，分别保存有范围和来源的熟悉讲法、偏向解法及具体作答不足。短摘要写已做对的前缀、第一断点和最小补充，下一检查只留一个动作，证据不够标未确认。用日常 `math_teaching_context.py resolve --for-teaching` 的相应已授权视图读回短摘要、偏好和下一检查，确认当日摘要有效后再备题。
2. 执行 [次日备题 Skill](../kaoyan-math-warmup/SKILL.md)。目标日为 D 的次日，仅从 D 已正式化的快存提炼知识点、基础公式、二级结论和解题断点。用考查次数定优先级，以现行三卷真题考法核准候选后压缩题量。数一同题须有本人做过的证据，同题接触间隔满 10 天。保存可直接开始的答案安全题单，记录覆盖缺口，不写曝光、作答或评分。
3. 交付 D 的离线 HTML 复习页。按 [visual-review](../kaoyan-math-visual-review/SKILL.md) 用第 1 步已核原件覆盖 D 全部有证据的已学题与小问。同次补充并回原题，每卡先给知识点标题和原题图，再依次给二级结论、基本方法与本题过程的双栏映射、基本公式。左栏方法树每步用箭头指向右栏的独立过程框。解释保持短，答案保护沿用复盘入口。后台验回 `数学一回滚复习系统/知识点复盘/阅读卡片/YYYY-MM-DD/index.html` 的题图、公式和逐步连线，再给链接。

在同一任务完成三步并分别汇报，附次日安全题单和 HTML 链接。已提交的入库只恢复尚未完成的本机派生步骤。当天无待入库项但已有同日有效版本时，接着补未完成的题单或复习页。备题实际缺题或遇到阻碍时写清缺项，复习页仍可从已核当日材料完成；正式材料有残项则在页内标记，不把残项冒充已入库或合格次日题。

Before creating working files, read the shared [T9 intermediate-file policy](../kaoyan-math-enhancement-intake/references/t9-intermediates.md). Keep plans, drafts, payloads, working scripts, backups, logs and reports in the verified T9 batch directory, including temporary files. Repository-resident formal data and immutable reference evidence remain governed by their native contracts. Completion also requires verified archival and cleanup of all batch intermediate copies after profiles and publication are current.

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
  --payload-file /Volumes/Study-Archive/03_数学/资料库/网页加工中间文件/DATE/BATCH/freeze.json \
  --consume-payload-file
```

Reuse an active freeze; never create a second active freeze for the same capture. A failed freeze means no formal write. New-source missing evidence becomes `needs_user` and remains pending.

An active freeze is a resume target, not a new transaction. If formal state changed after the freeze, or an uncommitted closeout prepare exists, do not repeat the writer apply. Revalidate and resume the partial formal closeout or the closeout commit respectively.

## Prepared Project A content

For an explicitly supplied Project A math v5 package, use kaoyan-math-enhancement-intake. The already completed formal_card, exam_writeup, knowledge_point_reviews and profile_updates are the semantic input. Perform exact source/version/identity checks and resolve only concrete conflicts; do not reassign or repeat whole-batch semantic compilation. Original raw evidence remains immutable. The existing serial writer, archive and closeout below remain authoritative.

After all real closeouts of the exact supplied A batch, accept its prepared profile update through math_learning_profiles.py accept --input PREPARED_PROFILES --event-id CLOSEOUT (repeat --event-id for every batch closeout). For deferred_batch_merge, use the [verified contribution scope](../kaoyan-math-enhancement-intake/references/profile-consolidation.md) and one consolidated row per concept. Local completion requires reading the actual teaching view, checking short_summary and next_check against the accepted version, and checking the relevant conditions, hint dependence and remaining limit. Report replica publication separately. Missing derived refresh is recovery-only, never another formal apply. A B review-audit uses its dedicated concept-review writer.

只维护已经存在的语义概况时走 `prepare/accept-maintenance`。若概况已落地而结果为 `local_refresh_pending`，用同一份 prepared 文件及完全相同的理由走 `resume-maintenance` 只续刷新，可加 `--refresh-only`。若当天正式 writer 改过来源版本导致准备失效，先核精确所影响证据再重准备，不重放正式学习事件。

## Native Evidence Read Topology

After freeze, read references/native-luna-read-contract.md for the evidence envelope. Delegate only under the active native proactive mode or the user's explicit authorization; otherwise the owning agent reads serially. Use native orchestration when independent reads help, without loading another orchestration Skill merely to enable concurrency. Do not impose a model, leaf count, effort, fork mode or service tier unless the user explicitly requires it for this task.

Every delegated read is bounded, read-only and tied to exact frozen paths/hashes. The parent reopens the cited bytes, resolves identity, mastery and relations, and performs every write serially. A leaf never allocates IDs, decides formal mastery or writes. Failed or ungrounded output is discarded; the parent continues from the raw evidence or records the precise unresolved item.

Do not revive Terra, Provider, MCP resolver/consumer, AnalysisPackage, Dispatcher or background formal-intake routes. Native engineering delegation is separate from the single-agent tutoring entry, which runs on the user-selected model.

## Parent Formal Decisions

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

## Teaching approach in the existing profile

During the authorized semantic pass, also identify the learner’s preferred or familiar explanation for each affected concrete operation. Follow the teaching-preference contract（项目内 `错题知识网络/schema/teaching_preferences_v1.md`）: preserve exact user quotes and scope; distinguish explicit preference, a representation followed by a concrete repair, and an independently used familiar route. Record the preferred method, notation and explanation order, plus evidenced approaches to avoid, in teaching_preferences. The default teaching route is problem cue → justified condition → needed formula → current substitution/action. Place the formula next to the step that uses it. Do not turn missing knowledge or a historical local why into an unsolicited derivation, general-use explanation or theory lesson; solve any proof actually required by the problem. Preserve the full formal solution contract, but keep the teaching approach operational. An assistant’s choice or “I understand” alone proves neither preference nor effectiveness. Retain existing preferences when no new evidence changes them; do not force a global style from one local request. Accept them with the same profile update, verify after_attempt/direct reads, and keep protected views closed. No preference adds a learning event, score or mastery claim.
当前稿合并与精简遵守现有摘要合同的完整性与去重条款（项目内 `错题知识网络/schema/teaching_preferences_v1.md`）：逐项保留有效个人事实，按作用域接入补充证据；旧版本走已有历史归档，不将整份旧稿叠入当前overview，不重复独立方法/考频/选填字段。


## Serial Formal Writer

新本地非空批次走数学本地正式质量 v1（项目内 `数学一回滚复习系统/schema/formal_quality_v1.md`）。冻结并核过原件后先 begin，落实真实候选，随后对实际成稿执行 requirements 和 finalize。写卡前必须拿到 QUALITY_PREPARED；保存同批 proof，并用 quick_intake.py apply-formal-targets --proof 交现有正式层锁内写入。先查已有 closeout 和质量状态，中断只续缺层。

Read `references/display-asset-closure.md`, then use the existing subject-local transaction in this order:

1. Apply each prepared grouped formal card once with its quality proof and include the exact freeze-generated `fast_intake_refs` and `fast_intake_source_refs`.
2. For every source manifest, run the zero-write display plan and apply only its exact authorization. Promote displayable images into `错题知识网络/assets/visual_wrong_questions/FORMAL_ID/`, rewrite only managed visual references, refresh and verify bridge membership, and create one `math-display-asset-closure-receipt-v1`. A package with no formal ID must still create explicit `no_display_proof`; its images remain archive-only.
3. Run the repository-local linter for every created or changed card:

```bash
python3 数学一回滚复习系统/scripts/math_formal_lint.py \
  --repo . \
  --freeze-id FREEZE_ID \
  --card REPOSITORY_RELATIVE_CARD_PATH
```

4. After all cards pass, run exactly one successful `python3 错题知识网络/scripts/wrongnet.py rebuild`.
5. Complete required targeted rollback. Read `references/rollback-closeout.md` when rollback applies.
6. Keep relations in SHADOW proposal mode unless current policy explicitly authorizes a formal edge.
7. Complete required math Wiki ingest, targeted lint/parity and visual verification.
8. For every final formal target, including `operation=unchanged`, read `错题知识网络/schema/teaching_context_v1.md` and materialize one answer-safe `math-teaching-context-v1` from the same frozen evidence and final card. The slice is a historical routing prior for `kaoyan-math-question-worker`, not a second formal card or learner profile. It must bind the final card path/hash, formal evidence source version, current freeze, exact capture bindings, capture evidence source version and package identities; it must preserve independent work versus hints and may contain only the first break, effective support/representation and unresolved prerequisites needed by Scheme D. It must not contain an answer, final result, full question, full solution or assistant history.

   Build the canonical payload outside the immutable package, then run:

   ```bash
   python3 错题知识网络/scripts/math_teaching_context.py \
     --repo . \
     materialize --input /Volumes/Study-Archive/03_数学/资料库/网页加工中间文件/DATE/BATCH/context-FORMAL_ID.json
   ```

   Require the returned `context_path`, `context_sha256`, `pointer_path` and `pointer_sha256`. Re-run `verify --formal-id FORMAL_ID` and require `status=valid`. Do not bind a closeout ID into this pre-closeout file. A missing, stale, answer-unsafe or mismatched slice blocks closeout; it does not authorize repeating an already-applied formal writer.
9. Submit one `math-fast-intake-closeout-v3` receipt with `model: unknown` and the exact `batch_receipts.teaching_contexts` array only after every formal, display, Wiki and teaching-context layer passes.

Every formal and derived write is serialized in the owning parent. Read-only leaves never run any step in this section.


## Explicit Per-Concept Formal Observations

For every new formal closeout, read `错题知识网络/schema/formal_concept_observations_v1.md` and include the optional v3 `concept_observations` extension. The writer requires it for this workflow; historical v3 receipts without the extension stay valid and are never backfilled by guessing. Cover every final formal target, including unchanged cards, with either source-grounded observations or an explicit `no_observation_reason` and an empty observation list.

Record each knowledge point on which this conversation actually demonstrates a wrong step, unresolved gap, hint-assisted correction or independently correct attempt. A card's `knowledge` list only describes involved concepts: never mark all its labels wrong from the card-level wrong_point. Bind each point to its exact stable concept key, the current freeze's Capture, original package and exact user turn quotations. Keep assistant hints separate; hinted correction is not independent mastery. Reuse the existing complete package and closeout, never create a knowledge-point review session or another Capture. Missing legacy dialogue can justify an explicit no-observation reason; it cannot justify invented quotations.

The normalized observations are committed atomically inside the original closeout. The existing postcommit builds stable per-closeout source projections under `错题知识网络/个人知识点索引/正式逐点观测/` and native index records of kind `formal_concept_observation`; an error there is projection-only recovery using the same closeout ID. Verify point-specific retrieval after refresh. `math_concept_index.point_history(repo_root, concept_keys)` is the read-only full-evidence interface for subsequent selection; it distinguishes formal intake from independent concept review and does not infer point errors from old card history. Its full evidence is internal and must not be copied onto an answer-protected learner surface.

## Post-Commit Raw Archive

Read `references/t9-raw-package-archive.md`. Archive begins only after the exact package capture has a completed analyzed terminal outcome and is committed by the successful closeout. Archivable outcomes are `curated`, `created`, `updated`, `already_current`, `skip`, `noop`, and `duplicate`. `needs_user` and `failed` remain on the local fast workspace with no cleanup. The archiver independently verifies that closeout binding.

For each package run the fixed command with its actual hashes and formal IDs:

```bash
python3 数学一回滚复习系统/scripts/archive_conversation_package.py \
  --repo . \
  --manifest REPOSITORY_RELATIVE_MANIFEST_PATH \
  --manifest-sha256 MANIFEST_SHA256 \
  --package-sha256 PACKAGE_SHA256 \
  --closeout-id MFI-CLOSE-ID \
  --terminal-outcome curated \
  --formal-id GS-000 \
  --archive-root /Volumes/Study-Archive \
  --subject-relative-root '03_数学/资料库/原始会话资料'
```

Repeat `--formal-id` for every actual formal ID bound to the package; omitting all IDs is allowed only when the closeout itself has no formal ID. The command independently derives and compares the terminal outcome and formal-ID set from `capture_results`/`formal_results`, so caller labels are never authority. Before any new cleanup it reopens the exact display closure, proves all formal binary references are stable or explicitly no-display, and binds the closure receipt plus formal-reference scan into the archive intent, receipt and pointer. It then performs sentinel validation, stage-copy, tree and manifest verification, atomic finalization, locator-note write and reread, append-only archive receipt, then writes and rereads the recovery pointer before local attachment cleanup.

For a closed historical Capture with no `math-conversation-package-v1`, do not skip it or fabricate a package. First run a zero-write preview, then apply its exact content-derived authorization:

```bash
python3 数学一回滚复习系统/scripts/archive_legacy_evidence.py \
  --repo . \
  --capture-id MFI-CAP-ID

python3 数学一回滚复习系统/scripts/archive_legacy_evidence.py \
  --repo . \
  --capture-id MFI-CAP-ID \
  --apply \
  --authorization MATH-LEGACY-ARCHIVE-APPLY-SHA256
```

The legacy command derives freeze, closeout, formal IDs and outcome only from the ledger. It preserves exact raw ledger lines plus every existing old source-bundle byte, or types the evidence as `ledger_only`; it states `conversation_complete=false` and `canonical_package=false`. It never calls formal writer, rebuild or closeout. Read the legacy section of `references/t9-raw-package-archive.md` before using it.

Treat `ledger_only` as valid only when no source-bundle binding exists. Apply must reauthorize under the shared ledger/archive locks, reject symlink archive paths and prove containment before copying. Planner completion must reuse the strict live verifier for deterministic IDs, exact pointer/receipt/locator bytes and the actual T9 manifest/tree; local synthetic surfaces are never sufficient.

Before source-bundle cleanup, bind the current ledger reference set/count and per-file delete-or-retain decision into authorization, receipt and pointer. Delete only an exact artifact whose sole proven reference is this Capture and whose verified pointer covers the same path/hash/size. Retain and report shared or unprovable files. Recompute the proof under both locks immediately before cleanup and every cleanup resume; drift stops deletion.

Treat pointer ownership as Capture-specific. Keep a compatible `legacy-archive-pointer.json` only for its owner; when a shared bundle's single pointer belongs to another Capture, use `legacy-archive-pointers/CAPTURE_ID.json` and never overwrite the existing pointer. A partial legacy transaction with verified intent/archive/locator/receipt resumes by reusing those exact identities and writing only its deterministic Capture pointer before the cleanup gate.

For a completed ledger-only archive created before `local_pointer_path`, use read-only old-contract verification and never rewrite it. Accept only exact old authorization/intent/receipt/pointer bytes plus current ledger and live T9 manifest/tree equality; all new ledger-only archives use v2.

If formal closeout succeeds but display, archive, locator, receipt or cleanup fails, report `FORMAL_COMMITTED_ARCHIVE_PENDING`. Do not rerun the formal writer. Resume only the exact post-commit component. Keep the local package and all heavy attachments until stable display, formal-reference scan, bridge membership, archive verification and Obsidian path receipt all succeed. Report `pending_component=display_assets|locator|archive|cleanup`.

Do not edit any Obsidian `.base` file; the locator note and receipt are this Skill's only Obsidian archive surfaces.

## Partial Failure

Before formal commit, any failed required layer, including teaching-context materialization or verification, keeps the capture pending and blocks closeout. Reuse the same freeze after revalidation. If final formal state already changed, resume `partial_formal_closeout` with writer apply forbidden and rebuild only the missing derived layers.

After formal commit, archive failure never invalidates or repeats formal work. It leaves the verified local package intact for archive-only resume.

`needs_user`, damaged/failed, `archive_pending` and `legacy_archive_pending` items remain explicit residuals, but ordinary item failure does not stop later `study_date` groups. Never relabel a historical capture to the cutoff date, never combine dates in one freeze and never create a cross-date formal transaction.

Never hide a pending formal or archive layer behind a success message.

## Completion

Report the frozen captures and grouped targets, actual card changes, lint, one rebuild, rollback, SHADOW, Wiki/visual/parity, per-target teaching-context verification, closeout ID, archive receipt ID, T9-relative path, locator-note path and local cleanup state.

Reopen the immutable baseline plan with `backlog-through-date --baseline-plan-file PLAN.json` and report the final global gate: `completed`, `already_consumed`, `needs_user`, `failed`, `archive_pending`, `legacy_archive_pending`, plus every residual capture at or before the cutoff. A batch is not globally clear while `residual` is nonempty.

Use `数学正式入库与原始包归档完成` only when both closeout and every package archive/locator receipt return `recorded` or verified `noop`. Report index and replica acceptance separately, and reserve replica-current claims for verified publication. A locally verified closeout can feed B/C while that independent sync is pending.

## Teaching And Post-Commit Boundary

When choosing the formal solution representation, preserve the correct, fast and reliable single exam mainline owned by question-worker; do not replace a learner-approved route with multiple full derivations. Complete original dialogue and solution bytes remain intact. Teaching uses its separate tutoring task on the user-selected model and complete 30-second target/40-second ceiling; formal curation retains the selected engineering runtime.

A successful closeout invokes the subject postcommit hook after releasing its write locks. The hook refreshes formal learning state and the local personal index. On retry, resume the affected derived step under the original event ID. New formal evidence becomes available to the next related teaching turn after local refresh.

## Current Project A Advice

When formalization is explicitly processing a verified Project A run, reopen its actual advice and original package evidence and decide every `(package_id, question_id)` item as accepted, modified, rejected or no_change. Record the result through `quick_intake.py record-advice-decision --payload-file` and verify through `verify-advice-decision --run-id`. A changed accepted/modified item must cite this run's real native closeout and after hash; an old closeout does not prove current advice acceptance. Rejected/no_change items create only the separate adjudication receipt, with no invented Capture, score or mastery. The command requests publication after releasing its lock; pending cloud sync is never authorization to replay formal writes.


The concept index is a derived teaching projection at `错题知识网络/个人知识点索引/index.sqlite3`. Verify `postcommit.concept_index.status` is `ready` or `noop`, retain its content `version`, and check the canonical formal-ID coverage after a formal library size change. A committed formal epoch invalidates an older index even if its rebuild fails; pending quick packages do not invalidate accepted personal history or become accepted events. Repair only this projection after a postcommit failure, never repeat formal apply.

## 全库向量续接

After accepting the final profiles and completing the batch's archive/locator work, run the existing postcommit continuation once with the exact closeout ID and whole-catalog vector refresh:

```bash
python3 数学一回滚复习系统/scripts/math_postcommit.py \
  --repo . \
  --event-id EXACT_CLOSEOUT_ID --refresh-only --refresh-all-profiles --refresh-global-vectors
```

核对 `global_vectors.status=ready|noop`、与 `concept_index.version` 同版、可检索知识点和近邻来源的覆盖数，以及 API 新嵌入量和复用量。此步骤核对全库知识点，更新新建或实际文本变化的 OpenAI 向量，并从全库重算跨点候选，允许旧知识点召回本批新增或修改的相关知识点。没有变化的输入复用同模型、同维度和同内容哈希的向量，归档迁址不产生新学习。发给 API 的是已核数学名称、通用条件和方法片段，个人摘要、原话、图和作答细节留本机。Decisions 继续核正式入库实际取用的候选和成稿，不能把相似度或模型概率当作掌握证据。

日终从现有原生索引重算全库学习路径、讲题短摘要投影和引用状态。概况正文依真实证据更新：检查本批新观察、全库既有摘要及失效来源，并追到本批题解所涉的旧前置和后续点。每个可核的连接写明从哪个操作的产物进入下一动作、适用条件、实际题卡和证据源。两端需要更新时一并验回。记录本身只说明解题的前后依赖，个人独立、提示后或未知继续按各自证据判断。

用 profile 更新的 `solution_connections` 保存上述连接。当前 closeout 涵盖的点可走原生 accept；已提交之后，跨题目标范围或旧摘要修复用原生 `prepare/accept-maintenance`，只续概况，保持学习事实。方法总表换版时优先核真版本与本点绑定，证实相关内容未变后可重绑原字节快照；实际操作或个人依据有变化时针对变化重新核定。回执分别给全库重算数、语义更新数、两端验回和仍待核项。

用错题讲解原入口验回当前摘要及必要的旧关联点，确认候选只提供范围定位。向量待办单列 `global_vectors=pending` 与原因；正式业务已提交时只续该后置命令，沿用请求回执。没有同版成功回执不得声称全库向量已更新。


## 本机读回与质量回执

原件归档、概况接受和本机索引刷新后，在本批原工作区完成核验：

```bash
python3 数学一回滚复习系统/scripts/math_formal_quality.py reconcile --workspace DIR
```

`reconcile` 实际调用 `math_teaching_context.py resolve --for-teaching` 对本批已接受的每个个人点读三个视图。`after_attempt` 和 `direct` 核对实际短摘要、下一检查及同一来源版本，`protected` 核对视图保护。通过后以 `VERIFIED_CURRENT` 和 `verification_basis=native_teaching_readback` 记录质量完成。已有正式提交只刷新本机缺层或续同一 `reconcile`。旧等待发布的批次也用原工作区继续。本地题单及复盘依据本机读回。真实旧网页回包的 close 仍可使用原生准备回执 `--legacy-return-receipt`。

用户明确要求远程访问或外发时，再走该交付要求对应的显式发布或打包入口。授权发布副本时，可用 `math_postcommit.py --event-id EXACT_CLOSEOUT_ID --publish` 请求副本。若要确认副本已达当前版本，发布后以 `study_publication.py verify-current --subject math` 的 `PUBLISHED_CURRENT` 验回。普通 `math_postcommit.py` 与兼容参数 `--refresh-only` 都只刷新本机。若同时核对回顾，按个人点与 `--recap-concept` 各自的实际范围处理。

## 方法v2与步骤证据接收（2026-10-23）

本地先读现行概况、方法和原页。仅处理旧包时，传输字段合同见三项目共同说明（共享目录 `../Study-Pro-Bridge/web-projects/A/MATH_WEB_ALIGNMENT.md`）及A字段合同（共享目录 `../Study-Pro-Bridge/web-projects/A/FORMAL_RENDERING_SCHEMA.md`）。读取methods、独立steps及依赖、conclusions的条件/例外/direct_use；旧方法与细分候选不等同，不按第一候选选路。选法先核当前题条件，再接本轮正确前缀、适用偏好和有据操作，不按拆分后的步骤个数计算熟悉率。

profile_updates现支持可选step_evidence。省略时原生prepare继承当前有效旧项；显式数组须完整保留仍成立旧观察再追加，不把本包增量当全量覆盖。state沿现有七类，scope限定对象/操作/条件；coverage缺省不补full_operation，partial_operation不证明整步掌握。结构化user/hint引文必须核原角色、轮次和逐字quote。嵌套source_refs与顶层引用一起映射并核验至最终稳定路径，不能只改顶层后留下staging路径。exam_brief和source_guards由本地投影，不接收为新学习事实。

删改旧步骤需step_evidence_revision_reason及真实依据，保留旧历史。accept对任何内容变化自动保存前驱版本，包括跨event更新；对已有观察或判断的归因更正仍经现有prepare/accept-maintenance提交精确更正裁决，不改原始事件，也不以新学习事件替代更正。普通缺省继承和保留旧项后追加不增加这一步。共享点跨片先汇合全部有效步骤、偏好、来源与最新事实，仍串行接受一份完整概况。

接收读回须同时核short_summary/next_check、teaching_preferences、step_evidence的作用域/覆盖以及exam_brief；预算省略整块不等于无记录。本地使用 math_teaching_context 的精确身份和 math_method_context 的方法/步骤目录，核对实际预算与原页。protected不暴露这些提示。不得为修引用或对齐方法新增学习、评分或调度事件。

## 按需资料提取与疑义复核（原入口）

本批 PDF、截图或网页原件辨识困难时，才复用 `../Study-Pro-Bridge/scripts/study_material_preprocess.py`：用 `../Study-Pro-Bridge/.venv-study-mcp/bin/python` 执行，传 `--subject math --source 原件绝对路径 --pages 1,3 --purpose reference`，purpose按来源角色选reference/question/user_work/solution；公开网页可用 `--url`，不带浏览器凭证。先本地文字提取，扫描页/图像按需调用视觉 API；不为清楚的资料重复增加一层模型。输出原件副本、提取稿和缓存走本科已核验 T9 冷目录，来源/hash/页码保持可追溯，不修改 Capture 或正式库。

`--review auto` 是默认，仅对提取疑义页追加 Decisions；已有明确疑义可用 `--review-pages 1,3`，页码必须属于本次 `--pages`，`--review off` 只跳过此旁路。它比较原页图与提取稿，提示可能漏项、混区、角色或文字不一致；HTML/TXT 没有原页图时明确未筛查。无疑义不默认每页复核；空白/过少内容等可程序核查的情况先用代码。失败保留已提取结果与未筛查原因，不重跑成功正式写入。

默认 `protected`，`after_attempt` 也只返回元数据；只有当前任务已授权读取该内容及相应答案范围时，才用 `--view direct --allow-answer-text`。正式审核授权不扩展到未来题、兄弟小问或其他答案。机器提取、疑义复核和回包 `evidence_prescreen` 是不同的派生辅助：均不替代实际核读原图、完整真实对话与本科语义审核；未标记不是审核通过，提示后完成不是独立掌握，缓存不是新学习。只将原证据支持的结论交既有唯一正式 writer，保留原日期、身份、原评分/掌握度与幂等恢复规则。

## 统一记忆的正式维护

数学统一记忆与读取合同（项目内 `错题知识网络/schema/math_memory_v1.md`）为本流程与讲题、快存的共同契约。沿用原 `profile_updates`；有逐项原始依据时填写可选 `claims`，已有偏好和步骤证据继续按原类型与作用域保留。旧稿缺少逐项依据时保持兼容和限制，不批量补造判断。概况接受、观察更正与实际做题是不同事件。

审核短摘要时，将需要保留的旧误解及其已核纠正、适用对象和必要条件、实际作答的提示依赖写成同一可审阅单元，逐项绑现有原件及修订依据。教材结论、本人表现和助手提示分开。不同条件下成立的记录并存；同范围冲突未决时显式保留，不按导入先后选真。没有足够证据时说明缺口，保留原件，不把观察开头、提示后改答或候选来源当作可迁移结论或独立表现。

维护时分别核对学习日期、获知日期、有效范围与更正前驱；同一作用域的证据冲突保留显式冲突，不按文件修改时间强选“最新”。对错误归因的更正须影响有效观察、相关逐点计数和依赖判断，原证据保留，评分与调度不随资料维护改变。

日终最终后置同时重算全库个人摘要投影、验已证跨点连接并刷新同版全库向量。同事件同版本复用已验证结果，派生层失败按原事件续办。后端性能评测只在系统改造或实际需要时运行。
