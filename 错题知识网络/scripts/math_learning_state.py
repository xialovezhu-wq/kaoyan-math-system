#!/usr/bin/env python3
"""Read the latest formal math history without changing learning facts.

The optional per-card file is a deterministic projection, not a second ledger.
Every read checks the live card and source-file metadata. A changed or missing
projection falls back to the real sources in the same call, without a write.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

import wrongnet


SCHEMA = "math-live-learning-state-v1"
FORMAL_RE = re.compile(r"^(?:GS|LA|PR)-\d{3,}$")
CONCEPT_RE = re.compile(r"^MATHWIKI-KNOWLEDGE-\d+$")
STORE_PATHS = (
    "数学一回滚复习系统/复习单元.json",
    "数学一回滚复习系统/复习记录.jsonl",
)
SCHEDULE_KEYS = (
    "复习单元ID", "掌握度", "下次复习日期", "当前间隔天数", "复习状态",
    "最近复发日期", "证据阶段", "连续延迟成功次数", "调度优先级",
)
# Teaching projections only. Canonical state and its source_version always
# retain the complete evidence; these limits never apply to refresh_states.
MAX_TEACHING_EVENTS = 24
MAX_TEACHING_EVENT_BYTES = 3072
MAX_TEACHING_REVIEW_BYTES = 16384
MAX_TEACHING_FORMAL_BYTES = 8192
MAX_TEACHING_STATE_BYTES = 32768


class LearningStateError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def safe_file(root: Path, path: Path) -> Path:
    root = root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise LearningStateError("source_outside_math_repository") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise LearningStateError("source_symlink_forbidden")
    if not path.is_file():
        raise LearningStateError("source_missing:" + relative.as_posix())
    return path


def stamp(path: Path) -> dict[str, int] | None:
    if not path.exists():
        return None
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode):
        raise LearningStateError("source_not_regular:" + str(path))
    return {"size": value.st_size, "mtime_ns": value.st_mtime_ns, "ctime_ns": value.st_ctime_ns, "inode": value.st_ino}


def store_stamps(root: Path) -> dict[str, Any]:
    result = {relative: stamp(root / relative) for relative in STORE_PATHS}
    directory = root / "错题知识网络/wiki/topics/knowledge_clusters"
    if directory.is_symlink():
        raise LearningStateError("concept_directory_symlink_forbidden")
    info = directory.stat() if directory.exists() else None
    result["concept_directory"] = {"mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns, "inode": info.st_ino} if info else None
    return result


def find_card(root: Path, formal_id: str) -> Path:
    if not FORMAL_RE.fullmatch(formal_id):
        raise LearningStateError("invalid_formal_id")
    matches = list((root / "错题知识网络/错题卡").glob(formal_id + "_*.md"))
    if len(matches) != 1:
        raise LearningStateError("formal_card_not_unique:" + formal_id)
    return safe_file(root, matches[0])


def read_stores(root: Path) -> dict[str, Any]:
    for _attempt in range(2):
        before = store_stamps(root)
        units_path, log_path = (root / p for p in STORE_PATHS)
        units = json.loads(units_path.read_text()) if units_path.exists() else []
        if not isinstance(units, list) or any(not isinstance(x, dict) for x in units):
            raise LearningStateError("invalid_review_units")
        unit_by_id = {str(u.get("复习单元ID")): u for u in units}
        by_card: dict[str, list[dict[str, Any]]] = {}
        for position, line in enumerate(log_path.read_text().splitlines() if log_path.exists() else []):
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise LearningStateError("invalid_review_event")
            card_id = event.get("delivered_card_id")
            attribution = "actual_delivery" if card_id else "associated_wrong_card"
            if not card_id:
                unit = unit_by_id.get(str(event.get("unit_id")), {})
                card_id = unit.get("关联错题ID")
                if unit.get("类型") not in (None, "", "错题"):
                    attribution = "related_unit_only"
            if FORMAL_RE.fullmatch(str(card_id or "")):
                by_card.setdefault(str(card_id), []).append({**event, "ledger_position": position, "_attribution": attribution})
        if before == store_stamps(root):
            return {"stamps": before, "units": units, "reviews": by_card}
    raise LearningStateError("learning_sources_changed_during_read")


def history_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)] if value not in (None, "", []) else []


def concept_bindings(root: Path, labels: list[str]) -> list[dict[str, str]]:
    directory = root / "错题知识网络/wiki/topics/knowledge_clusters"
    # File names provide a cheap candidate locator; the actual frontmatter is
    # then read and checked. Existing Wiki IDs survive changes to the label.
    names = list(directory.glob("MATHWIKI-KNOWLEDGE-*_*.md"))
    result = []
    for label in labels:
        candidates = [p for p in names if p.stem.partition("_")[2] == label]
        if len(candidates) != 1:
            continue
        path = safe_file(root, candidates[0])
        raw = path.read_bytes()
        meta, _ = wrongnet.split_front_matter(raw.decode())
        identity = str(meta.get("wiki_id", ""))
        if not CONCEPT_RE.fullmatch(identity) or str(meta.get("title", "")) != label:
            continue
        result.append({"concept_id": identity, "label": label, "path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()})
    return result


def build_state(root: Path, formal_id: str, stores: dict[str, Any] | None = None) -> dict[str, Any]:
    stores = stores or read_stores(root)
    path = find_card(root, formal_id)
    raw = path.read_bytes()
    meta, _ = wrongnet.split_front_matter(raw.decode())
    if str(meta.get("id")) != formal_id:
        raise LearningStateError("formal_identity_mismatch")
    matches = [u for u in stores["units"] if u.get("关联错题ID") == formal_id]
    question_units = [u for u in matches if u.get("类型") in (None, "", "错题")]
    related_units = [u for u in matches if u.get("类型") not in (None, "", "错题")]
    all_reviews = sorted(stores["reviews"].get(formal_id, []), key=lambda e: (str(e.get("date", "")), e["ledger_position"]))
    reviews = [e for e in all_reviews if e.get("_attribution") != "related_unit_only"]
    labels = [str(v) for v in meta.get("knowledge", [])] if isinstance(meta.get("knowledge"), list) else []
    gap = meta.get("method_gap") if isinstance(meta.get("method_gap"), dict) else {}
    core = {
        "formal_id": formal_id,
        "formal_card_path": path.relative_to(root).as_posix(),
        "formal_card_sha256": hashlib.sha256(raw).hexdigest(),
        "knowledge": labels,
        "concepts": concept_bindings(root, labels),
        "formal_history": {
            "wrong_history": history_items(meta.get("wrong_history")),
            "mastery_history": history_items(meta.get("mastery_history")),
            "wrong_point": str(meta.get("wrong_point") or ""),
            "missed_action": str(gap.get("missed_action") or ""),
            "evidence_origin": str(gap.get("evidence_origin") or "unknown"),
            "status": meta.get("status"),
        },
        "review_events": reviews,
        "scheduling": {key: question_units[0].get(key) for key in SCHEDULE_KEYS} if len(question_units) == 1 else None,
        "history_may_override_current": False,
    }
    if related_units:
        core["related_review_units"] = [{"类型": u.get("类型"), **{key: u.get(key) for key in SCHEDULE_KEYS}} for u in related_units]
        core["related_unit_reviews"] = [e for e in all_reviews if e.get("_attribution") == "related_unit_only"]
    if len(question_units) > 1:
        core["scheduling_conflict"] = {"reason": "multiple_wrong_card_units", "unit_ids": [u.get("复习单元ID") for u in question_units]}
    return {"schema_version": SCHEMA, "source_version": digest(core), "source_stamps": stores["stamps"], **core}


def state_path(root: Path, formal_id: str) -> Path:
    return root / "错题知识网络/教学投影" / formal_id / "learning-state.json"


def atomic_write(root: Path, path: Path, data: bytes) -> None:
    relative = path.relative_to(root)
    current = root
    for part in relative.parent.parts:
        current /= part
        if current.is_symlink():
            raise LearningStateError("projection_symlink_forbidden")
        current.mkdir(exist_ok=True)
    if path.is_symlink():
        raise LearningStateError("projection_symlink_forbidden")
    if path.is_file() and path.read_bytes() == data:
        return
    fd, name = tempfile.mkstemp(prefix=".learning-state-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def refresh_states(repo_root: Path | str, formal_ids: list[str]) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    stores = read_stores(root)
    states = [build_state(root, identity, stores) for identity in sorted(set(formal_ids))]
    if stores["stamps"] != store_stamps(root):
        raise LearningStateError("learning_sources_changed_before_publish")
    for value in states:
        atomic_write(root, state_path(root, value["formal_id"]), canonical(value))
    return {"status": "refreshed", "formal_ids": [s["formal_id"] for s in states], "versions": {s["formal_id"]: s["source_version"] for s in states}}


def load_state(repo_root: Path | str, formal_id: str, stores: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    card = find_card(root, formal_id)
    cached = state_path(root, formal_id)
    if stores is None and cached.is_file() and not cached.is_symlink():
        try:
            value = json.loads(cached.read_text())
            core = {k: v for k, v in value.items() if k not in {"schema_version", "source_version", "source_stamps"}}
            concepts_current = all(
                hashlib.sha256(safe_file(root, root / item["path"]).read_bytes()).hexdigest() == item["sha256"]
                for item in value.get("concepts", [])
            )
            if (value.get("schema_version") == SCHEMA and value.get("formal_id") == formal_id
                    and value.get("source_version") == digest(core)
                    and value.get("source_stamps") == store_stamps(root)
                    and value.get("formal_card_sha256") == hashlib.sha256(card.read_bytes()).hexdigest()
                    and concepts_current):
                return value
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return build_state(root, formal_id, stores)


def bounded_record(record: dict[str, Any], byte_limit: int) -> tuple[dict[str, Any], list[str]]:
    """Keep small fields intact; explicitly excerpt oversized evidence fields.

    A structured field too large to retain is represented by excerpt_json,
    never silently passed off as complete structured evidence. Source handles
    on the enclosing history/event identify the exact original for reopening.
    """
    result = dict(record)
    clipped: set[str] = set()
    while len(canonical(result)) > byte_limit:
        key = max(result, key=lambda name: len(canonical(result[name])))
        item = result[key]
        if isinstance(item, str):
            raw = item.encode("utf-8")
            result[key] = raw[:max(1, len(raw) // 2)].decode("utf-8", errors="ignore")
        else:
            raw = (item["excerpt_json"] if isinstance(item, dict) and set(item) == {"excerpt_json", "truncated"}
                   else canonical(item).decode("utf-8")).encode("utf-8")
            result[key] = {"excerpt_json": raw[:max(1, len(raw) // 2)].decode("utf-8", errors="ignore"), "truncated": True}
        clipped.add(key)
    return result, sorted(clipped)


def bounded_reviews(reviews: list[dict[str, Any]], view: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep the first event plus latest correction, hint and latest attempt.

    Fill remaining space newest-first, then return chronological order. The
    byte budget includes each event's exact one-based physical ledger line.
    """
    required = {0, len(reviews) - 1} if reviews else set()
    for field in ("correction_text", "hint_dependency"):
        for index in range(len(reviews) - 1, -1, -1):
            outcome = reviews[index].get("review_outcome")
            if isinstance(outcome, dict) and outcome.get(field) not in (None, "", [], {}):
                required.add(index)
                break
    selected: dict[int, dict[str, Any]] = {}
    clipped_count = 0
    for index in sorted(required) + [i for i in range(len(reviews) - 1, -1, -1) if i not in required]:
        if len(selected) >= MAX_TEACHING_EVENTS:
            break
        event = reviews[index]
        outcome = event.get("review_outcome") if isinstance(event.get("review_outcome"), dict) else {}
        row = {key: event.get(key) for key in ("event_id", "date", "score", "attempt_type", "advances_long_term", "delivered_card_id")}
        row.update({key: outcome.get(key) for key in ("project", "run_id", "source_commit", "hint_dependency", "independent_correct") if key in outcome})
        if view == "direct":
            row.update({key: outcome.get(key) for key in ("user_answer_text", "correction_text") if key in outcome})
        row, clipped = bounded_record(row, MAX_TEACHING_EVENT_BYTES - 512)
        row.update({"source_line": event["ledger_position"] + 1, "content_truncated": bool(clipped), "truncated_fields": clipped})
        if len(canonical(list(selected.values()) + [row])) > MAX_TEACHING_REVIEW_BYTES:
            break
        selected[index] = row
        clipped_count += bool(clipped)
    rows = [selected[i] for i in sorted(selected)]
    return rows, {"total_count": len(reviews), "returned_count": len(rows),
                  "truncated": len(rows) < len(reviews) or bool(clipped_count),
                  "content_truncated_count": clipped_count,
                  "event_limit": MAX_TEACHING_EVENTS, "byte_limit": MAX_TEACHING_REVIEW_BYTES,
                  "returned_bytes": len(canonical(rows)),
                  "retention": "first_latest_latest_correction_latest_hint_then_recent",
                  "source_path": STORE_PATHS[1], "line_base": 1}


def bounded_formal_events(events: list[str]) -> tuple[list[str], dict[str, Any]]:
    """Retain first/latest formal entries even when one entry is oversized."""
    required = {0, len(events) - 1} if events else set()
    selected = {}
    clipped = False
    for index in sorted(required) + [i for i in range(len(events) - 1, -1, -1) if i not in required]:
        if len(selected) >= MAX_TEACHING_EVENTS:
            break
        text, fields = bounded_record({"text": events[index]}, 512)
        if len(canonical(list(selected.values()) + [text["text"]])) > 1900:
            break
        selected[index] = text["text"]
        clipped |= bool(fields)
    indices = sorted(selected)
    return [selected[i] for i in indices], {
        "total_count": len(events), "returned_count": len(indices), "source_indices": indices,
        "index_base": 0, "truncated": len(indices) < len(events) or clipped}


def view_state(value: dict[str, Any], view: str) -> dict[str, Any]:
    if view not in {"protected", "after_attempt", "direct"}:
        raise LearningStateError("invalid_view")
    reviews = value["review_events"]
    history = value["formal_history"]
    public_events, review_window = bounded_reviews(reviews, view)
    review_window["source_stamp"] = value["source_stamps"][STORE_PATHS[1]]
    visible_history: dict[str, Any] = {
        "wrong_occurrences": len(history["wrong_history"]),
        "mastery_occurrences": len(history["mastery_history"]),
        "evidence_origin": history["evidence_origin"],
        "status": history["status"],
    }
    formal_events = {}
    formal_windows = {}
    if view == "direct":
        visible_history.update({key: item for key, item in history.items() if key not in {"wrong_history", "mastery_history"}})
        for key in ("wrong_history", "mastery_history"):
            formal_events[key], formal_windows[key] = bounded_formal_events(history[key])
    elif view == "after_attempt":
        # Operational prior only. Full old solutions/user answers remain behind
        # the explicit direct-disclosure view.
        for key in ("wrong_point", "missed_action"):
            text = history[key]
            if not re.search(r"正确答案|最终答案|最终结果|答案为|结果为|\\boxed|answer\s*[:=]", text, re.I):
                visible_history[key] = text
        visible_history["history_dates"] = sorted(set(re.findall(r"20\d{2}-\d{2}-\d{2}", " ".join(history["wrong_history"] + history["mastery_history"]))))
    visible_history, clipped_history = bounded_record(visible_history, MAX_TEACHING_FORMAL_BYTES // 2 if view == "direct" else MAX_TEACHING_FORMAL_BYTES)
    visible_history.update(formal_events)
    history_truncated = bool(clipped_history) or any(window["truncated"] for window in formal_windows.values())
    result = {
        "schema_version": SCHEMA, "formal_id": value["formal_id"], "source_version": value["source_version"],
        "formal_card_path": value["formal_card_path"], "formal_card_sha256": value["formal_card_sha256"],
        "concepts": value["concepts"], "formal_history": visible_history,
        "review_events": public_events, "review_history_window": review_window,
        "formal_history_window": {"truncated": history_truncated, "truncated_fields": clipped_history,
                                  "event_windows": formal_windows,
                                  "byte_limit": MAX_TEACHING_FORMAL_BYTES,
                                  "source_path": value["formal_card_path"],
                                  "source_sha256": value["formal_card_sha256"],
                                  "source_fields": ["wrong_history", "mastery_history", "wrong_point", "method_gap"]},
        "scheduling": value["scheduling"],
        "related_review_units": value.get("related_review_units", []),
        "related_unit_review_count": len(value.get("related_unit_reviews", [])),
        "related_units_do_not_prove_whole_question_mastery": True,
        "scheduling_conflict": value.get("scheduling_conflict"),
        "history_may_override_current": False,
        "latest_review_must_be_considered_before_older_failure_label": True,
    }
    evidence_keys = {"review_events", "review_history_window", "formal_history", "formal_history_window"}
    metadata, clipped_metadata = bounded_record({key: item for key, item in result.items() if key not in evidence_keys}, 4096)
    metadata.update({key: result[key] for key in evidence_keys})
    metadata["teaching_view_limits"] = {"byte_limit": MAX_TEACHING_STATE_BYTES,
                                       "encoding": "canonical_utf8_json", "metadata_truncated_fields": clipped_metadata}
    return metadata


def personal_context(repo_root: Path | str, formal_id: str, view: str = "protected", related_limit: int = 3) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    current = load_state(root, formal_id)
    related_ids: set[str] = set()
    # Prefer the smallest existing concept scope. This retrieves evidence by
    # literal shared knowledge, never declares the learner has the same error.
    scopes = []
    unavailable_related = []
    for concept in current["concepts"] if related_limit else []:
        try:
            text = safe_file(root, root / concept["path"]).read_text()
        except (OSError, ValueError) as exc:
            unavailable_related.append({"source_path": concept["path"], "reason": str(exc)})
            continue
        ids = set(re.findall(r"(?m)^\|\s*((?:GS|LA|PR)-\d+)\s*\|", text)) - {formal_id}
        if ids:
            scopes.append((len(ids), concept, ids))
    for _, _, ids in sorted(scopes, key=lambda row: (row[0], row[1]["concept_id"]))[:2]:
        related_ids.update(ids)
    related = []
    if related_ids and related_limit:
        stores = read_stores(root)
        if current["source_stamps"] != stores["stamps"]:
            current = build_state(root, formal_id, stores)
        ordered = sorted(related_ids, key=lambda identity: (max((str(e.get("date", "")) for e in stores["reviews"].get(identity, [])), default=""), identity), reverse=True)
        for identity in ordered:
            if len(related) >= min(max(related_limit, 0), 6):
                break
            try:
                state = load_state(root, identity, stores)
            except (OSError, ValueError) as exc:
                unavailable_related.append({"formal_id": identity, "reason": str(exc)})
                continue
            if not set(state["knowledge"]) & set(current["knowledge"]):
                continue
            related.append({"match_kind": "literal_shared_knowledge_not_proof_of_same_error", **view_state(state, view)})
        if store_stamps(root) != stores["stamps"]:
            raise LearningStateError("learning_sources_changed_during_related_read")
    failures = []
    failures_truncated = len(unavailable_related) > 6
    for failure in unavailable_related[:6]:
        row, clipped = bounded_record(failure, 384)
        failures.append(row)
        failures_truncated |= bool(clipped)
    return {"status": "available", "current": view_state(current, view), "related": related,
            "related_status": "partial" if unavailable_related else "available",
            "unavailable_related": failures, "related_failure_count": len(unavailable_related),
            "related_failures_truncated": failures_truncated,
            "related_candidate_count": len(related_ids), "related_read_count": len(related),
            "teaching_view_limits": {"byte_limit": (1 + min(max(related_limit, 0), 6)) * MAX_TEACHING_STATE_BYTES + 4096,
                                     "encoding": "canonical_utf8_json"},
            "current_evidence_authority": "external_runtime", "history_may_override_current": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("command", choices=("resolve", "refresh"))
    parser.add_argument("--formal-id", action="append", required=True)
    parser.add_argument("--view", choices=("protected", "after_attempt", "direct"), default="protected")
    args = parser.parse_args()
    try:
        value = refresh_states(args.repo, args.formal_id) if args.command == "refresh" else personal_context(args.repo, args.formal_id[0], args.view)
    except (OSError, ValueError) as exc:
        value = {"status": "unavailable", "reason": str(exc), "history_may_override_current": False}
        print(json.dumps(value, ensure_ascii=False))
        return 1
    print(json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
