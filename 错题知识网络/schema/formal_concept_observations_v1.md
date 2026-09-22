# 正式入库逐知识点观测 v1

这是 `math-fast-intake-closeout-v3` 的可选 `concept_observations` 顶层扩展。当前正式 Skill 的新批次必须填写；旧 v3 读回与重试不变。正式回执是唯一提交点，不创建 Capture、不创建 B 知识点复盘会话，不改原包。

```json
{
  "schema": "math-formal-concept-observations-v1",
  "targets": [{
    "formal_id": "GS-901",
    "no_observation_reason": "",
    "observations": [{
      "concept_key": "由 math_concept_index.concept_key(concept_label) 得到",
      "concept_label": "正式卡 knowledge 中的精确标签",
      "capture_event_id": "当前 freeze 中属于该正式目标的 Capture ID",
      "outcome": "wrong",
      "error_detail": "本轮真实错误的具体机制，不能仅重复知识点名",
      "user_evidence": [{"sequence": 1, "quote": "完整包中该条用户消息的精确原话"}],
      "hint_evidence": []
    }]
  }]
}
```

`targets` 与 closeout 的正式目标完整对应。`observations` 非空时原因须为空；无真实逐点证据时写空数组及非空原因。单个实际错误可以关联多个确实暴露断点的知识点，但不能把全题涉及点都判错。

`outcome` 只允许 `wrong`、`unresolved`、`corrected_after_hint`、`independent_correct`。前两者需要错误或未解决点的具体说明。所有观测都需要用户引用；`hint_evidence` 只能引用 assistant，且 `corrected_after_hint` 必须有早于最后用户作答的提示。独立正确不接受提示引用；父 Agent 仍须据完整对话判断是否受到先前提示，字段校验不能替代语义判断。

`sequence` 为完整 `conversation.json` 中从 1 开始的真实顺序。writer 复用原 freeze 和 package 校验器，核对完整包 hash、原始日期、目标绑定、原话和角色，纳入已有 prepare/commit 的文件读回。旧来源没有完整对话时不接受新逐点观察，使用原因声明，不补造历史。

规范化结果保存完整对话与全部原始来源路径/hash、Capture 冻结绑定、原始 study_date。正式逐点计错单位是“原始学习日 × 正式题 × 知识点”，同日同题补充 Capture、重复引用和修正不能膨胀为多次复发；不同实际步骤的全部观察仍保留。这是保守的日级 episode 计数，不声称同日同题曾有几次独立尝试。

派生文件位于 `错题知识网络/个人知识点索引/正式逐点观测/MFI-CLOSE-....json`。文件可由有效已提交 closeout 恢复；其路径/hash 稳定，不随无关 pending Capture 改变。索引记录种类为 `formal_concept_observation`，B 复盘仍为 `concept_review`，两者均保留 outcome 与证据角色，整卡旧历史不转成逐点计错。

内部选题读取 `math_concept_index.point_history(repo_root, concept_keys=None)`，返回当前版本与逐点 `events/latest_event/wrong_episode_count/point_source_version`，事件包含 `event_type= formal_intake | concept_review`、原始日期、outcomes、全部 observations、history、source_refs、related_formal_ids。该接口无写入、不自动 rebuild，完整历史只供内部证据包；学习展示必须经过答案保护。
