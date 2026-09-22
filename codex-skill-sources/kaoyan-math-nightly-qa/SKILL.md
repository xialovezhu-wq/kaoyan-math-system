---
name: kaoyan-math-nightly-qa
description: "Complete evidence-backed formal intake for the cumulative math backlog through an Asia/Shanghai cutoff date, or for an explicitly narrowed exact capture/package set. Use for 夜间质检, 睡前集中优化, 正式入库, 高质量改写今天所有入库错题, 立即完整正式入库, or another clear formal-intake request. The same Sol plans all unconsumed captures through the cutoff, preserves each original study date, freezes and writes one date at a time, and resumes partial, committed, canonical-package archive, or typed legacy-evidence archive work without duplicate formal apply. After formal commit, every current complete package and every closed historical Capture without one must pass its matching verified T9 archive, Obsidian locator, receipt and local pointer gate. Never fabricate a legacy conversation or use Terra, MCP, resolver, consumer, AnalysisPackage, adoption, Dispatcher or background handoff routes."
---

# Kaoyan Math Formal Intake

## Outcome

Turn the user-authorized pending math package set into verified formal cards and derived layers with one Sol writer, then archive every current complete package and already-closed historical legacy evidence set to the verified T9 volume and bind their data-disk-relative locations into Obsidian locator notes.

The immutable package and ledger are the fact layer. Semantic findings are formal-intake decisions, not retroactive edits to the raw conversation.

Morning warmup and Project C questions now enter this same pending Capture backlog without foreground scores. Their missing score_event_id is expected, not a missing prerequisite. Read the saved actual answer, hints, correction, queue/item and source before adjudicating mastery and scheduling through the formal writer. Preserve a stated score as user evidence until adjudicated. If an older score already exists for the same real attempt, check that exact event and do not advance its schedule a second time. Scorer commands with --formal-intake belong only to an already authorized formal operation, never to a resumed learning turn.

## Authorization

For a normal formal-intake trigger, compute `cutoff_date` in `Asia/Shanghai` and authorize every capture with original `study_date <= cutoff_date` that has not reached a trusted formal terminal state. A date supplied by the user is the cutoff, not an implicit only-that-day filter.

Narrow the backlog only when the user explicitly says `only today` / `只处理今天`, or supplies an exact capture/package subset. Never silently strand older unconsumed captures.

`只读`, `只检查`, or `不要修改` forces report-only mode: read pending packages and report gaps without freeze, formal writes, archive, Obsidian locator notes or cleanup.

No pending events means stop. Do not scan unrelated history.

## Authoritative Pending Set

First read `references/backlog-through-date.md`, then run the read-only canonical planner:

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
  --payload-file /private/tmp/math-fast-intake-freeze-YYYY-MM-DD.json \
  --consume-payload-file
```

Reuse an active freeze; never create a second active freeze for the same capture. A failed freeze means no formal write. New-source missing evidence becomes `needs_user` and remains pending.

An active freeze is a resume target, not a new transaction. If formal state changed after the freeze, or an uncommitted closeout prepare exists, do not repeat the writer apply. Revalidate and resume the partial formal closeout or the closeout commit respectively.

## Prepared Project A content

For an explicitly supplied Project A math v5 package, use kaoyan-math-enhancement-intake. The already completed formal_card, exam_writeup, knowledge_point_reviews and profile_updates are the semantic input. Perform exact source/version/identity checks and resolve only concrete conflicts; do not reassign or repeat whole-batch semantic compilation. Original raw evidence remains immutable. The existing serial writer, archive and closeout below remain authoritative.

After all real closeouts of the exact supplied A batch, accept its prepared profile update through math_learning_profiles.py accept --input PREPARED_PROFILES --event-id CLOSEOUT (repeat --event-id for every batch closeout). Preserve the web-authored whole-batch concept update; do not force it into one date or bind it only to an unrelated final closeout. Completion additionally requires the updated full learning pages, compact teaching summaries and published personal-context version. Missing derived refresh is recovery-only, never another formal apply. A B review-audit uses its dedicated concept-review writer rather than creating wrong cards for generated exercises.

## Native Evidence Read Topology

After freeze, read references/native-luna-read-contract.md for the evidence envelope. The parent that owns the formal transaction decides whether genuinely independent reads benefit from delegation. An Ultra root uses the current engineering model and native proactive orchestration without loading orchestrate merely to enable concurrency. Non-Ultra substantial independent work follows the original orchestrate Skill. Do not impose a model, leaf count, effort, fork mode or service tier unless the user explicitly requires it for this task.

Every delegated read is bounded, read-only and tied to exact frozen paths/hashes. The parent reopens the cited bytes, resolves identity, mastery and relations, and performs every write serially. A leaf never allocates IDs, decides formal mastery or writes. Failed or ungrounded output is discarded; the parent continues from the raw evidence or records the precise unresolved item.

Do not revive Terra, Provider, MCP resolver/consumer, AnalysisPackage, Dispatcher or background formal-intake routes. Native engineering delegation is separate from the single-agent Astra low tutoring entry.

## Parent Formal Decisions

The parent independently decides:

- source and target identity, duplicate merge and formal ID allocation;
- confirmed user facts versus assistant teaching;
- first break, later breaks, independently correct steps and hint dependence;
- mastery, taxonomy, methods, traps and relations;
- final formal-card content and required derived-layer actions.

Do not convert assistant explanation into independent mastery or turn missing evidence into a user error. Multiple captures for one real question produce one formal-card write while preserving each event.

## Serial Formal Writer

Read `references/display-asset-closure.md`, then use the existing subject-local transaction in this order:

1. Patch each grouped formal card once and add the exact freeze-generated `fast_intake_refs` and `fast_intake_source_refs`.
2. For every source manifest, run the zero-write display plan and apply only its exact authorization. Promote displayable images into `错题知识网络/assets/visual_wrong_questions/FORMAL_ID/`, rewrite only managed visual references, refresh and verify bridge membership, and create one `math-display-asset-closure-receipt-v1`. A package with no formal ID must still create explicit `no_display_proof`; its images remain archive-only.
3. Run the repository-local linter for every created or changed card:

```bash
python3 数学一回滚复习系统/scripts/math_formal_lint.py \
  --repo /Users/your-user/Documents/kaoyan-math \
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
     --repo /Users/your-user/Documents/kaoyan-math \
     materialize --input /private/tmp/math-teaching-context-FORMAL_ID.json
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
  --repo /Users/your-user/Documents/kaoyan-math \
  --manifest REPOSITORY_RELATIVE_MANIFEST_PATH \
  --manifest-sha256 MANIFEST_SHA256 \
  --package-sha256 PACKAGE_SHA256 \
  --closeout-id MFI-CLOSE-ID \
  --terminal-outcome curated \
  --formal-id GS-900 \
  --archive-root /Volumes/T9-Data \
  --subject-relative-root '03_数学/资料库/原始会话资料'
```

Repeat `--formal-id` for every actual formal ID bound to the package; omitting all IDs is allowed only when the closeout itself has no formal ID. The command independently derives and compares the terminal outcome and formal-ID set from `capture_results`/`formal_results`, so caller labels are never authority. Before any new cleanup it reopens the exact display closure, proves all formal binary references are stable or explicitly no-display, and binds the closure receipt plus formal-reference scan into the archive intent, receipt and pointer. It then performs sentinel validation, stage-copy, tree and manifest verification, atomic finalization, locator-note write and reread, append-only archive receipt, then writes and rereads the recovery pointer before local attachment cleanup.

For a closed historical Capture with no `math-conversation-package-v1`, do not skip it or fabricate a package. First run a zero-write preview, then apply its exact content-derived authorization:

```bash
python3 数学一回滚复习系统/scripts/archive_legacy_evidence.py \
  --repo /Users/your-user/Documents/kaoyan-math \
  --capture-id MFI-CAP-ID

python3 数学一回滚复习系统/scripts/archive_legacy_evidence.py \
  --repo /Users/your-user/Documents/kaoyan-math \
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

Use `数学正式入库与原始包归档完成` only when both closeout and every package archive/locator receipt return `recorded` or verified `noop`. Report index and replica acceptance separately, and do not call the full authorized closeout complete until the final personalization publication below returns `PUBLISHED_CURRENT`.

## Teaching And Post-Commit Boundary

When choosing the formal solution representation, preserve the correct, fast and reliable single exam mainline owned by question-worker; do not replace a learner-approved route with multiple full derivations. Complete original dialogue and solution bytes remain intact. Teaching uses its separate Astra low task and complete 30-second target/40-second ceiling; formal curation retains the selected engineering runtime.

A successful closeout invokes the subject postcommit hook after releasing its write locks. That hook refreshes current formal learning state and the cross-question knowledge-key personal index, then requests one deterministic publication process; it does not run a model or wait on network inside a teaching reply. Local refresh and cloud publication are distinct results. On retries, resume the missing postcommit component without another formal apply; new review events must be effective in the next related teaching turn, including an already-open task.

## Current Project A Advice

When formalization is explicitly processing a verified Project A run, reopen its actual advice and original package evidence and decide every `(package_id, question_id)` item as accepted, modified, rejected or no_change. Record the result through `quick_intake.py record-advice-decision --payload-file` and verify through `verify-advice-decision --run-id`. A changed accepted/modified item must cite this run's real native closeout and after hash; an old closeout does not prove current advice acceptance. Rejected/no_change items create only the separate adjudication receipt, with no invented Capture, score or mastery. The command requests publication after releasing its lock; pending cloud sync is never authorization to replay formal writes.


The concept index is a derived teaching projection at `错题知识网络/个人知识点索引/index.sqlite3`. Verify `postcommit.concept_index.status` is `ready` or `noop`, retain its content `version`, and check the canonical formal-ID coverage after a formal library size change. A committed formal epoch invalidates an older index even if its rebuild fails; pending quick packages do not invalidate accepted personal history or become accepted events. Repair only this projection after a postcommit failure, never repeat formal apply.

After the batch's required archive/locator cleanup has completed, call the existing postcommit continuation once with the exact closeout ID and `--refresh-only` so archive references are current as well:

```bash
python3 数学一回滚复习系统/scripts/math_postcommit.py \
  --repo /Users/your-user/Documents/kaoyan-math \
  --event-id EXACT_CLOSEOUT_ID --refresh-only
```

Knowledge labels, aliases and content hashes are prepared during this maintenance path. Live tutoring uses the small `math_teaching_context.py resolve --concept ...` query; it must not rebuild or hash the full library. Preserve evidence roles: a material reference, an unadjudicated archived user excerpt, a hinted correction and an independently correct answer are distinct.


## Final Personalization Publication

Formal intake authorization includes refreshing the native personal knowledge index and publishing its read-only MCP replica; do this without another user reminder. After the final archive/locator continuation above returns `concept_index.status=ready|noop`, explicitly execute the same `math_postcommit.py --repo ... --event-id EXACT_CLOSEOUT_ID` command without `--refresh-only`. The refresh-only command remains refresh-only and does not publish.

The continuation keeps the business closeout ID unchanged and requests a derived publication event keyed by that ID plus the current index/formal version. Thus archive/locator changes can publish a successor instead of being suppressed by the first closeout publication. The descriptor exports `personalization/math/manifest.json` and its complete native records/aliases from a read-only SQLite transaction. Confirm the returned index version, publication event ID and publication/replica readback separately; a pending publication is not complete replica acceptance.

If index refresh, export, publication or replica synchronization fails after formal success, resume only that postcommit component with the exact original closeout ID. Never repeat formal apply, invent a learning event, or change mastery to repair a derived copy. A `PENDING` publication remains explicitly pending until publisher/replica verification succeeds.

After the deterministic publisher finishes, run the shared read-only final verification:

```bash
/usr/local/bin/python3 /Users/your-user/Documents/Study-Pro-Bridge/study_publication.py \
  verify-current --subject math
```

Require `status=PUBLISHED_CURRENT`: the verifier checks every personalization file hash and compares current native identity with the published replica. `STARTED`, an older success receipt, or `SYNC_PENDING` is not current replica acceptance. On failure, preserve formal success and resume only the missing postcommit/publication component.
