#!/usr/bin/env python3
"""Deterministic evidence view for review and existing-card selection.

The formal wrong-question card remains the only source of truth.  This module
only normalizes its ``wrong_point`` and ``method_gap`` fields so selection and
generation code can share the same provenance and fail-closed rules.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


EVIDENCE_ORIGINS = {
    "user_confirmed",
    "model_inferred_from_solution",
    "pending_user_confirmation",
}
METHOD_GAP_FIELDS = (
    "enabled",
    "evidence_origin",
    "knowledge_gap_or_method_gap",
    "method_trigger",
    "expected_method",
    "expected_first_action",
    "missed_action",
    "action_gap_type",
    "related_method_card_id",
    "confidence",
    "need_user_confirmation",
)
EMPTY_VALUES = {"", "待补充", "待确认", "无", "未知", "none", "null", "-", ">", ">-", "|", "|-"}
PENDING_MARKERS = (
    "暂无明确个人错因",
    "暂无明确错因",
    "个人原始错因未记录",
    "个人错因未记录",
    "旧卡未记录用户",
    "用户实际漏点未记录",
    "用户实际漏步未记录",
    "需用户确认",
    "待用户确认",
    "待复做确认",
)
MODEL_DERIVED_MARKERS = (
    "根据题图与解析",
    "按题图与解析",
    "依据题图与解析",
    "根据解析",
    "按解析",
    "解析确认",
    "补强复做入口",
    "复做风险是",
    "复做检查点",
)
ERROR_ACTION_MARKERS = (
    "没有",
    "没能",
    "未先",
    "未能",
    "未写",
    "未做",
    "未判",
    "未识别",
    "未检查",
    "未代入",
    "未化简",
    "未展开",
    "未处理",
    "未调用",
    "未注意",
    "忘记",
    "忽略",
    "错误",
    "错把",
    "错用",
    "算错",
    "写错",
    "看错",
    "判错",
    "取错",
    "抄错",
    "写反",
    "漏掉",
    "漏写",
    "漏看",
    "误判",
    "误选",
    "选错",
    "混淆",
    "当成",
    "直接",
    "无法",
    "不会",
    "不能",
)
GENERIC_WRONG_POINTS = {
    "不会",
    "算错",
    "做错",
    "方法错误",
    "方法不对",
    "知识点不熟",
    "思路不清",
    "计算错误",
    "待确认",
    "待补充",
}


def normalized_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1].strip()
    return text


def clean_text(value: Any) -> str:
    text = normalized_text(value)
    return "" if text.lower() in EMPTY_VALUES else text


def text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for item in value if (text := clean_text(item))]
    text = clean_text(value)
    return [text] if text else []


def raw_method_gap(meta: dict[str, Any]) -> dict[str, Any]:
    raw = meta.get("method_gap")
    return dict(raw) if isinstance(raw, dict) else {}


def canonical_method_gap(meta: dict[str, Any]) -> dict[str, Any]:
    raw = raw_method_gap(meta)
    result: dict[str, Any] = {}
    for field in METHOD_GAP_FIELDS:
        value = raw.get(field)
        if field in {"enabled", "need_user_confirmation"}:
            result[field] = value if isinstance(value, bool) else False
        else:
            result[field] = clean_text(value)
    return result


def infer_evidence_origin(meta: dict[str, Any], method_gap: dict[str, Any]) -> tuple[str, bool]:
    declared = clean_text(method_gap.get("evidence_origin"))
    if declared in EVIDENCE_ORIGINS:
        if method_gap.get("need_user_confirmation") is True:
            return "pending_user_confirmation", True
        return declared, True

    combined = " ".join(
        clean_text(value)
        for value in (
            meta.get("wrong_point"),
            method_gap.get("missed_action"),
            method_gap.get("expected_first_action"),
            method_gap.get("method_trigger"),
        )
        if clean_text(value)
    )
    if (
        method_gap.get("need_user_confirmation") is True
        or any(marker in combined for marker in PENDING_MARKERS)
    ):
        return "pending_user_confirmation", False
    if any(marker in combined for marker in MODEL_DERIVED_MARKERS):
        return "model_inferred_from_solution", False
    return "legacy_unclassified", False


def is_specific_wrong_point(text: str, knowledge: list[str]) -> bool:
    """Accept an observed failure, not a topic label or a solution route."""
    value = clean_text(text)
    if not value or value in GENERIC_WRONG_POINTS:
        return False
    if any(marker in value for marker in PENDING_MARKERS + MODEL_DERIVED_MARKERS):
        return False
    folded = normalized_text(value).casefold()
    for item in knowledge:
        topic = normalized_text(item).casefold()
        if topic and folded in {
            topic,
            f"{topic}错误",
            f"{topic}不会",
            f"{topic}不熟",
            f"{topic}有问题",
        }:
            return False
    return len(value) >= 4 and any(marker in value for marker in ERROR_ACTION_MARKERS)


def is_specific_missed_action(text: str) -> bool:
    value = clean_text(text)
    if not value or any(marker in value for marker in PENDING_MARKERS + MODEL_DERIVED_MARKERS):
        return False
    return len(value) >= 4 and any(marker in value for marker in ERROR_ACTION_MARKERS)


def is_specific_instruction(text: str) -> bool:
    value = clean_text(text)
    if not value or any(marker in value for marker in PENDING_MARKERS):
        return False
    return len(value) >= 6


def evidence_label(origin: str) -> str:
    return {
        "user_confirmed": "用户确认错因",
        "model_inferred_from_solution": "模型根据解析推导的复做入口",
        "pending_user_confirmation": "待用户确认错因",
        "legacy_unclassified": "历史结构化证据，来源未分类",
        "missing": "具体错因缺失",
    }.get(origin, "具体错因缺失")


def extract_error_evidence(meta: dict[str, Any], card_id: str | None = None) -> dict[str, Any]:
    method_gap = canonical_method_gap(meta)
    wrong_point = clean_text(meta.get("wrong_point"))
    knowledge = text_list(meta.get("knowledge"))
    origin, origin_declared = infer_evidence_origin(meta, method_gap)
    declared_origin = clean_text(method_gap.get("evidence_origin"))
    evidence_values = [
        wrong_point,
        clean_text(method_gap.get("missed_action")),
        clean_text(method_gap.get("expected_first_action")),
        clean_text(method_gap.get("method_trigger")),
    ]
    has_any_evidence = any(evidence_values)
    if not has_any_evidence:
        origin = "missing"

    confidence = clean_text(method_gap.get("confidence")).lower()
    specific_fields = {
        "wrong_point": is_specific_wrong_point(wrong_point, knowledge),
        "missed_action": is_specific_missed_action(clean_text(method_gap.get("missed_action"))),
        "expected_first_action": is_specific_instruction(
            clean_text(method_gap.get("expected_first_action"))
        ),
        "method_trigger": is_specific_instruction(clean_text(method_gap.get("method_trigger"))),
    }
    has_observed_failure = specific_fields["wrong_point"] or specific_fields["missed_action"]
    # A trigger, expected action, gap taxonomy, or correct route can describe
    # how to solve the card, but none proves what the learner actually did
    # wrong.  At least one observed failure field is mandatory.
    has_structured_breakpoint = has_observed_failure
    gap_enabled = method_gap.get("enabled") is True
    # A confirmed top-level wrong_point is independently useful even when the
    # card does not classify the failure as a method gap.  A missed_action,
    # however, only participates when the method_gap block is enabled.
    confirmed_observed_failure = bool(
        specific_fields["wrong_point"]
        or (gap_enabled and specific_fields["missed_action"])
    )
    personal_confirmed = origin == "user_confirmed" and confirmed_observed_failure
    structured_targetable = bool(
        personal_confirmed
        or (
            gap_enabled
            and has_structured_breakpoint
            and origin == "legacy_unclassified"
            and confidence in {"high", "高"}
            and method_gap.get("need_user_confirmation") is not True
        )
    )
    selection_value = 0
    if structured_targetable and origin == "user_confirmed":
        selection_value = 5 if confidence in {"high", "高", ""} else (4 if confidence in {"medium", "中"} else 2)
    elif structured_targetable and origin == "legacy_unclassified":
        selection_value = 3

    canonical = {
        "card_id": clean_text(card_id or meta.get("id")),
        "knowledge": sorted(normalized_text(item) for item in knowledge),
        "wrong_point": wrong_point,
        "method_gap": method_gap,
        "origin": origin,
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source_version = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    evidence_id = f"EV-{source_version[:16]}"
    gap_payload = {
        "wrong_point": (
            normalized_text(wrong_point).casefold()
            if specific_fields["wrong_point"]
            else ""
        ),
        "missed_action": (
            normalized_text(method_gap.get("missed_action")).casefold()
            if specific_fields["missed_action"]
            else ""
        ),
        "expected_first_action": (
            normalized_text(method_gap.get("expected_first_action")).casefold()
            if specific_fields["expected_first_action"]
            else ""
        ),
        "action_gap_type": clean_text(method_gap.get("action_gap_type")),
        "related_method_card_id": clean_text(method_gap.get("related_method_card_id")),
    }
    gap_key = None
    if has_observed_failure:
        encoded_gap = json.dumps(
            gap_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        gap_key = f"GAP-{hashlib.sha256(encoded_gap.encode('utf-8')).hexdigest()[:20]}"
    return {
        "card_id": clean_text(card_id or meta.get("id")),
        "evidence_id": evidence_id,
        "gap_key": gap_key,
        "source_version": source_version,
        "source_hash": source_version,
        "origin": origin,
        "origin_declared": origin_declared,
        "declared_origin": declared_origin if declared_origin in EVIDENCE_ORIGINS else "",
        "origin_label": evidence_label(origin),
        "model_derived": bool(
            declared_origin == "model_inferred_from_solution"
            or any(marker in " ".join(evidence_values) for marker in MODEL_DERIVED_MARKERS)
        ),
        "needs_confirmation": bool(
            method_gap.get("need_user_confirmation") is True
            or origin == "pending_user_confirmation"
        ),
        "personal_confirmed": personal_confirmed,
        "structured_targetable": structured_targetable,
        "selection_value": selection_value,
        "knowledge": knowledge,
        "wrong_point": wrong_point,
        "method_gap": method_gap,
        "raw_method_gap": raw_method_gap(meta),
        "has_any_evidence": has_any_evidence,
        "has_specific_evidence": has_structured_breakpoint,
        "has_observed_failure": has_observed_failure,
        "specific_fields": specific_fields,
    }


def normalized_evidence_snapshot(
    snapshot: Any,
    card_id: str | None = None,
) -> dict[str, Any] | None:
    """Rebuild and authenticate an immutable evidence snapshot.

    Derived flags such as ``structured_targetable`` are never trusted from a
    stored queue or JSONL event.  Recomputing them from the canonical fields
    prevents a caller from changing knowledge or match semantics while keeping
    a stale self-declared ``source_version``.
    """

    if not isinstance(snapshot, dict):
        return None
    expected_version = clean_text(snapshot.get("source_version"))
    if not re.fullmatch(r"[0-9a-f]{64}", expected_version):
        return None
    snapshot_card_id = clean_text(snapshot.get("card_id") or card_id)
    if not snapshot_card_id:
        return None
    rebuilt = extract_error_evidence(
        {
            "wrong_point": snapshot.get("wrong_point"),
            "knowledge": snapshot.get("knowledge"),
            "method_gap": snapshot.get("method_gap"),
        },
        snapshot_card_id,
    )
    if rebuilt.get("source_version") != expected_version:
        return None
    return rebuilt


def shared_knowledge(anchor: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Return deterministic shared formal knowledge labels.

    This is deliberately a weaker relation than ``exact_evidence_match``.  A
    caller may use it to fill an existing-card queue, but must label the result
    as knowledge fallback rather than as the learner's same personal error.
    """
    left = {
        normalized_text(item).casefold(): normalized_text(item)
        for item in text_list(anchor.get("knowledge"))
    }
    right = {
        normalized_text(item).casefold(): normalized_text(item)
        for item in text_list(candidate.get("knowledge"))
    }
    return [left[key] for key in sorted(set(left) & set(right)) if key]


def exact_evidence_match(anchor: dict[str, Any], candidate: dict[str, Any]) -> tuple[int, list[str]]:
    """Return deterministic exact matches; semantic equivalence stays a model decision."""
    if not anchor.get("structured_targetable") or not candidate.get("structured_targetable"):
        return 0, []
    reasons: list[str] = []
    score = 0
    anchor_gap = anchor.get("method_gap") if isinstance(anchor.get("method_gap"), dict) else {}
    candidate_gap = candidate.get("method_gap") if isinstance(candidate.get("method_gap"), dict) else {}

    anchor_specific = anchor.get("specific_fields") if isinstance(anchor.get("specific_fields"), dict) else {}
    candidate_specific = (
        candidate.get("specific_fields") if isinstance(candidate.get("specific_fields"), dict) else {}
    )
    primary_match = False
    method_primary_match = False
    for field, weight, label in (
        ("missed_action", 5, "相同漏掉动作"),
        ("expected_first_action", 4, "相同第一动作"),
    ):
        left = clean_text(anchor_gap.get(field))
        right = clean_text(candidate_gap.get(field))
        if (
            anchor_specific.get(field) is True
            and candidate_specific.get(field) is True
            and left
            and right
            and normalized_text(left).casefold() == normalized_text(right).casefold()
        ):
            score += weight
            reasons.append(label)
            primary_match = True
            method_primary_match = True

    left_wrong = clean_text(anchor.get("wrong_point"))
    right_wrong = clean_text(candidate.get("wrong_point"))
    both_have_specific_method_gap = bool(
        anchor_gap.get("enabled") is True
        and candidate_gap.get("enabled") is True
        and (
            anchor_specific.get("missed_action") is True
            or anchor_specific.get("expected_first_action") is True
        )
        and (
            candidate_specific.get("missed_action") is True
            or candidate_specific.get("expected_first_action") is True
        )
    )
    if (
        anchor_specific.get("wrong_point") is True
        and candidate_specific.get("wrong_point") is True
        and left_wrong
        and right_wrong
        and normalized_text(left_wrong).casefold() == normalized_text(right_wrong).casefold()
        and (method_primary_match or not both_have_specific_method_gap)
    ):
        score += 5
        reasons.append("相同具体错点")
        primary_match = True

    trigger_equal = bool(
        anchor_specific.get("method_trigger") is True
        and candidate_specific.get("method_trigger") is True
        and clean_text(anchor_gap.get("method_trigger"))
        and normalized_text(anchor_gap.get("method_trigger")).casefold()
        == normalized_text(candidate_gap.get("method_trigger")).casefold()
    )
    action_gap_equal = bool(
        clean_text(anchor_gap.get("action_gap_type"))
        and clean_text(anchor_gap.get("action_gap_type")) == clean_text(candidate_gap.get("action_gap_type"))
    )
    method_card_equal = bool(
        clean_text(anchor_gap.get("related_method_card_id"))
        and clean_text(anchor_gap.get("related_method_card_id"))
        == clean_text(candidate_gap.get("related_method_card_id"))
    )
    # Trigger, taxonomy, and method-card equality are corroboration only.  A
    # correct solution route or broad topic is never personal-error evidence.
    if primary_match and trigger_equal:
        score += 1
        reasons.append("方法触发一致")
    if primary_match and action_gap_equal:
        score += 1
        reasons.append("动作断点类型一致")
    if primary_match and method_card_equal:
        score += 1
        reasons.append("方法卡一致")
    return score, reasons
