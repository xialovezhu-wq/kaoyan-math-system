# 数学快速入库事件与夜间收口合同

## 目标

学习中的单题错题记录以“立即保存当前题完整原始会话与附件、尽快释放会话”为目标。高质量正式卡改写、first break、mastery、taxonomy、关系判断、全量 wrongnet 重建、定向回滚和 Wiki 收口统一移到用户明确触发的正式入库回合。

这个拆分不降低证据标准。它把不可变的学习事实与可优化的正式表示分开：

- `快速入库来源/YYYY-MM-DD/MATHPKG-*/` 保存逐轮完整 user/assistant 原话、题图、解析图、作答图、solution text、来源身份、缺项与全部哈希。
- `快速入库事件.jsonl` 只追加对不可变会话包的事实绑定，不在快速阶段写 first break、mastery、taxonomy 或关系结论。
- 正式错题卡、回滚单元、wrongnet 生成层和 Wiki 是夜间根据这些事实更新的表示层。
- 夜间不得反向覆盖、删改或“润色”快速事件中的原始事实。
- 快速包、`attachments/` 和 `快速入库来源/` 中的二进制路径只属于临时证据层，禁止成为正式 Obsidian 图片引用。正式 writer 必须先复制到 `错题知识网络/assets/visual_wrong_questions/<FORMAL_ID>/`、改写引用并形成 `math-display-asset-closure-receipt-v1`，才可进入归档清理。

## 权威文件

- 快速事件账本：`数学一回滚复习系统/快速入库事件.jsonl`
- 新临时来源固化目录：`数学一回滚复习系统/快速入库来源/`
- 写入工具：`数学一回滚复习系统/scripts/quick_intake.py`
- 并发锁：`数学一回滚复习系统/.快速入库事件.jsonl.lock`
- 来源固化锁：`数学一回滚复习系统/.快速入库来源.lock`
- 正式收口锁：`数学一回滚复习系统/.正式层写入.lock`

锁文件不是学习数据，必须由 Git 忽略。账本采用追加式 JSONL；`pending` 状态由 capture、amendment、freeze、prepare、invalidation 与 closeout 回放得到，不原地修改旧事件。

## 白天快速路径

当前 fresh Capture 按以下顺序处理：

1. 用已有 `scheduler.py score-warmup` 写入唯一队列项的评分事件。
2. 用 `quick_intake.py stage-source` 和 `math-conversation-package-stage-v1` 固化完整会话包。当前已有多少附件就保存多少；题图、解析图或 solution text 缺失时仍保存包，并在 `missing_fields` 明示。
3. 构造一个 `math-fast-intake-capture-v3` 事实绑定，只引用会话包、当前题身份、评分回执和用户请求动作，不做语义分析。
4. 用 `quick_intake.py record` 追加 capture。
5. 收到 `state: pending_nightly` 后立即结束本次入库，让用户继续下一题。

快速路径只允许三类持久化仓库写入；`/private/tmp` 的一次性 payload 不属于学习事实：

- canonical warmup 评分。
- 每个 fresh Capture 对应的不可变完整会话包。
- 快速事件账本。

快速路径禁止：

- 改正式错题卡。
- 改 `复习单元.json`，warmup 评分自身的规范更新除外。
- 执行 `upsert-wrongnet`。
- 执行 `wrongnet.py rebuild`。
- 扫描关联旧卡或生成关系提案。
- 更新 Wiki。
- 读取完整历史任务或全库材料来追求即时“完美改写”。
- 调用模型、原生子智能体、MCP、后台服务或 handoff。
- 判断 first break、mastery、taxonomy 或 relations。

端到端性能目标为正常路径 30 秒内，验收门槛为 P95 不超过 60 秒。fresh Capture 路径包含会话包 payload、`stage-source`、capture payload 与 `record`，硬上限为 5 次工具调用，并最多进行一次确定性重试。快速路径没有模型组织证据步骤。

## fresh Capture 完整会话包

当前输入使用 `math-conversation-package-stage-v1`：

```json
{
  "schema_version": "math-conversation-package-stage-v1",
  "package_key": "warmup:WQ-example:QI-example",
  "study_date": "2026-07-18",
  "timezone": "Asia/Shanghai",
  "source": {
    "source_locator": "ID:112834 / 当前题",
    "question_id": "112834",
    "session_id": "optional-session",
    "item_id": "optional-item",
    "capture_identity": "warmup:WQ-example:QI-example"
  },
  "conversation": [
    {"role": "user", "text": "用户原始作答，逐字保存"},
    {"role": "assistant", "text": "助手当轮原始回复，逐字保存"},
    {"role": "user", "text": "后续纠正轮，继续按顺序保存"}
  ],
  "artifacts": [
    {"role": "question_image", "path": "/absolute/temporary/question.png"},
    {"role": "explanation_image", "path": "/absolute/temporary/explanation.png"},
    {"role": "user_work_image", "path": "/absolute/temporary/user-work.png"},
    {"role": "solution_text", "path": "/absolute/temporary/solution.txt"}
  ],
  "missing_fields": []
}
```

会话按数组原顺序完整保存，writer 只增加从 1 开始的 `sequence`，不裁剪、不摘要、不改写 `text`。附件角色支持 `question_image`、`solution_image`、`explanation_image`、`user_work_image`、`source_article_image`、`other_attachment` 和 `solution_text`。缺少附件不阻止快速保存；writer 自动把缺失的 `question_image` 或 `solution_text` 合并进 `missing_fields`。

物理目录固定为：

```text
快速入库来源/YYYY-MM-DD/MATHPKG-*/
  manifest.json
  conversation.json
  source.json
  attachments/
  receipt.json
```

`manifest.json` 绑定 subject、日期、时区、来源与题目/session/item/capture 身份、conversation/source/附件的仓库相对路径、角色、MIME、字节数和 SHA-256，并记录包级 `canonical_sha256`、`formal_write_count: 0`、`background_processing: none`。`receipt.json` 还固定 `model_call_count: 0` 和 `mcp_call_count: 0`。相同 `study_date + package_key + source_locator` 与相同字节返回 `noop`；相同身份不同字节失败关闭，绝不覆盖旧包。

## 历史 source bundle v1 兼容

`math-fast-intake-source-stage-v1` 与 source bundle v1 只为历史 v2 Capture、旧 pending、freeze、close、verify 和正式终态后的 legacy evidence archive 保留。现有字节不回填当时没有保存的会话；新的快速入库必须使用上面的完整会话包。历史来源完成验证归档后只可删除 manifest 声明的 artifact，必须保留原 manifest 与 `legacy-archive-pointer.json`。后续 reader 只有在 pointer、legacy receipt、Obsidian locator、T9 sentinel/UUID、归档 manifest/tree 和请求 artifact 哈希全部吻合时，才可从精确 T9 相对路径重开缺失字节。

- `new_source` 的题图或解析图。
- 已有正式卡本轮新提供、且尚未存在于仓库的附件。
- 唯一副本仍在 `/var`、`/private/tmp`、`/tmp`、剪贴板缓存或其他仓库外位置的来源。

来源固化输入使用 `math-fast-intake-source-stage-v1`：

```json
{
  "schema_version": "math-fast-intake-source-stage-v1",
  "study_date": "2026-07-18",
  "source_locator": "ID:112834 / 用户提供题目截图与标准解析截图 / 2026-07-18",
  "artifacts": [
    {"role": "question", "path": "/absolute/temporary/question.png"},
    {"role": "solution", "path": "/absolute/temporary/solution.png"},
    {"role": "solution_text", "path": "/absolute/temporary/solution.txt"}
  ]
}
```

角色只允许 `question`、`solution`、`solution_text`、`user_work`、`reference`。`solution_text` 只允许 UTF-8 `.txt` 或 `.md` 文件。writer 对其统一换行为 LF、去除首尾空白并固定一个结尾换行，再计算 SHA-256。其他 artifact 继续校验普通文件、扩展名与文件头、非空、单文件与总大小、重复文件和符号链接。随后按 `study_date + source_locator` 生成稳定 bundle ID，把文件原子复制到 `快速入库来源/YYYY-MM-DD/BUNDLE_ID/`，最后写 `manifest.json`。清单记录每个子文件的仓库相对路径、角色、MIME、大小和 SHA-256。

历史 v2 fresh Capture 当时要求 bundle 至少包含一张真实 `question` 图片并恰好包含一个 path-backed `solution_text` artifact。该规则只解释与验证旧 v2 字节；当前 v3 会话包允许缺项并把缺项写入 `missing_fields`。

相同身份与相同内容返回 `noop`；相同身份出现不同文件失败关闭，不覆盖旧来源。清单及子文件都是不可变事实。固化成功但 capture 失败时允许保留来源包供同一 capture 重试，不得因此声称 capture 已成功。

同一来源包创建后不允许增量追加。若之后又出现新的解析图或作答图，必须使用新的稳定 supplemental locator 单独固化并记录为 source-backed 表示事件，夜间再依据真实身份将多个事件合并到同一正式卡。

## 当前 capture-v3 输入

会话包固化成功后，`record` 只接受以下事实绑定作为当前默认合同：

```json
{
  "schema_version": "math-fast-intake-capture-v3",
  "attempt_id": "warmup:WQ-example:QI-example",
  "study_date": "2026-07-18",
  "target": {
    "kind": "formal_card",
    "formal_id": "GS-904",
    "source_locator": null,
    "source_hash_before": null
  },
  "score_event_id": "SCORE-000000000000000000000000",
  "requested_action": "record_recurrence",
  "thread_ref": "codex-task-or-thread-reference",
  "conversation_package": {
    "manifest_path": "数学一回滚复习系统/快速入库来源/2026-07-18/MATHPKG-.../manifest.json",
    "manifest_hash": "<64 lowercase hex>",
    "package_sha256": "<64 lowercase hex>"
  }
}
```

writer 重开 manifest、conversation、source、receipt 和每个附件并逐字节重验，只向 ledger 追加 package、target、score 和 requested action 的事实绑定。v3 event 不含 `evidence` 或 `episode_evidence`，也不出现 first break、mastery score、taxonomy、relations、模型、MCP、后台 handoff 或 producer attestation。历史 sidecar 原字节保留，但新 Capture 不再生成它。

带 `score_event_id` 时仍从 `复习记录.jsonl` 认证 attempt、日期、实际交付卡、队列项、分数与作答前正式卡哈希。评分是已有用户作答事实，不等于快速阶段进行 mastery 判断。

`target.kind: new_source` 仍要求稳定 `source_locator`；v3 将 `target.source_hash_before` 绑定到同一个会话包 manifest 哈希。会话包缺少题图或解析时可以保存并进入 pending，但正式入库 freeze 会在需要建立新题身份时要求足够的真实来源，绝不补造缺失材料。

## 历史 capture-v2 输入

以下结构只解释旧 v2 replay 与隔离兼容测试，不是新的快速入库默认合同：

```json
{
  "schema_version": "math-fast-intake-capture-v2",
  "attempt_id": "warmup:WQ-example:QI-example",
  "study_date": "2026-07-18",
  "target": {
    "kind": "formal_card",
    "formal_id": "GS-904",
    "source_locator": null,
    "source_hash_before": null
  },
  "score_event_id": "SCORE-000000000000000000000000",
  "requested_action": "record_recurrence",
  "thread_ref": "codex-task-or-thread-reference",
  "source_bundle": {
    "manifest_path": "数学一回滚复习系统/快速入库来源/2026-07-18/BUNDLE_ID/manifest.json",
    "manifest_hash": "<64 lowercase hex>"
  },
  "episode_evidence": {
    "solution_text": "经题源或当前讲解核验的解析文本",
    "user_answer_text": "用户本轮原始推导或作答",
    "teaching_turns": [
      {"speaker": "user", "kind": "reasoning", "text": "用户原始推理", "origin": "user_observed"},
      {"speaker": "assistant", "kind": "hint", "text": "本轮相关提示", "origin": "assistant_explained"}
    ]
  },
  "evidence": {
    "result": "wrong",
    "user_facts": [
      {
        "text": "用户本轮仍未识别第二条直线是两平面交线。",
        "origin": "user_observed"
      }
    ],
    "independent_correct_steps": [],
    "first_break": {
      "kind": "method_trigger",
      "text": "没有先把联立的两个平面方程识别为交线。",
      "origin": "user_confirmed"
    },
    "later_breaks": [],
    "hints_needed": [
      {
        "text": "提示后才调取两个法向量叉乘。",
        "origin": "user_observed"
      }
    ],
    "self_corrections": [],
    "mastery_score": 2,
    "mastery_source": "warmup_score",
    "score_basis": {
      "text": "方法入口未独立触发，提示后完成。",
      "origin": "source_verified"
    },
    "unresolved": []
  }
}
```

带 `score_event_id` 时，脚本从 `复习记录.jsonl` 认证：

- `attempt_id` 与学习日期。
- 实际交付卡，而不是 anchor 卡。
- 队列 ID 与队列项 ID。
- 分数、匹配模式、anchor ID 和作答前正式卡哈希。

capture 只引用这些小字段，不复制评分事件中的完整证据快照。

历史 v2 普通正式卡可以不带评分事件；脚本会验证正式 ID 唯一并记录当前文件哈希。旧 `source_bundle` 仍由 verify、pending、freeze 和 close 重验。

当前 fresh Capture 使用 `math-fast-intake-capture-v3`。历史 `math-fast-intake-capture-v1` 与 v2 事件继续 replay、pending、freeze、close 和 verify，不迁移、不修改；v2 的 solution-text 一致性门禁继续用于验证其原字节。

已有历史 `needs_user` capture 仍只能在 freeze 前通过 source-verified amendment 补入真实 manifest hash 与旧 `source_bundle`，不能把临时路径或未确认来源直接映射到任意旧卡。新 v3 缺项则以 immutable package 与 `missing_fields` 保存，不用 amendment 伪造旧时不存在的会话或附件。

Capture 必须保持 release-neutral，不得写入 release、activation、Dispatcher authority、MCP authority、消费状态或 handoff 状态，也不得把这些字段嵌入任意嵌套对象。

## 历史 v1/v2 语义证据

以下来源枚举只用于解释旧 v1/v2 capture 与 amendment。当前 v3 快速包保留 user/assistant 原始角色与原话，语义来源判断延后到同一 Sol 的正式入库回合：

- `user_observed`：用户真实作答或表达中直接观察到。
- `user_confirmed`：用户明确确认。
- `source_verified`：由队列、评分、题面或正式文件直接验证。
- `assistant_inferred`：模型根据现有证据推断，不能冒充用户事实。
- `assistant_explained`：本轮由助手提供的讲解或提示。
- `unresolved`：暂时无法确认。

`user_facts` 至少有一条，且至少一条必须是 `user_observed` 或 `user_confirmed`。这项门禁防止只有模型推断、没有真实学习证据的事件进入夜间正式流程。

第一个断点与后续断点分开保存。断点类型只允许：知识、概念、条件、方法触发、方法、计算、表达、身份或未知。用户某一步正确，不等于整个方法已经掌握；`independent_correct_steps` 只记录已确认正确的局部步骤。

## 幂等与失败恢复

capture 的稳定身份由 `attempt_id + target identity` 生成：

- 同一身份、同一规范证据再次提交返回 `noop`，不追加第二条。
- 同一身份出现不同证据时失败关闭，不覆盖旧事实。
- 评分成功但 capture 失败时，保留评分事件 ID、attempt ID 和同一证据包，重跑一次即可。
- 一次重试仍失败时不得声称入库成功；应返回紧凑恢复胶囊，等待后续恢复。

写入在独占锁内完成，追加后立即重新读取、验证内容哈希并回放账本。坏 JSON、坏哈希、未知事件引用或重复关闭都失败关闭。

`quick_intake.py verify --date YYYY-MM-DD` 同时验证该日账本回放、每个有效来源清单及其全部子文件，并返回 `source_bundle_count` 与 `source_artifact_count`。它不是实时学习路径的额外必做调用，但可用于批次验收和故障排查。

若当天稍后发现 capture 证据需要修正，可以在 freeze 之前使用 `amend` 追加完整修订事件。原 capture 仍保留；已经关闭或仍属于 active freeze 的 capture 不允许直接修订。历史 `new_source` 可在 freeze 前通过 amendment 同时补入 `target_patch.source_hash_before` 与 `target_patch.source_bundle`；二者必须绑定同一份真实清单。尚未冻结的正式卡 capture 也可用 source-verified target patch 绑定当前唯一正式卡哈希，用于同卡前序收口改写后的版本 rebase；该 rebase 必须使用 `reason.origin: source_verified`，且规范化后的 `evidence` 必须与当前有效证据完全相同，只允许改变来源版本绑定。原始 capture 版本仍保留。freeze 会固定完整 amendment ID 顺序、有效证据哈希、有效目标哈希和有效来源包哈希。

`pending` 会返回顶层 `active_freezes` 和每个 pending capture 的 `active_freeze_ids`；跨任务恢复必须复用原 freeze，工具拒绝把同一 capture 放进第二个 active freeze。若核心事实在正式卡和回滚状态尚未变化时被推翻，用户明确确认后可运行 `abort-freeze --freeze-id ID --reason TEXT`。它追加 `freeze_abort`，不关闭 capture；之后才允许 amend 和新 freeze。若目标正式卡或回滚单元已经变化，自动 abort 失败关闭，必须先人工核对已写状态。

freeze 后若只是表示层补充，先用原 freeze 完成当前收口，再另记 `update_representation` capture；不得把同一次作答伪装成新的错误或复发。若新信息推翻题源身份、核心用户事实或本次是否做错，不能强行关闭互相矛盾的证据。

## pending 目标集

普通正式入库触发先以 `Asia/Shanghai` 当日或用户给定日期作为 `cutoff_date`，执行只读规划：

```text
python3 数学一回滚复习系统/scripts/quick_intake.py backlog-through-date --cutoff-date YYYY-MM-DD
```

默认选择所有原 `study_date <= cutoff_date` 且未形成可信正式终态的 capture。只有显式 `--only-today`、`--capture-id` 或 `--package-id` 才缩小。输出的 `plan` 不包含生成时间，`plan_sha256` 是其 canonical JSON SHA-256；同一账本快照和选择必须得到完全相同的 plan 与哈希。

`date_groups` 按原 `study_date` 升序，每日开始前必须重放。跨日规划层不改日期，不 freeze，不 apply，不 close，不创建跨日正式事务。每一天仍复用现有 `pending --date`、`all_pending_for_date` / `explicit_subset` freeze、串行 writer 和 closeout。

planner 对 active freeze 返回 `resume`。freeze 后正式状态已变的 `partial_formal_closeout`、未提交 prepare 的 `closeout_commit`、完整会话包 closeout 已提交但归档未完成的 `archive_only`，以及没有 `math-conversation-package-v1` 的已收口历史 Capture 对应的 `legacy_archive_only`，都把 `writer_apply_policy` 固定为 `forbidden`。后者在 legacy receipt、locator 与 pointer 三者全部验证前必须保持 `legacy_archive_pending`，不得降为 `not_required` 或 `already_consumed`。`needs_user`、damaged/`failed`、`archive_pending` 和 `legacy_archive_pending` 保留为当日残项，但不阻止后续日期组。

初始响应可作为 `--baseline-plan-file`。脚本先重算并验证 baseline `plan_sha256`，再输出最终全局 gate：`completed`、`already_consumed`、`needs_user`、`failed`、`archive_pending`、`legacy_archive_pending` 和 cutoff 内所有 `residual`。

夜间开始时执行：

```text
python3 数学一回滚复习系统/scripts/quick_intake.py pending --date YYYY-MM-DD
```

输出是跨任务的权威目标集，不依赖当前聊天是否仍保留完整历史。输出按正式 ID 或新来源定位分组。同一卡同日多条 capture 在正式层只改写一次，但必须按时间保留每次事件的事实和断点。

## 用户明确正式入库后的处理顺序

1. 同一 Sol 用 `pending` 读取用户明确日期或集合的目标，重开完整会话包、旧 capture 与真实来源，完成只读身份计划。
2. 在任何正式写入前，用 `math-fast-intake-freeze-v1` 调用 `quick_intake.py freeze`，固定 package/manifest、capture、amendment、目标和正式卡修改前哈希。
3. 如需读取处理库，读取任务只能交给原生 `gpt-5.6-luna`、reasoning effort `max`、Fast service tier 的只读叶子，并返回同一个 Sol。Luna 不分配 ID、不作最终语义决定、不运行 writer、不写卡、账本、Wiki 或 receipt，也不继续委派。
4. Ultra 根任务直接使用原生 proactive 编排，不调用 `orchestrate` Skill。非 Ultra 根任务必须先读取并调用现有 `orchestrate` Skill 判断只读任务如何拆分；用户明确的 Luna Max Fast 约束优先。读取问题少且不值得拆分时由 Sol 直接读取。
5. Luna 失败、越界或证据不足时不得转回 Terra、Dispatcher、MCP、resolver、consumer、AnalysisPackage 或后台 handoff；Sol 只能重开原始包继续、记录 gap 或转 `needs_user`。
6. 同一 Sol 整合证据并独立作出身份、去重、first break、mastery、taxonomy、关系与正式内容决定；所有正式写入串行，同一正式目标只写一次。
7. 对每张改写卡运行仓库内只读 `math_formal_lint.py --repo ... --freeze-id ... --card ...`，全部通过后才执行一次成功的 wrongnet rebuild。
8. rebuild 后完成定向回滚、SHADOW 关系提案、Wiki、visual 与 parity；掌握候选、纯表示更新和否决裁决不得伪造 wrong event。
9. 所有结构化产物与当前教学切片通过后，用 `math-fast-intake-closeout-v3` 追加一次 closeout。持久回执中的 `model` 继续固定为 `unknown`，不伪造模型证明。历史 `math-fast-intake-closeout-v2` 仅保留账本回放、scheduler 读取与归档兼容，不得作为新提交版本。

学习事实日期使用 freeze 的 `study_date`；wrongnet 实际构建日来自当前 `wrong_questions.json.updated_at`，经验证后记为 `artifact_date`。`artifact_date` 不得早于 `study_date` 或晚于当前日期，Wiki `last_updated` 必须与它一致。隔天补做昨天的夜间收口时，回滚复发日期仍是昨天的 `study_date`，派生产物日期则是今天的 `artifact_date`。

任一必需层失败时不追加 closeout，capture 保持 pending，可在下次重跑。夜间不得为了闭环而捏造没有证据支持的错因、掌握状态或关系。

## 正式终态后的 T9 原始包归档

完成分析且已 closeout 的 `curated`、`created`、`updated`、`already_current`、`skip`、`noop` 或 `duplicate` package 必须归档；实际 `formal_ids` 可以为空。`needs_user` 与 `failed` 仍留在本机完整包，不归档、不清理。

归档工具必须从已提交 closeout 的 `capture_results` 与 `formal_results` 独立导出真实 terminal outcome 和 formal-ID 集合，并与调用参数比较。只要 closeout 有实际 formal ID，调用方就必须逐个传入；只有 closeout 本身没有 ID 时才允许空列表。调用方白名单字符串不能替代该检查。

归档根固定为 `/Volumes/T9-Data`，数学 subject-relative root 固定为 `03_数学/资料库/原始会话资料`。归档前必须验证 `00_迁移管理/状态/volume-sentinel.json` 的 SHA-256 为 `f086b32b29b2b38f1a28dffb8fde4fa850078332d8a23ae269cc8e857a6bd2ca`、`volume_name` 为 `T9-Data`、`volume_uuid` 为 `00000000-0000-0000-0000-000000000000`；检测到 `/Volumes/T9-Data 1` 时失败关闭。开始复制前先持久化 archive intent，它固定跨重试的 intent ID 与 `archive_verified_at`。

顺序固定为本机 package 与 closeout 验证、稳定展示闭环重验、持久化 intent、T9 同父 staging copy、tree/manifest/package SHA 验证、atomic final、写并重读 `错题知识网络/wiki/sources/raw_archives/PACKAGE_ID.md`、追加并重读 `数学一回滚复习系统/原始会话归档回执.jsonl`。只有 display closure、formal-reference scan、bridge membership、archive 与 Obsidian path 全部 verified 后，才先原子写并重读带 cleanup intent 的 `archive-pointer.json`，随后删除本机 `attachments/`；pointer 写失败时本机完整包保持不变，重试复用同一 intent、locator bytes 与 receipt identity。不编辑 `.base`。

formal closeout 已提交但归档未完成时状态是 `FORMAL_COMMITTED_ARCHIVE_PENDING`。此时不得重跑 formal writer，只能用相同 package、closeout、terminal outcome 与哈希幂等恢复归档。

### 无完整会话包的历史 Capture

已可信 closeout 但没有 `math-conversation-package-v1` 的历史 Capture 必须走独立的 archive-only 命令，不能伪装成完整会话包：

```text
python3 数学一回滚复习系统/scripts/archive_legacy_evidence.py \
  --repo /Users/your-user/Documents/kaoyan-math \
  --capture-id MFI-CAP-...
```

默认只预览，必须返回 `preview_write_count: 0` 与内容派生的精确 `authorization`。实际执行必须重开同一账本状态并同时传入 `--apply --authorization EXACT_VALUE`；任何 ledger、manifest 或 artifact 漂移都会改变授权或直接失败，且在授权匹配前不得创建 intent、T9 staging、locator、receipt 或 pointer。调用方不能传入或覆盖 freeze、closeout、formal IDs 与 outcome；工具只从账本回放导出。

apply 必须同时持有快速事件 ledger lock 与原始会话 archive lock，在首个 intent 写入前重新读取并 replay 当前账本，同时比较所选原始行哈希和内容授权。锁内结果与 preview 不一致时在 intent 前失败。`source_bundle` 只有真正 absent/null 时才允许 `ledger_only`；字段存在但类型、manifest path/hash 或实际字节无效时必须 damaged/fail，不能降级。

归档包 schema 固定为 `math-legacy-evidence-archive-package-v1`，并明确写入 `conversation_complete: false`、`canonical_package: false`。它保存 capture/amendment/freeze/prepare/closeout 的原始 ledger 行字节；有历史 source bundle 时还保存其原始 manifest 与每个现存 artifact，完全没有 bundle 时标为 `ledger_only`。不得创建 `conversation.json`、不得补造 turns、不得把 ledger-only 证据描述成会话包。

apply 仍执行 sentinel/name/UUID 校验、拒绝 `T9-Data 1`、拒绝 archive root 或 destination/staging parent symlink、在 mkdir/copy 前证明 resolved destination 位于验证后的 T9 内、同父 staging、逐文件复核和原子发布，路径为 `03_数学/资料库/原始会话资料/STUDY_DATE/MATHLEGACY-*`。随后依次写并重读含 truth flags 的 `raw_archive_locator`、追加并重读 `math-legacy-evidence-archive-receipt-v1`、写并重读 `math-legacy-evidence-archive-pointer-v1`。只有上述门禁全部通过，source-bundle 模式才删除本地 artifact 并保留 manifest+pointer；`ledger_only` 不执行 heavy cleanup。任何失败只恢复这一 archive-only 事务，绝不调用 formal writer、wrongnet rebuild 或 closeout。

source-bundle cleanup 还必须绑定 `math-legacy-source-cleanup-proof-v1`：从当前 ledger 重算引用同一 manifest/artifact 的全部 Capture ID、引用数、不可证明 binding，并为每个文件固定 `delete_exclusive_reference`、`retain_shared_reference` 或 `retain_unprovable_reference`。proof 同时进入 authorization、receipt 和 pointer。只有目标 Capture 是唯一可证明引用且 pointer 覆盖精确 path/hash/size 时才删除；共享或不可证明文件保留并报告。双锁内在首次 cleanup 和每次 resume cleanup 前再次 replay 并比较 proof，引用漂移在删除前失败。

pointer 所有权按 Capture 区分。已有 `legacy-archive-pointer.json` 属于当前 Capture 时保持兼容；若它属于共享 bundle 的另一个 Capture，当前事务必须改用 `legacy-archive-pointers/CAPTURE_ID.json`，不得覆盖旧 pointer。新事务把选定的仓库相对 pointer path 写入 authorization、receipt 与 pointer；已持久化旧 intent/receipt 但尚未写 pointer 的失败事务复用原 authorization/receipt，只补写确定性的 Capture 专属 pointer，并由 strict planner verifier 绑定实际路径。reader 同时识别旧 single pointer 与 pointer 目录。

在 `local_pointer_path` 字段加入前已经完成的 ledger-only 事务只做只读兼容：strict verifier 必须重导旧 authorization 与 deterministic intent/receipt IDs，并逐项核对当前 ledger、live sentinel、T9 exact tree/manifest、locator、旧 receipt 与旧 pointer 原字节；全部一致才允许 `already_consumed`。不得重写旧文件，任一不符转 damaged。新的 ledger-only 事务继续使用 pointer-path v2。

### 已完成旧合同的 successor 身份修复

若旧归档已经真实完成，T9 exact tree、manifest/package/tree SHA、旧 intent、receipt、pointer 与 locator 原字节均能自洽重验，但因后续授权合同扩展而出现 `legacy_archive_intent_identity_mismatch`，只能建立独立 successor 证明，禁止覆盖旧证据：

```text
python3 数学一回滚复习系统/scripts/archive_legacy_evidence.py \
  --repo /Users/your-user/Documents/kaoyan-math \
  --capture-id MFI-CAP-... \
  --repair-identity
```

预览必须为零写入并返回 `MATH-LEGACY-ARCHIVE-REPAIR-APPLY-*`。实际执行只允许增加 `math-legacy-evidence-archive-repair-successor-v1`，仍需传入同一预览的 `--apply --authorization EXACT_VALUE`；它不得修改旧 intent、receipt ledger、pointer、locator、正式卡、wrongnet、closeout 或 T9 字节。apply 在 ledger/archive 双锁内重新推导授权，并在写 successor 后立即调用同一 strict live verifier。

source-bundle 的 successor 必须逐图证明 T9 归档字节，并重新执行正式引用扫描。`canonical_display_closure_verified`、`historical_display_closure_verified` 与 `stable_display_successor_verified` 可以声明对应展示证明；找不到当前稳定资产时只能写 `archived_only_legacy_display_successor`，明确表示“历史图片在 T9 完整保存，但不声称当前已在 Obsidian 展示”，不得冒充 canonical closure。任何旧表面、定位器语义、T9 树或当前正式引用扫描异常都必须 fail closed，不得用 successor 掩盖。

planner 的完成判定必须复用同一 strict verifier，重新推导 authorization 与 deterministic intent/receipt IDs，要求所有字段和文件字节精确绑定，验证 safe relpath、live T9 sentinel、实际 archive manifest 与 exact tree。仅有合成 pointer/receipt/locator 不能成为 `already_consumed`。

## freeze 与 closeout 门禁

freeze 输入必须声明 `all_pending_for_date` 或 `explicit_subset`，并把每个 capture 恰好分配到一个正式目标。`existing_formal` 必须与 capture 的正式 ID 和当前来源哈希一致；`new_source_created` 要求冻结时该正式 ID 尚不存在；`new_source_merged` 要求冻结时目标卡唯一存在。新来源两种模式的 `source_binding.artifact_path` 必须指向 capture 的仓库内 manifest，`artifact_hash` 与 `resolved_source_hash` 都必须等于 manifest hash；来源 locator 必须一致。临时目录、仓库外文件、单独抽出的某张子图都不能替代清单。已有正式卡的新附件作为 `supplemental_source_bundles` 随 freeze 固定，不改变正式卡身份。

freeze 与 close 都会重验 manifest 结构、目录身份、每个子文件的路径、大小、文件头和 SHA-256。close 把 manifest 与每个子文件分别加入 `verified_artifacts`，在 `closeout_prepare` 后再次逐文件哈希；任一子文件被删除、替换或并发改动都会使 prepare 失效，capture 保持 pending。

freeze 同时保存目标卡已有的 `fast_intake_refs`、`fast_intake_source_refs`，以及目标回滚单元的修改前哈希、processed event 集合和调度历史 event 集合。返回值直接给出本批需要写入正式卡的规范 token：

- `fast_intake_refs`：`capture-v1:{capture_event_id}:{effective_evidence_hash}:{requested_action}`。
- `fast_intake_source_refs`：`source-v1:{来源 locator 与来源哈希的 canonical JSON SHA-256}`。

这些 token 必须作为正式卡 frontmatter 的扁平列表新增，不能只把同样字符串放在正文、注释或回执中。主来源与 existing-formal supplemental 来源都生成 `fast_intake_source_refs`。正式卡未变化时不得伪造新增 token；存在新的 source ref 时正式结果不得声明 `unchanged`。正式卡发生创建或更新时，freeze 前后新增 token 集合必须与该目标的冻结 capture 精确一致。`new_source_merged` 必须真实更新正式卡，来源清单及全部子文件在 close 时会再次哈希。

`math-fast-intake-closeout-v3` 不再接受自由文本 `passed` 或任意字符串回执，必须引用唯一 `freeze_id` 并包含：

- 每个正式目标唯一一条 `created`、`updated` 或 `unchanged` 结果，附当前路径、哈希和实际 changed fields。
- 每个 capture 唯一一条与 `requested_action` 匹配的 outcome。做错与复发必须更新或创建正式卡，并绑定 `复习单元.json` 中 freeze 后新增的 processed event 和 unit canonical hash；复发还必须绑定唯一的本日 `正式错题复发` 历史条目。表示更新、掌握确认、掌握否决按正式卡或 closeout 绑定，不得制造错题事件；掌握确认还必须与现有回滚单元状态一致。已提交且完整性回放通过的 `mastery_confirmed`，仅在 freeze 绑定的 effective evidence 同时满足 `result=correct`、`mastery_score>=4`、至少一条 `independent_correct_steps` 来自用户观察或用户确认且 `hints_needed` 为空时，才可被调度器解释为永久交付排除证据；存在 amendment 时不得退回读取原 capture 的旧证据。
- `batch_receipts.teaching_contexts` 必须是数组，与每个 `formal_results` 目标一一对应；`operation=unchanged` 也不例外。若确实没有 formal target，该数组必须为空。每项至少包含 `formal_id`、`context_path`、`context_sha256`、`pointer_path`、`pointer_sha256`；缺失、重复或额外目标均失败关闭。

教学切片文件使用 `math-teaching-context-v1`，固定位于 `错题知识网络/教学投影/<FORMAL_ID>/versions/<CONTEXT_SHA256>.json`；当前指针使用 `math-teaching-context-pointer-v1`，固定为 `错题知识网络/教学投影/<FORMAL_ID>/current.json`。路径必须是规范的仓库相对路径，不允许绝对路径、`.`、`..`、越界、缺失文件或非普通文件。

切片顶层必须绑定同一 `formal_id`，`source_bindings` 至少包含并通过：

- `formal_card_path` 与 `formal_card_sha256`：必须等于本次 `formal_results` 的最终正式卡路径与原始文件 SHA-256，不得引用更新前旧卡。
- `formal_evidence_source_version`：必须从同一最终正式卡用 `training_evidence.extract_error_evidence` 重算，与原始文件 SHA-256 分开绑定。
- `freeze_id`、`capture_event_ids` 和 `capture_bindings`：必须等于当前 freeze 中该 formal target 的完整、排序后 capture 集合与快照。`capture_bindings` 每项只用 `capture_event_id`、`capture_content_hash`、`amendment_event_ids`、`effective_evidence_hash`、`effective_target_hash` 进入绑定计算。
- `capture_evidence_source_version`：唯一 canonical 算法是对 `{"freeze_id": FREEZE_ID, "formal_id": FORMAL_ID, "capture_bindings": SORTED_BINDINGS}` 执行 `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`，对无尾换行的 UTF-8 字节求 SHA-256。任一 capture、amendment、effective evidence 或 effective target 改变都必须得到新版本。

closeout 必须复验 context 和 pointer 回执哈希，pointer 内容必须当前指向同一 context、最终正式卡和两个 evidence source version。内容寻址 context 文件进入 `verified_artifacts`，在 prepare 前和 commit 前再次哈希；`current.json` 是可合法向前更新的当前指针，不写入历史不可变 artifact 集，但在同一 prepare/commit 窗口仍必须重验回执哈希与当前指向。缺失、错哈希、旧卡、freeze/capture/evidence 不一致或 prepare 后漂移均不追加 closeout commit；capture 恢复 pending 可重试。
- wrongnet 九个生成物的当前 SHA-256、目标 projection hash 和一次 rebuild 工作流声明。close 会用 canonical wrongnet parser 从最终正式卡重算目标 projection，再与主快照比较；该声明不是命令执行次数的密码学审计。
- 每张目标卡的 Wiki source summary 当前哈希及 `formal_projection_sha256`。close 会重算目标级 subject、knowledge、methods、error causes、source/index/coverage/matrix 唯一性、稳定簇引用、成员关系、控制字符和必要字段。
- 关系层的逐目标 SHADOW 裁决，以及 visual 的逐目标 `passed` 或 `not_applicable` 回执。

close 从规范化到提交全程同时持有正式收口锁和账本锁。它先追加 `closeout_prepare`；prepare 不关闭 capture。随后再次哈希所有已验证产物，只有最终复核通过才追加 closeout commit，回放时也只有 commit 会写入 `closed_by`。复核失败会失效 prepare，capture 保持 pending，同一原 freeze 可按新 generation 重试且事件 ID 不冲突。该互斥保证只覆盖同样遵守正式收口锁的 writer；绕过锁的外部进程不在可证明边界内。

`all_pending_for_date` 只要求 freeze 创建时覆盖当日全部 pending。freeze 后新增的无关 capture 留给后续批次，不使已经开始正式工作的原 freeze 失效；同一正式目标的后来 capture 若仍绑定改写前版本，close 会失败并要求对未冻结 capture 做 source-verified 版本 rebase，避免它永久 pending。原冻结 capture 自身、amendment、证据或目标发生变化仍会失败关闭。完全相同且仍有效的成功回执以 `request_hash` 返回 `noop`，即使正式卡后来发生了其他合法变化，也不会重复关闭。当前 closeout 没有受信模型注入通道，因此 `model` 固定写 `unknown`；模型选择由用户在任务外完成，不能由收口 Agent 自报高能力模型名称。

只有这些门禁全部满足，`close` 才追加 `nightly_closed` 回执。原 capture、amendment 与 freeze 永不改写；任何失败项继续 pending。

## 完成措辞

白天成功后只能说：

```text
快速记录成功，已进入今晚的正式优化队列。
```

不得在白天声称“正式卡、回滚、网络和 Wiki 已全部更新”。夜间全部门禁通过后，才可以说“夜间正式收口完成”。


## 新来源的非错误裁决

`requested_action=record_wrong` 是收件请求，不等同于已确认做错。完整原件表明只有正确推理或机制询问时，正式收口可使用 `wrong_rejected`，仍保存原始 Capture 与来源，并通过 closeout 保存证据哈希。此分支仅适用于本次创建的新来源卡：`mistake_count=0`、无明确做错事件、freeze 前和收口时都不存在回滚单元；不能用它抹掉已有失败或绕过已有回滚事件。教学切片仍须通过答案安全和来源绑定验证。
