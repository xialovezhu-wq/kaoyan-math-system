# Visual Review Boundaries

## Protected Data

The review workflow never edits:

- `错题知识网络/错题卡/*.md`;
- `错题知识网络/生成/`;
- `数学一回滚复习系统/复习单元.json` or `复习记录.jsonl`;
- raw screenshots, PDFs, source notes, Chronicle records, or source exports.

It does not run wrongnet rebuild or scheduler write commands.

## Authorization

- An ordinary request to summarize or review authorizes inspection and a chat response only.
- An explicit request for HTML, saving, or a finished artifact authorizes one file and, if needed, one safe review/wiki subdirectory inside this project.
- Updating Tutor/StudyVault or adding another durable summary still requires that requested scope; creating the necessary safe subdirectory is covered by the explicit artifact request.
- Formal card changes and unified redo selection route to their dedicated skills.

## Safe Artifact Locations

Prefer an existing project-approved directory such as:

- `错题知识网络/wiki/reviews/`;
- `错题知识网络/wiki/operation_center/review_outputs/`.

Do not save to the repository root, `错题卡/`, `生成/`, rollback folders, or raw-source directories. If no existing safe directory is suitable, create one project-local review subdirectory for the explicitly requested artifact. Do not overwrite another artifact or broaden the project scope.

## Evidence Protection

The artifact may contain IDs, short source handles, topic labels, concrete error patterns, method gaps, first-action reminders, and tomorrow’s route. It must not reproduce complete problem statements, long solutions, answer keys, source images, or private screen history that is not needed for the review.

Missing facts remain `待确认`, `未记录`, `待补充`, or `待评分`. Never infer date, duration, ID, source, wrong cause, mastery, or redo result from screen context alone.
