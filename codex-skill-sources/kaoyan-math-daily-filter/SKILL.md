---
name: kaoyan-math-daily-filter
description: "Post-study selection of already ingested formal math wrong cards. Use only after the user has finished a section or a set of questions and asks for 学习后的五道题, 根据今天这些错题筛旧题, 纠错题, 迁移检查, or an equivalent shortlist grounded in explicit completed formal IDs. Rank exact personal-gap matches first, then clearly labeled shared-knowledge fallback; exclude day 0 through day 7 activity and return fewer cards when necessary. Never author a math question. Do not use for 今天开始学习选五道, 让我今天做五道, morning/due review, or any request made before the current study set exists; those belong to kaoyan-math-warmup."
---

# Kaoyan Math Daily Filter

## Outcome

Return at most five existing formal old cards whose redo value is supported by the explicit formal IDs completed in the current study set. Make no writes and never create a question.

## Trigger Gate

Trigger only when both conditions hold:

1. the user is asking after a completed section or question set; and
2. the anchor set can be identified from explicit formal IDs in the current task or from IDs the user supplies.

The real-world phrase “今天的学习选出五道你认为最有价值的错题，让我今天做” is a study-start request. Route it to `kaoyan-math-warmup` and stop; do not load this skill's ranking workflow.

If the user asks AI to invent “new correction, variation, or transfer questions”, explain that math question generation is disabled and offer a shortlist of existing formal cards only. If no reliable completed anchor exists, ask only for the missing formal ID or route to warmup when the intent is study-start.

## Success Criteria

- Anchor IDs come only from the completed current set; never scan the library to guess what “today” means.
- Run one unified `intake_recommend.py` command for the whole anchor set.
- Rank concrete `wrong_point`, `missed_action`, `expected_first_action`, `method_trigger`, or supported `method_gap` matches before any knowledge fallback.
- A fallback card must share a literal formal `knowledge` label with an anchor and be labeled `knowledge_fallback — 不代表同一错因`.
- Exclude anchors, `status=已掌握`, and cards with actual learning activity from day 0 through day 7; day 8 is the first default eligible day.
- Permanently exclude every actual delivered card with verified no-hint independent-correct evidence. Canonical scores 4-5 count; score 3 by itself does not because hint-assisted completion may receive 3. Explicit legacy text must prove whole-question independent, closed-book, or no-hint correctness; the user's own explicit statement that the current problem was done correctly also counts under the user's declared vocabulary. Partial-step, hint-assisted, or system-inferred result-only text does not count. Later downgrade or failure never restores the card.
- Initial intake, wrong/redo history, mastery scoring, and actual delivery are activity. Relation maintenance, Wiki synchronization, file modification time, or rebuild time alone do not restart the seven-day clock.
- Explicit current-task evidence that a candidate formal card was substantively updated also excludes it, even if the card lacks a dated history row. The repository has no complete historical ledger for undated metadata updates, so report the audited event sources and never claim stronger historical completeness.
- Return fewer than requested when evidence-backed formal cards are insufficient.
- For every result report formal ID, source, latest actual learning date, attempt count, all recorded dates, match tier, evidence provenance, and a specific selection reason.

## Evidence Route

After the trigger gate passes, read `references/daily-filter-workflow.md`. Read `references/output-template.md` only when composing the final response.

Run once for the complete anchor set:

```bash
python3 错题知识网络/scripts/intake_recommend.py --date YYYY-MM-DD --seed-id GS-902 --seed-id LA-910 --top 5
```

The repository loader attributes proxy scores to the actually delivered formal card and includes formal-card learning history. The old Skill script is only a compatibility forwarder; do not add another activity loader.

The generated snapshot is a candidate source, not self-validating truth. For each final seed and candidate, compare ranking-critical evidence with the live formal card. If the snapshot is stale or disagrees with the live card, stop this read-only run and route the rebuild to an explicitly authorized write workflow; do not rebuild inside daily-filter or continue ranking from stale evidence.

The repository loader audits formal `date`, `wrong_history`, `mastery_history`, rollback first/recurrence dates, delivered review events, and warmup delivery. The repository recommender must reuse the scheduler's permanent-delivery exclusion set so the same card cannot re-enter through exact, related, or knowledge-fallback paths. Also apply any explicit current-task update evidence. An undated historical update that appears in none of those sources is not reconstructible; disclose that boundary rather than treating file mtime as learning activity.

Use at most two meaningful read-only fallbacks: inspect the live card or query `wrongnet.py related ID --ignore-declared`. Do not build a second recommender.

## Decision Rules

Tier one requires the same concrete action gap, first-action failure, trigger, or reliable wrong point. A correct solution route, broad chapter, generic method, weak score, or `related` field alone cannot prove it.

Tier two is allowed only after tier one is insufficient. It requires a literal shared formal knowledge label and cannot be described as the user's same error. Preserve `user_confirmed`, `model_inferred_from_solution`, and `pending_user_confirmation` as different evidence states.

Missing time is `时间未记录`; missing count is `次数未记录`; missing ranking-critical evidence is `待确认`. Never infer user mastery or cause from problem difficulty or standard analysis.

## Stop Conditions

- Stop after at most five eligible formal cards.
- Stop with fewer cards when the library or evidence is insufficient.
- Stop and report stale evidence when live cards and the generated snapshot conflict.
- Stop this skill immediately after routing a study-start request to warmup.

## Completion

Use `references/output-template.md`. Confirm the run was post-study and read-only, list the anchor IDs, state the day-0-through-day-7 exclusions, and say explicitly that no question or data was created. Prefer an Obsidian-opening link, but do not expose answer text in chat.

## Current Read And Teaching Boundary

Use the canonical repository recommender and live formal evidence. Do not add an MCP canary, a second recommender or a model benchmark to a live shortlist. Candidate projections do not establish the same personal error by themselves.

If the learner proceeds to one selected problem, route to question-worker's separate Astra low entry: latest relevant formal history, one fast and reliable exam mainline, the complete 30-second target/40-second ceiling, and unchanged answer protection. Selection itself remains read-only and is not evidence of a completed review.

