#!/usr/bin/env python3
"""Two-phase, model-native semantic selection for math warmup v5.

This module never calls a model.  It freezes deterministic eligibility and
validates a semantic plan produced by a native Luna leaf and reopened by the
root Sol agent.  The separation is intentional: dates, identities, hashes,
exclusions, idempotence, and writes are code-owned; semantic comparison is not.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping


CANDIDATE_SCHEMA_VERSION = "warmup-candidate-bundle-v2"
SEMANTIC_PLAN_SCHEMA_VERSION = "warmup-semantic-plan-v1"
SUCCESSOR_SCHEMA_VERSION = "prestudy-warmup-v5"
ALLOWED_MATCH_LEVELS = {"exact_gap", "fine_knowledge", "confusable_boundary"}
DEFAULT_STAGE_WINDOWS = {
    "unstable": [1, 2],
    "first_independent_correct": [5, 10],
    "second_independent_correct": [18, 35],
    "third_independent_correct": [40, 75],
    "long_term_maintenance": [75, 120],
}
PRIVATE_MAINTENANCE_PATTERN = re.compile(
    r"仅做(?:知识点|关系|语义)|没有新增用户作答|无新增用户作答|"
    r"Wiki|重建|索引|(?:索引|数据|正式|回滚)同步|关系维护|文件修改|"
    r"(?:旧|历史|批量|结构化).{0,12}导入|日期来自(?:标题|来源|文件名)|"
    r"待评分语义复核|导入记录|仅保留来源定位|仅确认一条导入|"
    r"(?:本轮|本次).{0,8}(?:只|仅).{0,35}(?:补强|补全|复做入口|视觉错连|语义复核)|"
    r"待评分.{0,30}(?:缺少|缺乏|没有).{0,12}(?:作答|过程)|"
    r"(?:缺少|未记录).{0,12}用户.{0,10}(?:作答|过程)"
)
LEGACY_UNDATED_IMPORT_PATTERN = re.compile(
    r"(?:旧|历史|批量|结构化).{0,12}导入|日期(?:来自(?:标题|来源|文件名)|未归档|未确认)"
)
INDEPENDENT_CORRECT_PATTERN = re.compile(
    r"(?:无提示|未使用提示|没有提示|独立|闭卷).{0,20}(?:做对|答对|正确|完成)|"
    r"(?:做对|答对|正确|完成).{0,20}(?:无提示|独立|闭卷)"
)
UNSTABLE_PATTERN = re.compile(
    r"做错|出错|错误|不会|无法启动|选错|复发|尚未独立|未独立|"
    r"提示后|讲解后|解析后|看过答案|看过解析|AI评分\s*[0-3](?:/5)?"
)
ACTIVITY_PATTERN = re.compile(
    r"作答|复做|做错|做对|答对|正确|不会|无法启动|选错|复发|"
    r"提示|讲解|解析|闭卷|独立|评分"
)
DATE_IN_TEXT_PATTERN = re.compile(r"(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)")


class WarmupV5Error(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def format_date(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, date) else None


def positive_window(value: Any, default: list[int], *, field: str) -> list[int]:
    raw = value if isinstance(value, list) else default
    if len(raw) != 2:
        raise WarmupV5Error(f"{field} 必须是 [最小天数, 最大天数]")
    try:
        low, high = int(raw[0]), int(raw[1])
    except (TypeError, ValueError) as exc:
        raise WarmupV5Error(f"{field} 必须包含整数") from exc
    if low <= 0 or high < low:
        raise WarmupV5Error(f"{field} 必须满足 0 < 最小天数 <= 最大天数")
    return [low, high]


def stage_windows(config: Mapping[str, Any]) -> dict[str, list[int]]:
    raw = config.get("stage_windows")
    raw = raw if isinstance(raw, dict) else {}
    return {
        name: positive_window(raw.get(name), default, field=f"stage_windows.{name}")
        for name, default in DEFAULT_STAGE_WINDOWS.items()
    }


def stage_name_for_successes(successes: int) -> str:
    if successes <= 0:
        return "unstable"
    if successes == 1:
        return "first_independent_correct"
    if successes == 2:
        return "second_independent_correct"
    if successes == 3:
        return "third_independent_correct"
    return "long_term_maintenance"


def stage_index(stage_name: str) -> int:
    order = [
        "unstable",
        "first_independent_correct",
        "second_independent_correct",
        "third_independent_correct",
        "long_term_maintenance",
    ]
    return order.index(stage_name)


def choose_interval(
    window: list[int],
    *,
    high_risk: bool,
    activity_date: date,
    exam_date: date,
) -> tuple[int, list[int], str]:
    low, high = window
    remaining = max(1, (exam_date - activity_date).days)
    bounded_low = min(low, remaining)
    bounded_high = min(high, remaining)
    if bounded_high < bounded_low:
        bounded_low = bounded_high
    target = bounded_low if high_risk else (bounded_low + bounded_high + 1) // 2
    reason = "高风险取窗口下界" if high_risk else "普通风险取窗口中部"
    if bounded_high != high:
        reason += "；受考试剩余保持期有界压缩"
    return max(1, target), [max(1, bounded_low), max(1, bounded_high)], reason


def stage_schedule_after_score(
    *,
    score: int,
    unit: dict[str, Any],
    config: Mapping[str, Any],
    current_date: date,
    exam_date: date,
) -> dict[str, Any]:
    """Return a configurable evidence-stage schedule after a real attempt."""

    windows = stage_windows(config)
    old_successes = max(0, int(unit.get("连续延迟成功次数") or 0))
    if score >= 4:
        successes = old_successes + 1
    else:
        # Wrong, unable-to-start, or hint-assisted completion has not yet
        # independently verified the repair, so the evidence stage restarts.
        successes = 0
    name = stage_name_for_successes(successes)
    high_risk = (
        unit.get("调度优先级") == "高"
        or int(unit.get("重要程度") or 3) >= 5
        or int(unit.get("错误次数") or 0) >= 3
        or int(unit.get("掌握度") or 3) <= 2
    )
    interval, bounded_window, reason = choose_interval(
        windows[name],
        high_risk=high_risk,
        activity_date=current_date,
        exam_date=exam_date,
    )
    return {
        "stage_name": name,
        "stage_index": stage_index(name),
        "independent_successes": successes,
        "window_days": bounded_window,
        "interval_days": interval,
        "selection_reason": reason,
        "scheduling_priority": "普通" if successes >= 2 else "高",
    }


def text_date(value: Any) -> date | None:
    match = DATE_IN_TEXT_PATTERN.search(str(value or ""))
    return parse_date(match.group(1)) if match else None


def add_activity(
    target: dict[str, list[dict[str, Any]]],
    card_id: str,
    *,
    event_date: date | None,
    kind: str,
    evidence_id: str,
    source: str,
) -> None:
    if event_date is None or not card_id:
        return
    item = {
        "date": event_date.isoformat(),
        "kind": kind,
        "evidence_id": evidence_id,
        "source": source,
    }
    bucket = target.setdefault(card_id, [])
    if item not in bucket:
        bucket.append(item)


def load_quick_intake_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WarmupV5Error(f"快速入库事件第 {line_number} 行不是有效 JSON") from exc
        if isinstance(item, dict):
            result.append(item)
    return result


def real_activity_index(
    *,
    legacy: Mapping[str, Any],
    cards_by_id: dict[str, tuple[Path, dict[str, Any]]],
    units: list[dict[str, Any]],
    before_date: date,
) -> dict[str, list[dict[str, Any]]]:
    """Build typed learning activity; maintenance metadata never enters here."""

    result: dict[str, list[dict[str, Any]]] = {}
    card_by_unit: dict[str, str] = {}
    for unit in units:
        card_id = str(unit.get("关联错题ID") or "").strip()
        unit_id = str(unit.get("复习单元ID") or "").strip()
        if not card_id:
            continue
        if unit_id:
            card_by_unit[unit_id] = card_id
        card_data = cards_by_id.get(card_id, (None, {}))[1]
        history = " ".join(str(x) for field in ("wrong_history", "mastery_history")
                           for x in (card_data.get(field) or []))
        # Unsynchronized legacy units often copied the spreadsheet import date
        # into both fields. Explicit import/unknown-date prose cannot prove a
        # real contact. Actual card events, Captures and review/delivery logs
        # below remain authoritative and are never suppressed by this check.
        if not unit.get("定点同步状态") and (
            LEGACY_UNDATED_IMPORT_PATTERN.search(history)
            or str(card_data.get("import_batch", "")).startswith("XLSX-")
        ):
            continue
        add_activity(
            result,
            card_id,
            event_date=parse_date(unit.get("首次学习日期")),
            kind="initial_learning",
            evidence_id=f"unit:{unit_id}:first",
            source="复习单元.首次学习日期",
        )
        add_activity(
            result,
            card_id,
            event_date=parse_date(unit.get("最近复发日期")),
            kind="wrong_or_unverified",
            evidence_id=f"unit:{unit_id}:recurrence",
            source="复习单元.最近复发日期",
        )

    for card_id, (path, data) in cards_by_id.items():
        for field in ("wrong_history", "mastery_history"):
            entries = data.get(field)
            if not isinstance(entries, list):
                continue
            for index, entry in enumerate(entries):
                text = str(entry or "").strip()
                event_date = text_date(text)
                if event_date is None or PRIVATE_MAINTENANCE_PATTERN.search(text):
                    continue
                if field == "wrong_history":
                    kind = "wrong_or_unverified"
                elif INDEPENDENT_CORRECT_PATTERN.search(text):
                    kind = "independent_correct"
                elif UNSTABLE_PATTERN.search(text):
                    kind = "wrong_or_unverified"
                elif ACTIVITY_PATTERN.search(text):
                    kind = "answer_or_exposure"
                else:
                    continue
                add_activity(
                    result,
                    card_id,
                    event_date=event_date,
                    kind=kind,
                    evidence_id=f"card:{sha256_path(path)}:{field}:{index}",
                    source=f"{path.name}:{field}[{index}]",
                )

    for event in legacy["load_review_logs"]():
        event_date = parse_date(event.get("date"))
        if event_date is None or event_date >= before_date:
            continue
        card_id = str(event.get("delivered_card_id") or "").strip()
        if not card_id:
            card_id = card_by_unit.get(str(event.get("unit_id") or "").strip(), "")
        score = legacy["to_int"](event.get("score"), -1)
        kind = "independent_correct" if score >= 4 else "wrong_or_unverified"
        add_activity(
            result,
            card_id,
            event_date=event_date,
            kind=kind,
            evidence_id=str(event.get("event_id") or canonical_json(event)),
            source="复习记录.jsonl",
        )

    for queue in legacy["load_warmup_logs"]():
        event_date = parse_date(queue.get("date"))
        if event_date is None or event_date >= before_date:
            continue
        selected = queue.get("selected")
        if not isinstance(selected, list):
            continue
        for index, item in enumerate(selected):
            if isinstance(item, dict):
                card_id = str(item.get("delivered_card_id") or item.get("id") or "").strip()
            else:
                card_id = str(item or "").strip()
            add_activity(
                result,
                card_id,
                event_date=event_date,
                kind="answer_or_exposure",
                evidence_id=f"queue:{queue.get('queue_id')}:{index}",
                source="学习前5题记录.jsonl",
            )

    quick_path = Path(legacy["QUICK_INTAKE_EVENTS_PATH"])
    for event in load_quick_intake_events(quick_path):
        if event.get("event_type") != "capture":
            continue
        target = event.get("target") if isinstance(event.get("target"), dict) else {}
        score_ref = event.get("score_ref") if isinstance(event.get("score_ref"), dict) else {}
        card_id = str(target.get("formal_id") or score_ref.get("formal_id") or "").strip()
        event_date = parse_date(event.get("study_date") or score_ref.get("study_date"))
        if event_date is None or event_date >= before_date:
            continue
        score = legacy["to_int"](score_ref.get("score"), -1)
        kind = "independent_correct" if score >= 4 else "wrong_or_unverified"
        add_activity(
            result,
            card_id,
            event_date=event_date,
            kind=kind,
            evidence_id=str(event.get("event_id") or canonical_json(event)),
            source="快速入库事件.jsonl",
        )

    for card_id in result:
        result[card_id].sort(key=lambda item: (item["date"], item["kind"], item["evidence_id"]))
    return result


def activity_stage(
    activities: list[dict[str, Any]],
    *,
    independently_correct_from_formal: bool,
) -> tuple[str, int, date | None]:
    if not activities:
        successes = 1 if independently_correct_from_formal else 0
        return stage_name_for_successes(successes), successes, None
    successes = 0
    grouped: dict[str, set[str]] = {}
    for item in activities:
        grouped.setdefault(str(item["date"]), set()).add(str(item["kind"]))
    for day in sorted(grouped):
        kinds = grouped[day]
        if "wrong_or_unverified" in kinds:
            successes = 0
        elif "independent_correct" in kinds:
            successes += 1
        else:
            successes = 0
    latest = parse_date(sorted(grouped)[-1])
    return stage_name_for_successes(successes), successes, latest


def cards_by_id_from_candidates(
    legacy: Mapping[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, tuple[Path, dict[str, Any]]]:
    result: dict[str, tuple[Path, dict[str, Any]]] = {}
    repo_root = Path(legacy["REPO_ROOT"]).resolve()
    for candidate in candidates:
        card_id = str(candidate.get("id") or "")
        path = (repo_root / str(candidate.get("path") or "")).resolve()
        try:
            path.relative_to(repo_root)
        except ValueError as exc:
            raise WarmupV5Error(f"正式卡路径越出仓库：{card_id}") from exc
        data = legacy["parse_card_frontmatter"](path)
        result[card_id] = (path, data)
    return result


def anchor_rows(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = [{**row, "anchor_id": row.get("anchor_id") or row.get("formal_id")} for row in bundle.get("anchors", [])]
    return indexed_rows(rows, field="anchor_id", label="anchors")


def concept_history(legacy: Mapping[str, Any]) -> dict[str, Any]:
    """Read typed point evidence only; related cards never gain activity here."""
    loader = legacy.get("load_concept_point_history")
    root = Path(legacy["REPO_ROOT"])
    if loader is None:
        index = root / "错题知识网络/个人知识点索引/index.sqlite3"
        # Old isolated repositories have no concept subsystem at all.
        if not index.exists() and not (root / "错题知识网络/scripts/math_concept_index.py").exists():
            return {"status": "ready", "points": []}
        import math_concept_index
        loader = lambda: math_concept_index.point_history(root)
    result = loader()
    if result.get("status") != "ready":
        raise WarmupV5Error("concept_history_not_ready_refresh_required")
    return result


def concept_evidence_for_day(legacy: Mapping[str, Any], current_date: date, limit: int) -> tuple[list[dict], dict]:
    points = []
    for original in concept_history(legacy).get("points", []):
        point = deepcopy(original)
        events = [event for event in point.get("events", [])
                  if parse_date(event.get("study_date")) is not None and parse_date(event["study_date"]) <= current_date]
        if not events:
            continue
        for event in events:
            for ref in event.get("source_refs", []):
                path = (Path(legacy["REPO_ROOT"]) / ref["path"]).resolve()
                if not path.is_relative_to(Path(legacy["REPO_ROOT"]).resolve()) or not path.is_file() or sha256_path(path) != ref["sha256"]:
                    raise WarmupV5Error("concept_source_changed_refresh_required:" + ref["path"])
        point["wrong_episode_count"] = len({e.get("episode_id", e["event_id"]) for e in events if "wrong" in e.get("outcomes", [])})
        point["events"] = events
        point["latest_event"] = events[-1]
        point.pop("point_source_version", None)
        point["point_source_version"] = sha256_bytes(canonical_json(point).encode())
        if len(canonical_json(point).encode()) > 2_000_000:
            raise WarmupV5Error("concept_evidence_point_exceeds_bound:" + point["concept_key"])
        points.append(point)
    points.sort(key=lambda p: (bool(set(p["latest_event"].get("outcomes", [])) & {"wrong", "unresolved", "corrected_after_hint"}), p["latest_event"]["study_date"], p["concept_key"]), reverse=True)
    selected = points[:limit]
    return selected, {"schema_version": "warmup-concept-evidence-v1", "point_limit": limit,
                      "total_point_count": len(points), "included_point_count": len(selected),
                      "omitted_concept_keys": [p["concept_key"] for p in points[limit:]],
                      "complete_events_for_included_points": True,
                      "source_version": sha256_bytes(canonical_json(selected).encode())}


def concept_anchors(points: list[dict], current_date: date, windows: dict, exam_date: date) -> list[dict]:
    rows = []
    for point in points:
        activity = []
        for event in point["events"]:
            outcomes = event.get("outcomes", [])
            kind = "wrong_or_unverified" if any(v in {"wrong", "unresolved", "corrected_after_hint"} for v in outcomes) else "independent_correct"
            activity.append({"date": event["study_date"], "kind": kind, "evidence_id": event["event_id"]})
        stage, successes, last_day = activity_stage(activity, independently_correct_from_formal=False)
        if last_day is None:
            continue
        interval, window, reason = choose_interval(windows[stage], high_risk=stage == "unstable", activity_date=last_day, exam_date=exam_date)
        due = last_day + timedelta(days=interval)
        if due > current_date:
            continue
        refs = list({ref["path"]: ref for event in point["events"] for ref in event["source_refs"]}.values())
        rows.append({"anchor_id": point["concept_key"], "anchor_kind": "concept_review",
                     "concept_key": point["concept_key"], "label": point["label"],
                     "source_refs": refs, "point_source_version": point["point_source_version"],
                     "related_formal_ids": point.get("formal_ids", []), "anchor_due": True,
                     "last_real_activity_date": last_day.isoformat(), "real_activity_evidence": activity,
                     "stage_name": stage, "independent_successes": successes, "stage_window_days": window,
                     "chosen_interval_days": interval, "interval_reason": reason,
                     "effective_due_date": due.isoformat(), "deterministic_priority": int(stage == "unstable")})
    return rows


def build_candidate_bundle(
    *,
    current_date: date,
    count: int,
    legacy: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    config = legacy["load_progress_config"]()
    exam_date = legacy["load_exam_date"](required=True)
    if not isinstance(exam_date, date):
        raise WarmupV5Error("缺少有效 exam_date")
    if current_date > exam_date:
        raise WarmupV5Error("学习前队列日期不得晚于考试日期")
    units = legacy["load_units"]()
    candidates = legacy["build_warmup_candidates"](
        current_date,
        config,
        units,
        exam_date=exam_date,
    )
    candidates_by_id = {str(item.get("id")): item for item in candidates}
    cards_by_id = cards_by_id_from_candidates(legacy, candidates)
    activities = real_activity_index(
        legacy=legacy,
        cards_by_id=cards_by_id,
        units=units,
        # Events on the target date are genuine Day 0 activity and must count.
        before_date=current_date + timedelta(days=1),
    )
    windows = stage_windows(config)
    exclude_recent_days = legacy["to_int"](config.get("exclude_recent_days"), 7)
    if exclude_recent_days != 7:
        raise WarmupV5Error("warmup v5 的交付硬门禁必须保持 Day 0-7")
    delivery_cutoff = current_date - timedelta(days=8)
    units_by_card = legacy["unit_by_card_id"](units)

    deterministic_rows: dict[str, dict[str, Any]] = {}
    anchors: list[dict[str, Any]] = []
    repair_window = positive_window(
        config.get("same_item_repair_window"),
        [1, 2],
        field="same_item_repair_window",
    )
    repairs: list[dict[str, Any]] = []

    for card_id, candidate in candidates_by_id.items():
        card_activities = activities.get(card_id, [])
        name, successes, latest_activity = activity_stage(
            card_activities,
            independently_correct_from_formal=bool(candidate.get("independently_correct")),
        )
        high_risk = legacy["unit_is_high_risk"](units_by_card[card_id]) if card_id in units_by_card else False
        effective_due: date | None = None
        chosen_interval: int | None = None
        bounded_window = windows[name]
        interval_reason = "缺少真实活动日期，不生成到期 anchor"
        if latest_activity is not None:
            chosen_interval, bounded_window, interval_reason = choose_interval(
                windows[name],
                high_risk=high_risk,
                activity_date=latest_activity,
                exam_date=exam_date,
            )
            effective_due = latest_activity + timedelta(days=chosen_interval)
        row = {
            "formal_id": card_id,
            "anchor_id": card_id,
            "anchor_kind": "formal_card",
            "path": candidate.get("path"),
            "sha256": candidate.get("card_source_version"),
            "source_version": candidate.get("card_source_version"),
            "evidence_source_version": candidate.get("evidence_source_version"),
            "unit_source_version": candidate.get("unit_source_version"),
            "public_source": candidate.get("source"),
            "module": candidate.get("module"),
            "last_real_activity_date": format_date(latest_activity),
            "real_activity_evidence": card_activities,
            "stage_name": name,
            "independent_successes": successes,
            "stage_window_days": bounded_window,
            "chosen_interval_days": chosen_interval,
            "interval_reason": interval_reason,
            "effective_due_date": format_date(effective_due),
            "permanently_delivery_excluded": bool(candidate.get("independently_correct")),
            "status": candidate.get("status"),
        }
        deterministic_rows[card_id] = row
        unit = units_by_card.get(card_id)
        if unit is not None and effective_due is not None and effective_due <= current_date:
            anchors.append(
                {
                    **row,
                    "anchor_unit_id": unit.get("复习单元ID"),
                    "anchor_due": True,
                    "deterministic_priority": legacy["priority_score"](unit, current_date),
                }
            )
        if latest_activity is not None and name == "unstable":
            age = (current_date - latest_activity).days
            if repair_window[0] <= age <= repair_window[1]:
                repairs.append(
                    {
                        "formal_id": card_id,
                        "path": candidate.get("path"),
                        "sha256": candidate.get("card_source_version"),
                        "last_real_activity_date": latest_activity.isoformat(),
                        "repair_age_days": age,
                        "channel": "same_item_repair",
                        "occupies_daily_warmup_slot": False,
                        "advances_long_term": False,
                    }
                )

    points, concept_contract = concept_evidence_for_day(legacy, current_date, max(count * 16, 80))
    anchors.extend(concept_anchors(points, current_date, windows, exam_date))
    anchors.sort(
        key=lambda item: (
            stage_index(str(item.get("stage_name") or "unstable")),
            -(
                parse_date(item.get("last_real_activity_date")).toordinal()
                if parse_date(item.get("last_real_activity_date"))
                else 0
            ),
            0 if item.get("anchor_kind") == "concept_review" else 1,
            str(item.get("effective_due_date") or "9999-12-31"),
            -int(item.get("deterministic_priority") or 0),
            str(item.get("anchor_id")),
        )
    )
    anchor_limit = max(count * 8, 40)
    bounded_anchors = anchors[:anchor_limit]

    eligible_candidates: list[dict[str, Any]] = []
    recent_exclusions: list[dict[str, Any]] = []
    for card_id, candidate in candidates_by_id.items():
        row = deterministic_rows[card_id]
        last_activity = parse_date(row.get("last_real_activity_date"))
        if last_activity is not None and (current_date - last_activity).days <= 7:
            recent_exclusions.append(
                {
                    "formal_id": card_id,
                    "last_real_activity_date": last_activity.isoformat(),
                    "excluded_day_age": (current_date - last_activity).days,
                }
            )
            continue
        if str(candidate.get("status") or "") in legacy["MASTERED_STATUSES"]:
            continue
        if candidate.get("independently_correct"):
            continue
        eligible_candidates.append(
            {
                "formal_id": card_id,
                "path": candidate.get("path"),
                "sha256": candidate.get("card_source_version"),
                "source_version": candidate.get("card_source_version"),
                "evidence_source_version": candidate.get("evidence_source_version"),
                "unit_source_version": candidate.get("unit_source_version"),
                "public_source": candidate.get("source"),
                "module": candidate.get("module"),
                "last_real_activity_date": format_date(last_activity),
                "real_activity_evidence": row["real_activity_evidence"],
                "day_gate": "eligible_day_8_or_older" if last_activity else "eligible_no_recorded_activity",
            }
        )
    eligible_candidates.sort(key=lambda item: str(item["formal_id"]))
    recent_exclusions.sort(key=lambda item: str(item["formal_id"]))
    repairs.sort(key=lambda item: (item["last_real_activity_date"], item["formal_id"]))

    payload: dict[str, Any] = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "date": current_date.isoformat(),
        "requested_count": count,
        "exam_date": exam_date.isoformat(),
        "delivery_gate": {
            "exclude_day_0_through_7": True,
            "first_eligible_day": 8,
            "eligible_on_or_before": delivery_cutoff.isoformat(),
        },
        "stage_windows": windows,
        "same_item_repair_window": repair_window,
        "allowed_roots": sorted({str(Path(legacy["WRONGNET_CARDS_DIR"]).resolve()),
                                *[str((Path(legacy["REPO_ROOT"]) / ref["path"]).resolve().parent)
                                  for p in points for event in p["events"] for ref in event["source_refs"]]}),
        "concept_evidence": points,
        "concept_evidence_contract": concept_contract,
        "semantic_contract": {
            "python_semantic_ranking_performed": False,
            "native_reader_required": True,
            "supported_plan_schemas": [SEMANTIC_PLAN_SCHEMA_VERSION, "warmup-semantic-plan-v2", "warmup-semantic-plan-v3"],
        },
        "anchors": bounded_anchors,
        "eligible_candidates": eligible_candidates,
        "same_item_repairs": repairs,
        "recent_delivery_exclusions": recent_exclusions,
        "stats": {
            "all_due_anchor_count": len(anchors),
            "concept_anchor_scope": "included_concept_evidence_only",
            "omitted_concept_count": len(concept_contract["omitted_concept_keys"]),
            "bounded_anchor_count": len(bounded_anchors),
            "eligible_candidate_count": len(eligible_candidates),
            "recent_delivery_exclusion_count": len(recent_exclusions),
            "same_item_repair_count": len(repairs),
            "anchor_limit": anchor_limit,
        },
    }
    payload["candidate_bundle_sha256"] = sha256_bytes(canonical_json(payload).encode("utf-8"))
    return payload, candidates_by_id


def verify_bundle_self_hash(bundle: dict[str, Any]) -> str:
    expected = str(bundle.get("candidate_bundle_sha256") or "")
    payload = deepcopy(bundle)
    payload.pop("candidate_bundle_sha256", None)
    actual = sha256_bytes(canonical_json(payload).encode("utf-8"))
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or actual != expected:
        raise WarmupV5Error("candidate bundle 自身哈希无效")
    return expected


def write_or_print(payload: dict[str, Any], output: Any, legacy: Mapping[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output:
        path = Path(str(output)).expanduser().resolve()
        legacy["atomic_write_text"](path, text)
        print(f"已写入只读候选包：{path}（{payload.get('candidate_bundle_sha256', 'n/a')}）")
    else:
        print(text, end="")


def command_context(args: Any, legacy: Mapping[str, Any]) -> tuple[date, int]:
    current_date = legacy["today_from_arg"](getattr(args, "date", None))
    config = legacy["load_progress_config"]()
    count = getattr(args, "count", None) or legacy["to_int"](config.get("default_count"), 5)
    if count <= 0:
        raise WarmupV5Error("题目数量必须大于 0")
    return current_date, count


def cmd_candidates(args: Any, legacy: Mapping[str, Any]) -> None:
    try:
        current_date, count = command_context(args, legacy)
        bundle, _ = build_candidate_bundle(current_date=current_date, count=count, legacy=legacy)
        write_or_print(bundle, getattr(args, "output", None), legacy)
    except (WarmupV5Error, legacy["RollbackSyncError"]) as exc:
        raise SystemExit(str(exc)) from exc


def cmd_same_item_repair(args: Any, legacy: Mapping[str, Any]) -> None:
    try:
        current_date = legacy["today_from_arg"](getattr(args, "date", None))
        config = legacy["load_progress_config"]()
        count = legacy["to_int"](config.get("default_count"), 5)
        bundle, _ = build_candidate_bundle(current_date=current_date, count=count, legacy=legacy)
        payload = {
            "schema_version": "same-item-repair-v1",
            "date": current_date.isoformat(),
            "occupies_daily_warmup_slot": False,
            "advances_long_term": False,
            "items": bundle["same_item_repairs"],
        }
        write_or_print(payload, getattr(args, "output", None), legacy)
    except (WarmupV5Error, legacy["RollbackSyncError"]) as exc:
        raise SystemExit(str(exc)) from exc


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WarmupV5Error(f"{label} 不是可读 JSON：{path}") from exc
    if not isinstance(value, dict):
        raise WarmupV5Error(f"{label} 顶层必须是对象")
    return value


def indexed_rows(rows: Any, *, field: str, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise WarmupV5Error(f"{label} 必须是数组")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise WarmupV5Error(f"{label} 元素必须是对象")
        identity = str(row.get(field) or "").strip()
        if not identity or identity in result:
            raise WarmupV5Error(f"{label} 的 {field} 缺失或重复：{identity}")
        result[identity] = row
    return result


def verify_semantic_plan(
    *,
    plan: dict[str, Any],
    bundle: dict[str, Any],
    repo_root: Path,
    count: int,
) -> list[dict[str, Any]]:
    if plan.get("schema_version") not in (SEMANTIC_PLAN_SCHEMA_VERSION, "warmup-semantic-plan-v2", "warmup-semantic-plan-v3"):
        raise WarmupV5Error("semantic plan schema_version 无效")
    bundle_sha = verify_bundle_self_hash(bundle)
    if plan.get("candidate_bundle_sha256") != bundle_sha:
        raise WarmupV5Error("semantic plan 未绑定当前 candidate bundle")
    native = plan.get("schema_version") in {"warmup-semantic-plan-v2", "warmup-semantic-plan-v3"}
    execution = plan.get("reader_execution" if native else "luna_execution")
    if not isinstance(execution, dict):
        raise WarmupV5Error("semantic plan 缺少原生 reader execution")
    required = {"read_only": True, "semantic_read_performed": True, "status": "completed"}
    if not native:
        required.update(model="gpt-5.6-luna", reasoning_effort="max")
    for field, expected in required.items():
        if execution.get(field) != expected:
            raise WarmupV5Error(f"原生读取执行字段无效：{field}")
    if not str(execution.get("agent_id") or "").strip():
        raise WarmupV5Error("原生读取执行缺少 agent_id")
    if native and execution.get("execution_kind") != "native_subagent":
        raise WarmupV5Error("v2 必须绑定 native_subagent，外部 C 不得冒充")
    if plan.get("semantic_ordering_decided") is not True:
        raise WarmupV5Error("Luna 语义结果必须实际决定候选顺序")

    sol = plan.get("sol_verification")
    if not isinstance(sol, dict) or sol.get("sol_reopened") is not True:
        raise WarmupV5Error("主 Sol 尚未重开相同字节")
    if not str(sol.get("verified_at") or "").strip():
        raise WarmupV5Error("主 Sol 复核缺少 verified_at")
    verified_rows = indexed_rows(
        sol.get("verified_evidence"),
        field="path",
        label="sol_verification.verified_evidence",
    )

    anchors = anchor_rows(bundle)
    candidates = indexed_rows(
        bundle.get("eligible_candidates"),
        field="formal_id",
        label="eligible_candidates",
    )
    recent_ids = {
        str(item.get("formal_id"))
        for item in bundle.get("recent_delivery_exclusions", [])
        if isinstance(item, dict)
    }
    selections = plan.get("selections")
    if not isinstance(selections, list):
        raise WarmupV5Error("semantic plan selections 必须是数组")
    if len(selections) > count:
        raise WarmupV5Error("semantic plan 不能超过请求题数")
    used_anchors: set[str] = set()
    used_deliveries: set[str] = set()
    verified: list[dict[str, Any]] = []
    for expected_rank, selection in enumerate(selections, start=1):
        if not isinstance(selection, dict) or int(selection.get("rank") or -1) != expected_rank:
            raise WarmupV5Error("semantic plan rank 必须从 1 连续递增")
        anchor_id = str(selection.get("anchor_id") or "").strip()
        delivered_id = str(selection.get("delivered_card_id") or "").strip()
        if anchor_id not in anchors or delivered_id not in candidates:
            raise WarmupV5Error(f"语义选择越出冻结范围：{anchor_id} -> {delivered_id}")
        if delivered_id in recent_ids:
            raise WarmupV5Error(f"Day 0-7 实际交付题被语义计划选中：{delivered_id}")
        if anchor_id == delivered_id:
            raise WarmupV5Error("每日迁移检查不得用同一原题替代 same_item_repair")
        if anchor_id in used_anchors or delivered_id in used_deliveries:
            raise WarmupV5Error("semantic plan anchor 或 delivered_card_id 重复")
        match_level = str(selection.get("match_level") or "")
        if match_level not in ALLOWED_MATCH_LEVELS:
            raise WarmupV5Error(f"match_level 无效：{match_level}")
        if not str(selection.get("private_reason") or "").strip():
            raise WarmupV5Error("Luna 选择缺少私有语义理由")
        if not str(selection.get("public_value_reason") or "").strip():
            raise WarmupV5Error("Luna 选择缺少答案安全的公开价值理由")
        alternatives = selection.get("alternatives_considered")
        if not isinstance(alternatives, list) or not alternatives:
            raise WarmupV5Error("Luna 必须比较至少一个未选替代候选")
        evidence = selection.get("evidence")
        if not isinstance(evidence, list):
            raise WarmupV5Error("语义选择 evidence 必须是数组")
        anchor = anchors[anchor_id]
        if anchor.get("anchor_kind") == "concept_review" and plan.get("schema_version") != "warmup-semantic-plan-v3":
            raise WarmupV5Error("concept_anchor_requires_semantic_plan_v3")
        refs = anchor.get("source_refs") or [{"path": anchor["path"], "sha256": anchor["sha256"]}]
        expected_evidence = {
            *[("anchor", ref["path"], ref["sha256"]) for ref in refs],
            ("candidate", str(candidates[delivered_id]["path"]), str(candidates[delivered_id]["sha256"])),
        }
        actual_evidence = {
            (str(item.get("role")), str(item.get("path")), str(item.get("sha256")))
            for item in evidence
            if isinstance(item, dict)
        }
        if not expected_evidence.issubset(actual_evidence):
            raise WarmupV5Error("Luna evidence 未绑定 anchor 与 candidate 的冻结路径/哈希")
        for _, relative, expected_sha in expected_evidence:
            path = (repo_root / relative).resolve()
            try:
                path.relative_to(repo_root)
            except ValueError as exc:
                raise WarmupV5Error(f"语义证据路径越出仓库：{relative}") from exc
            if not path.is_file() or sha256_path(path) != expected_sha:
                raise WarmupV5Error(f"语义证据字节已变化：{relative}")
            sol_row = verified_rows.get(relative)
            if sol_row is None or sol_row.get("sha256") != expected_sha:
                raise WarmupV5Error(f"主 Sol 未重开并复核证据：{relative}")
        used_anchors.add(anchor_id)
        used_deliveries.add(delivered_id)
        verified.append(selection)
    return verified


def successor_paths(
    *,
    current_date: date,
    count: int,
    queue_id: str,
    legacy: Mapping[str, Any],
) -> tuple[Path, Path]:
    suffix = "学习前5题" if count == 5 else f"学习前{count}题"
    public = Path(legacy["OUT_DIR"]).resolve() / f"{current_date.isoformat()}_{suffix}.successor-{queue_id}.md"
    return public, public.with_suffix(".internal.json")


def render_successor(
    *,
    current_date: date,
    count: int,
    queue_id: str,
    predecessor_id: str,
    selected: list[dict[str, Any]],
    plan_rows: list[dict[str, Any]],
    bundle: dict[str, Any],
) -> str:
    lines = [
        f"# {current_date.isoformat()} 学习前 {count} 题（v5 successor）",
        "",
        "用途：由确定性门禁冻结范围、原生代理实读正式卡语义、父代理重开同字节复核后生成。",
        "",
        f"队列 ID：{queue_id}",
        f"替代历史队列：{predecessor_id or '无（当天首次语义队列）'}",
        "",
        "## 选题边界",
        f"- Day 0-7 原题硬排除；{bundle['delivery_gate']['eligible_on_or_before']} 或更早才可实际投放。",
        "- same_item_repair 是独立通道，不占本队列名额。",
        "- 原生代理只做语义读取和价值比较；日期、身份、哈希、排除和写入由确定性代码复核。",
        "- 本页不公开 wrong_point、method_gap、私有错因、答案或解析。",
        "- 正式旧卡不足时少出，不生成题、不用近期题补位。",
        "",
        f"## 今日实际 {len(selected)} 题",
    ]
    for index, (item, semantic) in enumerate(zip(selected, plan_rows), start=1):
        lines.extend(
            [
                f"### {index}. {item.get('id')}",
                f"- 来源：{item.get('source') or '未记录'}",
                f"- 源版本：{str(item.get('card_source_version') or '')[:16]}",
                f"- 语义匹配层级：{semantic.get('match_level')}",
                f"- 选择价值：{semantic.get('public_value_reason')}",
                f"- 最近真实活动：{semantic.get('delivered_last_real_activity_date') or '无已记录活动'}",
                "- 题面状态：question_surface_pending（需由主 Sol 单独核验纯题面资产）",
                "",
                "本题结束后复用单题讲解与快速入库，只保存完整 Capture，随后继续预处理的下一题。",
                f"- Capture 附加身份：`--queue-id {queue_id} --item-id {item.get('queue_item_id')}`；不需要评分事件。",
                "- 正式判分、长期调度、知识点更新与发布在后续正式入库时处理。",
                "",
            ]
        )
    if len(selected) < count:
        lines.append(f"- 仅有 {len(selected)} 道通过全部门禁；不补近期题或生成题。")
    lines.append("")
    return "\n".join(lines)


def cmd_successor(args: Any, legacy: Mapping[str, Any]) -> None:
    try:
        current_date = legacy["today_from_arg"](getattr(args, "date", None))
        count = int(getattr(args, "count", 0))
        if count <= 0:
            raise WarmupV5Error("题目数量必须大于 0")
        predecessor_id = str(getattr(args, "supersedes_queue_id", "") or "").strip()
        if predecessor_id and not re.fullmatch(r"WQ-[0-9a-f]{24}", predecessor_id):
            raise WarmupV5Error("supersedes queue_id 无效")
        candidate_path = Path(str(getattr(args, "candidate_bundle"))).expanduser().resolve()
        semantic_path = Path(str(getattr(args, "semantic_plan"))).expanduser().resolve()
        supplied_bundle = load_json_object(candidate_path, "candidate bundle")
        supplied_bundle_sha = verify_bundle_self_hash(supplied_bundle)
        plan = load_json_object(semantic_path, "semantic plan")
        plan_sha = sha256_path(semantic_path)
        repo_root = Path(legacy["REPO_ROOT"]).resolve()

        logs = legacy["load_warmup_logs"]()
        def same_request(row: dict[str, Any]) -> bool:
            return (row.get("date") == current_date.isoformat()
                    and legacy["to_int"](row.get("requested_count"), -1) == count)

        if predecessor_id:
            predecessor_matches = [row for row in logs if row.get("queue_id") == predecessor_id]
            if len(predecessor_matches) != 1:
                raise WarmupV5Error("被替代队列必须唯一存在")
            if not same_request(predecessor_matches[0]):
                raise WarmupV5Error("successor 与历史队列日期/数量不一致")
            successors = [row for row in logs if row.get("supersedes_queue_id") == predecessor_id]
        else:
            # An initial semantic queue needs no artificial legacy deliveries.
            successors = [row for row in logs if same_request(row)]
        if successors:
            if len(successors) != 1:
                raise WarmupV5Error("历史队列存在多个 successor，拒绝分叉")
            existing = successors[0]
            if (
                existing.get("candidate_bundle_sha256") != supplied_bundle_sha
                or existing.get("semantic_plan_sha256") != plan_sha
            ):
                raise WarmupV5Error("历史队列已有不同 successor，拒绝覆盖或伪装复用")
            public = repo_root / str(existing.get("public_path") or "")
            internal = repo_root / str(existing.get("internal_path") or "")
            if (
                not public.is_file()
                or not internal.is_file()
                or sha256_path(public) != existing.get("public_sha256")
                or sha256_path(internal) != existing.get("internal_sha256")
            ):
                raise WarmupV5Error("已记录 successor 文件缺失或哈希漂移")
            print(f"successor 已存在，本次 noop：{public}（{existing.get('queue_id')}）")
            return

        live_bundle, live_candidates = build_candidate_bundle(
            current_date=current_date,
            count=count,
            legacy=legacy,
        )
        if canonical_json(supplied_bundle) != canonical_json(live_bundle):
            raise WarmupV5Error("candidate bundle 已过期；硬门禁或来源字节发生变化")
        plan_rows = verify_semantic_plan(
            plan=plan,
            bundle=supplied_bundle,
            repo_root=repo_root,
            count=count,
        )

        bundle_anchors = anchor_rows(supplied_bundle)
        bundle_candidates = indexed_rows(
            supplied_bundle["eligible_candidates"],
            field="formal_id",
            label="eligible_candidates",
        )
        native = plan.get("schema_version") in {"warmup-semantic-plan-v2", "warmup-semantic-plan-v3"}
        execution_key = "reader_execution" if native else "luna_execution"
        execution = plan[execution_key]
        query_key = "reader_query_id" if native else "luna_query_id"
        request_version = "native-reader-semantic-v2" if native else "native-luna-semantic-v1"
        selected: list[dict[str, Any]] = []
        enriched_plan_rows: list[dict[str, Any]] = []
        for row in plan_rows:
            anchor_id = str(row["anchor_id"])
            delivered_id = str(row["delivered_card_id"])
            selection_anchor = bundle_anchors[anchor_id]
            is_concept = selection_anchor.get("anchor_kind") == "concept_review"
            anchor = live_candidates[delivered_id if is_concept else anchor_id]
            delivered = live_candidates[delivered_id]
            match_level = str(row["match_level"])
            match_mode = "exact_gap" if match_level == "exact_gap" else "knowledge_fallback"
            item = legacy["attach_warmup_anchor"](
                delivered,
                anchor,
                selection_mode=f"{'native' if native else 'luna'}_semantic_{match_level}",
                match_mode=match_mode,
                match_reasons=["原生代理只读语义比较；父代理同哈希复核"],
            )
            if is_concept:
                # Actual delivered card is the only score target. The concept
                # remains an immutable selection reason, never a fake unit.
                item = legacy["attach_direct_due"](delivered)
                item["selection_mode"] = f"native_concept_{match_level}"
                item["selection_anchor"] = deepcopy(selection_anchor)
            item["semantic_selection_v5"] = True
            item["semantic_match_level"] = match_level
            item["semantic_private_reason"] = row["private_reason"]
            item["semantic_public_value_reason"] = row["public_value_reason"]
            item[query_key] = str(execution["agent_id"])
            item["candidate_bundle_sha256"] = supplied_bundle_sha
            item["semantic_plan_sha256"] = plan_sha
            item["semantic_evidence"] = deepcopy(row["evidence"])
            selected.append(item)
            enriched = deepcopy(row)
            enriched["delivered_last_real_activity_date"] = bundle_candidates[delivered_id].get(
                "last_real_activity_date"
            )
            enriched["anchor_effective_due_date"] = bundle_anchors[anchor_id].get(
                "effective_due_date"
            )
            enriched_plan_rows.append(enriched)

        queue_payload = {
            "schema_version": SUCCESSOR_SCHEMA_VERSION,
            "date": current_date.isoformat(),
            "requested_count": count,
            "supersedes_queue_id": predecessor_id,
            "candidate_bundle_sha256": supplied_bundle_sha,
            "semantic_plan_sha256": plan_sha,
            "selected": [
                {
                    "anchor_id": item.get("anchor_id"),
                    "delivered_card_id": item.get("id"),
                    "card_source_version": item.get("card_source_version"),
                    "anchor_card_source_version": item.get("anchor_card_source_version"),
                    "semantic_match_level": item.get("semantic_match_level"),
                }
                for item in selected
            ],
        }
        queue_id = f"WQ-{sha256_bytes(canonical_json(queue_payload).encode('utf-8'))[:24]}"
        public_path, internal_path = successor_paths(
            current_date=current_date,
            count=count,
            queue_id=queue_id,
            legacy=legacy,
        )
        internal_selected: list[dict[str, Any]] = []
        for item in selected:
            internal = legacy["warmup_internal_item"](item)
            internal.update(
                {
                    "semantic_selection_v5": True,
                    "semantic_match_level": item["semantic_match_level"],
                    "semantic_private_reason": item["semantic_private_reason"],
                    "semantic_public_value_reason": item["semantic_public_value_reason"],
                    query_key: item[query_key],
                    "candidate_bundle_sha256": supplied_bundle_sha,
                    "semantic_plan_sha256": plan_sha,
                    "semantic_evidence": deepcopy(item["semantic_evidence"]),
                }
            )
            if item.get("selection_anchor"):
                internal["selection_anchor"] = deepcopy(item["selection_anchor"])
            internal_selected.append(internal)
        manifest = {
            "schema_version": SUCCESSOR_SCHEMA_VERSION,
            "queue_id": queue_id,
            "date": current_date.isoformat(),
            "mode": "prestudy",
            "request_version": request_version,
            "requested_count": count,
            "actual_count": len(selected),
            "exam_date": supplied_bundle["exam_date"],
            "supersedes_queue_id": predecessor_id,
            "candidate_bundle_sha256": supplied_bundle_sha,
            "semantic_plan_sha256": plan_sha,
            execution_key: deepcopy(execution),
            "sol_verification": deepcopy(plan["sol_verification"]),
            "semantic_ordering_decided": True,
            "selected": internal_selected,
        }
        public_text = render_successor(
            current_date=current_date,
            count=count,
            queue_id=queue_id,
            predecessor_id=predecessor_id,
            selected=selected,
            plan_rows=enriched_plan_rows,
            bundle=supplied_bundle,
        )
        internal_text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        public_relative = public_path.relative_to(repo_root).as_posix()
        internal_relative = internal_path.relative_to(repo_root).as_posix()
        log_selected: list[dict[str, Any]] = []
        for item in internal_selected:
            log_selected.append(
                {
                    key: deepcopy(item.get(key))
                    for key in (
                        "queue_item_id",
                        "id",
                        "delivered_card_id",
                        "delivered_unit_id",
                        "unit_id",
                        "anchor_id",
                        "anchor_unit_id",
                        "anchor_gap_occurrence_id",
                        "selection_mode",
                        "match_mode",
                        "card_source_version",
                        "evidence_source_version",
                        "unit_source_version",
                        "anchor_card_source_version",
                        "anchor_unit_source_version",
                        "anchor_evidence_source_version",
                        "selection_anchor",
                        "semantic_selection_v5",
                        "semantic_match_level",
                        query_key,
                    )
                }
            )
        log_entry = {
            "schema_version": SUCCESSOR_SCHEMA_VERSION,
            "queue_id": queue_id,
            "date": current_date.isoformat(),
            "mode": "prestudy",
            "request_version": request_version,
            "requested_count": count,
            "actual_count": len(selected),
            "supersedes_queue_id": predecessor_id,
            "candidate_bundle_sha256": supplied_bundle_sha,
            "semantic_plan_sha256": plan_sha,
            ("reader_agent_id" if native else "luna_agent_id"): execution["agent_id"],
            "public_path": public_relative,
            "public_sha256": sha256_bytes(public_text.encode("utf-8")),
            "internal_path": internal_relative,
            "internal_sha256": sha256_bytes(internal_text.encode("utf-8")),
            "selected": log_selected,
        }

        lock_path = Path(legacy["WARMUP_LOG_PATH"]).with_name(
            f".{Path(legacy['WARMUP_LOG_PATH']).name}.lock"
        )
        with legacy["exclusive_file_lock"](lock_path):
            live_logs = legacy["load_warmup_logs"]()
            if any((row.get("supersedes_queue_id") == predecessor_id if predecessor_id else same_request(row)) for row in live_logs):
                raise WarmupV5Error("并发创建了 successor；请重跑以核对 noop")
            if public_path.exists() or internal_path.exists():
                raise WarmupV5Error("successor 输出路径已存在但没有唯一日志，拒绝覆盖")
            legacy["atomic_write_text"](public_path, public_text)
            legacy["atomic_write_text"](internal_path, internal_text)
            legacy["append_jsonl_entry"](legacy["WARMUP_LOG_PATH"], log_entry)
        print(f"已生成 successor：{public_path}（{queue_id}，替代 {predecessor_id}）")
    except (WarmupV5Error, legacy["RollbackSyncError"]) as exc:
        raise SystemExit(str(exc)) from exc
