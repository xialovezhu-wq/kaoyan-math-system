# 数学讲题有界教学切片 v1

## 目的

`math-teaching-context-v1` 只保存会改变当前一道题讲解路由的历史证据。它不是学习者画像、答案缓存、题库索引或复习调度器。

当前题面和用户本轮真实作答始终由调用方提供并具有最高优先级。切片中的所有教学证据均为 `prior_only`，只能帮助选择提示强度或表示方式，不能替代本轮首断点判断。

## 固定路径

- 版本：`错题知识网络/教学投影/<FORMAL_ID>/versions/<CONTEXT_SHA256>.json`
- 当前指针：`错题知识网络/教学投影/<FORMAL_ID>/current.json`

版本文件是 canonical JSON、内容寻址且不可变；`current.json` 独立原子替换并最后写入。同一 payload 重复物化必须得到相同版本路径和哈希，且不得因当前时间产生新版本。

## 文档结构

```json
{
  "schema_version": "math-teaching-context-v1",
  "formal_id": "GS-907",
  "precedence": {
    "current_question_evidence": "external_runtime_authoritative",
    "historical_context": "prior_only",
    "history_must_not_override_current": true
  },
  "source_bindings": {
    "formal_card_path": "错题知识网络/错题卡/GS-907_fixture.md",
    "formal_card_sha256": "<sha256>",
    "formal_evidence_id": "EV-<id>",
    "formal_evidence_source_version": "<training_evidence source_version>",
    "freeze_id": "MFI-FREEZE-...",
    "capture_event_ids": ["MFI-CAP-..."],
    "capture_bindings": [
      {
        "capture_event_id": "MFI-CAP-...",
        "capture_content_hash": "<sha256>",
        "amendment_event_ids": [],
        "effective_evidence_hash": "<sha256>",
        "effective_target_hash": "<sha256>"
      }
    ],
    "capture_evidence_source_version": "<sha256>",
    "package_bindings": [
      {
        "capture_event_id": "MFI-CAP-...",
        "package_id": "MATHPKG-...",
        "package_sha256": "<sha256>"
      }
    ]
  },
  "prior": {
    "evidence_scope": "prior_only",
    "action_gap_type": "B3-METHOD",
    "evidence_origin": "user_confirmed",
    "needs_confirmation": false,
    "first_break": {
      "kind": "method",
      "text": "历史首断点的最短描述",
      "evidence_origin": "user_confirmed",
      "source_capture_id": "MFI-CAP-..."
    },
    "independent_correct_steps": [],
    "hint_dependency": {
      "level": "l2",
      "text": "达到继续作答所需的最低历史提示层级",
      "evidence_origin": "user_observed",
      "source_capture_id": "MFI-CAP-..."
    },
    "effective_representation": [
      {
        "kind": "object_table",
        "text": "历史上有效的最小表示方式",
        "evidence_origin": "user_observed",
        "source_capture_id": "MFI-CAP-..."
      }
    ],
    "unresolved": [],
    "c_followup": {
      "eligible": true,
      "after_current_question_only": true,
      "reason": "B2/B3 只标记后续辨型复习资格"
    }
  }
}
```

调用方可额外提供 `artifact_date` 和按升序去重的 `study_dates`。物化器不会自行补当前时间。

## 两类证据版本

`formal_evidence_source_version` 由 `training_evidence.extract_error_evidence` 对最终正式卡重新计算。

`capture_evidence_source_version` 使用无尾随换行的 canonical JSON 计算：

```text
sha256({
  freeze_id,
  formal_id,
  capture_bindings: sorted by capture_event_id
})
```

其中每个 capture binding 仅包含 `capture_event_id`、`capture_content_hash`、`amendment_event_ids`、`effective_evidence_hash` 和 `effective_target_hash`。package 映射不进入该公式，但每个 capture 必须恰好绑定一个 package ID 和哈希。

## 视图

- `protected`：仅返回历史动作断点类型、证据边界、提示等级、表示类型及 C 后续资格；隐藏首断点文本、独立正确步骤、提示文本、未解决文本和全部 intake/package 技术绑定。
- `after_attempt`：用户已经真实尝试后返回完整 `prior`。
- `direct`：用户明确要求直接讲解时返回完整 `prior`。

三种视图都明确输出 `current_question_evidence.authority=external_runtime` 和 `history_may_override=false`。C 只允许 B2/B3 标记为后续资格，且必须保持 `after_current_question_only=true`。

## 答案安全与边界

版本文件本身禁止答案、正确选项、最终结果、完整解析、完整题干、assistant 历史、conversation/transcript/teaching turns 等字段或内容，不依赖 protected 视图事后遮蔽。文本和数组均有硬上限。

所有路径必须是 repo-relative。物化与验证只精确读取绑定的正式卡、固定 pointer 和固定 version；不扫描错题库、Obsidian、ledger 或 T9。

## CLI

```bash
python3 错题知识网络/scripts/math_teaching_context.py --repo . materialize --input /path/to/context.json
python3 错题知识网络/scripts/math_teaching_context.py --repo . resolve --formal-id GS-907 --view protected
python3 错题知识网络/scripts/math_teaching_context.py --repo . verify --formal-id GS-907
```

`resolve` 在缺失、漂移或损坏时返回 `status=unavailable`，不会扩大读取范围。`verify` 返回严格校验结果。物化回执包含 `formal_id`、`context_path`、`context_sha256`、`pointer_path` 和 `pointer_sha256`，供正式 closeout 门禁绑定。
