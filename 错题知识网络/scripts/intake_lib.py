#!/usr/bin/env python3
"""Shared read-only helpers for the intake_* fast-path scripts.

Data source is 生成/wrong_questions.json (produced by wrongnet.py rebuild).
This module never writes anything.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import training_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_JSON = PROJECT_ROOT / "错题知识网络" / "生成" / "wrong_questions.json"

DATE_RE = re.compile(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月]?(\d{1,2})")
MASTERED = "已掌握"


def load_generated_cards() -> tuple[list[dict[str, Any]], str]:
    """Return (cards, updated_at). Empty list when the generated JSON is missing."""
    if not GENERATED_JSON.exists():
        return [], "missing"
    try:
        data = json.loads(GENERATED_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], "invalid_json"
    return data.get("cards", []), str(data.get("updated_at", "unknown"))


def _entry_text(item: Any) -> str:
    if isinstance(item, dict):
        return "；".join(f"{key}: {value}" for key, value in item.items() if str(value).strip())
    return str(item).strip()


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [text for item in value if (text := _entry_text(item))]
    text = _entry_text(value)
    return [text] if text else []


def extract_dates(entries: Any) -> list[str]:
    """ISO-normalized dates found in wrong_history-style strings, ascending."""
    dates: list[str] = []
    for entry in as_list(entries):
        match = DATE_RE.search(entry)
        if match:
            year, month, day = match.groups()
            dates.append(f"{year}-{int(month):02d}-{int(day):02d}")
    return sorted(set(dates))


def is_mastered(meta: dict[str, Any]) -> bool:
    return str(meta.get("status", "")).strip() == MASTERED


def card_brief(card: dict[str, Any]) -> dict[str, Any]:
    meta = card.get("meta", {})
    dates = extract_dates(meta.get("wrong_history"))
    mastery = as_list(meta.get("mastery_history"))
    card_id = str(card.get("id") or meta.get("id") or "?")
    evidence = training_evidence.extract_error_evidence(meta, card_id)
    raw_method_gap = training_evidence.raw_method_gap(meta)
    return {
        "id": card_id,
        "title": str(meta.get("title", "")).strip(),
        "source": str(meta.get("source", "")).strip(),
        "status": str(meta.get("status", "")).strip(),
        "mistake_count": meta.get("mistake_count", ""),
        "dates": dates,
        "latest": dates[-1] if dates else "",
        "mastery_latest": mastery[-1] if mastery else "",
        "knowledge": as_list(meta.get("knowledge")),
        "wrong_point": str(meta.get("wrong_point", "")).strip(),
        # Preserve every formal-card field for the semantic review layer.  The
        # normalized, fail-closed subset used for deterministic ranking lives
        # under ``evidence.method_gap``.
        "method_gap": raw_method_gap,
        "evidence": evidence,
        "source_version": evidence["source_version"],
        "source_hash": evidence["source_hash"],
        "question_summary": str(meta.get("question_summary", "")).strip(),
        "methods": as_list(meta.get("methods")),
        "traps": as_list(meta.get("traps")),
        "path": card.get("path", ""),
    }


def history_phrase(brief: dict[str, Any]) -> str:
    """Render the mandatory redo-history phrase: latest date + count + all dates."""
    dates = brief["dates"]
    if dates:
        return f"最近 {dates[-1]}（已做{len(dates)}遍：{'、'.join(dates)}）"
    count = brief.get("mistake_count")
    count_text = f"记录次数 {count}" if str(count).strip() not in {"", "None"} else "次数未记录"
    return f"日期未确认（{count_text}）"


def redo_line(brief: dict[str, Any]) -> str:
    """One ready-to-quote data line for old-question recommendations."""
    head = brief["id"]
    label = brief["source"] or brief["title"]
    if label:
        head = f"{head}｜{label}"
    parts = [head, history_phrase(brief)]
    if brief["wrong_point"]:
        parts.append(f"错点：{brief['wrong_point']}")
    evidence = brief.get("evidence") if isinstance(brief.get("evidence"), dict) else {}
    if evidence:
        parts.append(f"错因证据：{evidence.get('origin_label', '待确认')}")
        method_gap = evidence.get("method_gap") if isinstance(evidence.get("method_gap"), dict) else {}
        if method_gap.get("missed_action"):
            parts.append(f"漏掉动作：{method_gap['missed_action']}")
        if method_gap.get("expected_first_action"):
            parts.append(f"应做第一动作：{method_gap['expected_first_action']}")
        if method_gap.get("method_trigger"):
            parts.append(f"方法触发：{method_gap['method_trigger']}")
        if method_gap.get("action_gap_type"):
            parts.append(f"动作断点：{method_gap['action_gap_type']}")
        parts.append(f"证据版本：{evidence.get('source_version', '')}")
    if brief["knowledge"]:
        parts.append(f"知识点：{'、'.join(brief['knowledge'][:4])}")
    if brief["mastery_latest"]:
        parts.append(f"掌握度：{brief['mastery_latest']}")
    parts.append(f"http://127.0.0.1:8765/open/{brief['id']}")
    return "｜".join(parts)


def cards_by_knowledge(cards: list[dict[str, Any]], tag: str) -> list[dict[str, Any]]:
    """Briefs of non-mastered cards whose knowledge matches tag (exact first, then fuzzy)."""
    tag = tag.strip()
    exact: list[dict[str, Any]] = []
    fuzzy: list[dict[str, Any]] = []
    for card in cards:
        meta = card.get("meta", {})
        if is_mastered(meta):
            continue
        knowledge = as_list(meta.get("knowledge"))
        if any(item == tag for item in knowledge):
            exact.append(card_brief(card))
        elif any(tag in item or item in tag for item in knowledge if item):
            fuzzy.append(card_brief(card))
    key = lambda brief: (brief["latest"] or "0000-00-00")  # noqa: E731 - local sort key
    exact.sort(key=key, reverse=True)
    fuzzy.sort(key=key, reverse=True)
    return exact + fuzzy
