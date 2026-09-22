# 不支持正常入口时的人工保存

仅当前会话没有可读日志，或显式补充同一次已保存事件时使用。不得为普通单题改用本路线。

### Manual fallback

Use the payload steps below only when the current task has no readable rollout, exact boundaries cannot be established, or a same-episode supplement requires the existing supplemental contract. Preserve the complete dialogue; do not drop a missing image-only message or silently substitute a summary to use the fast path.

Before freezing the package, check the current handoff: when the user closes the question and requests quick intake, the question-worker must first display its concise `卷面写法` if the complete problem can be solved and checked and no explicit answer-protection or save-only instruction remains. If it is missing, complete that question-worker step in the foreground before returning here; do not proceed straight to `stage-source` merely because the last teaching turn was a local explanation or no user final number was supplied. The displayed solution remains assistant evidence, not proof of independent user mastery. Missing conditions, explicit answer protection, or an explicitly unfinished/save-only request keep the evidence-only route.

Create one compact stage payload with `apply_patch` under `/private/tmp`. Include every user and assistant turn related to this question in original order. Do not summarize, trim, rewrite, keep only first/last turns, or omit later correction rounds.

When `kaoyan-math-question-worker` has already surfaced a math-first `卷面写法` before a synchronized quick-intake handoff, preserve that exact assistant turn verbatim in `conversation`. Do not generate a write-up inside this intake Skill, and do not summarize, expand, reformat or replace the displayed version with a second version. If no authorized completed write-up exists because the question is unresolved or answer-protected, preserve the current evidence only.

Raw conversation text and solution_text attachments are evidence, not structured routing metadata. Preserve solution_text as the exact original UTF-8 bytes, including CRLF and leading/trailing whitespace; do not normalize it. Preserve conversation text verbatim even when the user pasted a local absolute path or the mathematics contains a drive-like LaTeX fragment such as `S:\quad`; do not redact or rewrite those turns. The local-path prohibition still applies to structured `source` identities, Capture target/thread fields, and every durable locator. Artifact `path` may be an absolute temporary input only because `stage-source` immediately copies and hash-binds it under the repository package; the manifest stores the repository-relative copy.

```json
{
  "schema_version": "math-conversation-package-stage-v1",
  "package_key": "STABLE_ATTEMPT_ID",
  "study_date": "YYYY-MM-DD",
  "timezone": "Asia/Shanghai",
  "source": {
    "source_locator": "STABLE SOURCE LOCATOR",
    "question_id": "KNOWN ID OR null",
    "formal_id": "KNOWN GS/LA/PR ID OR null",
    "session_id": "KNOWN ID OR null",
    "item_id": "KNOWN ID OR null",
    "capture_identity": "STABLE_ATTEMPT_ID"
  },
  "conversation": [
    {"role": "user", "text": "EXACT USER TURN"},
    {"role": "assistant", "text": "EXACT ASSISTANT TURN"}
  ],
  "artifacts": [
    {"role": "question_image", "path": "/absolute/temporary/question.png"},
    {"role": "explanation_image", "path": "/absolute/temporary/explanation.png"},
    {"role": "user_work_image", "path": "/absolute/temporary/user-work.png"},
    {"role": "solution_text", "path": "/absolute/temporary/solution.txt"}
  ],
  "missing_fields": []
}
```

Allowed attachment roles are `question_image`, `solution_image`, `explanation_image`, `user_work_image`, `source_article_image`, `other_attachment`, and `solution_text`. Include all currently available files. Missing images, solution text or metadata do not block quick capture; name each known absence in `missing_fields`. Do not fabricate a substitute or use a formal-card answer as the current solution text.

Run:

```bash
python3 数学一回滚复习系统/scripts/quick_intake.py stage-source \
  --payload-file /private/tmp/math-conversation-package-STABLE_ID.json \
  --consume-payload-file
```

Success is `recorded` or `noop` with `state: conversation_package_staged`, repository-relative `manifest_path`, `manifest_hash`, `package_id`, `package_sha256`, `formal_write_count: 0`, `background_processing: none`, and zero model/MCP calls. The package contains `manifest.json`, `conversation.json`, `source.json`, `attachments/`, and `receipt.json`.

For an initial package, `package_key`, `source.capture_identity`, and Capture `attempt_id` must match. Retain any already known formal ID in `source.formal_id` (or a formal `source.question_id`); it must match the Capture target. Do not infer a formal ID for a new question.

The same package identity and different bytes fails closed. Never overwrite or mutate a package. For a later attachment or correction in the same episode, create a new stable `package_key`, set `source.capture_identity` to the original Capture attempt ID, and add `source.supplements_capture_id` with the original Capture event ID. The second Capture keeps the original attempt ID, study date, target and score event ID, and uses `requested_action: update_representation`. The writer validates the parent and appends a package-specific supplemental event. Retry that same payload for a noop; never invent a new attempt or request a new recurrence merely to bypass a conflict.

## Capture V3

Create a second compact payload with `apply_patch`:

```json
{
  "schema_version": "math-fast-intake-capture-v3",
  "attempt_id": "STABLE_ATTEMPT_ID",
  "study_date": "YYYY-MM-DD",
  "target": {
    "kind": "formal_card",
    "formal_id": "GS-900",
    "source_locator": null,
    "source_hash_before": null
  },
  "score_event_id": "SCORE-... OR null",
  "requested_action": "record_recurrence",
  "thread_ref": "TASK REFERENCE OR null",
  "conversation_package": {
    "manifest_path": "REPOSITORY-RELATIVE manifest.json",
    "manifest_hash": "64-CHAR LOWERCASE SHA-256",
    "package_sha256": "64-CHAR LOWERCASE SHA-256"
  }
}
```

Allowed requested actions remain `record_wrong`, `record_recurrence`, `update_representation`, and `mastery_candidate`; they preserve the user's requested operation, not a semantic conclusion. Do not add `evidence`, `episode_evidence`, first-break, mastery-score, taxonomy, relation, release, activation, authority, consumer, adoption, analysis-package, Terra, MCP, or background-handoff fields.

Run:

```bash
python3 数学一回滚复习系统/scripts/quick_intake.py record \
  --payload-file /private/tmp/math-fast-intake-STABLE_ID.json \
  --consume-payload-file
```

Success requires `recorded` or identical-evidence `noop`, `capture_schema_version: math-fast-intake-capture-v3`, matching package IDs and hashes, `state: awaiting_sol_formalization`, integer `formal_write_count: 0`, `background_processing: none`, zero model/MCP calls, and consumed payload. This state never schedules background or nightly work. Do not analyze or process the package until the user explicitly starts formal intake.

## Recovery

The initial event ID remains stable for attempt plus target identity; a same-episode supplemental event also binds its original Capture and new package ID. Same identity and same bytes is a noop; changed bytes fail closed. If package staging succeeds but Capture fails, retain the immutable local package and retry the same Capture once. After one failure, return the package and payload identities without claiming success.

Outside the live path, `quick_intake.py verify --date YYYY-MM-DD` replays the ledger and rehashes legacy bundles plus v3 package files.

