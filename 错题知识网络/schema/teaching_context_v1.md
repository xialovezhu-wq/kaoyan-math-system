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
  "formal_id": "GS-748",
  "precedence": {
    "current_question_evidence": "external_runtime_authoritative",
    "historical_context": "prior_only",
    "history_must_not_override_current": true
  },
  "source_bindings": {
    "formal_card_path": "错题知识网络/错题卡/GS-748_fixture.md",
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
python3 错题知识网络/scripts/math_teaching_context.py --repo . resolve --formal-id GS-748 --view protected
python3 错题知识网络/scripts/math_teaching_context.py --repo . verify --formal-id GS-748
```

精确旧切片读取函数 `resolve_context` 在缺失、漂移或损坏时返回 `status=unavailable`，不会扩大读取范围；普通讲题CLI的当前摘要恢复见下节。`verify` 返回严格校验结果。物化回执包含 `formal_id`、`context_path`、`context_sha256`、`pointer_path` 和 `pointer_sha256`，供正式 closeout 门禁绑定。


## 当前讲题查询的有界恢复

有界 `resolve` 按最终紧凑 JSON（UTF-8，不计换行）测量 `--max-bytes`，含 `total`、`returned`、`truncated` 和实际送达的扩展元数据。预算不够时省略完整记录或完整材料块，不拆正文和条件。4500 字节验收覆盖三视图；`protected` 不返回观察正文或历史定位。只有现行且范围匹配的审核短摘要可指导讲法，证据不足时按本题题设与作答继续。

普通讲题的 `resolve --concept` / `--source-question-id` / `--formal-id` 读取当前 `math_learning_profiles` 派生视图。先用确切名称、已登记别名和身份；未命中时同次读取最多3个当前候选，返回 `resolution` 与逐项 `retrieval_scope`。候选须按当前题的对象、目标和操作核对，不能把名称相似或父主题相同当作精确个人史命中。可用重复的 `--fallback-concept` 指定已确认的相关名称或父主题；该参数仅在主查询未命中时生效。候选保留当前视图的答案保护和来源校验，原始 `unknown` 不被抹去。

CLI观察到派生索引缺失或来源变化时，返回相应失效状态；讲题不触发构建器。底层 `math_learning_profiles.resolve` 保持只读，`--full-evidence` 保持原合同。

讲题模式追加 `--for-teaching`，返回 `teaching_inputs`。逐点返回本轮应核对的证据角色及 JSON Pointer；只指向本响应实际包含的完整字段。顶级 available 不改写各点的语义状态。语义过期时不标记该旧摘要为可用，但独立核验的偏好和有效的具体观察可分别使用。精确题号加细点若具备同一快照，可从只读索引取得最近一组同题逐点观测；来源漂移或同日无法排序不选赢家，附当次适用的子问边界，不借用卡级或其他题观测。after_attempt 只返回观察类型、顺序和来源；direct 才可附短的已接纳观察注解（不是用户原话）。protected 的 points 为空，不读取这层。扩展预算不足时整组省略，不挤掉已读的公式或条件。它不自动选解法或授权制图；本题真实作答、题面和本轮权限仍优先。

考频JSON保留实际年份及来源校验；默认播报只给高/中/低频、question_count去重考查次数及必要范围，不列年份、不把year_count当题次。父主题统计仍须标明，多个主题次数不相加。
