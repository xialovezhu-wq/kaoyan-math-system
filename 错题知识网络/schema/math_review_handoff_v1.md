# 数学项目 B 审核与项目 C 交接合同

本合同把项目 B 的本地学习、GPT-6 审核、正式知识点更新和项目 C 交接分开。B 只封存完整原始证据，不创建 Capture、正式知识点观察、错题卡、评分或掌握度记录。GPT-6 才能基于完整证据提交唯一正式学习事件。

入口：`错题知识网络/scripts/math_review_handoff.py`。

## 1. B 原始证据

结束学习后，用一个命令指定本地 Codex rollout、真实 session、精确消息边界、真实起止时间、原 B 复盘包和附件映射：

```bash
python3 错题知识网络/scripts/math_review_handoff.py preserve \
  --rollout /absolute/path/to/rollout.jsonl \
  --session-id CODEX_SESSION_ID \
  --study-date YYYY-MM-DD \
  --started-at 'YYYY-MM-DDTHH:MM:SS+08:00' \
  --ended-at 'YYYY-MM-DDTHH:MM:SS+08:00' \
  --start-line FIRST_B_LEARNING_MESSAGE_LINE \
  --end-user-line FINAL_B_USER_MESSAGE_LINE \
  --end-assistant-line FINAL_VISIBLE_ASSISTANT_MESSAGE_LINE \
  --review-package /absolute/path/to/B-review-package.zip \
  --artifacts-json /absolute/path/to/artifacts.json
```

边界是原 JSONL 的 1-based 物理行号，闭区间。`start-line` 必须是可见用户或助手消息；`end-user-line` 必须是本场最后一个可见用户消息；可选 `end-assistant-line` 只能包含其后的最后一个可见助手收尾，中间不能跨过另一条用户消息。没有助手收尾时省略 `--end-assistant-line`。没有未自动解析的附件时省略 `--artifacts-json`。

附件映射沿用快速入库的形状，但本入口不会调用快速入库或 Capture：

```json
{
  "artifacts": [
    {
      "message_line": 123,
      "block_index": 0,
      "role": "question_image",
      "path": "/absolute/path/to/image.png"
    }
  ],
  "missing_attachments": [
    {
      "message_line": 130,
      "block_index": 1,
      "reason": "原附件已不可取得"
    }
  ]
}
```

`preserve` 使用 `math_session_io.py` 读取精确范围，保存范围内原 JSONL 字节、逐字会话、原 B 包文件和实际附件。稳定 `session_id` 决定唯一 `B-REVIEW-EVIDENCE-*`。相同内容重试为 `noop`；同一 session 的不同内容拒绝，不覆盖已经封存的字节。

纯图片或其他非文本消息在原 JSONL 和附件归档中保持原字节，`conversation.json` 对应 turn 的 `text` 为空。正式 `concept-review-session-v1` 要求每个 turn 有非空文本，因此审核入口只在其派生副本中写入带原物理行号的 `[non-text message preserved verbatim ...]` 定位标记；该标记不是用户作答内容，审核必须回到原块和附件判断，不能把标记当作学习事实。

读回命令同时校验全部归档文件，并返回精确来源清单、归档清单和完整会话：

```bash
python3 错题知识网络/scripts/math_review_handoff.py read \
  --session-id CODEX_SESSION_ID
```

来源文件仍存在时，结果区分 `exact`、`changed`、`missing` 或 `unavailable`。来源缺失不损坏已经逐文件哈希验证的归档。

`math-b-review-evidence-v1` 的 manifest 包含：

- `project=B`、`subject=math`、`evidence_id`、`session_id`、真实 `study_date/started_at/ended_at`；
- rollout 的绝对来源路径、session、精确边界、所选原字节 SHA-256 与大小；
- B 包的来源类型、manifest SHA-256、run/source commit 和逐文件归档；
- `message_boundaries`、逐字 `conversation.json`、附件和明确缺失附件；
- `archive_files[]` 的相对路径、SHA-256 与大小；
- `write_scope=raw_evidence_only_no_capture_no_formal_observations`。

## 2. GPT-6 审核输入

GPT-6 应先完整读取 B 证据和相关知识点历史，再编写 `math-review-audit-v1`。不得从助手讲解反推用户掌握，不得把未作答记成错误，也不得把 B 生成题建立成正式错题卡。

```json
{
  "schema": "math-review-audit-v1",
  "subject": "math",
  "evidence_session_id": "CODEX_SESSION_ID",
  "audit_summary": "只写证据支持的本场短结论",
  "observations": [
    {
      "observation_id": "stable-observation-id",
      "concept_key": "MATH-CONCEPT-000000000000000000000000",
      "question_ref": "B-package-question-id",
      "outcome": "wrong|independent_correct|corrected_after_hint|unresolved",
      "error_detail": "wrong 时填写第一处明确错误；其他结果可为空字符串",
      "user_turn_indices": [0],
      "hint_turn_indices": [],
      "related_formal_ids": []
    }
  ],
  "assistant_mistakes": [
    {
      "mistake_id": "stable-assistant-mistake-id",
      "assistant_turn_indices": [1],
      "finding": "助手原回复中可核对的问题",
      "correction": "核实后的修正"
    }
  ],
  "profile_updates": {
    "schema": "math-learning-profile-update-v1",
    "updates": [
      {
        "concept_key": "MATH-CONCEPT-000000000000000000000000",
        "overview": "证据支持的完整知识点概况",
        "short_summary": "后续讲题可直接读取的短摘要",
        "progress": ["按时间或证据描述变化，不虚构表现"],
        "next_check": "下一次需要独立检查的具体动作",
        "source_refs": [
          {"path": "repository/relative/evidence", "sha256": "64-hex"}
        ]
      }
    ]
  }
}
```

`timeline` 是单个 update 的可选字段。脚本会把本次 B 原始 manifest 的仓库相对路径与真实 SHA-256 补入每个 update 的 `source_refs`，随后调用 `math_learning_profiles.prepare_updates(root,payload)`。所有规范键、观察证据索引、关联正式 ID 和来源哈希仍由现有本科校验器检查。

`profile_updates` 的知识点集合必须与 `observations` 的知识点集合完全相同，避免正式事件提交后才发现摘要缺失或多写了本场没有观察的知识点。入口在冻结审核输入前执行现有 session 校验；结构、证据索引或知识点不合法时不会留下正式事件或占用该 session 的审核回执。

提交命令：

```bash
python3 错题知识网络/scripts/math_review_handoff.py audit \
  --input /absolute/path/to/math-review-audit.json
```

顺序固定为：

1. 校验原始 B 归档并运行 `prepare_updates`；
2. 在正式写入前持久保存原审核输入、规范化摘要 payload 和待提交 `concept-review-session-v1`；
3. 调用 `math_concept_review.commit_session(..., postcommit=False)`；
4. 读回真实已提交事件后调用 `accept_updates(root,prepared,event_id)`；
5. 调用既有 `math_postcommit.run_after_commit`，刷新知识点页、短摘要索引和发布；
6. 只在 `verify-current --subject math` 返回 `PUBLISHED_CURRENT` 后生成项目 C ZIP。

任一步在正式提交后失败，都只恢复尚未完成的后续阶段，不重算已冻结的审核/profile basis，也不重复接受已经成功的 profile：

```bash
python3 错题知识网络/scripts/math_review_handoff.py resume \
  --evidence-id B-REVIEW-EVIDENCE-32_HEX
```

同一 `session_id` 精确重试先核对并复用冻结的审核输入、profile 和唯一 `CONCEPT-REVIEW-*` 事件，事件数不增加；已完成时只校验并返回既有 C ZIP。若该 session 已有不同的不可变正式内容，返回 `required_correction_unsupported`，保留原事件并等待显式支持的修订路径；不得覆盖旧记录，也不得伪造第二次学习。

## 3. 项目 C 交接

C ZIP 只在以下状态同时成立时生成：真实正式事件可读回；知识点更新已 `accepted` 或幂等 `noop`；本地 postcommit 的学习状态与知识点索引已刷新；发布读回为 `PUBLISHED_CURRENT`。

ZIP 固定包含：

- `START_HERE.md`：本场短结论、各知识点短摘要、下一检查点和 C 使用边界；
- `handoff.json`：`math-c-handoff-v1` 结构化依据、正式事件、助手错误修正、审核时 profile 更新和最新发布身份；审核时 profile 明确标为 audit-as-of，当前状态以 `latest_mcp_snapshot` 为准；
- `refs.json`：每个来源的路径与 SHA-256，以及最新已发布 snapshot 读回。

C 只能从现有正式错题卡选择真实旧题，继续保护答案。B 生成题只作为本场证据，不能成为正式错题卡，也不能冒充原题复做、计分或掌握度更新。
