---
name: kaoyan-math-weak-edge-audit
description: "Bounded read-only semantic review of the existing `生成/弱边审计清单.md` backlog or an explicit set of formal-ID edge pairs. Use for 弱边审计, 继续弱边审计, 清理弱边清单, or a named pair such as 审计 GS-902 与 GS-903 的边. Under current SHADOW policy, produce keep, delete, or needs-user proposals from independent fine-grained evidence but do not edit formal `related`. When the user says 我一个个看 or asks for a 待裁决目录, output a numbered directory and stop until the user chooses one item. Do not use for today's card-quality/relationship closeout, generic 复核错题关联, new intake, or full-library taxonomy work; today's bounded closeout belongs to kaoyan-math-nightly-qa."
---

# Kaoyan Math Weak Edge Audit

## Outcome

Review a bounded weak-edge backlog or explicit edge set and classify every in-scope logical edge as `保留提案`, `删除提案`, or `需用户裁决`, using both formal cards and independent mathematical evidence. Current SHADOW mode is proposal-only.

## Trigger And Mode

Valid scope is one of:

- `错题知识网络/生成/弱边审计清单.md`, default maximum 40 entries;
- explicit formal-ID pairs supplied by the user;
- one numbered item previously selected from a decision directory.

The generic request “审核今天的错题，让关系更紧密” belongs to `kaoyan-math-nightly-qa`. Route it there and stop.

All current runs are read-only because `formal_write_in_shadow` is false. “我一个个看”, “列目录让我裁决”, or equivalent means decision-directory mode: enumerate all pending pairs with short evidence summaries and stable numbers, then stop. Later review only the one number the user selects.

## Decision Evidence

Read both formal cards for every edge. Ignore existing `related` while deciding whether the relationship is mathematically supported.

Use the current `AI维护规则.md` and `schema/relationship_signal_policy.json`:

- Keep or promote only with the same concrete trigger plus another structure signal, the same concrete first action, the same specific trap, a specific question template plus method, or a verified progressive topic chain.
- Delete or reject when support is only a chapter, broad knowledge, generic method, generic error cause, generic action-gap type, text similarity, or generated score.
- Escalate when source identity, fine-grained mechanism, or topic-chain role is genuinely ambiguous.

Existing `related`, the generated checklist, and similarity scores are candidate signals and cannot self-prove the edge.

## Canonical Storage Boundary

The logical edge is undirected but current formal storage allows one canonical declaration. The repository does not define an owner algorithm. Do not enforce reciprocal entries, choose an owner, move a declaration, or normalize duplicates inside this skill.

Every proposal names the current declaration state and the independent rationale. A future formal edit requires both a mode/policy change and a shared canonical-owner rule outside this skill.

## Execution Boundary

Parse and deduplicate the selected edge set, group pairs sharing a card, then read the necessary cards. This skill stays one Agent because semantic decisions are tightly coupled.

Do not modify formal cards, `related`, rationale, generated files, Wiki, or review state, and do not run a write rebuild. The generated checklist remains a candidate source, not an editable output.

## Stop Conditions

- In decision-directory mode, stop immediately after the complete numbered directory.
- Stop at the requested/default limit and report remaining backlog.
- A missing card is a structural blocker, not automatically a mathematical `需用户裁决`.
- A stale or missing checklist requires a normal rebuild or explicit-pair scope; do not invent entries.
- A request to apply proposals is blocked by current SHADOW policy; report the required policy change rather than writing.

## Completion

For each pair report IDs, proposal, independent evidence, and current declaration location if any. Summarize keep, delete, user-decision, structural-blocker, and remaining counts; confirm `formal writes: 0` and `rebuild: not run`. In decision-directory mode, give the numbered directory and wait for the user's selection.

## Current Read And Teaching Boundary

Read the exact named formal cards and current relationship policy through the canonical local route. Use real current evidence; no mandatory cold-MCP request or source bundle may self-prove a relationship. Keep proposal-only SHADOW, canonical-owner uncertainty and the user's decision-directory stop intact.

If a concrete question needs explanation, hand it to question-worker's separate Astra low teaching entry and its complete 30-second target/40-second ceiling. That explanation uses the latest relevant formal history and one fast, reliable exam mainline; edge-audit metadata neither overrides current work nor authorizes a second full method or answer disclosure.

