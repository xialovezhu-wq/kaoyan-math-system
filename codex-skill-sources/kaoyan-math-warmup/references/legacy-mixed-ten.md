---
name: kaoyan-math-warmup
description: 数学C默认本地选择和校验晨间十题，旧队列按原身份逐题恢复，保存完整Capture。
---

# Kaoyan Math Warmup

For selection exports, Project C handoff ZIPs/prompts, preparation payloads and working logs, follow the shared [T9 intermediate-file policy](../../kaoyan-math-enhancement-intake/references/t9-intermediates.md). Initialize a verified T9 batch directory and use it for every output and TMPDIR; do not fall back to the system disk. Active canonical queues and formal learning records retain their native locations. The user sends the ZIP/prompt to the web model and returns its result manually.

仅当收到恢复检查点、progress.overall_status为partial/blocked，或报告仍有未完成项时，先转kaoyan-math-web-recovery保全并续接；不要拒绝后结束。完整业务包附有complete进度报告时照常接收，不循环转回恢复Skill。补齐后回到本Skill，已完成的学习与正式提交不重放。


## 历史十题与旧五题路由

本页及其旧命令只用于理解和恢复已经登记、开始的历史流程。新提议的每日五题统一走 [次日五题合同](exam-priority-five.md)，即使请求回看较早的日期。此处旧示例的七天门禁、旧题池与早期语义计划格式不适用于新备题。

新功能启用配置为数学一回滚复习系统/公式记忆配置.json。活动公式库为practice_only：只用已配题且已去重的canonical规则；归档项不可进入日常。逐题只选实际用到且条件适用的variant，详见[已核公式调用](../../kaoyan-math-question-worker/references/formula-memory-v1.md)。新warmup-candidate-bundle-v3选择10道：5 formal_wrong＋5 exam_formula，沿现有C备题/本地核验导入链；只有practice_ready且逐题原始q+t版本匹配的数学一公式真题进入候选。完整约束见Study-Pro-Bridge/web-projects/C现行WORKFLOW与MATH_WEB_ALIGNMENT。资料维护不是A正式学习事件，不伪造closeout。

先恢复已冻结/已开始的真实队列，数量、ID、题序不变。新请求用scheduler.py warmup-candidates --count 10取得typed候选；由当前本地 Codex 语义选择后交 prepare-local-review-source 核验，实际开场才show-review-source。默认warmup在新配置下恢复同日已注册v3源；返回 local_authoring_required 时当前会话即按响应的 candidate_command 本地取候选、选题并注册，不能把该中间状态交给用户当作最终阻碍，不用旧warmup-successor硬凑10个正式卡。新旧两个轨道必须按原题ID/精确别名/题面SHA去重，保留Day0–7、独立正确永久排除及源保护。缺5+5合格题如实保留不足。

v1/v2五题与旧native v5仍可原样续用；下文formal-only候选、--count 5与semantic-selection-v5专门用于旧五题分支，不外推成新十题。不得用10替换已开始的5，也不把MATH1伪装GS/LA/PR。v3每题沿show结果的capture_arguments保留真实题源、queue/item及文字题认证参数。

公式轨用[已核公式调用](../../kaoyan-math-question-worker/references/formula-memory-v1.md)：先真实回忆/应用，再在聊天中给出当前许可的必要公式与简要理由；正常错题也可按需要调用。沿用question-worker的聊天讲解流程，不启动或同步公式显示会话。关题只保存完整对话和原始附件，不附显示记录，仍不即时评分/FSRS。

## Outcome

At study start, resume the existing frozen identity. A new v3 source delivers protected typed ten (five formal cards and five formula-linked exam questions); legacy formal-only sources keep their original count. Deterministic code decides eligibility and identity; a bounded native reader does the real semantic reading and value comparison; the owning parent reopens the same bytes and owns the final decision and the only serialized queue write.

Finish selection and prepare the whole question set before the learner starts. During learning, use the shared question-worker and wrong-intake path for every actual question. Record complete raw Capture evidence only; formal scores, long-term scheduling, mastery, indexes and publication belong to later user-authorized formal intake.

## Project C daily execution

当前本地 Codex 用 scheduler.py warmup-candidates --date YYYY-MM-DD --count 10 --output 已核验T9路径 取得本地 v3 候选，不读外部工作流。对本批已接受概况、必要原话、线索与条件逐项比对；记录私有选择依据，定一份 5 formal_wrong + 5 exam_formula 的精确清单；若不足仅报告真实缺项。B/C 可从同一已验 A 基线独立准备。沿当前队列原身份续办。

本地成稿采用 math-review-source-v3、subject=math、project=C、实际 run_id/target_date 和 questions[]。selection_basis 绑定 candidate_bundle_sha256、formal_candidate_bundle_sha256（formal_lane_basis 中）、formula_registry_version、exam_source_version、选题所用 concept_evidence_versions 与其完整 source_refs；行须提供真实题号、source_kind、最后实际接触状态和本地原题/私有解析文件绝对路径。旧错题行另写 formal_id、formal_card_sha256、state_source_version、anchor_id；公式题行写 formal_id=null、formula_entry_ids、formula_registry_version、exam_source_version、source_record_sha256。精确值从已核候选与本机正式题卡/教学状态取，不用标题猜题。原题实质与页面必须经作者核验，题面安全内容与答案分开。省略 source_commit，不能把本地指纹冒充云端 commit。

调用 scheduler.py prepare-local-review-source --manifest-file 已核本地成稿.json。该入口按原候选重算、题图/解析、正式卡、状态版本及近7天/永久独立正确规则核验，注册 local_project_c_formula10；返回 SOURCE_REGISTERED_NOT_STUDIED。只有明确开始学习才 show-review-source。旧网页回包单用 import-review-source 验原发布及身份；待同步云端不阻挡新本地路径。

Already imported external_project_c sources keep their original provenance. Resume these from the registered local source. Historical delivery notes about uploading or waiting do not start a new transfer. Call show-review-source once at actual startup, then reuse the verified queue, original images and precomputed per-question profiles. Do not repeat selection or inspect all source code between questions. Every finished actual item, correct or incorrect, goes directly to wrong-intake with its actual typed source identity, returned capture_arguments, queue/item and complete current conversation. No score event is required. Preserve first answer, hints, corrections, available artifacts and the displayed write-up as raw evidence. A user's reported score is saved as their statement, not immediately applied to the schedule. B generated review exercises retain their separate evidence route.

## Canonical Entry

Work from the verified current math repository root. The real entry is the repository scheduler, never a script claimed to live inside this Skill:

```bash
python3 数学一回滚复习系统/scripts/scheduler.py --help
python3 数学一回滚复习系统/scripts/scheduler.py warmup-candidates --help
python3 数学一回滚复习系统/scripts/scheduler.py warmup-successor --help
```

Before creating a legacy native v5 queue, read `references/semantic-selection-v5.md`; new typed ten follows the v3 C flow above. Use the current local date unless the user supplies another date.

The old `warmup` queue and its public/internal files remain historical evidence. Do not overwrite, delete, or silently reuse an old queue when a new semantic selection is required.

## Evidence-stage Schedule

The scheduler resolves the configured window from the latest real learning activity and the evidence stage. The default first-version windows are deliberately ranges rather than claims of one scientifically exact interval:

| Current evidence stage | Default due window after latest real activity |
|---|---:|
| Wrong, unable to start, or corrected but not independently verified | 1-2 days |
| First no-hint independent correct result | 5-10 days |
| Second no-hint independent correct result | 18-35 days |
| Third no-hint independent correct result | 40-75 days |
| Repeatedly stable but retained for long-term maintenance | 75-120 days |

Use the scheduler's versioned configuration and make only bounded adjustments for the target examination date and remaining retention horizon. Do not prompt-engineer a fixed `1, 7, 31` schedule.

An activity date must come from documented contact with the real question: delivery or viewing, an attempt, an error, a redo, hint or solution exposure, or a formal learning result that records that interaction. File modification time, ingestion time by itself, Wiki or graph rebuild, relation maintenance, index refresh, and synchronization are not learning activity.

These windows determine when a gap anchor or repair deserves attention. They never override the delivered-card Day 0-7 gate.

## Two Separate Lanes

For an unresolved original card, the scheduler may expose a short repair lane:

```bash
python3 数学一回滚复习系统/scripts/scheduler.py same-item-repair \
  --date YYYY-MM-DD \
  --output ${MATH_COLD_ROOT}/DATE/BATCH/same-item-repairs.json
```

`same_item_repair` may return the original card after 1-2 days, but it is not one of the daily queue items, not a transfer check, and not evidence that the surrounding knowledge point is stable merely because the repeated route is fluent.

The daily queue instead tries to test transfer with another eligible formal old card. A recent original card may be a private anchor, but it must never be an actual daily delivery during Day 0-7.

## Hard Day 0-7 Delivery Gate

For target day `D`, exclude an actual `delivered_card_id` if any real learning activity for that card occurred from `D-7` through `D`, inclusive. Day 8 is the first eligible delivery day.

For example, on 2026-08-28, activity from 2026-08-21 through 2026-08-28 excludes the card; 2026-08-20 is the newest potentially eligible activity date. A recent card can only anchor a search for another old card outside the gate. Never use a recent card to reach the requested count; return fewer items.

## Legacy formal-only v5 selection and commit

First export the deterministic eligible range:

```bash
python3 数学一回滚复习系统/scripts/scheduler.py warmup-candidates \
  --date YYYY-MM-DD \
  --count 5 \
  --output ${MATH_COLD_ROOT}/DATE/BATCH/warmup-candidates.json
```

This step owns only configured stage windows, activity dates, Day 0-7 exclusion, formal identity, source version and hashes, permanent exclusions, deduplication, allowed roots, and the bounded candidate range. It must not use structured semantic labels to pick or rank the final five.

Then perform the native reader and parent verification protocol in `references/semantic-selection-v5.md`. The native reader must actually read the raw allowed candidate evidence and its result must decide or materially change the semantic ordering. It is invalid to let Python preselect five and ask Luna to endorse them.

After the parent reopens every cited selected byte and completes the fail-closed semantic plan, serialize the successor:

```bash
python3 数学一回滚复习系统/scripts/scheduler.py warmup-successor \
  --date YYYY-MM-DD \
  --count 5 \
  --candidate-bundle ${MATH_COLD_ROOT}/DATE/BATCH/warmup-candidates.json \
  --semantic-plan ${MATH_COLD_ROOT}/DATE/BATCH/warmup-semantic-plan.json \
  --supersedes-queue-id WQ-EXACT-OLD-QUEUE-ID
```

When replacing a queue, use the exact existing queue ID. Never fabricate it or edit old manifests/logs to bypass idempotency. If no prior queue exists, follow the current `warmup-successor --help` new-queue contract rather than inventing a superseded queue.

For `预览`, `只看候选`, or `不要记录`, stop after candidate export, the required native semantic read, and parent hash verification. Do not run `warmup-successor`.

If the reader fails, is decorative, exceeds scope, or lacks hash-bound evidence, discard the result. Retry only with the same bounded eligible set or stop. Never widen the date gate, admit an informal card, fall back to Python semantic ranking, or pad the queue.

## Explicit Knowledge-point Evidence

`warmup-candidate-bundle-v2` also exports `concept_evidence` as a paged workflow collection and `concept_evidence_contract` with scope, omitted keys and hashes. Each included point contains all saved events, observations and dialogue; never describe a bounded subset as complete global coverage. A stale index or changed source requires refresh, not a card-only fallback.

Use `anchor_id` for every anchor. A formal-card anchor additionally has a real `formal_id`; a `concept_review` anchor has `concept_key` and all `source_refs`, without a fake formal ID. Both independent review sessions and explicitly formalized point observations can supply the anchor. Wrong, unresolved and hint-corrected evidence enters the unstable window and must influence semantic priority. Correctness at a point never permanently excludes its related formal cards or creates card-level activity.

Use `warmup-semantic-plan-v3` and actual `reader_execution` for a selected concept anchor. Read its complete included events and source bytes, compare eligible old cards semantically, and reopen every source reference plus the selected card hash. The internal queue preserves the concept as `selection_anchor`; its scoring anchor and unit identify only the actual delivered formal card. Never advance a related original card or bulk-edit due dates from a point-level result.

Project C imports use `math-review-source-v2`, `selection_basis` and per-question `anchor_id` as specified in the reference. Older C sources remain readable; an old source that omits newer relevant concept facts must refresh before a new import.

## Semantic Value Order

Select only formal old cards and prefer, in order:

1. The same concrete wrong point or first method break.
2. The same fine-grained knowledge point.
3. An evidence-backed confusable method or condition boundary that tests discrimination.

Avoid redundant cards when another eligible card adds a stronger transfer check. The native reader compares those meanings from raw evidence; deterministic code does not infer them from tags. The parent retains the final judgment after reopening the same hashes.

## Answer Protection

Before the attempt, never publish an answer, standard solution, `wrong_point`, `method_gap`, private anchor reason, or any wording that reveals the needed method or lets the answer be inferred.

Use only each selection's reviewed `public_value_reason` to explain value. The public queue supplies identity and source, not necessarily a safe problem surface. Mark an unverified item `question_surface_pending`. Show a visual only when it is explicitly verified question-only.

## Per-item Links

Show every actual `delivered_card_id` as its own clickable Obsidian-opening entry. Never link the private anchor ID.

Resolve without opening an answer-bearing destination:

1. Use `http://127.0.0.1:8765/open/FORMAL_ID` when the verified bridge snapshot contains the delivered ID and the bridge is listening.
2. Otherwise use a URL-encoded `obsidian://open?vault=kaoyan-math&file=...` when the vault-relative path is verified.
3. Otherwise use a local-file link and state that no verified Obsidian route was available.

The visible label may use only public queue fields. Do not enrich it from private evidence or answer-bearing titles.

## Permanent Independent-correct Exclusion

Once an actual delivered formal card has verified no-hint independent-correct evidence, never deliver that card again in any warmup mode. It may remain a private anchor for finding a different never-correct card.

Canonical scores 4-5 trigger this exclusion. Score 3 alone does not, because it may be hint-assisted. Legacy text counts only when it explicitly proves whole-question no-hint, independent, or closed-book completion, or records the user's explicit statement that the current problem was independently correct. Partial, hint-assisted, inferred, or independence-unverified evidence cannot exclude the card.

## Verified Project C Delivery

For a source already imported through the Bridge, use its actual `run_id` with `scheduler.py show-review-source --run-id RUN_ID --date YYYY-MM-DD`. This verifies the registered original question hashes, creates the protected question display and appends one delivery to the existing warmup ledger. Show the returned exact original question paths. A `DISPLAY_READY` result is delivery preparation, never an answer or score. Do not expose the separate solution files or private reason.

Project C retains `external_project_c` provenance and its exact queue/item/run/commit identities. Keep these in the complete Capture and its source identity. During learning do not call `record-review-outcome`, `score-warmup`, `score` or postcommit, and do not add `--formal-intake` to bypass the Capture route. An older package's immediate-scoring instruction is superseded by this current workflow.

## Per-question Fast Capture

Throughout this Skill, a finished item means the user explicitly requested saving (“快速入库”, “保存这题”) or closure of the current item (“这题结束”, “进入下一题”, “下一题”). Only that signal triggers Capture preparation and saving, regardless of correctness; navigate according to the user's request. A request for a complete explanation, answer or exam-paper write-up, a correct answer, “懂了”, or the assistant finishing its explanation never triggers saving or navigation. Finish that teaching reply and remain on the current item. “继续讲” and “继续推导” continue teaching the same item. Apply this gate even when an earlier handoff says “每题完成后保存”; include it in newly generated study-start prompts. Explicit saving/closure does not authorize formal scoring. A read-only preview or a request not to save still controls its own scope.

Hand wrong-intake the actual delivered formal ID, existing attempt if any, current session/log, exact question-start message, date, queue/item, all available artifacts and the displayed write-up position. Use `capture_current_math.py` directly; if boundaries are missing, one `prepare` then one save. Pass `--queue-id QUEUE_ID --item-id QUEUE_ITEM_ID` without creating a score event. Never replace the delivered ID with the selection anchor.

After `recorded` or `noop`, `formal_write_count=0` and `score_write_count=0`, give the short saved receipt and show the next prepared question in the same turn when requested. Do not reopen packages, inspect scorers, refresh profiles or publish between questions. Reuse already verified question assets, links and unchanged profiles.

If an older event was already formally scored, preserve it and reuse the existing Capture/attempt; do not rescore or resave a completed item. A missing legacy score link is handled in formal intake or an explicitly requested repair, never by a source-code investigation during learning.

Later formal intake reads the complete pending Captures, checks any existing formal events to prevent duplication, and adjudicates scores, hint dependence, scheduling and knowledge-point updates together. Use enhancement-intake for a supplied A return, or nightly-qa for the authorized raw backlog.

## Quiet Learning Celebration

After verifying that the user's current answer correctly completes the current question or the explicitly checked subquestion, call the official Codex confetti tool once: `tools.mcp__codex_app__fire_confetti({})` through `functions.exec` (tool owner: `mcp__codex_app`). Both independent and hint-assisted correct answers qualify; celebration never upgrades independent mastery or authorizes a score, intake, or other learning write.

Do not fire for an incorrect or partly correct checked answer, an unchecked intermediate step, an explanation or closure alone, historical evidence, an audit fixture, or a replay. Keep answer protection and existing scoring/navigation rules. Deduplicate the same answer across retries and handoffs. If the tool is unavailable or its result is not `fired: true`, continue without claiming it fired; do not create a replacement script or retry the effect for that answer.

This Skill owns celebration for delivered warmup items, including an explicitly checked subquestion; a handoff to `kaoyan-math-question-worker` must not fire again. Deduplicate by the delivered item/subquestion and actual answer turn, using the stable `score_event_id` and `attempt_id` when already available. A score noop or replay is not a new answer; never create a score just to trigger confetti.

## Completion

Report the target date, actual count, new queue ID and exact superseded queue ID when applicable. For every delivered card report its public source, answer-safe entry, question-surface status, answer-safe value reason, and the latest verified real activity date proving it is outside Day 0-7.

Also report the candidate-bundle hash, the real native reader ID and observed execution metadata, and that the parent reopened the cited hashes. Do not expose the semantic plan's private reasons or private anchor evidence.

If the requested contract cannot be completed, report the exact shortage rather than padding or claiming completion. Stop before exposing an unsafe surface. For the legacy formal-only successor path preserve its own verification rules. A new local v3 source binds its local Codex origin, native candidate hash and source verification; never invent a remote commit or reader proof.

## Teaching, Current State And External Sources

The current root controls native engineering delegation without a fixed model/count/effort/fork/service tier. Never fabricate a legacy Luna proof to satisfy an older schema. Keep legacy queue receipts immutable; use only the currently supported input schema and source label. An external project-C selection must have its own provenance, exact source_commit and independent local eligibility checks; it is not a native-reader execution or a fabricated predecessor.

During the learner's actual question, use question-worker's entry on whichever model the user selected and 10–20-second substantive-feedback target and single best exam method. Apply question-worker's first-use version check to the prepared teacher context; if its version is absent, stale, or not yet verified for this question, use one bounded current question/concept query with the appropriate answer-protection view, then reuse that returned context for same-question follow-ups. Keep the frozen question, order and learning progress unchanged, and do not let old errors override correct current work. Teaching and Capture finish before formal intake; no formal postcommit runs on this real-time path. Preserve Day0-7, permanent independent-correct exclusion, the same-item repair lane, hint distinctions, and all public/private answer boundaries.

## 实际讲题的考频与选填输出

逐题讲解同时遵循question-worker的2026-10-27交付要求：每次实质讲解明示当前已公开考点的频次等级、去重考查次数及必要统计范围，不列具体年份或出现年份数；选择/填空先读取并核用choice_fill_guidance，二级结论须带公式/内容及适用条件。旧预处理只有方法名或结论ID不能当作读过完整依据；在当前题允许的view内通过原生有界查询及其候选/索引刷新恢复流程补当前个性化摘要、exam_frequency与技巧小包；首词未命中不得直接当作无摘要，精确预算不足按required_min_bytes补足一次。不改冻结题面/题序、不重发曝光或保存，不以统计或技巧要求绕过答案保护。

## 历史网页 C 回包的来源核查

C项目固定指令与每次交接按Study-Pro-Bridge/web-projects/C的PROJECT_INSTRUCTIONS.txt、WORKFLOW.md、MATH_WEB_ALIGNMENT.md。A直达交接保留已接受概况及有效偏好、步骤证据/范围、方法投影引用；旧包缺这些字段时用固定快照query(domain="personal_context")补读当前点，再用query(domain="math_methods")读精确方法/步骤/结论，不能把S/C ID冒充concept_key。exam_brief是派生导航；partial_operation、提示后、只看过、自报及未知均不提升为整题独立正确。

依据真实操作目标比较合格旧卡，方法条件与个人证据分别核对；不改变Day0–7、独立正确排除、真实活动日期、同目标久远优先和答案保护。B/C并发备题仍只产生各一份成品；最多5片只约束A输入分片，旧C v2仍5道正式旧题；新C v3按5正式错题+5公式真题交付10道。旧active/paused与已经接收的交接保持原身份，不为换固定说明重放学习、审核或导入。

## 仅历史网页 C 的 API 说明

每次新 C 交付携带当前 `MATH_WEB_ALIGNMENT.md`，核对其“现有 API 辅助入口与证据边界”与 `library(subject="math")` 的 `semantic_discovery`、`material_preprocessing` 声明；网页无需用户再次提醒，沿固定 `source_commit` 按说明使用既有 `query` 的 `semantic_candidates`、`material_prepare` 域。专用 `semantic_search` 尚未显示时沿原 `query` 域调用，不另建入口。精确候选/知识点优先原生读取，仅字面/别名定位不足时按需发现候选；只有已授权资料预处理需求才用视觉提取及疑义页复核，不为备题强制调用 API。候选相关度不决定资格或最终排序，提取稿不替代原图核读；API 缺失、降级或未筛查均明确保留，不能绕过本 Skill 的排除、答案保护和本地最终复核。
