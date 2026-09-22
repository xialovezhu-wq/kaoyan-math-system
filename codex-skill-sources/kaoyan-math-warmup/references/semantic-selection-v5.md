# Semantic Selection V5

Read this file for every new or replacement warmup queue. The protocol makes deterministic eligibility and model semantic judgment independently auditable.

## 1. Deterministic Candidate Bundle

Run the repository entry:

```bash
python3 数学一回滚复习系统/scripts/scheduler.py warmup-candidates \
  --date YYYY-MM-DD \
  --count 5 \
  --output /private/tmp/math-warmup-candidates-YYYY-MM-DD.json
```

Reopen the output and record its SHA-256. Accept only a schema/version supported by the current scheduler help.

Deterministic code owns:

- configured evidence-stage due windows and bounded examination-horizon adjustment;
- latest real learning activity and the inclusive Day 0-7 exclusion;
- formal-card identity, exact allowed roots, source version, path and SHA-256;
- permanent independent-correct exclusion, deduplication and idempotent identities;
- a bounded eligible candidate range and final serialized write gates.

It must not choose the final five by `wrong_point`, `method_gap`, topic tags, Wiki clusters, title similarity, or another semantic proxy. The exported ordering is not the value ranking.

## 2. Native Semantic Read

Let the current root choose useful independent readers through its supported native orchestration. Do not fix model, count, effort, fork mode or service tier unless explicitly requested. Pass only the exact candidate bundle/hash, allowed roots and identities, and a bounded semantic comparison task. Readers must actually inspect raw allowed evidence and report exact hashes; they cannot write, allocate IDs, change eligibility or decide formal mastery.

A call that merely endorses Python-preselected cards is invalid. The semantic reading must materially determine the order. The parent retains final judgment and reopens the same cited bytes. Preserve observed runtime metadata truthfully; never fake Luna fields for an external source or a different native execution.

## 3. Semantic Question

Ask the reader to compare evidence in this order:

1. `exact_gap`: the same concrete wrong point or first method break.
2. `fine_knowledge`: the same fine-grained knowledge point when exact-gap evidence is unavailable.
3. `confusable_boundary`: an evidence-backed easy-to-confuse method, applicability condition, or boundary that tests discrimination.

Within a level, prefer stronger raw evidence, clearer transfer value, and a set that avoids redundant checks. Do not use recency to relax eligibility; every candidate has already passed deterministic gates. Return fewer selections when the evidence cannot support the requested count.

For each recommendation, The reader returns:

- `rank`, `anchor_id`, and `delivered_card_id` from the bundle;
- one allowed `match_level`;
- `private_reason` grounded in raw semantics;
- an answer-safe `public_value_reason` that reveals no answer, solution, private wrong point, first method break, or method cue;
- exact anchor and candidate evidence paths with their observed SHA-256 values.

## 4. Parent Sol Reopen

The parent Sol must reopen the candidate bundle and every selected anchor/candidate evidence path. Recompute and compare all cited hashes. Independently verify:

- the candidate is inside the exported allowed set;
- formal identity and source version match;
- latest real activity is outside Day 0-7 for the delivered card;
- permanent independent-correct exclusion did not apply;
- the public reason and question surface are answer-safe;
- The reader's private semantic reason is supported by the same bytes.

The parent owns final judgment. Reject a bad selection. Do not replace it from outside the bundle, relax a hard gate, or ask Python to rank semantics. If replacement is useful, ask a bounded native reader to read the remaining bounded set, then reopen its evidence again.

## 5. Semantic Plan V1

Create the plan only after the native reader result and Sol reopen succeed. Use this minimum shape; preserve any additional fields required by current scheduler help:

```json
{
  "schema_version": "warmup-semantic-plan-v1",
  "candidate_bundle_sha256": "SHA256",
  "luna_execution": {
    "agent_id": "NATIVE_AGENT_ID",
    "model": "gpt-5.6-luna",
    "reasoning_effort": "max",
    "read_only": true,
    "semantic_read_performed": true,
    "status": "completed"
  },
  "semantic_ordering_decided": true,
  "sol_verification": {
    "sol_reopened": true,
    "verified_at": "RFC3339_TIMESTAMP",
    "verified_evidence": [
      {"path": "ALLOWED_PATH", "sha256": "SHA256"}
    ]
  },
  "selections": [
    {
      "rank": 1,
      "anchor_id": "FORMAL_ANCHOR_ID",
      "delivered_card_id": "FORMAL_DELIVERED_ID",
      "match_level": "exact_gap",
      "private_reason": "PRIVATE_HASH_GROUNDED_REASON",
      "public_value_reason": "ANSWER_SAFE_REASON",
      "alternatives_considered": [
        {"delivered_card_id": "OTHER_ELIGIBLE_ID", "reason_not_selected": "PRIVATE_COMPARISON"}
      ],
      "evidence": [
        {"role": "anchor", "path": "ALLOWED_PATH", "sha256": "SHA256"},
        {"role": "candidate", "path": "ALLOWED_PATH", "sha256": "SHA256"}
      ]
    }
  ]
}
```

Do not claim `semantic_read_performed=true` unless the native leaf actually read raw candidate bytes. Do not claim `sol_reopened=true` until the parent recomputed the hashes.

Keep `private_reason` and private anchor evidence out of public output. `public_value_reason` still requires Sol answer-safety review before it is shown.

## 6. Append-only Successor

For an existing queue, submit only through:

```bash
python3 数学一回滚复习系统/scripts/scheduler.py warmup-successor \
  --date YYYY-MM-DD \
  --count 5 \
  --candidate-bundle /private/tmp/math-warmup-candidates-YYYY-MM-DD.json \
  --semantic-plan /private/tmp/math-warmup-semantic-plan-YYYY-MM-DD.json \
  --supersedes-queue-id WQ-EXACT-OLD-QUEUE-ID
```

The scheduler must fail closed on a bundle/plan/hash/Luna/Sol mismatch. It owns the new queue ID, locks, atomic derived writes and idempotent noop behavior.

After submission, reopen both queue manifests and the append-only log. Prove the old queue bytes are unchanged, the new queue records the exact predecessor, and a repeated identical submission returns the same successor/noop. Never edit an old log or manifest by hand.

## 7. Failure Boundary

If candidate export, Luna, Sol reopen, answer-safety review, or successor validation fails:

- keep Day 0-7 and permanent exclusions unchanged;
- do not admit informal or recently active cards;
- do not use Python semantic fallback;
- do not pad to five;
- do not write or mislabel a queue as complete.

Return the verified subset only when the scheduler accepts a hash-bound plan for that subset; otherwise stop with the precise failed gate.

The JSON shown above is the historical v1 Luna binding. Retain it only for a genuinely matching legacy execution. Current native or external-C inputs require their supported distinct contract; a model name is not an execution proof. Teaching itself follows question-worker and never launches this selection protocol during a live single-question explanation.


## 8. Concept anchors and project C v2

The candidate schema is `warmup-candidate-bundle-v2`. Read the `anchors`, `eligible_candidates` and `concept_evidence` workflow collections through EOF; inspect `concept_evidence_contract.omitted_concept_keys` before claiming scope completeness. All events for an included point are retained. Bounds are explicit, and no observation or dialogue is cut in the middle.

For native concept selection use `warmup-semantic-plan-v3`; replace historical `luna_execution` with `reader_execution` containing observed `agent_id`, `execution_kind: native_subagent`, `read_only`, `semantic_read_performed`, and `status: completed`. `selections[].anchor_id` is the concept key. Include every anchor `source_refs` entry with role `anchor` and the delivered formal-card entry with role `candidate`; parent verification must reopen all of them. Existing v1/v2 card-only plans remain supported.

A C source uses `schema_version: math-review-source-v2`. Keep the existing exact run, commit, original surface and per-card state bindings, add each question's `anchor_id`, and add:

```json
{
  "selection_basis": {
    "schema_version": "warmup-candidate-bundle-v2",
    "candidate_bundle_sha256": "HASH_FROM_WORKFLOW",
    "concept_evidence_versions": [
      {
        "concept_key": "MATH-CONCEPT-24_HEX_DIGITS",
        "point_source_version": "HASH_FROM_CONCEPT_EVIDENCE",
        "source_refs": [{"path": "EXACT_SOURCE_PATH", "sha256": "EXACT_SHA256"}]
      }
    ]
  }
}
```

For each considered point, copy the union of all event source references. Include every selected concept anchor and all points with explicit facts associated with the selected formal cards. The local importer checks the selected anchor remains due, all delivered cards remain eligible, current point versions, complete source references, and published source hashes. The candidate-bundle hash is preserved as selection provenance; independent local gates and per-point versions decide freshness so an unrelated point update does not invalidate the selection.

Do not infer matching error from formal-card association. Exact gap, fine knowledge and boundary comparisons remain model judgments grounded in the full evidence. Concept-derived queue scores apply solely to the actual delivered question, retain its exposure and independent-correct exclusion, and do not mark the point or related cards mastered.
