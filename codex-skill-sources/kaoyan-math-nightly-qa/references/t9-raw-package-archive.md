# T9 Raw Package Archive

New archive work runs only after the package's capture is committed by one successful `math-fast-intake-closeout-v3` event, whose formal targets already passed the required teaching-context gate, with a completed analyzed outcome: `curated`, `created`, `updated`, `already_current`, `skip`, `noop`, or `duplicate`. Historical trusted `math-fast-intake-closeout-v2` events remain archive-compatible and are never rewritten merely because they predate teaching contexts. `needs_user` and `failed` stay local and are never cleaned. The archive command verifies the closeout ID, terminal outcome and final formal-ID mapping before copying; the final ID list may be empty.

## Volume Identity

The exact archive root is `/Volumes/T9-Data`. Reject `/Volumes/T9-Data 1` and any alternate root.

Before every copy, verify `/Volumes/T9-Data/00_迁移管理/状态/volume-sentinel.json` with all three gates:

- SHA-256 `f086b32b29b2b38f1a28dffb8fde4fa850078332d8a23ae269cc8e857a6bd2ca`;
- `volume_name: T9-Data`;
- `volume_uuid: 00000000-0000-0000-0000-000000000000`.

Reject a symlink archive root and any symlink in an existing destination or staging parent component. Before creating a directory or copying bytes, resolve the planned destination against the verified root and prove it remains inside that exact T9 volume; recheck after parent creation and before atomic publish.

The math subject-relative root is `03_数学/资料库/原始会话资料`. The final package directory is that root plus `study_date/package_id`, always expressed relative to the T9 root in receipts and Obsidian.

## Required Order

1. Revalidate the complete immutable local package and formal closeout binding. Derive the actual archivable terminal outcome and formal IDs from closeout `capture_results`/`formal_results`; reject a forged caller outcome or omitted nonempty formal-ID set. Reopen the exact display closure for that manifest/formal-ID set and require zero temporary binary references. An empty formal-ID set still requires explicit `no_display_proof`.
2. Persist and reread one deterministic local archive intent. It fixes the archive intent ID and `archive_verified_at` across every retry.
3. Copy to a same-parent staging directory on T9.
4. Compare the full relative file tree, byte sizes and SHA-256 values; separately recheck manifest SHA and package canonical SHA.
5. Atomically rename staging to the final directory. An existing exact tree is an idempotent noop; any conflict fails closed.
6. Write `错题知识网络/wiki/sources/raw_archives/PACKAGE_ID.md`, reread identical bytes and hash it.
7. Append and reread one archive receipt in `数学一回滚复习系统/原始会话归档回执.jsonl`.
8. Bind display closure receipt ID/SHA, formal-reference scan SHA, stable-asset count, no-display proof and `pending_component` into the archive receipt and pointer. Only after display, archive and Obsidian path states are all verified, atomically write and reread `archive-pointer.json` with a cleanup intent. Only then remove local `attachments/`. Keep local manifest, conversation, source and package receipt so the pointer can be validated and cleanup can resume.

The locator note frontmatter contains exactly the archive authority fields: `type=raw_archive_locator`, `subject=math`, `package_id`, `formal_ids`, `archive_volume=T9-Data`, `raw_archive_relpath`, `raw_archive_manifest_sha256`, `raw_archive_package_sha256`, `archive_verified_at`, and `archive_status=verified`.

Do not edit `.base` files.

## Historical Capture Without A Canonical Package

A trusted closed historical Capture without `math-conversation-package-v1` is still archive-required. Classify it as `legacy_archive_pending/legacy_archive_only`; never call freeze, the formal writer, rebuild or closeout again.

Preview the exact capture with zero writes:

```bash
python3 数学一回滚复习系统/scripts/archive_legacy_evidence.py \
  --repo /Users/your-user/Documents/kaoyan-math \
  --capture-id MFI-CAP-ID
```

Only after checking the preview, apply the same content-derived authorization:

```bash
python3 数学一回滚复习系统/scripts/archive_legacy_evidence.py \
  --repo /Users/your-user/Documents/kaoyan-math \
  --capture-id MFI-CAP-ID \
  --apply \
  --authorization MATH-LEGACY-ARCHIVE-APPLY-SHA256
```

The caller supplies only the capture selector and exact preview authorization. The tool derives the freeze, closeout, formal IDs and terminal outcome from the replayed ledger. Its typed package preserves the selected raw ledger lines byte-for-byte; it also preserves the old source-bundle manifest and every artifact when present, or records `ledger_only` when none exists. It must state `conversation_complete=false` and `canonical_package=false` and must not create turns or claim a conversation package.

`ledger_only` is allowed only when the source-bundle field is truly absent or null. A present nonempty binding that is malformed, incomplete or unreadable fails closed; it must never be downgraded to ledger-only evidence.

For apply, hold the subject ledger lock and archive lock together, reread and replay the ledger, and recompute both the selected raw-line fingerprints and content authorization immediately before the first intent write. Any mismatch aborts before intent, staging, locator, receipt or pointer creation.

The same volume, staging, per-file verification, atomic publish, locator, receipt and pointer ordering applies. Legacy source artifacts are cleaned only after the legacy pointer is written and reread; the local manifest and pointer remain. Existing source-bundle readers may reopen a missing artifact only through that exact pointer after revalidating receipt, locator, T9 identity, archive manifest/tree and the requested file hash. Ledger-only packages have no heavy cleanup.

Cleanup is exclusive-reference only. Derive every current ledger Capture that effectively references the same source manifest/artifacts, plus any binding whose reference cannot be proved. Bind the resulting reference IDs/count, unprovable set and per-file delete-or-retain decision into preview authorization, receipt and pointer. Delete a heavy file only when the sole proven reference is the target Capture and the verified pointer covers its exact path/hash/size. Shared or unprovable files remain local and are reported. While holding both locks, recompute the proof immediately before every cleanup or resumed cleanup; any reference drift stops cleanup without deleting bytes.

Pointer ownership is per Capture, even when source bytes are shared. Preserve an existing `legacy-archive-pointer.json` when it belongs to the target Capture. If that single-file pointer belongs to another Capture, write and verify `legacy-archive-pointers/CAPTURE_ID.json`; never overwrite the other Capture's pointer. New transactions bind the selected repository-relative pointer path into authorization, receipt and pointer. Compatibility recovery may reuse an already persisted legacy authorization/receipt and add only the deterministic Capture-specific pointer, after which strict planner verification binds the actual selected path. Readers accept both the old single pointer and verified Capture-specific pointer directory.

Already-completed ledger-only transactions created before `local_pointer_path` remain read-only compatible. Accept them only by deriving the exact old authorization, deterministic intent/receipt IDs and old pointer field set, then verifying the current ledger facts, live T9 sentinel, exact archive tree/manifest, locator bytes, receipt row and pointer bytes. Never rewrite these old surfaces. Any mismatch is damaged; new ledger-only transactions always use the pointer-path v2 contract.

Planner completion reuses the same strict verifier. It rederives the current authorization and deterministic intent/receipt identities, requires exact field and byte bindings, validates the safe relative path and live sentinel, and compares the actual archived manifest and full tree. A synthetic pointer/receipt/locator trio is damaged evidence, not `already_consumed`.

## Recovery

If formal work is committed but any archive step fails, report `FORMAL_COMMITTED_ARCHIVE_PENDING`. Do not rerun formal-card, rebuild, rollback, Wiki or closeout work. Retry only the same archive command with identical package, closeout, hashes and formal IDs.

The cumulative backlog planner reports a canonical package failure as `archive_pending` with `resume_phase=archive_only`, and a no-canonical-package historical Capture as `legacy_archive_pending` with `resume_phase=legacy_archive_only`; both have `writer_apply_policy=forbidden`. Keep either in the final global residual gate until its matching pointer, receipt and locator verification all succeed; continue later study dates without consuming it twice.

Local heavy files remain until both the locator-note reread and append-only archive receipt reread pass. A pointer-write failure leaves the complete local package untouched. An existing verified pointer resumes incomplete cleanup; a completed pointer plus receipt is a verified noop on retry.
