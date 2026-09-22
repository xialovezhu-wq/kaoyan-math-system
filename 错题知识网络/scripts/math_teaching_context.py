#!/usr/bin/env python3
"""Materialize and resolve one bounded math teaching context by formal ID.

The version object is immutable and content-addressed.  ``current.json`` is
the only mutable pointer and is replaced last.  The hot resolver reads that
exact pointer and version only; it never scans the wrong-card library, intake
ledger, conversation packages, Obsidian, or T9.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

import training_evidence
import math_learning_state


CONTEXT_SCHEMA = "math-teaching-context-v1"
POINTER_SCHEMA = "math-teaching-context-pointer-v1"
RECEIPT_SCHEMA = "math-teaching-context-materialize-receipt-v1"
VERIFY_SCHEMA = "math-teaching-context-verify-result-v1"
VIEW_SCHEMA = "math-teaching-context-view-v1"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECTION_REL = PurePosixPath("错题知识网络/教学投影")
FORMAL_ID_RE = re.compile(r"^(?:GS|LA|PR)-\d+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MAX_INPUT_BYTES = 64 * 1024
MAX_CONTEXT_BYTES = 32 * 1024
MAX_POINTER_BYTES = 8 * 1024
MAX_TEXT = 480
MAX_LIST_ITEMS = 16

_SCHEDULER_PARSER: Any = None

PRECEDENCE = {
    "current_question_evidence": "external_runtime_authoritative",
    "historical_context": "prior_only",
    "history_must_not_override_current": True,
}

ALLOWED_EVIDENCE_ORIGINS = {
    "user_observed",
    "user_confirmed",
    "source_verified",
    "assistant_inferred",
    "assistant_explained",
    "unresolved",
    "missing",
    "legacy_unclassified",
    "model_inferred_from_solution",
    "pending_user_confirmation",
}
ALLOWED_BREAK_KINDS = {
    "knowledge",
    "concept",
    "condition",
    "method_trigger",
    "method",
    "calculation",
    "expression",
    "identity",
    "object_role",
    "unknown",
}
ALLOWED_HINT_LEVELS = {
    "none",
    "l1",
    "l2",
    "l3",
    "l4",
    "l5",
    "direct_explanation",
    "mixed",
    "unknown",
}
ALLOWED_REPRESENTATIONS = {
    "object_table",
    "minimal_diagram",
    "worked_example",
    "contrast",
    "equation_chain",
    "verbal",
    "unknown",
}

FORBIDDEN_KEY_FRAGMENTS = {
    "answer",
    "solution",
    "correct_option",
    "correct_answer",
    "final_result",
    "question_text",
    "question_stem",
    "full_question",
    "assistant_history",
    "assistant_turns",
    "conversation",
    "transcript",
    "teaching_turns",
    "完整解析",
    "标准答案",
    "正确答案",
    "正确选项",
    "最终结果",
    "题目全文",
    "完整题干",
    "助手历史",
}
FORBIDDEN_PEDAGOGICAL_MARKERS = (
    "标准答案",
    "正确答案",
    "答案为",
    "正确选项",
    "完整解析",
    "答案解析",
    "最终结果",
    "final result",
    "final_result",
    "correct option",
    "correct_option",
    "correct answer",
    "correct_answer",
    "full question",
    "question stem",
    "assistant history",
    "assistant transcript",
    "solution:",
    "answer:",
)


class TeachingContextError(ValueError):
    """Stable validation or integrity failure."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_file_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_formal_card_frontmatter(path: Path) -> dict[str, Any]:
    """Use the same established parser as the formal closeout gate."""

    global _SCHEDULER_PARSER
    if _SCHEDULER_PARSER is None:
        scheduler_path = (
            Path(__file__).resolve().parents[2]
            / "数学一回滚复习系统"
            / "scripts"
            / "scheduler.py"
        )
        if not scheduler_path.is_file():
            raise TeachingContextError("frontmatter_parser_missing", str(scheduler_path))
        module_name = "_math_teaching_context_scheduler"
        spec = importlib.util.spec_from_file_location(module_name, scheduler_path)
        if spec is None or spec.loader is None:
            raise TeachingContextError("frontmatter_parser_missing", str(scheduler_path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _SCHEDULER_PARSER = module.parse_card_frontmatter
    parsed = _SCHEDULER_PARSER(path)
    if not isinstance(parsed, dict):
        raise TeachingContextError("formal_card_frontmatter_missing", path.name)
    return parsed


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TeachingContextError("invalid_schema", f"{field} must be an object")
    return dict(value)


def _keys(
    value: Mapping[str, Any],
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = sorted(required - set(value))
    unexpected = sorted(set(value) - required - optional)
    if missing:
        raise TeachingContextError("invalid_schema", f"{field} missing {missing}")
    if unexpected:
        raise TeachingContextError("invalid_schema", f"{field} has unknown keys {unexpected}")


def _text(
    value: Any,
    field: str,
    *,
    max_length: int = MAX_TEXT,
    allow_empty: bool = False,
    pedagogical: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TeachingContextError("invalid_schema", f"{field} must be text")
    result = re.sub(r"\s+", " ", value).strip()
    if not result and not allow_empty:
        raise TeachingContextError("invalid_schema", f"{field} must not be empty")
    if len(result) > max_length:
        raise TeachingContextError("bounded_context_exceeded", f"{field} is too long")
    if pedagogical:
        folded = result.casefold()
        for marker in FORBIDDEN_PEDAGOGICAL_MARKERS:
            if marker.casefold() in folded:
                raise TeachingContextError("answer_unsafe_content", f"{field} contains {marker}")
    return result


def _safe_id(value: Any, field: str, *, allow_empty: bool = False) -> str:
    result = _text(value, field, max_length=160, allow_empty=allow_empty)
    if result and not SAFE_ID_RE.fullmatch(result):
        raise TeachingContextError("invalid_schema", f"{field} is not a safe ID")
    return result


def _hash(value: Any, field: str) -> str:
    result = _text(value, field, max_length=64)
    if not SHA256_RE.fullmatch(result):
        raise TeachingContextError("invalid_schema", f"{field} is not sha256")
    return result


def _date(value: Any, field: str) -> str:
    result = _text(value, field, max_length=10)
    if not DATE_RE.fullmatch(result):
        raise TeachingContextError("invalid_schema", f"{field} must use YYYY-MM-DD")
    try:
        from datetime import date

        if date.fromisoformat(result).isoformat() != result:
            raise ValueError
    except ValueError as exc:
        raise TeachingContextError("invalid_schema", f"{field} is not a valid date") from exc
    return result


def _recursive_forbidden_key_check(value: Any, field: str = "context") -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                raise TeachingContextError("invalid_schema", f"{field} contains a non-text key")
            folded = raw_key.casefold().replace("-", "_").replace(" ", "_")
            if any(marker.casefold() in folded for marker in FORBIDDEN_KEY_FRAGMENTS):
                raise TeachingContextError("answer_unsafe_content", f"forbidden field {field}.{raw_key}")
            _recursive_forbidden_key_check(child, f"{field}.{raw_key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _recursive_forbidden_key_check(child, f"{field}[{index}]")


def _regular_file(path: Path, field: str) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise TeachingContextError("source_missing", f"{field} is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise TeachingContextError("unsafe_path", f"{field} must be a regular non-symlink file")
    return info


def _repo_relative_text(value: Any, field: str) -> str:
    result = _text(value, field, max_length=1024)
    if "\\" in result:
        raise TeachingContextError("unsafe_path", f"{field} contains a backslash")
    path = PurePosixPath(result)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TeachingContextError("unsafe_path", f"{field} is not repo-relative")
    return path.as_posix()


def _repo_file(repo_root: Path, relative: str, field: str) -> Path:
    root = repo_root.resolve()
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise TeachingContextError("unsafe_path", f"{field} crosses a symlink")
    _regular_file(current, field)
    try:
        current.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise TeachingContextError("unsafe_path", f"{field} escapes repo") from exc
    return current


def _ensure_safe_directory(repo_root: Path, directory: Path, field: str) -> None:
    root = repo_root.resolve()
    try:
        relative = directory.relative_to(root)
    except ValueError as exc:
        raise TeachingContextError("unsafe_path", f"{field} escapes repo") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise TeachingContextError("unsafe_path", f"{field} crosses a symlink")
    directory.mkdir(parents=True, exist_ok=True)


def _normalize_capture_binding(value: Any, field: str) -> dict[str, Any]:
    item = _mapping(value, field)
    required = {
        "capture_event_id",
        "capture_content_hash",
        "amendment_event_ids",
        "effective_evidence_hash",
        "effective_target_hash",
    }
    _keys(item, field, required)
    amendments = item["amendment_event_ids"]
    if not isinstance(amendments, list) or len(amendments) > MAX_LIST_ITEMS:
        raise TeachingContextError("invalid_schema", f"{field}.amendment_event_ids is invalid")
    normalized_amendments = [
        _safe_id(entry, f"{field}.amendment_event_ids[{index}]")
        for index, entry in enumerate(amendments)
    ]
    if len(set(normalized_amendments)) != len(normalized_amendments):
        raise TeachingContextError("invalid_schema", f"{field}.amendment_event_ids has duplicates")
    return {
        "capture_event_id": _safe_id(item["capture_event_id"], f"{field}.capture_event_id"),
        "capture_content_hash": _hash(item["capture_content_hash"], f"{field}.capture_content_hash"),
        "amendment_event_ids": normalized_amendments,
        "effective_evidence_hash": _hash(
            item["effective_evidence_hash"], f"{field}.effective_evidence_hash"
        ),
        "effective_target_hash": _hash(
            item["effective_target_hash"], f"{field}.effective_target_hash"
        ),
    }


def capture_evidence_source_version(
    formal_id: str,
    freeze_id: str,
    capture_bindings: Sequence[Mapping[str, Any]],
) -> str:
    """Hash the frozen evidence contract used by the closeout gate.

    The hash deliberately excludes package metadata.  It is exactly the
    canonical freeze/formal/capture tuple agreed with formal closeout.
    """

    core = [
        {
            "capture_event_id": item["capture_event_id"],
            "capture_content_hash": item["capture_content_hash"],
            "amendment_event_ids": list(item["amendment_event_ids"]),
            "effective_evidence_hash": item["effective_evidence_hash"],
            "effective_target_hash": item["effective_target_hash"],
        }
        for item in sorted(capture_bindings, key=lambda row: str(row["capture_event_id"]))
    ]
    return sha256_value(
        {
            "freeze_id": freeze_id,
            "formal_id": formal_id,
            "capture_bindings": core,
        }
    )


def _normalize_package_binding(
    value: Any,
    field: str,
    capture_ids: set[str],
) -> dict[str, str]:
    item = _mapping(value, field)
    _keys(item, field, {"capture_event_id", "package_id", "package_sha256"})
    capture_id = _safe_id(item["capture_event_id"], f"{field}.capture_event_id")
    if capture_id not in capture_ids:
        raise TeachingContextError("binding_mismatch", f"{field} references another capture")
    return {
        "capture_event_id": capture_id,
        "package_id": _safe_id(item["package_id"], f"{field}.package_id"),
        "package_sha256": _hash(item["package_sha256"], f"{field}.package_sha256"),
    }


def _normalize_prior_atom(
    value: Any,
    field: str,
    capture_ids: set[str],
    *,
    allow_empty: bool = False,
) -> dict[str, str]:
    item = _mapping(value, field)
    _keys(item, field, {"text", "evidence_origin", "source_capture_id"})
    text = _text(
        item["text"],
        f"{field}.text",
        max_length=MAX_TEXT,
        allow_empty=allow_empty,
        pedagogical=True,
    )
    origin = _text(item["evidence_origin"], f"{field}.evidence_origin", max_length=64)
    if origin not in ALLOWED_EVIDENCE_ORIGINS:
        raise TeachingContextError("invalid_schema", f"{field}.evidence_origin is invalid")
    source = _safe_id(
        item["source_capture_id"],
        f"{field}.source_capture_id",
        allow_empty=allow_empty,
    )
    if source and source not in capture_ids:
        raise TeachingContextError("binding_mismatch", f"{field} references another capture")
    if not text and (origin != "missing" or source):
        raise TeachingContextError("invalid_schema", f"{field} empty evidence must be missing")
    return {"text": text, "evidence_origin": origin, "source_capture_id": source}


def _normalize_atom_list(value: Any, field: str, capture_ids: set[str]) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
        raise TeachingContextError("invalid_schema", f"{field} must be a bounded list")
    return [
        _normalize_prior_atom(item, f"{field}[{index}]", capture_ids)
        for index, item in enumerate(value)
    ]


def _normalize_first_break(value: Any, capture_ids: set[str]) -> dict[str, str]:
    item = _mapping(value, "prior.first_break")
    _keys(
        item,
        "prior.first_break",
        {"kind", "text", "evidence_origin", "source_capture_id"},
    )
    kind = _text(item["kind"], "prior.first_break.kind", max_length=40)
    if kind not in ALLOWED_BREAK_KINDS:
        raise TeachingContextError("invalid_schema", "prior.first_break.kind is invalid")
    atom = _normalize_prior_atom(
        {
            "text": item["text"],
            "evidence_origin": item["evidence_origin"],
            "source_capture_id": item["source_capture_id"],
        },
        "prior.first_break",
        capture_ids,
        allow_empty=kind == "unknown",
    )
    return {"kind": kind, **atom}


def _normalize_hint_dependency(value: Any, capture_ids: set[str]) -> dict[str, str]:
    item = _mapping(value, "prior.hint_dependency")
    _keys(
        item,
        "prior.hint_dependency",
        {"level", "text", "evidence_origin", "source_capture_id"},
    )
    level = _text(item["level"], "prior.hint_dependency.level", max_length=32).lower()
    if level not in ALLOWED_HINT_LEVELS:
        raise TeachingContextError("invalid_schema", "prior.hint_dependency.level is invalid")
    atom = _normalize_prior_atom(
        {
            "text": item["text"],
            "evidence_origin": item["evidence_origin"],
            "source_capture_id": item["source_capture_id"],
        },
        "prior.hint_dependency",
        capture_ids,
        allow_empty=level in {"none", "unknown"},
    )
    return {"level": level, **atom}


def _normalize_representations(value: Any, capture_ids: set[str]) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 6:
        raise TeachingContextError(
            "invalid_schema", "prior.effective_representation must be a bounded list"
        )
    result: list[dict[str, str]] = []
    for index, raw in enumerate(value):
        field = f"prior.effective_representation[{index}]"
        item = _mapping(raw, field)
        _keys(item, field, {"kind", "text", "evidence_origin", "source_capture_id"})
        kind = _text(item["kind"], f"{field}.kind", max_length=40)
        if kind not in ALLOWED_REPRESENTATIONS:
            raise TeachingContextError("invalid_schema", f"{field}.kind is invalid")
        atom = _normalize_prior_atom(
            {
                "text": item["text"],
                "evidence_origin": item["evidence_origin"],
                "source_capture_id": item["source_capture_id"],
            },
            field,
            capture_ids,
            allow_empty=kind == "unknown",
        )
        result.append({"kind": kind, **atom})
    return result


def _c_followup_expected(action_gap_type: str) -> bool:
    value = action_gap_type.strip().upper().replace("_", "-")
    return value in {"B2", "B2-TRIGGER", "B3", "B3-METHOD"}


def _normalize_prior(
    value: Any,
    capture_ids: set[str],
    derived_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    prior = _mapping(value, "prior")
    required = {
        "evidence_scope",
        "action_gap_type",
        "evidence_origin",
        "needs_confirmation",
        "first_break",
        "independent_correct_steps",
        "hint_dependency",
        "effective_representation",
        "unresolved",
        "c_followup",
    }
    _keys(prior, "prior", required)
    if prior["evidence_scope"] != "prior_only":
        raise TeachingContextError("invalid_precedence", "prior.evidence_scope must be prior_only")

    derived_gap = derived_evidence.get("method_gap")
    if not isinstance(derived_gap, dict):
        derived_gap = {}
    expected_gap = training_evidence.clean_text(derived_gap.get("action_gap_type")) or "UNKNOWN"
    action_gap = _text(prior["action_gap_type"], "prior.action_gap_type", max_length=64)
    if action_gap != expected_gap:
        raise TeachingContextError("formal_evidence_drift", "action_gap_type differs from final card")
    origin = _text(prior["evidence_origin"], "prior.evidence_origin", max_length=64)
    if origin != derived_evidence.get("origin"):
        raise TeachingContextError("formal_evidence_drift", "evidence_origin differs from final card")
    needs_confirmation = prior["needs_confirmation"]
    if not isinstance(needs_confirmation, bool):
        raise TeachingContextError("invalid_schema", "prior.needs_confirmation must be boolean")
    if needs_confirmation is not bool(derived_evidence.get("needs_confirmation")):
        raise TeachingContextError("formal_evidence_drift", "needs_confirmation differs from final card")

    followup = _mapping(prior["c_followup"], "prior.c_followup")
    _keys(
        followup,
        "prior.c_followup",
        {"eligible", "after_current_question_only", "reason"},
    )
    if not isinstance(followup["eligible"], bool):
        raise TeachingContextError("invalid_schema", "prior.c_followup.eligible must be boolean")
    if followup["after_current_question_only"] is not True:
        raise TeachingContextError(
            "invalid_precedence", "C followup must remain outside the current question"
        )
    expected_followup = _c_followup_expected(action_gap)
    if followup["eligible"] is not expected_followup:
        raise TeachingContextError(
            "routing_mismatch", "C followup eligibility must follow B2/B3 only"
        )

    return {
        "evidence_scope": "prior_only",
        "action_gap_type": action_gap,
        "evidence_origin": origin,
        "needs_confirmation": needs_confirmation,
        "first_break": _normalize_first_break(prior["first_break"], capture_ids),
        "independent_correct_steps": _normalize_atom_list(
            prior["independent_correct_steps"], "prior.independent_correct_steps", capture_ids
        ),
        "hint_dependency": _normalize_hint_dependency(prior["hint_dependency"], capture_ids),
        "effective_representation": _normalize_representations(
            prior["effective_representation"], capture_ids
        ),
        "unresolved": _normalize_atom_list(prior["unresolved"], "prior.unresolved", capture_ids),
        "c_followup": {
            "eligible": expected_followup,
            "after_current_question_only": True,
            "reason": _text(
                followup["reason"],
                "prior.c_followup.reason",
                max_length=320,
                allow_empty=not expected_followup,
                pedagogical=True,
            ),
        },
    }


def _card_and_evidence(
    repo_root: Path,
    formal_id: str,
    relative_path: str,
    expected_hash: str,
) -> tuple[Path, dict[str, Any]]:
    if not relative_path.startswith("错题知识网络/错题卡/"):
        raise TeachingContextError("unsafe_path", "formal card path is outside the card directory")
    path = _repo_file(repo_root, relative_path, "source_bindings.formal_card_path")
    if sha256_file(path) != expected_hash:
        raise TeachingContextError("formal_card_hash_mismatch", formal_id)
    meta = parse_formal_card_frontmatter(path)
    if training_evidence.clean_text(meta.get("id")) != formal_id:
        raise TeachingContextError("formal_card_id_mismatch", formal_id)
    evidence = training_evidence.extract_error_evidence(meta, formal_id)
    return path, evidence


def normalize_context_document(repo_root: Path | str, value: Any) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    document = _mapping(value, "context")
    _recursive_forbidden_key_check(document)
    required = {"schema_version", "formal_id", "precedence", "source_bindings", "prior"}
    optional = {"artifact_date", "study_dates"}
    _keys(document, "context", required, optional)
    if document["schema_version"] != CONTEXT_SCHEMA:
        raise TeachingContextError("unsupported_schema", str(document["schema_version"]))
    formal_id = _text(document["formal_id"], "formal_id", max_length=32)
    if not FORMAL_ID_RE.fullmatch(formal_id):
        raise TeachingContextError("invalid_formal_id", formal_id)
    if document["precedence"] != PRECEDENCE:
        raise TeachingContextError("invalid_precedence", "current evidence must remain external")

    bindings = _mapping(document["source_bindings"], "source_bindings")
    binding_keys = {
        "formal_card_path",
        "formal_card_sha256",
        "formal_evidence_id",
        "formal_evidence_source_version",
        "freeze_id",
        "capture_event_ids",
        "capture_bindings",
        "capture_evidence_source_version",
        "package_bindings",
    }
    _keys(bindings, "source_bindings", binding_keys)
    card_path = _repo_relative_text(bindings["formal_card_path"], "source_bindings.formal_card_path")
    card_hash = _hash(bindings["formal_card_sha256"], "source_bindings.formal_card_sha256")
    _path, derived_evidence = _card_and_evidence(root, formal_id, card_path, card_hash)

    formal_evidence_id = _safe_id(
        bindings["formal_evidence_id"], "source_bindings.formal_evidence_id"
    )
    formal_evidence_version = _hash(
        bindings["formal_evidence_source_version"],
        "source_bindings.formal_evidence_source_version",
    )
    if formal_evidence_id != derived_evidence.get("evidence_id"):
        raise TeachingContextError("formal_evidence_drift", "formal evidence ID mismatch")
    if formal_evidence_version != derived_evidence.get("source_version"):
        raise TeachingContextError("formal_evidence_drift", "formal evidence version mismatch")

    freeze_id = _safe_id(bindings["freeze_id"], "source_bindings.freeze_id")
    raw_capture_ids = bindings["capture_event_ids"]
    if not isinstance(raw_capture_ids, list) or not raw_capture_ids or len(raw_capture_ids) > MAX_LIST_ITEMS:
        raise TeachingContextError("invalid_schema", "source_bindings.capture_event_ids is invalid")
    capture_ids = [
        _safe_id(item, f"source_bindings.capture_event_ids[{index}]")
        for index, item in enumerate(raw_capture_ids)
    ]
    if capture_ids != sorted(set(capture_ids)):
        raise TeachingContextError(
            "invalid_schema", "source_bindings.capture_event_ids must be sorted and unique"
        )
    raw_capture_bindings = bindings["capture_bindings"]
    if not isinstance(raw_capture_bindings, list) or len(raw_capture_bindings) != len(capture_ids):
        raise TeachingContextError("binding_mismatch", "capture bindings do not close")
    capture_bindings = [
        _normalize_capture_binding(item, f"source_bindings.capture_bindings[{index}]")
        for index, item in enumerate(raw_capture_bindings)
    ]
    capture_bindings.sort(key=lambda item: item["capture_event_id"])
    if [item["capture_event_id"] for item in capture_bindings] != capture_ids:
        raise TeachingContextError("binding_mismatch", "capture binding IDs differ")
    capture_version = _hash(
        bindings["capture_evidence_source_version"],
        "source_bindings.capture_evidence_source_version",
    )
    expected_capture_version = capture_evidence_source_version(
        formal_id, freeze_id, capture_bindings
    )
    if capture_version != expected_capture_version:
        raise TeachingContextError("capture_evidence_version_mismatch", formal_id)

    raw_packages = bindings["package_bindings"]
    if not isinstance(raw_packages, list) or len(raw_packages) != len(capture_ids):
        raise TeachingContextError("binding_mismatch", "package bindings do not close")
    packages = [
        _normalize_package_binding(
            item,
            f"source_bindings.package_bindings[{index}]",
            set(capture_ids),
        )
        for index, item in enumerate(raw_packages)
    ]
    packages.sort(key=lambda item: item["capture_event_id"])
    if [item["capture_event_id"] for item in packages] != capture_ids:
        raise TeachingContextError("binding_mismatch", "every capture needs one package")

    normalized: dict[str, Any] = {
        "schema_version": CONTEXT_SCHEMA,
        "formal_id": formal_id,
        "precedence": dict(PRECEDENCE),
        "source_bindings": {
            "formal_card_path": card_path,
            "formal_card_sha256": card_hash,
            "formal_evidence_id": formal_evidence_id,
            "formal_evidence_source_version": formal_evidence_version,
            "freeze_id": freeze_id,
            "capture_event_ids": capture_ids,
            "capture_bindings": capture_bindings,
            "capture_evidence_source_version": capture_version,
            "package_bindings": packages,
        },
        "prior": _normalize_prior(document["prior"], set(capture_ids), derived_evidence),
    }
    if "artifact_date" in document:
        normalized["artifact_date"] = _date(document["artifact_date"], "artifact_date")
    if "study_dates" in document:
        raw_dates = document["study_dates"]
        if not isinstance(raw_dates, list) or len(raw_dates) > MAX_LIST_ITEMS:
            raise TeachingContextError("invalid_schema", "study_dates must be a bounded list")
        dates = [_date(item, f"study_dates[{index}]") for index, item in enumerate(raw_dates)]
        if dates != sorted(set(dates)):
            raise TeachingContextError("invalid_schema", "study_dates must be sorted and unique")
        normalized["study_dates"] = dates

    payload = canonical_file_bytes(normalized)
    if len(payload) > MAX_CONTEXT_BYTES:
        raise TeachingContextError("bounded_context_exceeded", formal_id)
    return normalized


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _materialize_lock(repo_root: Path, formal_id: str) -> Iterator[None]:
    directory = repo_root / Path(*PROJECTION_REL.parts) / formal_id
    _ensure_safe_directory(repo_root, directory, "teaching projection directory")
    lock_path = directory / ".materialize.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise TeachingContextError("unsafe_path", "teaching projection lock is unsafe") from exc
    with os.fdopen(descriptor, "a+b") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise TeachingContextError("unsafe_path", "teaching projection lock is not regular")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _relative_to_repo(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root.resolve()).as_posix()


def materialize_context(repo_root: Path | str, value: Any) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    normalized = normalize_context_document(root, value)
    formal_id = normalized["formal_id"]
    payload = canonical_file_bytes(normalized)
    context_hash = sha256_bytes(payload)
    base = root / Path(*PROJECTION_REL.parts) / formal_id
    version_path = base / "versions" / f"{context_hash}.json"
    pointer_path = base / "current.json"
    bindings = normalized["source_bindings"]
    pointer = {
        "schema_version": POINTER_SCHEMA,
        "formal_id": formal_id,
        "context_path": _relative_to_repo(root, version_path),
        "context_sha256": context_hash,
        "formal_card_path": bindings["formal_card_path"],
        "formal_card_sha256": bindings["formal_card_sha256"],
        "formal_evidence_source_version": bindings["formal_evidence_source_version"],
        "capture_evidence_source_version": bindings["capture_evidence_source_version"],
        "learning_state_source_version": math_learning_state.load_state(root, formal_id)["source_version"],
    }
    pointer_payload = canonical_file_bytes(pointer)

    with _materialize_lock(root, formal_id):
        _ensure_safe_directory(root, version_path.parent, "teaching version directory")
        if version_path.exists():
            _regular_file(version_path, "teaching version")
            if version_path.read_bytes() != payload:
                raise TeachingContextError("content_address_collision", formal_id)
        else:
            _atomic_write(version_path, payload)
        if pointer_path.exists():
            _regular_file(pointer_path, "teaching pointer")
            unchanged = pointer_path.read_bytes() == pointer_payload
        else:
            unchanged = False
        if not unchanged:
            _atomic_write(pointer_path, pointer_payload)

    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": "already_current" if unchanged else "created",
        "formal_id": formal_id,
        "context_path": pointer["context_path"],
        "context_sha256": context_hash,
        "pointer_path": _relative_to_repo(root, pointer_path),
        "pointer_sha256": sha256_bytes(pointer_payload),
        "source_bindings": copy.deepcopy(bindings),
    }


def _read_json(path: Path, field: str, max_bytes: int) -> dict[str, Any]:
    info = _regular_file(path, field)
    if info.st_size > max_bytes:
        raise TeachingContextError("bounded_context_exceeded", field)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TeachingContextError("invalid_json", field) from exc
    if not isinstance(value, dict):
        raise TeachingContextError("invalid_json", f"{field} must be an object")
    return value


def _normalize_pointer(repo_root: Path, formal_id: str, value: Any) -> dict[str, Any]:
    pointer = _mapping(value, "pointer")
    required = {
        "schema_version",
        "formal_id",
        "context_path",
        "context_sha256",
        "formal_card_path",
        "formal_card_sha256",
        "formal_evidence_source_version",
        "capture_evidence_source_version",
    }
    _keys(pointer, "pointer", required, {"learning_state_source_version"})
    if pointer["schema_version"] != POINTER_SCHEMA or pointer["formal_id"] != formal_id:
        raise TeachingContextError("pointer_identity_mismatch", formal_id)
    context_hash = _hash(pointer["context_sha256"], "pointer.context_sha256")
    context_path = _repo_relative_text(pointer["context_path"], "pointer.context_path")
    expected = (PROJECTION_REL / formal_id / "versions" / f"{context_hash}.json").as_posix()
    if context_path != expected:
        raise TeachingContextError("pointer_path_mismatch", formal_id)
    normalized = {
        "schema_version": POINTER_SCHEMA,
        "formal_id": formal_id,
        "context_path": context_path,
        "context_sha256": context_hash,
        "formal_card_path": _repo_relative_text(
            pointer["formal_card_path"], "pointer.formal_card_path"
        ),
        "formal_card_sha256": _hash(
            pointer["formal_card_sha256"], "pointer.formal_card_sha256"
        ),
        "formal_evidence_source_version": _hash(
            pointer["formal_evidence_source_version"],
            "pointer.formal_evidence_source_version",
        ),
        "capture_evidence_source_version": _hash(
            pointer["capture_evidence_source_version"],
            "pointer.capture_evidence_source_version",
        ),
    }
    if "learning_state_source_version" in pointer:
        normalized["learning_state_source_version"] = _hash(pointer["learning_state_source_version"], "pointer.learning_state_source_version")
    return normalized


def _verify_or_raise(repo_root: Path, formal_id: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
    if not FORMAL_ID_RE.fullmatch(formal_id):
        raise TeachingContextError("invalid_formal_id", formal_id)
    pointer_path = repo_root / Path(*PROJECTION_REL.parts) / formal_id / "current.json"
    if not pointer_path.exists():
        raise TeachingContextError("pointer_missing", formal_id)
    pointer_raw = _read_json(pointer_path, "teaching pointer", MAX_POINTER_BYTES)
    pointer = _normalize_pointer(repo_root, formal_id, pointer_raw)
    if canonical_file_bytes(pointer_raw) != pointer_path.read_bytes():
        raise TeachingContextError("pointer_not_canonical", formal_id)
    context_path = _repo_file(repo_root, pointer["context_path"], "teaching version")
    if sha256_file(context_path) != pointer["context_sha256"]:
        raise TeachingContextError("context_hash_mismatch", formal_id)
    raw_context = _read_json(context_path, "teaching version", MAX_CONTEXT_BYTES)
    normalized = normalize_context_document(repo_root, raw_context)
    if canonical_file_bytes(normalized) != context_path.read_bytes():
        raise TeachingContextError("context_not_canonical", formal_id)
    bindings = normalized["source_bindings"]
    comparisons = {
        "formal_card_path": bindings["formal_card_path"],
        "formal_card_sha256": bindings["formal_card_sha256"],
        "formal_evidence_source_version": bindings["formal_evidence_source_version"],
        "capture_evidence_source_version": bindings["capture_evidence_source_version"],
    }
    for field, expected in comparisons.items():
        if pointer[field] != expected:
            raise TeachingContextError("pointer_binding_mismatch", field)
    if pointer.get("learning_state_source_version") is not None:
        try:
            live_version = math_learning_state.load_state(repo_root, formal_id)["source_version"]
        except (OSError, ValueError) as exc:
            raise TeachingContextError("learning_state_unavailable", formal_id) from exc
        if pointer["learning_state_source_version"] != live_version:
            raise TeachingContextError("learning_state_changed", formal_id)
    return pointer, normalized, pointer_path


def verify_context(repo_root: Path | str, formal_id: str) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    try:
        pointer, context, pointer_path = _verify_or_raise(root, formal_id)
    except TeachingContextError as exc:
        return {
            "schema_version": VERIFY_SCHEMA,
            "status": "invalid",
            "formal_id": formal_id,
            "reason_code": exc.code,
        }
    bindings = context["source_bindings"]
    return {
        "schema_version": VERIFY_SCHEMA,
        "status": "valid",
        "formal_id": formal_id,
        "context_path": pointer["context_path"],
        "context_sha256": pointer["context_sha256"],
        "pointer_path": _relative_to_repo(root, pointer_path),
        "pointer_sha256": sha256_file(pointer_path),
        "source_bindings": copy.deepcopy(bindings),
    }


def _protected_prior(prior: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "evidence_scope": "prior_only",
        "action_gap_type": prior["action_gap_type"],
        "evidence_origin": prior["evidence_origin"],
        "needs_confirmation": prior["needs_confirmation"],
        "hint_dependency": {
            "level": prior["hint_dependency"]["level"],
            "evidence_origin": prior["hint_dependency"]["evidence_origin"],
        },
        "effective_representation": [
            {
                "kind": item["kind"],
                "evidence_origin": item["evidence_origin"],
            }
            for item in prior["effective_representation"]
        ],
        "c_followup": {
            "eligible": prior["c_followup"]["eligible"],
            "after_current_question_only": True,
        },
    }


def resolve_context(
    repo_root: Path | str,
    formal_id: str,
    view: str = "protected",
    related_limit: int = 3,
) -> dict[str, Any]:
    if view not in {"protected", "after_attempt", "direct"}:
        raise TeachingContextError("invalid_view", view)
    if type(related_limit) is not int or not 0 <= related_limit <= 6:
        raise TeachingContextError("invalid_related_limit", str(related_limit))
    root = Path(repo_root).resolve()
    try:
        personal = math_learning_state.personal_context(root, formal_id, view, related_limit=related_limit)
    except (OSError, ValueError) as exc:
        personal = {"status": "unavailable", "reason": str(exc), "history_may_override_current": False}
    try:
        _pointer, context, _pointer_path = _verify_or_raise(root, formal_id)
    except TeachingContextError as exc:
        return {
            "schema_version": VIEW_SCHEMA,
            "status": "available_current_state" if personal["status"] == "available" else "unavailable",
            "formal_id": formal_id,
            "view": view,
            "reason_code": exc.code,
            "prior": {},
            "personal_context": personal,
            "historical_prior_status": "discarded_untrusted_or_stale",
            "current_question_evidence": {
                "authority": "external_runtime",
                "required": True,
                "history_may_override": False,
            },
        }
    prior = context["prior"]
    bound = bool(_pointer.get("learning_state_source_version"))
    current_available = personal["status"] == "available" and bool(personal.get("current"))
    current_bound = current_available and bound and (
        _pointer["learning_state_source_version"] == personal["current"]["source_version"])
    return {
        "schema_version": VIEW_SCHEMA,
        "status": ("available" if current_bound else "available_current_state") if current_available else "unavailable",
        "formal_id": formal_id,
        "view": view,
        "current_question_evidence": {
            "authority": "external_runtime",
            "required": True,
            "history_may_override": False,
        },
        "prior": (_protected_prior(prior) if view == "protected" else copy.deepcopy(prior)) if current_bound else {},
        "personal_context": personal,
        "historical_prior_status": ("current_bound" if current_bound else
                                    "discarded_current_state_unavailable" if not current_available else
                                    "discarded_learning_state_changed" if bound else "legacy_unbound_not_used_as_current"),
    }


def _load_input(path: Path) -> dict[str, Any]:
    info = _regular_file(path, "materialize input")
    if info.st_size > MAX_INPUT_BYTES:
        raise TeachingContextError("bounded_context_exceeded", "materialize input")
    return _read_json(path, "materialize input", MAX_INPUT_BYTES)


def _teaching_atom(value: Any, max_bytes: int = 900) -> Any:
    """Keep a complete short evidence atom or a verifiable omission, never half a claim."""
    if len(canonical_json(value).encode("utf-8")) <= max_bytes:
        return value
    return {"omitted": True, "sha256": sha256_value(value),
            "reason": "long_evidence_requires_exact_source_read"}


def teaching_record_projection(record: dict, raw_record: dict, view: str) -> dict:
    """Bound the teaching surface before native pagination, without altering stored evidence.

    Protected views already hide mathematical content. Direct teaching still uses
    this short surface; the native index/export remains the full evidence route.
    """
    if view == "protected":
        return record
    result = {key: value for key, value in record.items()
              if key not in {"summary", "history", "text", "metadata"}}
    summary = record.get("summary", {})
    if record.get("kind") in {"concept_review", "formal_concept_observation"}:
        rows = summary.get("observations", [])
        # Preserve the latest state, latest actual error, one earlier concrete
        # error, and latest hint-assisted correction. Positions are source order.
        candidates = [("latest_observation", len(rows) - 1)] if rows else []
        wrong = [i for i, row in enumerate(rows) if row.get("outcome") == "wrong"]
        corrected = [i for i, row in enumerate(rows) if row.get("outcome") == "corrected_after_hint"]
        if wrong:
            candidates += [("latest_actual_error", wrong[-1]), ("earlier_actual_error", wrong[0])]
        if corrected:
            candidates.append(("latest_hint_assisted_correction", corrected[-1]))
        selected: dict[int, dict] = {}
        for reason, position in candidates:
            if position in selected:
                selected[position]["selection_reasons"].append(reason)
                continue
            row = rows[position]
            item = {key: _teaching_atom(row[key], 420) for key in (
                "observation_id", "concept_key", "concept_label", "capture_event_id",
                "question_ref", "outcome", "error_detail", "user_turn_indices",
                "hint_turn_indices", "related_formal_ids", "correction_text", "hint_dependency"
            ) if key in row}
            item.update({"source_observation_index": position, "selection_reasons": [reason]})
            for role, field in (("user", "user_evidence"), ("assistant", "hint_evidence")):
                evidence = row.get(field)
                if evidence is None:
                    index_field = "user_turn_indices" if role == "user" else "hint_turn_indices"
                    conversation = raw_record.get("history", {}).get("conversation", [])
                    indices = row.get(index_field, [])
                    evidence = [{"sequence": index, "quote": conversation[index]["text"]}
                                for index in indices[-1:]
                                if type(index) is int and 0 <= index < len(conversation)
                                and conversation[index].get("role") == role]
                item[field] = [_teaching_atom(atom, 420) for atom in evidence[-1:]]
                item[field + "_total"] = len(row.get(field, row.get(
                    "user_turn_indices" if role == "user" else "hint_turn_indices", [])))
            selected[position] = item
        result["summary"] = {key: _teaching_atom(summary[key]) for key in (
            "event_id", "episode_id", "session_id", "study_date", "source_ordinal", "attribution"
        ) if key in summary}
        result["summary"].update({"observations": list(selected.values()),
                                  "observation_total": len(rows),
                                  "observations_omitted": len(rows) - len(selected),
                                  "selection_scope": "within_this_event_not_global_latest"})
    elif summary:
        result["summary"] = {key: _teaching_atom(summary[key]) for key in (
            "wrong_point", "first_wrong", "latest_wrong", "wrong_history_dates",
            "mastery_history_dates", "latest_mastery_history", "latest_review_event",
            "latest_correction_text", "latest_hint_dependency", "exact_duplicate_fields"
        ) if key in summary}
    result["teaching_projection"] = "bounded_evidence_v1;omissions_are_not_absence_of_error"
    return result


def resolve_teaching_concepts(repo_root: Path | str, concepts: list[str],
                             view: str = "protected", max_bytes: int = 10000,
                             offset: int = 0, material_limit: int = 1) -> dict:
    import math_learning_profiles
    # Full evidence remains available through math_concept_index. The learning
    # entry reads already prepared rows instead of projecting every raw record.
    if offset:
        return {'status':'full_history_requires_explicit_read','records':[]}
    return math_learning_profiles.resolve(repo_root, concepts, view, max_bytes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(PROJECT_ROOT), help="kaoyan-math repository root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize = subparsers.add_parser("materialize", help="validate and publish one slice")
    materialize.add_argument("--input", required=True, help="path to a JSON context document")

    resolve = subparsers.add_parser("resolve", help="resolve one exact formal ID")
    resolve.add_argument("--formal-id", help="Optional exact-card history route; new questions use --concept")
    resolve.add_argument('--source-question-id', help='Exact printed source ID; zero match is a new source')
    resolve.add_argument('--known-version', help='Reuse this same-question response when unchanged')
    resolve.add_argument('--full-evidence', action='store_true', help='Explicit maintenance/history read, outside normal teaching')
    resolve.add_argument("--concept", action="append", dest="concepts",
                         help="Knowledge label, alias or stable key extracted from the current problem; repeat for multiple concepts")
    resolve.add_argument("--max-bytes", type=int, default=4500,
                         help="Combined UTF-8 budget for prepared teaching summaries (default 4500)")
    resolve.add_argument("--offset", type=int, default=0)
    resolve.add_argument("--material-limit", type=int, default=1,
                         help="Maximum reference-only items per concept page; default 1 leaves room for personal history")
    resolve.add_argument("--expected-version", help="Pin subsequent pages to the first result version")
    resolve.add_argument("--related-limit", type=int, choices=range(7), default=3,
                         help="0 reads only current personal evidence; add related cards only when needed")
    resolve.add_argument(
        "--view",
        choices=("protected", "after_attempt", "direct"),
        default="protected",
    )

    verify = subparsers.add_parser("verify", help="verify one exact formal ID")
    verify.add_argument("--formal-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "materialize":
            result = materialize_context(args.repo, _load_input(Path(args.input)))
            code = 0
        elif args.command == "resolve":
            if not args.full_evidence and (args.concepts or args.formal_id or args.source_question_id):
                import math_learning_profiles
                result = math_learning_profiles.resolve(args.repo,args.concepts or [],args.view,args.max_bytes,
                    args.known_version,args.formal_id,args.source_question_id)
            elif args.concepts:
                import math_concept_index
                result = math_concept_index.resolve_concepts(
                    args.repo, args.concepts, args.view, args.max_bytes, args.offset,
                    material_limit=args.material_limit)
                if args.expected_version and result.get("version") != args.expected_version:
                    result = {"schema_version": "math-concept-teaching-context-v1",
                              "status": "stale_page", "reason": "index_version_changed",
                              "records": []}
            elif args.formal_id:
                result = resolve_context(args.repo, args.formal_id, args.view, args.related_limit)
            else:
                raise TeachingContextError("concept_or_formal_id_required", "resolve")
            code = 0
        else:
            result = verify_context(args.repo, args.formal_id)
            code = 0 if result["status"] == "valid" else 1
    except TeachingContextError as exc:
        result = {
            "schema_version": "math-teaching-context-error-v1",
            "status": "error",
            "reason_code": exc.code,
        }
        code = 2
    except (OSError, ValueError, sqlite3.Error) as exc:
        result = {"schema_version": "math-teaching-context-error-v1", "status": "unavailable",
                  "reason_code": "personal_context_unavailable", "reason": str(exc)}
        code = 2
    if args.command == "resolve" and args.concepts:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
