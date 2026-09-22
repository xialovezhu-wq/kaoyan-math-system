# Backlog Through Date

## Canonical Planning

The ordinary formal trigger is cumulative. Compute `cutoff_date` in `Asia/Shanghai`, then run the read-only `quick_intake.py backlog-through-date --cutoff-date YYYY-MM-DD` entry. Its `plan` is canonical JSON and `plan_sha256` binds the exact ledger snapshot, selection, original dates, classifications and execution contract.

Only `--only-today` or explicit repeated `--capture-id` / `--package-id` arguments may narrow the cumulative set. Future captures are excluded and reported separately.

## Per-Date Barrier

Process `date_groups` by ascending original `study_date`. Before every group, replay the current ledger. Reuse the existing per-date `pending`, `all_pending_for_date` or explicit-subset freeze, serial writer and closeout APIs. Preserve the capture's `study_date`; the cutoff date is not an artifact date and is never written over historical learning facts.

No freeze, writer apply, closeout or archive transaction may cross two study dates.

## Resume Classification

- `pending`: freeze once, then apply once after the normal gates.
- `resume/frozen_formal_processing`: reuse the active freeze; apply only after revalidation.
- `resume/partial_formal_closeout`: formal state already changed; do not repeat apply.
- `resume/closeout_commit`: an uncommitted prepare exists; do not repeat apply, resume the same closeout.
- `archive_pending/archive_only`: trusted formal closeout exists; never repeat formal work, resume only archive.
- `legacy_archive_pending/legacy_archive_only`: trusted formal closeout exists but the historical Capture has no `math-conversation-package-v1`; never call freeze or formal work, and run only the authorized typed legacy-evidence archive command.
- `already_consumed`: trusted formal closeout and required archive receipt/locator/pointer are complete; exclude from work.
- `needs_user` or `failed`: keep the exact residual and continue later dates.

## Final Gate

Persist the initial response unchanged. After all date groups, pass that file back with `--baseline-plan-file`. Verify its SHA before use. The final gate must list `completed`, `already_consumed`, `needs_user`, `failed`, `archive_pending`, `legacy_archive_pending` and every cutoff-bounded `residual`. A closed historical Capture is not complete merely because no canonical conversation package exists; it remains a legacy archive residual until its typed receipt, locator and pointer verify. Do not summarize the whole backlog as complete while any residual remains.
