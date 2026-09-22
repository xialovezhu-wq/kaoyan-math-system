# 数学知识点复盘正式会话 v1

本合同面向一场结束后的知识点复盘。学习中不生成 Capture；全部会话一次校验、一次原子提交，正式锚点只用已有 `MATH-CONCEPT-<24 hex>`。错误机制是 observation 的 `error_detail`，不创建互斥知识点，也不创建生成变式题的正式 ID。

## 输入

根对象字段必须齐全，schema 为 `concept-review-session-v1`，subject 为 `math`：

- `session_id`：稳定的原始会话/task 标识（非空，最多 128 字符）；可含路径样式字符，存储目录由数学科目和完整标识的哈希决定，不把原始标识拼进路径。
- `study_date`：`YYYY-MM-DD`，必须是 `started_at` 在 Asia/Shanghai 的日期。
- `started_at`、`ended_at`：带时区的 ISO 时间，结束不能早于开始。目标 1800 秒；超时只记录 `over_budget`，不丢弃真实学习证据。
- `conversation`：按原顺序保存完整 `{role: user|assistant, text: 原话}` 数组。不可摘要、拼造或删减。程序校验结构与被引原话，完整性仍由调用者按整场对话负责。
- `artifacts`：文件路径字符串，或 `{path, sha256?, role?, name?}`；path 可为相对 repo 或绝对本地路径。全部文件复制封存，逐件哈希与原件核对；role/name 原样保留。无附件时显式空数组。
- `observations`：数组，每条具有下列全部字段，不接受静默丢失的未知字段。

Observation 字段：

- `observation_id`：本会话内唯一标识。
- `concept_key`：精确存在的规范知识点键，不接收未知键、显示名或模糊别名。
- `question_ref`：本复盘包的题号或局部引用；生成变式也只用此字段。
- `outcome`：`wrong`、`independent_correct`、`corrected_after_hint`、`unresolved`。
- `error_detail`：真实错误/表现的说明。wrong 必须非空；其余允许空字符串。不能从标签关联推断错误。
- `user_turn_indices`：零基整数数组，必须非空，全部指向 user 原话；不可重复。
- `hint_turn_indices`：零基整数数组，全部指向 assistant 原话；不可重复。independent_correct 不允许提示引用；corrected_after_hint 必须存在早于所引修正作答的提示。
- `related_formal_ids`：已与本知识点关联的正式题 ID 数组，可以为空；仅来源关联，不表示这些题本轮被复做。

首次明确作答错误、后来提示后修复应写两条 observation，分别引用各自真实原话。`corrected_after_hint` 不能自行反推出前面一定有一次错误；`unresolved` 可能只是未完成，不能自动算错。同一 session、同一 concept，`wrong_session_count` 最多为 1，所有 observation 仍完整保留。不将旧卡错误条目数累计为新知识点复发数，也不根据一次表现修改长期掌握度。

## 权威与恢复

权威目录：`数学一回滚复习系统/知识点复盘/正式会话/CONCEPT-REVIEW-<hash>/`。

目录中的 `session.json` 保存完整规范输入、知识点绑定、身份和内容哈希，`artifacts/` 保存复制后的文件。暂存目录位于权威目录外；文件 fsync 后整体 rename 是唯一提交点。不存在需要与之双写的权威 ledger。

相同 session_id、相同内容重试为 noop；不同内容拒绝。原附件已移动时，可用已封存且校验通过的文件恢复同一提交。提交之后的索引或发布失败返回 `committed: true` 和 pending 状态，只重试 postcommit，不重放学习事实。

## 索引与展示

`math_concept_index` 索引新来源为 `kind=concept_review` 的个人证据，关联同一个知识点键；不插入正式错题卡 history，不写复习记录、调度或 Capture。查询将概念复盘视为个人证据，不占普通材料限额。`resolved.review_markers` 只计算新增完整会话。

`protected` 隐藏 session_id、question_ref、错误细节、完整原话、附件内容与原文件名；仅保留知识点、聚合数量与匿名来源定位。`after_attempt` 提供观察摘要，`direct` 额外提供完整会话。发布快照包含完整源会话和附件的 `source_mappings`，不是不可读的仓库路径孤立引用。

可重建入口：`错题知识网络/个人知识点索引/知识点复盘/index.md`；单点页按 concept_key 命名，链接既有 Wiki 与关联正式题，显示新会话标记。页面是派生视图，不建立另一套语义权威。

## 命令

```sh
python3 错题知识网络/scripts/math_concept_review.py refresh
python3 错题知识网络/scripts/math_concept_review.py commit --input /absolute/session.json
python3 错题知识网络/scripts/math_concept_review.py recover --event-id CONCEPT-REVIEW-...
```

`refresh` 只更新结构和投影，不创建正式学习事件。commit/recover 的 `--refresh-only` 禁止请求网络发布但完成本地刷新。隔离测试通过 `--repo-root` 指定临时仓库；测试不得在正式库写入 fixture 会话。
