---
name: kaoyan-math-warmup
description: "数学晨间、学习前五题和到期旧题的选题与预处理。已准备队列直接逐题学习，复用 question-worker 快速讲解和 wrong-intake 完整 Capture；实时不评分或更新长期调度，正式处理留到晚间入库。保留原生语义选题、Day 0-7、独立正确排除、答案保护和精确交付身份。学习后按已完成正式ID筛题使用 daily-filter。"
---

# Kaoyan Math Warmup

仅当收到恢复检查点、progress.overall_status为partial/blocked，或报告仍有未完成项时，先转kaoyan-math-web-recovery保全并续接；不要拒绝后结束。完整业务包附有complete进度报告时照常接收，不循环转回恢复Skill。补齐后回到本Skill，已完成的学习与正式提交不重放。

## Outcome

At study start, deliver up to the requested number of answer-protected formal old cards. Deterministic code decides eligibility and identity; a bounded native reader does the real semantic reading and value comparison; the owning parent reopens the same bytes and owns the final decision and the only serialized queue write.

Finish selection and prepare the whole question set before the learner starts. During learning, use the shared question-worker and wrong-intake path for every actual question. Record complete raw Capture evidence only; formal scores, long-term scheduling, mastery, indexes and publication belong to later user-authorized formal intake.

## Project C daily execution

Already imported external_project_c sources keep their original provenance. Call show-review-source once at actual startup, then reuse the verified queue, original images and precomputed per-question profiles. Do not repeat selection or inspect all source code between questions. Every finished actual item, correct or incorrect, goes directly to wrong-intake with its delivered formal ID, queue/item and complete current conversation. No score event is required. Preserve first answer, hints, corrections, available artifacts and the displayed write-up as raw evidence. A user's reported score is saved as their statement, not immediately applied to the schedule. B generated review exercises retain their separate evidence route.

## Canonical Entry

Work from `/Users/your-user/Documents/kaoyan-math`. The real entry is the repository scheduler, never a script claimed to live inside this Skill:

```bash
python3 数学一回滚复习系统/scripts/scheduler.py --help
python3 数学一回滚复习系统/scripts/scheduler.py warmup-candidates --help
python3 数学一回滚复习系统/scripts/scheduler.py warmup-successor --help
```

Before creating or replacing a queue, read `references/semantic-selection-v5.md`. Use the current local date unless the user supplies another date.

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
  --output /private/tmp/math-same-item-repairs-YYYY-MM-DD.json
```

`same_item_repair` may return the original card after 1-2 days, but it is not one of the daily five, not a transfer check, and not evidence that the surrounding knowledge point is stable merely because the repeated route is fluent.

The daily queue instead tries to test transfer with another eligible formal old card. A recent original card may be a private anchor, but it must never be an actual daily delivery during Day 0-7.

## Hard Day 0-7 Delivery Gate

For target day `D`, exclude an actual `delivered_card_id` if any real learning activity for that card occurred from `D-7` through `D`, inclusive. Day 8 is the first eligible delivery day.

For example, on 2026-08-28, activity from 2026-08-21 through 2026-08-28 excludes the card; 2026-08-20 is the newest potentially eligible activity date. A recent card can only anchor a search for another old card outside the gate. Never use a recent card to reach the requested count; return fewer items.

## Queue Selection And Commit

First export the deterministic eligible range:

```bash
python3 数学一回滚复习系统/scripts/scheduler.py warmup-candidates \
  --date YYYY-MM-DD \
  --count 5 \
  --output /private/tmp/math-warmup-candidates-YYYY-MM-DD.json
```

This step owns only configured stage windows, activity dates, Day 0-7 exclusion, formal identity, source version and hashes, permanent exclusions, deduplication, allowed roots, and the bounded candidate range. It must not use structured semantic labels to pick or rank the final five.

Then perform the native reader and parent verification protocol in `references/semantic-selection-v5.md`. The native reader must actually read the raw allowed candidate evidence and its result must decide or materially change the semantic ordering. It is invalid to let Python preselect five and ask Luna to endorse them.

After the parent reopens every cited selected byte and completes the fail-closed semantic plan, serialize the successor:

```bash
python3 数学一回滚复习系统/scripts/scheduler.py warmup-successor \
  --date YYYY-MM-DD \
  --count 5 \
  --candidate-bundle /private/tmp/math-warmup-candidates-YYYY-MM-DD.json \
  --semantic-plan /private/tmp/math-warmup-semantic-plan-YYYY-MM-DD.json \
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

The authorized morning learning workflow includes saving each finished actual item, regardless of correctness. A request to keep going or quickly save does not authorize formal scoring. A read-only preview or a request not to save still controls its own scope.

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

Stop with fewer than five rather than padding. Stop before exposing an unsafe surface. Stop before a write if exact queue identity, actual native semantic execution, same-byte Sol verification, or successor idempotency cannot be proven.

## Teaching, Current State And External Sources

The current root controls native engineering delegation without a fixed model/count/effort/fork/service tier. Never fabricate a legacy Luna proof to satisfy an older schema. Keep legacy queue receipts immutable; use only the currently supported input schema and source label. An external project-C selection must have its own provenance, exact source_commit and independent local eligibility checks; it is not a native-reader execution or a fabricated predecessor.

During the learner's actual question, use question-worker's current user-selected DeepSeek-V4.1-Flash entry and 10–20-second substantive-feedback target and single best exam method. Reuse the prepared related profile without letting old errors override correct current work. Teaching and Capture finish before formal intake; no formal postcommit runs on this real-time path. Preserve Day0-7, permanent independent-correct exclusion, the same-item repair lane, hint distinctions, and all public/private answer boundaries.
