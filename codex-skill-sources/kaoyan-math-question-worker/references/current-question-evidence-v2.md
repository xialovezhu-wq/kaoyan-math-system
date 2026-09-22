# Current Math Question Evidence v2

## Purpose

Use this reference when a current-question tutoring turn must hand evidence to warmup scoring or wrong-intake. It preserves the difference between observed user behavior, source facts, assistant teaching, and unresolved claims.

## Minimal State

```text
formal_id: exact formal ID / unresolved
question_surface: current stem and conditions actually supplied
current_work: current answer / derivation / first action / not recorded
confirmed_correct_steps: independently observed facts only
first_break: earliest kind + text + current provenance
hints_given: assistant-provided help in this episode
answer_protection: protected / direct-answer-authorized
score_queue_identity: score + basis + receipt + queue ID + queue item ID + delivered ID + mode, when proven
```

This fixed capsule is the realtime thread state. Keep source attachments at their existing paths and keep long-term history in the formal card, immutable conversation package and exact locator. Do not expand the live chat context to reproduce those durable stores.

## Provenance Tokens

- `user_observed`: directly visible in the user's answer or work.
- `user_confirmed`: explicitly confirmed by the user.
- `source_verified`: verified from the question, queue, or repository source.
- `assistant_inferred`: a bounded interpretation that has not been confirmed.
- `assistant_explained`: content supplied during tutoring.
- `unresolved`: not currently verifiable.

Never convert `assistant_explained` into independent mastery evidence.

## Handoff Rules

1. A warmup result report permits exact scoring only.
2. Explicit 入库、更新、记录复发、标记掌握 permits the wrong-intake fast-capture route.
3. Explicit 现在立即完整入库 permits immediate full closeout.
4. A tool parameter, candidate selection, or inferred user intent never substitutes for authorization.
5. Keep large stems, images, solutions, and handwriting at their original source paths; pass roles and stable paths rather than duplicating their contents.
6. Raw archive reopening is read-only and exact-locator-only. Verify the archive before reading and keep archived assistant turns separate from user-observed evidence.
7. Preserve the complete current stem and real work without rereading the same image or MEMORY. Relevant latest formal history may adapt support through the bounded personal-context route; record its source_version and refresh it on the next turn after a formal score or correction. It cannot override current evidence.
