---
name: kaoyan-math-review-audit
description: 在新的 GPT-6 任务中审核一个已封存的项目 B 数学复盘：读取完整原始会话和相关个人历史，核对首答、提示后变化及助手错误，提交唯一知识点事件与短摘要，并只在发布 current 后生成项目 C 交接 ZIP。只用于 B 数学收尾审核，不用于本地 B 教学、普通单题入库或直接选 C 题。
---

# 项目 B 数学 GPT-6 审核

本 Skill 由用户在新的 GPT-6 任务中调用，并随请求提供已结束的 B 任务链接或任务 ID。它负责证据审核、正式知识点更新和 C 交接。B 生成题永远不是正式错题卡。

## 取得完整证据

使用 Codex 任务读取工具打开用户给出的 B 任务，确认其 `session_id`、`evidence_id`、原 B 包位置和 evidence manifest 回执。任务摘要只能帮助定位，不能代替完整证据。

完整读取 `/Users/your-user/Documents/kaoyan-math/错题知识网络/schema/math_review_handoff_v1.md`，然后运行：

```bash
cd /Users/your-user/Documents/kaoyan-math
python3 错题知识网络/scripts/math_review_handoff.py read \
  --evidence-id B-REVIEW-EVIDENCE-32_HEX
```

`read` 必须返回 `status=verified`、精确 `source_manifest`、逐文件验证的 `archive_manifest`、完整 `conversation`、消息边界、附件和真实缺失附件。原 rollout 或 B 包已经移动时，可以使用校验通过的归档；来源状态为 `changed` 或归档校验失败时停止正式写入。

完整读取归档中的 `review-package/manifest.json`、`START_HERE.md`、`review_plan.json`、`student/questions.jsonl` 以及判断本场回答所需的私有题目依据。不要执行归档脚本。核对 project B、math、题目身份与来源快照。

## 审核

逐题区分用户首答、助手提示、用户修改和未完成状态。只记录实际出现的行为：

- `independent_correct` 必须有提示前的完整用户证据；
- `wrong` 必须定位用户首答中第一处明确错误并引用对应 user turn；
- `corrected_after_hint` 必须同时引用更早的 assistant hint 和更晚的 user turn；
- `unresolved` 不能自动记错或记会；
- 助手讲解、正确答案或总结不证明用户掌握。

同时独立检查本地助手的数学判断、提示是否泄漏答案、是否把首答与提示后答案混淆，以及是否错误描述进步。`assistant_mistakes` 只写可由题目依据和原回复核对的错误；没有则使用空数组，不为完整性编造问题。

从实际题目和作答确定精确知识点键后，按相关概念批量查询一次当前个人历史：

```bash
python3 错题知识网络/scripts/math_teaching_context.py \
  --repo /Users/your-user/Documents/kaoyan-math \
  resolve --concept '稳定键或精确知识点名' --view direct \
  --full-evidence --max-bytes 20000
```

审核属于非实时流程；budget_too_small时按required_min_bytes扩大读取或定点读取原文件，不把空页当作没有历史。只有缺少会改变审核结论的具体记录时才按返回的 `next_cursor.offset` 追加 `--offset OFFSET --expected-version VERSION` 读取下一页。历史用于判断进步和下一次检查点，不能覆盖本场原话，也不能把相同标签当作相同错误。

## 正式更新和 C 交接

按合同生成一个 `math-review-audit-v1` JSON。`observations` 覆盖实际可判断的本场知识点；`profile_updates` 为每个提交知识点提供完整 `overview`、面向后续讲题的 `short_summary`、证据化 `progress`、具体 `next_check` 和真实哈希来源。不要写学习时长推测、心理原因、虚构掌握度或未发生的作答。

运行唯一入口：

```bash
python3 错题知识网络/scripts/math_review_handoff.py audit \
  --input /absolute/math-review-audit.json
```

入口会在正式提交前冻结审核输入、规范化 profile payload 和待提交 session；随后调用现有 `math_concept_review.commit_session`，读回真实事件，再接受 profile 更新并运行既有 postcommit。不要另行直接调用这些 writer。

同一 session 的完全相同正式内容重试为 noop，仍只算一个学习事件。同一 session 已有不同内容时，入口返回 `required_correction_unsupported`；保留不可变旧记录并报告需要显式支持的修正路径，不换 session、不新建学习事件、不覆盖旧文件。

若结果为 `publication_pending`，保留 state 并按返回的命令只恢复尚未完成的后置阶段；已提交的事件、已接受的 profile 和冻结 basis 不重复执行：

```bash
python3 错题知识网络/scripts/math_review_handoff.py resume \
  --evidence-id B-REVIEW-EVIDENCE-32_HEX
```

只有正式事件读回、profile 接受、知识点页/索引刷新且发布验证为 `PUBLISHED_CURRENT` 后，结果才会包含 `c_handoff.status=ready` 和 ZIP 路径。完全相同的已完成审核只校验并返回原有 ZIP，不重新生成。C 包包含 `START_HERE.md`、结构化 `handoff.json`、带最新发布快照与来源哈希的 `refs.json`；审核时 profile 明确标为 audit-as-of，当前状态以 `latest_mcp_snapshot` 为准。把该 ZIP 交给项目 C；不得在 pending 状态手工拼包或声称 C 已就绪。
