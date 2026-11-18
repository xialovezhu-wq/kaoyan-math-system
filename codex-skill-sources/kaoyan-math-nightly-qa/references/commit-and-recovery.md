# 单写者提交、归档与中断恢复

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
     materialize --input ${MATH_COLD_ROOT}/DATE/BATCH/context-FORMAL_ID.json
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
  --archive-root ${STUDY_ARCHIVE_ROOT} \
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

交接使用原生 `maintenance_summary`。分别给正式事实、原事件或维护 ID、同版必需与可选组件、发布和独立读回。`completed_local` 沿用核心刷新含义，待恢复阶段和原失败保留在原回执；按 `recovery.actions` 续接，发布阶段使用原发布身份。没有同版阶段依据时保留 unknown 或 stale，不补写学习。外部资料的 `source_verified` 只供参考；独立步骤和明确偏好依赖原生核验的用户轮次。

## Current Project A Advice

When formalization is explicitly processing a verified Project A run, reopen its actual advice and original package evidence and decide every `(package_id, question_id)` item as accepted, modified, rejected or no_change. Record the result through `quick_intake.py record-advice-decision --payload-file` and verify through `verify-advice-decision --run-id`. A changed accepted/modified item must cite this run's real native closeout and after hash; an old closeout does not prove current advice acceptance. Rejected/no_change items create only the separate adjudication receipt, with no invented Capture, score or mastery. The command requests publication after releasing its lock; pending cloud sync is never authorization to replay formal writes.


The concept index is a derived teaching projection at `错题知识网络/个人知识点索引/index.sqlite3`. Verify `postcommit.concept_index.status` is `ready` or `noop`, retain its content `version`, and check the canonical formal-ID coverage after a formal library size change. A committed formal epoch invalidates an older index even if its rebuild fails; pending quick packages do not invalidate accepted personal history or become accepted events. Repair only this projection after a postcommit failure, never repeat formal apply.
