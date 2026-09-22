# Targeted Rollback Closeout

Use rollback only when the final Sol decision and frozen evidence require a wrong, recurrence or eligible high-priority review update.

Preview the current formal ID with `scheduler.py upsert-wrongnet --id FORMAL-ID --date YYYY-MM-DD --dry-run`, adding `--expect-recurrence` for a verified recurrence. Apply the same command without `--dry-run` only after the preview matches the current formal-card source version and intended occurrence.

Accept only a verified success or same-source noop. Never replace this with bulk sync, never increment recurrence twice for multiple package representations of the same attempt, and never manufacture a wrong event for a representation update or rejected mastery candidate.
