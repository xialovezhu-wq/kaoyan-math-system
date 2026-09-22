# Exact Raw Archive Reopen

Use this reference only after the current formal card and already-available Obsidian evidence are insufficient and they identify one exact locator note.

Do not search the raw-archive directory or T9. Pass the exact repository-relative locator note to the read-only reopen command.

Do not substitute a formal ID, source ID or fuzzy retrieval key for the locator. One formal card may bind multiple historical packages, so locator discovery during a learner turn is outside this skill.

Verify only:

```bash
python3 数学一回滚复习系统/scripts/archive_conversation_package.py \
  --mode reopen \
  --repo /Users/your-user/Documents/kaoyan-math \
  --locator-note '错题知识网络/wiki/sources/raw_archives/PACKAGE_ID.md' \
  --read-kind verify \
  --archive-root /Volumes/T9-Data
```

Read the exact conversation when it is necessary:

```bash
python3 数学一回滚复习系统/scripts/archive_conversation_package.py \
  --mode reopen \
  --repo /Users/your-user/Documents/kaoyan-math \
  --locator-note '错题知识网络/wiki/sources/raw_archives/PACKAGE_ID.md' \
  --read-kind conversation \
  --archive-root /Volumes/T9-Data
```

Select one exact attachment by role and one-based index:

```bash
python3 数学一回滚复习系统/scripts/archive_conversation_package.py \
  --mode reopen \
  --repo /Users/your-user/Documents/kaoyan-math \
  --locator-note '错题知识网络/wiki/sources/raw_archives/PACKAGE_ID.md' \
  --read-kind attachment \
  --attachment-role question_image \
  --attachment-index 1 \
  --archive-root /Volumes/T9-Data
```

The command rejects the wrong volume, `/Volumes/T9-Data 1`, unsafe paths, mismatched locator filenames, manifest/package hashes, undeclared files and imprecise attachment selections. It never lists the archive root.

For an image, inspect only the returned exact `archive_path`. For text, use the returned verified text. Preserve answer protection and provenance; archived assistant content is not independent user work.
