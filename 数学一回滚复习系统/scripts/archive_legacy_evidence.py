#!/usr/bin/env python3
"""Archive one closed historical math Capture without fabricating a conversation."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARCHIVE_ROOT = Path("/Volumes/T9-Data")
DEFAULT_SUBJECT_RELATIVE_ROOT = Path("03_数学/资料库/原始会话资料")
SENTINEL_RELATIVE_PATH = Path("00_迁移管理/状态/volume-sentinel.json")
SENTINEL_SHA256 = "f086b32b29b2b38f1a28dffb8fde4fa850078332d8a23ae269cc8e857a6bd2ca"
EXPECTED_VOLUME_NAME = "T9-Data"
EXPECTED_VOLUME_UUID = "00000000-0000-0000-0000-000000000000"
PACKAGE_SCHEMA = "math-legacy-evidence-archive-package-v1"
PREVIEW_SCHEMA = "math-legacy-evidence-archive-preview-v1"
INTENT_SCHEMA = "math-legacy-evidence-archive-intent-v1"
RECEIPT_SCHEMA = "math-legacy-evidence-archive-receipt-v1"
POINTER_SCHEMA = "math-legacy-evidence-archive-pointer-v1"
RECEIPT_SCHEMA_V2 = "math-legacy-evidence-archive-receipt-v2"
POINTER_SCHEMA_V2 = "math-legacy-evidence-archive-pointer-v2"
LOCATOR_TYPE = "raw_archive_locator"
RECEIPTS_RELATIVE_PATH = Path("数学一回滚复习系统/原始会话归档回执.jsonl")
INTENT_RELATIVE_ROOT = Path("数学一回滚复习系统/原始会话归档意图")
LEDGER_RELATIVE_PATH = Path("数学一回滚复习系统/快速入库事件.jsonl")
LOCK_RELATIVE_PATH = Path("数学一回滚复习系统/.原始会话归档.lock")
LEDGER_ONLY_POINTER_ROOT = Path("数学一回滚复习系统/历史证据归档指针")
LOCATOR_RELATIVE_ROOT = Path("错题知识网络/wiki/sources/raw_archives")
LEGACY_POINTER_FILENAME = "legacy-archive-pointer.json"
LEGACY_POINTER_DIRECTORY = "legacy-archive-pointers"
CAPTURE_ID_RE = re.compile(r"^MFI-CAP-[0-9a-f]{24}$")
FORMAL_ID_RE = re.compile(r"^(?:GS|LA|PR)-\d{3,}$")
LEGACY_PACKAGE_ID_RE = re.compile(r"^MATHLEGACY-[0-9a-f]{24}$")
AUTHORIZATION_PREFIX = "MATH-LEGACY-ARCHIVE-APPLY-"
REPAIR_PREVIEW_SCHEMA = "math-legacy-evidence-archive-repair-preview-v1"
REPAIR_RECORD_SCHEMA = "math-legacy-evidence-archive-repair-successor-v1"
REPAIR_AUTHORIZATION_PREFIX = "MATH-LEGACY-ARCHIVE-REPAIR-APPLY-"
REPAIR_ID_PREFIX = "MATH-LEGACY-ARCHIVE-REPAIR-"
REPAIR_RELATIVE_ROOT = Path("数学一回滚复习系统/历史证据归档修复证明")
DISPLAY_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


class LegacyArchiveError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_json_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def now_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_quick_intake(repo: Path, archive_root: Path) -> Any:
    path = repo / "数学一回滚复习系统/scripts/quick_intake.py"
    spec = importlib.util.spec_from_file_location("math_legacy_archive_quick_intake", path)
    if spec is None or spec.loader is None:
        raise LegacyArchiveError("quick_intake_import_invalid")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    module.REPO_ROOT = repo
    module.ROOT = repo / "数学一回滚复习系统"
    module.EVENTS_PATH = repo / LEDGER_RELATIVE_PATH
    module.SOURCE_STAGING_ROOT = module.ROOT / "快速入库来源"
    module.ARCHIVE_ROOT = archive_root
    module.ARCHIVE_SENTINEL_PATH = archive_root / SENTINEL_RELATIVE_PATH
    module.ARCHIVE_SENTINEL_SHA256 = SENTINEL_SHA256
    module.ARCHIVE_VOLUME_UUID = EXPECTED_VOLUME_UUID
    return module


def load_display_assets(repo: Path) -> Any:
    path = repo / "数学一回滚复习系统/scripts/display_assets.py"
    spec = importlib.util.spec_from_file_location("math_legacy_archive_display_assets", path)
    if spec is None or spec.loader is None:
        raise LegacyArchiveError("display_assets_import_invalid")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def safe_relative_path(value: str | Path, field: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise LegacyArchiveError(f"{field}_unsafe")
    return relative


def verified_archive_path(
    archive_root: Path,
    relative: str | Path,
    *,
    field: str,
) -> Path:
    """Reject descendant symlinks and prove the lexical path remains under T9."""
    root = archive_root.resolve(strict=True)
    relative_path = safe_relative_path(relative, field)
    candidate = root / relative_path
    current = root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            raise LegacyArchiveError(f"{field}_symlink_forbidden")
        if current.exists() and current != candidate and not current.is_dir():
            raise LegacyArchiveError(f"{field}_parent_not_directory")
    resolved = candidate.resolve(strict=False)
    if root not in resolved.parents:
        raise LegacyArchiveError(f"{field}_escapes_t9")
    return candidate


def validate_volume(archive_root: Path) -> dict[str, Any]:
    if archive_root.is_symlink():
        raise LegacyArchiveError("archive_root_symlink_forbidden")
    try:
        root = archive_root.resolve(strict=True)
        expected_root = DEFAULT_ARCHIVE_ROOT.resolve(strict=True)
    except OSError as exc:
        raise LegacyArchiveError("archive_root_unavailable") from exc
    if root != expected_root or root.name != EXPECTED_VOLUME_NAME:
        raise LegacyArchiveError("archive_root_must_be_exact_t9_data")
    ambiguous = {Path("/Volumes/T9-Data 1"), root.with_name(f"{root.name} 1")}
    if any(path.exists() for path in ambiguous):
        raise LegacyArchiveError("ambiguous_t9_mount_suffix_present")
    sentinel_path = verified_archive_path(
        root, SENTINEL_RELATIVE_PATH, field="volume_sentinel_path"
    )
    if not sentinel_path.is_file() or sha256_file(sentinel_path) != SENTINEL_SHA256:
        raise LegacyArchiveError("volume_sentinel_sha256_mismatch")
    try:
        sentinel = json.loads(sentinel_path.read_text(encoding="utf-8"))
        expected_mount = Path(str(sentinel.get("expected_mount_point"))).resolve(strict=True)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyArchiveError("volume_sentinel_invalid") from exc
    if (
        sentinel.get("volume_name") != EXPECTED_VOLUME_NAME
        or sentinel.get("volume_uuid") != EXPECTED_VOLUME_UUID
        or expected_mount != root
    ):
        raise LegacyArchiveError("volume_sentinel_identity_mismatch")
    return sentinel


def tree_inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise LegacyArchiveError("archive_tree_contains_symlink")
        if path.is_file():
            rows.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return rows


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def load_receipts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise LegacyArchiveError("archive_receipt_ledger_unreadable") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LegacyArchiveError(
                f"archive_receipt_ledger_invalid_json:{line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise LegacyArchiveError(f"archive_receipt_ledger_invalid_row:{line_number}")
        rows.append(row)
    return rows


def append_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(receipt))
        handle.flush()
        os.fsync(handle.fileno())


def raw_ledger_line_index(
    ledger_path: Path, parsed_events: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    try:
        raw = ledger_path.read_bytes()
    except OSError as exc:
        raise LegacyArchiveError("ledger_unreadable") from exc
    parsed_by_id = {row["event_id"]: row for row in parsed_events}
    result: dict[str, dict[str, Any]] = {}
    for line_number, raw_line in enumerate(raw.splitlines(keepends=True), start=1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LegacyArchiveError(f"ledger_raw_line_invalid:{line_number}") from exc
        event_id = row.get("event_id") if isinstance(row, dict) else None
        if not isinstance(event_id, str) or event_id in result:
            raise LegacyArchiveError(f"ledger_raw_event_identity_invalid:{line_number}")
        if parsed_by_id.get(event_id) != row:
            raise LegacyArchiveError(f"ledger_raw_event_parse_mismatch:{line_number}")
        result[event_id] = {
            "line_number": line_number,
            "raw": raw_line,
            "event": row,
        }
    if set(result) != set(parsed_by_id):
        raise LegacyArchiveError("ledger_raw_event_set_mismatch")
    return result


def lineage_event_ids(
    state: dict[str, Any], capture_id: str, closeout: dict[str, Any]
) -> list[str]:
    capture = state["captures"][capture_id]
    freeze_id = closeout.get("freeze_id")
    freeze = state["freezes"].get(freeze_id)
    if not isinstance(freeze, dict) or capture_id not in freeze.get("capture_event_ids", []):
        raise LegacyArchiveError("formal_freeze_binding_invalid")
    selected = {capture["event_id"], freeze_id, closeout["event_id"]}
    selected.update(row["event_id"] for row in state["amendments"][capture_id])
    prepare_id = closeout.get("prepare_id")
    if prepare_id is not None:
        prepare = state["prepares"].get(prepare_id)
        if (
            not isinstance(prepare, dict)
            or prepare.get("freeze_id") != freeze_id
            or capture_id not in prepare.get("capture_event_ids", [])
        ):
            raise LegacyArchiveError("formal_prepare_binding_invalid")
        selected.add(prepare_id)
    return sorted(selected)


def _payload_inventory(payload_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "path": row["archive_path"],
                "size": row["size"],
                "sha256": row["sha256"],
            }
            for row in payload_files
        ],
        key=lambda row: row["path"],
    )


def select_local_pointer_path(
    repo: Path,
    source_bundle: dict[str, Any] | None,
    capture_id: str,
) -> Path:
    if source_bundle is None:
        return repo / LEDGER_ONLY_POINTER_ROOT / f"{capture_id}.json"
    manifest = repo / source_bundle["manifest_path"]
    single = manifest.parent / LEGACY_POINTER_FILENAME
    capture_specific = manifest.parent / LEGACY_POINTER_DIRECTORY / f"{capture_id}.json"
    if capture_specific.exists():
        return capture_specific
    if not single.exists():
        return single
    try:
        owner = json.loads(single.read_text(encoding="utf-8")).get("capture_event_id")
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        owner = None
    if owner == capture_id:
        return single
    return capture_specific


def _source_payload(
    *,
    quick: Any,
    repo: Path,
    capture: dict[str, Any],
    amendments: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]], dict[str, Path]]:
    declared_bindings: list[Any] = []
    if capture.get("source_bundle") is not None:
        declared_bindings.append(capture.get("source_bundle"))
    for amendment in amendments:
        patch = amendment.get("target_patch")
        if isinstance(patch, dict) and patch.get("source_bundle") is not None:
            declared_bindings.append(patch.get("source_bundle"))
    if any(not isinstance(item, dict) or not item for item in declared_bindings):
        raise LegacyArchiveError("source_bundle_present_but_invalid")
    bundle = quick.effective_source_bundle(capture, amendments)
    if bundle is None:
        if declared_bindings:
            raise LegacyArchiveError("source_bundle_present_but_unresolved")
        return "ledger_only", None, [], {}
    if not isinstance(bundle, dict):
        raise LegacyArchiveError("source_bundle_reference_invalid")
    manifest_relative = bundle.get("manifest_path")
    manifest_hash = bundle.get("manifest_hash")
    if not isinstance(manifest_relative, str) or not isinstance(manifest_hash, str):
        raise LegacyArchiveError("source_bundle_binding_incomplete")
    try:
        document, manifest_path, child_paths = quick.validate_source_bundle_manifest(
            manifest_relative,
            f"legacy_archive.capture[{capture['event_id']}].source_bundle",
            expected_hash=manifest_hash,
            expected_date=capture["study_date"],
            require_question=False,
        )
    except (OSError, ValueError) as exc:
        raise LegacyArchiveError(f"source_bundle_invalid:{exc}") from exc
    if document.get("schema_version") == quick.CONVERSATION_PACKAGE_SCHEMA:
        raise LegacyArchiveError("legacy_archive_rejects_canonical_conversation_package")
    if document.get("schema_version") != quick.SOURCE_BUNDLE_SCHEMA:
        raise LegacyArchiveError("legacy_source_bundle_schema_invalid")
    if len(child_paths) != len(document.get("artifacts", [])):
        raise LegacyArchiveError("legacy_source_bundle_artifact_count_mismatch")

    payload_files: list[dict[str, Any]] = []
    payload_sources: dict[str, Path] = {}
    manifest_archive_path = "source-bundle/manifest.json"
    payload_files.append(
        {
            "kind": "source_bundle_manifest",
            "original_path": manifest_relative,
            "archive_path": manifest_archive_path,
            "size": manifest_path.stat().st_size,
            "sha256": sha256_file(manifest_path),
            "media_type": "application/json; charset=utf-8",
        }
    )
    payload_sources[manifest_archive_path] = manifest_path
    seen_archive_paths = {manifest_archive_path}
    for artifact, source_path in zip(document["artifacts"], child_paths):
        original_path = artifact.get("path")
        if not isinstance(original_path, str):
            raise LegacyArchiveError("legacy_source_artifact_original_path_invalid")
        archive_path = f"source-bundle/{Path(original_path).name}"
        if archive_path in seen_archive_paths:
            raise LegacyArchiveError("legacy_source_artifact_archive_path_conflict")
        seen_archive_paths.add(archive_path)
        if (
            not source_path.is_file()
            or source_path.stat().st_size != artifact.get("size")
            or sha256_file(source_path) != artifact.get("sha256")
        ):
            raise LegacyArchiveError("legacy_source_artifact_hash_drift")
        payload_files.append(
            {
                "kind": "source_artifact",
                "role": artifact.get("role"),
                "original_path": original_path,
                "archive_path": archive_path,
                "size": artifact.get("size"),
                "sha256": artifact.get("sha256"),
                "media_type": artifact.get("media_type"),
            }
        )
        payload_sources[archive_path] = source_path
    source_bundle = {
        "schema_version": document["schema_version"],
        "bundle_id": document["bundle_id"],
        "manifest_path": manifest_relative,
        "manifest_sha256": manifest_hash,
        "source_locator": document["source_locator"],
        "artifact_count": len(document["artifacts"]),
    }
    return "source_bundle", source_bundle, payload_files, payload_sources


def build_cleanup_proof(
    *,
    quick: Any,
    state: dict[str, Any],
    target_capture_id: str,
    source_bundle: dict[str, Any] | None,
    cleanup_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if source_bundle is None:
        return {
            "schema_version": "math-legacy-source-cleanup-proof-v1",
            "target_capture_event_id": target_capture_id,
            "source_bundle_manifest_path": None,
            "source_bundle_manifest_sha256": None,
            "reference_capture_ids": [],
            "reference_count": 0,
            "unprovable_capture_ids": [],
            "overall_decision": "not_applicable_ledger_only",
            "items": [],
        }
    manifest_path = source_bundle["manifest_path"]
    manifest_sha256 = source_bundle["manifest_sha256"]
    reference_ids: list[str] = []
    unprovable_ids: list[str] = []
    for capture_id, capture in state["captures"].items():
        amendments = state["amendments"][capture_id]
        binding_error = quick.source_bundle_binding_error(capture, amendments)
        if binding_error is not None:
            unprovable_ids.append(capture_id)
            continue
        binding = quick.effective_source_bundle(capture, amendments)
        if not isinstance(binding, dict):
            continue
        if binding.get("manifest_path") != manifest_path:
            continue
        if binding.get("manifest_hash") != manifest_sha256:
            unprovable_ids.append(capture_id)
            continue
        reference_ids.append(capture_id)
    reference_ids = sorted(set(reference_ids))
    unprovable_ids = sorted(set(unprovable_ids))
    if target_capture_id not in reference_ids:
        raise LegacyArchiveError("cleanup_target_source_reference_not_proven")
    if unprovable_ids:
        decision = "retain_unprovable_reference"
    elif reference_ids != [target_capture_id]:
        decision = "retain_shared_reference"
    else:
        decision = "delete_exclusive_reference"
    items = [
        {
            "path": row["path"],
            "size": row["size"],
            "sha256": row["sha256"],
            "reference_capture_ids": reference_ids,
            "reference_count": len(reference_ids),
            "unprovable_capture_ids": unprovable_ids,
            "decision": decision,
            "verified_pointer_coverage_required": True,
        }
        for row in cleanup_candidates
    ]
    return {
        "schema_version": "math-legacy-source-cleanup-proof-v1",
        "target_capture_event_id": target_capture_id,
        "source_bundle_manifest_path": manifest_path,
        "source_bundle_manifest_sha256": manifest_sha256,
        "reference_capture_ids": reference_ids,
        "reference_count": len(reference_ids),
        "unprovable_capture_ids": unprovable_ids,
        "overall_decision": decision,
        "items": items,
    }


def build_legacy_archive_plan(
    *,
    repo: Path,
    capture_id: str,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
    subject_relative_root: Path = DEFAULT_SUBJECT_RELATIVE_ROOT,
) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    if not CAPTURE_ID_RE.fullmatch(capture_id):
        raise LegacyArchiveError("capture_id_invalid")
    if subject_relative_root != DEFAULT_SUBJECT_RELATIVE_ROOT:
        raise LegacyArchiveError("subject_relative_root_mismatch")
    sentinel = validate_volume(archive_root)
    quick = load_quick_intake(repo, archive_root)
    ledger_path = repo / LEDGER_RELATIVE_PATH
    events = quick.load_jsonl(ledger_path)
    state = quick.replay(events)
    capture = state["captures"].get(capture_id)
    if not isinstance(capture, dict):
        raise LegacyArchiveError("capture_not_found")
    closeout_id = state["closed_by"].get(capture_id)
    if not isinstance(closeout_id, str):
        raise LegacyArchiveError("capture_has_no_trusted_formal_closeout")
    if closeout_id in state.get("invalidated_closeouts", set()):
        raise LegacyArchiveError("formal_closeout_invalidated")
    closeout = state["closeouts"].get(closeout_id)
    if not isinstance(closeout, dict):
        raise LegacyArchiveError("formal_closeout_missing")
    freeze_id = closeout.get("freeze_id")
    freeze = state["freezes"].get(freeze_id)
    if not isinstance(freeze_id, str) or not isinstance(freeze, dict):
        raise LegacyArchiveError("formal_freeze_missing")
    if capture_id not in closeout.get("capture_event_ids", []):
        raise LegacyArchiveError("formal_closeout_capture_binding_invalid")
    try:
        formal_ids, terminal_outcome = quick.derived_archive_terminal_facts(
            closeout, capture_id
        )
    except ValueError as exc:
        raise LegacyArchiveError(f"formal_terminal_facts_invalid:{exc}") from exc
    if not all(FORMAL_ID_RE.fullmatch(item) for item in formal_ids):
        raise LegacyArchiveError("formal_ids_invalid")

    amendments = state["amendments"][capture_id]
    evidence_mode, source_bundle, source_rows, source_paths = _source_payload(
        quick=quick,
        repo=repo,
        capture=capture,
        amendments=amendments,
    )
    conversation_binding = capture.get("conversation_package")
    if conversation_binding is not None:
        if not isinstance(conversation_binding, dict) or not conversation_binding:
            raise LegacyArchiveError("conversation_package_present_but_invalid")
        raise LegacyArchiveError("legacy_archive_rejects_canonical_conversation_package")

    raw_index = raw_ledger_line_index(ledger_path, events)
    selected_ids = lineage_event_ids(state, capture_id, closeout)
    selected_ids.sort(key=lambda item: raw_index[item]["line_number"])
    ledger_bytes = b"".join(raw_index[item]["raw"] for item in selected_ids)
    ledger_events = [
        {
            "event_id": item,
            "event_type": raw_index[item]["event"].get("event_type"),
            "line_number": raw_index[item]["line_number"],
            "raw_line_size": len(raw_index[item]["raw"]),
            "raw_line_sha256": sha256_bytes(raw_index[item]["raw"]),
        }
        for item in selected_ids
    ]
    ledger_archive_path = "ledger-events.jsonl"
    payload_files = [
        {
            "kind": "ledger_events",
            "original_path": LEDGER_RELATIVE_PATH.as_posix(),
            "archive_path": ledger_archive_path,
            "size": len(ledger_bytes),
            "sha256": sha256_bytes(ledger_bytes),
            "media_type": "application/x-ndjson; charset=utf-8",
        },
        *source_rows,
    ]
    payload_inventory = _payload_inventory(payload_files)
    identity = {
        "capture_event_id": capture_id,
        "study_date": capture.get("study_date"),
        "freeze_id": freeze_id,
        "closeout_id": closeout_id,
        "formal_ids": formal_ids,
        "terminal_outcome": terminal_outcome,
        "evidence_mode": evidence_mode,
        "ledger_events": ledger_events,
        "payload_inventory": payload_inventory,
    }
    legacy_package_id = "MATHLEGACY-" + sha256_value(identity)[:24]
    manifest_core = {
        "schema_version": PACKAGE_SCHEMA,
        "legacy_package_id": legacy_package_id,
        "subject": "math",
        "study_date": capture.get("study_date"),
        "evidence_mode": evidence_mode,
        "conversation_complete": False,
        "canonical_package": False,
        "capture_event_id": capture_id,
        "freeze_id": freeze_id,
        "closeout_id": closeout_id,
        "formal_ids": formal_ids,
        "terminal_outcome": terminal_outcome,
        "ledger_events": ledger_events,
        "source_bundle": source_bundle,
        "payload_files": payload_files,
        "payload_tree_sha256": sha256_value(payload_inventory),
        "formal_write_count": 0,
        "formal_actions_invoked": [],
        "background_processing": "none",
    }
    manifest = {**manifest_core, "canonical_sha256": sha256_value(manifest_core)}
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_sha256 = sha256_bytes(manifest_bytes)
    full_inventory = sorted(
        [
            {
                "path": "manifest.json",
                "size": len(manifest_bytes),
                "sha256": manifest_sha256,
            },
            *payload_inventory,
        ],
        key=lambda row: row["path"],
    )
    archive_tree_sha256 = sha256_value(full_inventory)
    archive_relpath = (
        subject_relative_root / str(capture.get("study_date")) / legacy_package_id
    ).as_posix()
    cleanup_candidates = [
        {
            "path": row["original_path"],
            "size": row["size"],
            "sha256": row["sha256"],
        }
        for row in payload_files
        if row["kind"] == "source_artifact"
    ]
    cleanup_proof = build_cleanup_proof(
        quick=quick,
        state=state,
        target_capture_id=capture_id,
        source_bundle=source_bundle,
        cleanup_candidates=cleanup_candidates,
    )
    pointer_path = select_local_pointer_path(repo, source_bundle, capture_id)
    try:
        pointer_relative = pointer_path.relative_to(repo).as_posix()
    except ValueError as exc:
        raise LegacyArchiveError("local_pointer_path_outside_repo") from exc
    base_authorization_core = {
        "schema_version": PREVIEW_SCHEMA,
        "operation": "legacy_evidence_archive_only",
        "capture_event_id": capture_id,
        "study_date": capture.get("study_date"),
        "freeze_id": freeze_id,
        "closeout_id": closeout_id,
        "formal_ids": formal_ids,
        "terminal_outcome": terminal_outcome,
        "legacy_package_id": legacy_package_id,
        "evidence_mode": evidence_mode,
        "conversation_complete": False,
        "canonical_package": False,
        "raw_archive_relpath": archive_relpath,
        "raw_archive_manifest_sha256": manifest_sha256,
        "raw_archive_package_sha256": manifest["canonical_sha256"],
        "archive_tree_sha256": archive_tree_sha256,
        "payload_inventory": full_inventory,
        "cleanup_candidates": cleanup_candidates,
        "cleanup_proof": cleanup_proof,
        "archive_volume": sentinel["volume_name"],
        "archive_volume_uuid": sentinel["volume_uuid"],
        "formal_write_count": 0,
        "formal_actions_invoked": [],
    }
    base_authorization = AUTHORIZATION_PREFIX + sha256_value(base_authorization_core)
    display_closure: dict[str, Any] | None = None
    display_closure_error: str | None = None
    if evidence_mode == "source_bundle" and isinstance(source_bundle, dict):
        try:
            display = load_display_assets(repo)
            display_closure = display.verify_closure_for_source(
                repo=repo,
                manifest_relative=source_bundle["manifest_path"],
                expected_manifest_sha256=source_bundle["manifest_sha256"],
                expected_package_sha256=None,
                formal_ids=formal_ids,
            )
        except ValueError as exc:
            display_closure_error = str(exc)
    v2_authorization_core = {
        **base_authorization_core,
        "local_pointer_path": pointer_relative,
        "display_closure": display_closure,
    }
    v2_authorization = AUTHORIZATION_PREFIX + sha256_value(v2_authorization_core)
    existing_intent_path = (
        repo / INTENT_RELATIVE_ROOT / f"{legacy_package_id}.json"
    )
    existing_intent_authorization = None
    if existing_intent_path.exists():
        try:
            existing_intent = json.loads(existing_intent_path.read_text(encoding="utf-8"))
            if isinstance(existing_intent, dict):
                existing_intent_authorization = existing_intent.get("authorization")
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing_intent_authorization = None
    pointer_document: dict[str, Any] | None = None
    if pointer_path.exists():
        try:
            value = json.loads(pointer_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                pointer_document = value
        except (OSError, UnicodeError, json.JSONDecodeError):
            pointer_document = None
    legacy_contract = (
        existing_intent_authorization == base_authorization
        or (
            isinstance(pointer_document, dict)
            and pointer_document.get("capture_event_id") == capture_id
            and pointer_document.get("authorization") == base_authorization
            and "local_pointer_path" not in pointer_document
        )
    )
    authorization_core = (
        base_authorization_core if legacy_contract else v2_authorization_core
    )
    authorization = base_authorization if legacy_contract else v2_authorization
    pointer_contract = (
        "legacy_single_v1"
        if legacy_contract
        and (
            pointer_path.name == LEGACY_POINTER_FILENAME
            or (
                isinstance(pointer_document, dict)
                and pointer_document.get("capture_event_id") == capture_id
                and "local_pointer_path" not in pointer_document
            )
        )
        else "legacy_receipt_capture_pointer_v2"
        if legacy_contract
        else "capture_pointer_v2"
    )
    public = {
        "status": "preview",
        **authorization_core,
        "authorization": authorization,
        "apply_required": True,
        "preview_write_count": 0,
        "source_bundle_manifest_path": (
            source_bundle.get("manifest_path") if isinstance(source_bundle, dict) else None
        ),
        "source_bundle_manifest_sha256": (
            source_bundle.get("manifest_sha256") if isinstance(source_bundle, dict) else None
        ),
        "ledger_event_ids": selected_ids,
        "local_pointer_path": pointer_relative,
        "pointer_contract": pointer_contract,
        "display_closure": display_closure,
        "display_closure_status": (
            "verified"
            if display_closure is not None
            else "not_applicable_ledger_only"
            if evidence_mode == "ledger_only"
            else "missing"
        ),
        "display_closure_error": display_closure_error,
        "apply_ready": evidence_mode == "ledger_only" or display_closure is not None or legacy_contract,
    }
    return {
        "public": public,
        "authorization_core": authorization_core,
        "manifest": manifest,
        "manifest_bytes": manifest_bytes,
        "full_inventory": full_inventory,
        "ledger_bytes": ledger_bytes,
        "source_paths": source_paths,
        "cleanup_candidates": cleanup_candidates,
        "cleanup_proof": cleanup_proof,
        "pointer_path": pointer_path,
        "pointer_contract": pointer_contract,
        "legacy_receipt_contract": legacy_contract,
        "display_closure": display_closure,
        "repo": repo,
        "archive_root": archive_root.resolve(strict=True),
        "subject_relative_root": subject_relative_root,
    }


def intent_identity(plan: dict[str, Any]) -> dict[str, Any]:
    public = plan["public"]
    return {
        "authorization": public["authorization"],
        "legacy_package_id": public["legacy_package_id"],
        "capture_event_id": public["capture_event_id"],
        "freeze_id": public["freeze_id"],
        "closeout_id": public["closeout_id"],
        "raw_archive_manifest_sha256": public["raw_archive_manifest_sha256"],
        "raw_archive_package_sha256": public["raw_archive_package_sha256"],
        "archive_tree_sha256": public["archive_tree_sha256"],
    }


def intent_path(plan: dict[str, Any]) -> Path:
    return (
        plan["repo"]
        / INTENT_RELATIVE_ROOT
        / f"{plan['public']['legacy_package_id']}.json"
    )


def repair_record_path(plan: dict[str, Any]) -> Path:
    return (
        plan["repo"]
        / REPAIR_RELATIVE_ROOT
        / f"{plan['public']['capture_event_id']}.json"
    )


def live_repair_binding(plan: dict[str, Any]) -> dict[str, Any]:
    public = plan["public"]
    return {
        "capture_event_id": public["capture_event_id"],
        "study_date": public["study_date"],
        "freeze_id": public["freeze_id"],
        "closeout_id": public["closeout_id"],
        "formal_ids": public["formal_ids"],
        "terminal_outcome": public["terminal_outcome"],
        "legacy_package_id": public["legacy_package_id"],
        "evidence_mode": public["evidence_mode"],
        "conversation_complete": False,
        "canonical_package": False,
        "raw_archive_relpath": public["raw_archive_relpath"],
        "raw_archive_manifest_sha256": public["raw_archive_manifest_sha256"],
        "raw_archive_package_sha256": public["raw_archive_package_sha256"],
        "archive_tree_sha256": public["archive_tree_sha256"],
        "payload_inventory_sha256": sha256_value(plan["full_inventory"]),
        "cleanup_proof_sha256": sha256_value(plan["cleanup_proof"]),
        "local_pointer_path": public["local_pointer_path"],
        "source_bundle_manifest_path": public.get("source_bundle_manifest_path"),
        "source_bundle_manifest_sha256": public.get(
            "source_bundle_manifest_sha256"
        ),
        "archive_volume": EXPECTED_VOLUME_NAME,
        "archive_volume_uuid": EXPECTED_VOLUME_UUID,
    }


def verify_predecessor_archive_surfaces(plan: dict[str, Any]) -> dict[str, Any]:
    """Verify the completed old contract without rewriting it.

    This accepts the predecessor's own authorization as historical identity,
    while requiring every immutable ledger/archive binding and every live T9
    byte to equal the currently rederived package.
    """
    public = plan["public"]
    current_intent_path = intent_path(plan)
    if current_intent_path.is_symlink() or not current_intent_path.is_file():
        raise LegacyArchiveError("legacy_repair_predecessor_intent_missing")
    try:
        intent = json.loads(current_intent_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyArchiveError("legacy_repair_predecessor_intent_invalid") from exc
    identity_keys = (
        "authorization",
        "legacy_package_id",
        "capture_event_id",
        "freeze_id",
        "closeout_id",
        "raw_archive_manifest_sha256",
        "raw_archive_package_sha256",
        "archive_tree_sha256",
    )
    old_identity = {key: intent.get(key) for key in identity_keys}
    expected_intent_id = "MATH-LEGACY-ARCHIVE-INTENT-" + sha256_value(
        old_identity
    )[:24]
    immutable_keys = tuple(key for key in identity_keys if key != "authorization")
    if (
        not isinstance(intent, dict)
        or intent.get("schema_version") != INTENT_SCHEMA
        or intent.get("intent_id") != expected_intent_id
        or not isinstance(intent.get("archive_verified_at"), str)
        or not intent["archive_verified_at"]
        or any(intent.get(key) != public.get(key) for key in immutable_keys)
        or current_intent_path.read_bytes() != canonical_json_bytes(intent)
    ):
        raise LegacyArchiveError("legacy_repair_predecessor_intent_binding_invalid")

    pointer_path = plan["pointer_path"]
    if pointer_path.is_symlink() or not pointer_path.is_file():
        raise LegacyArchiveError("legacy_repair_predecessor_pointer_missing")
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyArchiveError("legacy_repair_predecessor_pointer_invalid") from exc
    pointer_relative = pointer_path.relative_to(plan["repo"]).as_posix()
    if (
        not isinstance(pointer, dict)
        or pointer.get("schema_version") not in {POINTER_SCHEMA, POINTER_SCHEMA_V2}
        or pointer.get("archive_status") != "verified"
        or pointer.get("archive_intent_id") != intent["intent_id"]
        or pointer.get("authorization") != intent["authorization"]
        or any(pointer.get(key) != public.get(key) for key in immutable_keys)
        or pointer.get("formal_ids") != public["formal_ids"]
        or pointer.get("terminal_outcome") != public["terminal_outcome"]
        or pointer.get("evidence_mode") != public["evidence_mode"]
        or pointer.get("conversation_complete") is not False
        or pointer.get("canonical_package") is not False
        or pointer.get("archive_volume") != EXPECTED_VOLUME_NAME
        or pointer.get("raw_archive_relpath") != public["raw_archive_relpath"]
        or pointer.get("source_bundle_manifest_path")
        != public.get("source_bundle_manifest_path")
        or pointer.get("source_bundle_manifest_sha256")
        != public.get("source_bundle_manifest_sha256")
        or pointer.get("cleanup_proof") != plan["cleanup_proof"]
        or pointer.get("cleanup_intent")
        != (
            "remove_local_source_artifacts_after_verified_legacy_archive_locator_receipt"
            if public["evidence_mode"] == "source_bundle"
            else "none_ledger_only"
        )
        or (
            "local_pointer_path" in pointer
            and pointer.get("local_pointer_path") != pointer_relative
        )
    ):
        raise LegacyArchiveError("legacy_repair_predecessor_pointer_binding_invalid")

    receipt_id = pointer.get("archive_receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id:
        raise LegacyArchiveError("legacy_repair_predecessor_receipt_id_missing")
    receipts_path = plan["repo"] / RECEIPTS_RELATIVE_PATH
    if receipts_path.is_symlink():
        raise LegacyArchiveError("legacy_repair_receipt_ledger_symlink_forbidden")
    matches = [
        row for row in load_receipts(receipts_path) if row.get("receipt_id") == receipt_id
    ]
    if len(matches) != 1:
        raise LegacyArchiveError("legacy_repair_predecessor_receipt_not_unique")
    receipt = matches[0]
    if (
        receipt.get("schema_version") not in {RECEIPT_SCHEMA, RECEIPT_SCHEMA_V2}
        or receipt.get("archive_status") != "verified"
        or receipt.get("obsidian_path_status") != "verified"
        or receipt.get("archive_intent_id") != intent["intent_id"]
        or receipt.get("authorization") != intent["authorization"]
        or any(receipt.get(key) != public.get(key) for key in immutable_keys)
        or receipt.get("formal_ids") != public["formal_ids"]
        or receipt.get("terminal_outcome") != public["terminal_outcome"]
        or receipt.get("evidence_mode") != public["evidence_mode"]
        or receipt.get("conversation_complete") is not False
        or receipt.get("canonical_package") is not False
        or receipt.get("archive_volume") != EXPECTED_VOLUME_NAME
        or receipt.get("raw_archive_relpath") != public["raw_archive_relpath"]
        or receipt.get("source_bundle_manifest_path")
        != public.get("source_bundle_manifest_path")
        or receipt.get("source_bundle_manifest_sha256")
        != public.get("source_bundle_manifest_sha256")
        or receipt.get("cleanup_proof") != plan["cleanup_proof"]
        or (
            "local_pointer_path" in receipt
            and receipt.get("local_pointer_path") != pointer_relative
        )
    ):
        raise LegacyArchiveError("legacy_repair_predecessor_receipt_binding_invalid")
    receipt_identity = {
        "authorization": intent["authorization"],
        "legacy_package_id": public["legacy_package_id"],
        "capture_event_id": public["capture_event_id"],
        "closeout_id": public["closeout_id"],
        "archive_intent_id": intent["intent_id"],
        "raw_archive_manifest_sha256": public["raw_archive_manifest_sha256"],
        "raw_archive_package_sha256": public["raw_archive_package_sha256"],
        "archive_tree_sha256": public["archive_tree_sha256"],
        "obsidian_locator_sha256": receipt.get("obsidian_locator_sha256"),
    }
    expected_receipt_id = "MATH-LEGACY-ARCHIVE-" + sha256_value(
        receipt_identity
    )[:24]
    if receipt_id != expected_receipt_id or pointer.get("archive_receipt_id") != receipt_id:
        raise LegacyArchiveError("legacy_repair_predecessor_receipt_id_invalid")
    if public["evidence_mode"] == "source_bundle" and (
        pointer.get("schema_version") == POINTER_SCHEMA_V2
        or receipt.get("schema_version") == RECEIPT_SCHEMA_V2
    ):
        closure_keys = (
            "display_closure_receipt_id",
            "display_closure_receipt_path",
            "display_closure_receipt_sha256",
            "formal_reference_scan_sha256",
            "stable_asset_count",
            "no_display_proof",
        )
        closure_value = pointer.get("display_closure_receipt_path")
        closure_hash = pointer.get("display_closure_receipt_sha256")
        if (
            pointer.get("schema_version") != POINTER_SCHEMA_V2
            or receipt.get("schema_version") != RECEIPT_SCHEMA_V2
            or pointer.get("pending_component") is not None
            or receipt.get("pending_component") is not None
            or any(pointer.get(key) != receipt.get(key) for key in closure_keys)
            or not isinstance(closure_value, str)
            or not isinstance(closure_hash, str)
        ):
            raise LegacyArchiveError(
                "legacy_repair_predecessor_display_binding_invalid"
            )
        closure_relative = safe_relative_path(
            closure_value, "legacy_repair_predecessor_display_closure"
        )
        closure_path = plan["repo"] / closure_relative
        if (
            closure_path.is_symlink()
            or not closure_path.is_file()
            or sha256_file(closure_path) != closure_hash
        ):
            raise LegacyArchiveError(
                "legacy_repair_predecessor_display_closure_invalid"
            )

    locator_value = receipt.get("obsidian_locator_path")
    locator_sha256 = receipt.get("obsidian_locator_sha256")
    if not isinstance(locator_value, str) or not isinstance(locator_sha256, str):
        raise LegacyArchiveError("legacy_repair_predecessor_locator_binding_missing")
    locator_relative = safe_relative_path(locator_value, "legacy_repair_locator")
    locator_path = plan["repo"] / locator_relative
    if (
        locator_path.is_symlink()
        or not locator_path.is_file()
        or sha256_file(locator_path) != locator_sha256
        or pointer.get("obsidian_locator_path") != locator_value
        or pointer.get("obsidian_locator_sha256") != locator_sha256
    ):
        raise LegacyArchiveError("legacy_repair_predecessor_locator_invalid")
    locator_text = locator_path.read_text(encoding="utf-8")

    def locator_scalar(key: str) -> Any:
        match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+)$", locator_text)
        if not match:
            return None
        raw = match.group(1).strip()
        if raw in {"true", "false"}:
            return raw == "true"
        try:
            return json.loads(raw) if raw.startswith(('"', "'")) else raw
        except json.JSONDecodeError:
            return raw.strip("'\"")

    if (
        locator_scalar("package_id") != public["legacy_package_id"]
        or locator_scalar("legacy_package_id") != public["legacy_package_id"]
        or locator_scalar("capture_event_id") != public["capture_event_id"]
        or locator_scalar("evidence_mode") != public["evidence_mode"]
        or locator_scalar("conversation_complete") is not False
        or locator_scalar("canonical_package") is not False
        or locator_scalar("archive_volume") != EXPECTED_VOLUME_NAME
        or locator_scalar("raw_archive_relpath") != public["raw_archive_relpath"]
        or locator_scalar("raw_archive_manifest_sha256")
        != public["raw_archive_manifest_sha256"]
        or locator_scalar("raw_archive_package_sha256")
        != public["raw_archive_package_sha256"]
        or locator_scalar("raw_archive_tree_sha256")
        != public["archive_tree_sha256"]
        or locator_scalar("archive_status") != "verified"
    ):
        raise LegacyArchiveError("legacy_repair_predecessor_locator_semantics_invalid")

    destination = verified_archive_path(
        plan["archive_root"],
        public["raw_archive_relpath"],
        field="legacy_repair_archive_destination",
    )
    if destination.is_symlink() or not destination.is_dir():
        raise LegacyArchiveError("legacy_repair_archive_destination_missing")
    archive_inventory = tree_inventory(destination)
    if (
        archive_inventory != plan["full_inventory"]
        or sha256_value(archive_inventory) != public["archive_tree_sha256"]
    ):
        raise LegacyArchiveError("legacy_repair_archive_tree_mismatch")
    archived_manifest = destination / "manifest.json"
    if (
        archived_manifest.is_symlink()
        or not archived_manifest.is_file()
        or archived_manifest.read_bytes() != plan["manifest_bytes"]
        or sha256_file(archived_manifest) != public["raw_archive_manifest_sha256"]
    ):
        raise LegacyArchiveError("legacy_repair_archive_manifest_mismatch")

    return {
        "predecessor_contract": "verified_legacy_v1_or_v2",
        "authorization": intent["authorization"],
        "intent_id": intent["intent_id"],
        "intent_path": current_intent_path.relative_to(plan["repo"]).as_posix(),
        "intent_sha256": sha256_file(current_intent_path),
        "pointer_schema_version": pointer["schema_version"],
        "pointer_path": pointer_relative,
        "pointer_sha256": sha256_file(pointer_path),
        "receipt_schema_version": receipt["schema_version"],
        "receipt_id": receipt_id,
        "receipt_sha256": sha256_value(receipt),
        "locator_path": locator_value,
        "locator_sha256": locator_sha256,
        "raw_archive_relpath": public["raw_archive_relpath"],
        "raw_archive_manifest_sha256": public["raw_archive_manifest_sha256"],
        "raw_archive_package_sha256": public["raw_archive_package_sha256"],
        "archive_tree_sha256": public["archive_tree_sha256"],
        "cleanup_proof_sha256": sha256_value(plan["cleanup_proof"]),
        "old_surfaces_preserved": True,
        "t9_tree_verified": True,
    }


def build_legacy_display_successor_proof(
    plan: dict[str, Any]
) -> dict[str, Any]:
    public = plan["public"]
    if public["evidence_mode"] == "ledger_only":
        return {
            "state": "not_applicable_ledger_only",
            "formal_reference_scan": None,
            "assets": [],
            "canonical_display_closure": None,
            "historical_display_closures": [],
        }

    display = load_display_assets(plan["repo"])
    scan = display.scan_formal_references(plan["repo"], public["formal_ids"])
    if scan.get("status") != "passed":
        raise LegacyArchiveError("legacy_repair_formal_reference_scan_failed")
    destination = verified_archive_path(
        plan["archive_root"],
        public["raw_archive_relpath"],
        field="legacy_repair_display_archive_destination",
    )
    stable_by_hash: dict[str, list[str]] = {}
    for formal_id in public["formal_ids"]:
        try:
            card = display.formal_card_path(plan["repo"], formal_id)
            card_text = card.read_text(encoding="utf-8")
            refs = display.frontmatter_list(card_text, "lecture_refs")
        except (OSError, UnicodeError, ValueError) as exc:
            raise LegacyArchiveError(
                f"legacy_repair_formal_card_unreadable:{formal_id}:{exc}"
            ) from exc
        for value in refs:
            normalized = value.replace("\\", "/")
            if not normalized.startswith(
                f"错题知识网络/assets/visual_wrong_questions/{formal_id}/"
            ):
                continue
            suffix = Path(normalized.split("#", 1)[0]).suffix.lower()
            if suffix not in DISPLAY_IMAGE_SUFFIXES:
                continue
            try:
                stable = display.safe_repo_path(
                    plan["repo"], normalized, "legacy_repair_stable_asset"
                )
            except ValueError:
                continue
            if stable.is_file():
                stable_by_hash.setdefault(sha256_file(stable), []).append(normalized)

    assets: list[dict[str, Any]] = []
    for item in plan["manifest"].get("payload_files", []):
        if (
            item.get("kind") != "source_artifact"
            or Path(str(item.get("archive_path", ""))).suffix.lower()
            not in DISPLAY_IMAGE_SUFFIXES
        ):
            continue
        archive_relative = safe_relative_path(
            item["archive_path"], "legacy_repair_display_asset"
        )
        archived = destination / archive_relative
        if (
            archived.is_symlink()
            or not archived.is_file()
            or archived.stat().st_size != item["size"]
            or sha256_file(archived) != item["sha256"]
        ):
            raise LegacyArchiveError("legacy_repair_display_archived_asset_mismatch")
        stable_matches = sorted(set(stable_by_hash.get(item["sha256"], [])))
        assets.append(
            {
                "role": item.get("role"),
                "original_path": item["original_path"],
                "archive_path": item["archive_path"],
                "size": item["size"],
                "sha256": item["sha256"],
                "disposition": (
                    "stable_display_verified"
                    if stable_matches
                    else "archived_only_legacy_source"
                ),
                "stable_vault_paths": stable_matches,
            }
        )

    historical: list[dict[str, Any]] = []
    for formal_id in public["formal_ids"]:
        try:
            verified = display.verify_historical_closure_for_formal(
                repo=plan["repo"], formal_id=formal_id
            )
            historical.append({"formal_id": formal_id, "status": "verified", **verified})
        except (OSError, UnicodeError, ValueError) as exc:
            historical.append(
                {"formal_id": formal_id, "status": "unavailable", "error": str(exc)}
            )
    canonical = plan.get("display_closure")
    if canonical is not None:
        state = "canonical_display_closure_verified"
    elif historical and all(row["status"] == "verified" for row in historical):
        state = "historical_display_closure_verified"
    elif not assets:
        state = "explicit_no_display_successor"
    elif all(row["disposition"] == "stable_display_verified" for row in assets):
        state = "stable_display_successor_verified"
    else:
        state = "archived_only_legacy_display_successor"
    return {
        "state": state,
        "formal_reference_scan": scan,
        "assets": assets,
        "canonical_display_closure": canonical,
        "historical_display_closures": historical,
        "claim_boundary": (
            "archived_only means T9 byte preservation, not current Obsidian display"
        ),
    }


def build_legacy_archive_repair_plan(
    *,
    repo: Path,
    capture_id: str,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
    subject_relative_root: Path = DEFAULT_SUBJECT_RELATIVE_ROOT,
) -> dict[str, Any]:
    plan = build_legacy_archive_plan(
        repo=repo,
        capture_id=capture_id,
        archive_root=archive_root,
        subject_relative_root=subject_relative_root,
    )
    validate_volume(plan["archive_root"])
    predecessor = verify_predecessor_archive_surfaces(plan)
    display_proof = build_legacy_display_successor_proof(plan)
    core = {
        "schema_version": REPAIR_RECORD_SCHEMA,
        "operation": "legacy_archive_identity_successor_only",
        "repair_binding": live_repair_binding(plan),
        "predecessor_proof": predecessor,
        "display_successor_proof": display_proof,
        "old_intent_overwritten": False,
        "old_receipt_overwritten": False,
        "old_pointer_overwritten": False,
        "old_locator_overwritten": False,
        "t9_write_count": 0,
        "formal_write_count": 0,
        "formal_actions_invoked": [],
        "status": "verified",
    }
    authorization = REPAIR_AUTHORIZATION_PREFIX + sha256_value(core)
    repair_id = REPAIR_ID_PREFIX + sha256_value(core)[:24]
    public = {
        "schema_version": REPAIR_PREVIEW_SCHEMA,
        "status": "repair_preview",
        "operation": core["operation"],
        "capture_event_id": capture_id,
        "legacy_package_id": plan["public"]["legacy_package_id"],
        "evidence_mode": plan["public"]["evidence_mode"],
        "repair_id": repair_id,
        "repair_path": repair_record_path(plan).relative_to(plan["repo"]).as_posix(),
        "authorization": authorization,
        "apply_ready": True,
        "preview_write_count": 0,
        "predecessor_authorization": predecessor["authorization"],
        "current_unaccepted_authorization": plan["public"]["authorization"],
        "display_successor_state": display_proof["state"],
        "old_surfaces_preserved": True,
        "t9_write_count": 0,
        "formal_write_count": 0,
        "formal_actions_invoked": [],
    }
    return {
        "public": public,
        "record_core": core,
        "authorization": authorization,
        "repair_id": repair_id,
        "repair_path": repair_record_path(plan),
        "legacy_plan": plan,
    }


def validate_recorded_historical_snapshot(
    plan: dict[str, Any], display: Any, row: dict[str, Any]
) -> None:
    """Verify an immutable historical display proof without rebuilding it.

    A later formal intake may legitimately change the card body or metadata.
    Reconstructing the old card preimage from today's card would then turn a
    valid historical proof into a false failure.  The historical supplement is
    content-addressed, so verify its frozen bytes here; live display safety is
    checked separately by the current reference scan and stable-asset hashes.
    """
    formal_id = row.get("formal_id")
    if formal_id not in plan["public"]["formal_ids"]:
        raise LegacyArchiveError(
            "legacy_repair_historical_display_formal_id_invalid"
        )
    relative = row.get("historical_closure_supplement_path")
    expected_sha = row.get("historical_closure_supplement_sha256")
    expected_id = row.get("historical_closure_supplement_id")
    if not isinstance(relative, str) or not isinstance(expected_sha, str):
        raise LegacyArchiveError(
            "legacy_repair_historical_display_snapshot_binding_invalid"
        )
    try:
        path = display.safe_repo_path(
            plan["repo"], relative, "legacy_repair_historical_snapshot"
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise LegacyArchiveError(
            f"legacy_repair_historical_display_snapshot_unreadable:{exc}"
        ) from exc
    if path.is_symlink() or not path.is_file() or sha256_file(path) != expected_sha:
        raise LegacyArchiveError(
            "legacy_repair_historical_display_snapshot_hash_mismatch"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyArchiveError(
            "legacy_repair_historical_display_snapshot_invalid"
        ) from exc
    if (
        not isinstance(document, dict)
        or path.read_bytes() != display.canonical_json_bytes(document)
        or document.get("schema_version") != display.HISTORICAL_SUPPLEMENT_SCHEMA
        or document.get("formal_id") != formal_id
        or document.get("status") != "verified"
        or document.get("canonical_package") is not False
        or document.get("conversation_complete") is not False
    ):
        raise LegacyArchiveError(
            "legacy_repair_historical_display_snapshot_invalid"
        )
    core = {key: value for key, value in document.items() if key != "supplement_id"}
    derived_id = "MATH-DISPLAY-HIST-CLOSE-" + display.sha256_bytes(
        display.canonical_json_bytes(core)
    )[:24]
    if document.get("supplement_id") != derived_id or expected_id != derived_id:
        raise LegacyArchiveError(
            "legacy_repair_historical_display_snapshot_identity_mismatch"
        )
    for row_key, document_key in (
        ("formal_reference_scan_sha256", "formal_reference_scan_sha256"),
        ("stable_asset_count", "stable_asset_count"),
        ("no_display_proof", "no_display_proof"),
        ("pending_component", "pending_component"),
    ):
        if row.get(row_key) != document.get(document_key):
            raise LegacyArchiveError(
                "legacy_repair_historical_display_snapshot_field_mismatch"
            )
    receipt_relative = document.get("repair_receipt_path")
    receipt_sha = document.get("repair_receipt_sha256")
    if not isinstance(receipt_relative, str) or not isinstance(receipt_sha, str):
        raise LegacyArchiveError(
            "legacy_repair_historical_display_receipt_binding_invalid"
        )
    try:
        receipt = display.safe_repo_path(
            plan["repo"], receipt_relative, "legacy_repair_historical_receipt"
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise LegacyArchiveError(
            f"legacy_repair_historical_display_receipt_unreadable:{exc}"
        ) from exc
    if receipt.is_symlink() or not receipt.is_file() or sha256_file(receipt) != receipt_sha:
        raise LegacyArchiveError(
            "legacy_repair_historical_display_receipt_hash_mismatch"
        )


def validate_recorded_display_successor(
    plan: dict[str, Any], proof: dict[str, Any]
) -> None:
    public = plan["public"]
    if public["evidence_mode"] == "ledger_only":
        if (
            proof.get("state") != "not_applicable_ledger_only"
            or proof.get("assets") != []
        ):
            raise LegacyArchiveError("legacy_repair_ledger_only_display_proof_invalid")
        return
    display = load_display_assets(plan["repo"])
    current_scan = display.scan_formal_references(plan["repo"], public["formal_ids"])
    if current_scan.get("status") != "passed":
        raise LegacyArchiveError("legacy_repair_current_formal_reference_scan_failed")
    current_stable_refs = {
        value
        for surface in current_scan.get("surfaces", [])
        if isinstance(surface, dict)
        for value in surface.get("lecture_refs", [])
        if isinstance(value, str)
    }
    recorded_scan = proof.get("formal_reference_scan")
    if not isinstance(recorded_scan, dict) or recorded_scan.get("status") != "passed":
        raise LegacyArchiveError("legacy_repair_recorded_formal_reference_scan_invalid")
    assets = proof.get("assets")
    if not isinstance(assets, list):
        raise LegacyArchiveError("legacy_repair_display_assets_invalid")
    expected = sorted(
        (
            item.get("role"),
            item.get("original_path"),
            item.get("archive_path"),
            item.get("size"),
            item.get("sha256"),
        )
        for item in plan["manifest"].get("payload_files", [])
        if item.get("kind") == "source_artifact"
        and Path(str(item.get("archive_path", ""))).suffix.lower()
        in DISPLAY_IMAGE_SUFFIXES
    )
    recorded = sorted(
        (
            item.get("role"),
            item.get("original_path"),
            item.get("archive_path"),
            item.get("size"),
            item.get("sha256"),
        )
        for item in assets
        if isinstance(item, dict)
    )
    if expected != recorded:
        raise LegacyArchiveError("legacy_repair_display_asset_set_drift")
    destination = verified_archive_path(
        plan["archive_root"],
        public["raw_archive_relpath"],
        field="legacy_repair_verify_display_destination",
    )
    for item in assets:
        disposition = item.get("disposition")
        if disposition not in {
            "stable_display_verified",
            "archived_only_legacy_source",
        }:
            raise LegacyArchiveError("legacy_repair_display_disposition_invalid")
        archived = destination / safe_relative_path(
            item["archive_path"], "legacy_repair_verify_display_asset"
        )
        if (
            archived.is_symlink()
            or not archived.is_file()
            or archived.stat().st_size != item["size"]
            or sha256_file(archived) != item["sha256"]
        ):
            raise LegacyArchiveError("legacy_repair_recorded_archive_asset_mismatch")
        stable_paths = item.get("stable_vault_paths")
        if not isinstance(stable_paths, list) or not all(
            isinstance(value, str) for value in stable_paths
        ):
            raise LegacyArchiveError("legacy_repair_stable_paths_invalid")
        if disposition == "stable_display_verified" and not stable_paths:
            raise LegacyArchiveError("legacy_repair_stable_display_proof_empty")
        for value in stable_paths:
            stable = display.safe_repo_path(
                plan["repo"], value, "legacy_repair_verify_stable_asset"
            )
            if not stable.is_file() or sha256_file(stable) != item["sha256"]:
                raise LegacyArchiveError("legacy_repair_stable_asset_drift")
            if (
                disposition == "stable_display_verified"
                and value not in current_stable_refs
            ):
                raise LegacyArchiveError(
                    "legacy_repair_stable_asset_not_currently_referenced"
                )

    canonical = proof.get("canonical_display_closure")
    if canonical is not None:
        if not isinstance(canonical, dict):
            raise LegacyArchiveError("legacy_repair_canonical_display_proof_invalid")
        try:
            current_canonical = display.verify_closure_for_source(
                repo=plan["repo"],
                manifest_relative=public["source_bundle_manifest_path"],
                expected_manifest_sha256=public["source_bundle_manifest_sha256"],
                expected_package_sha256=None,
                formal_ids=public["formal_ids"],
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise LegacyArchiveError(
                f"legacy_repair_canonical_display_proof_drift:{exc}"
            ) from exc
        if current_canonical != canonical:
            raise LegacyArchiveError("legacy_repair_canonical_display_proof_drift")
    historical = proof.get("historical_display_closures")
    if not isinstance(historical, list):
        raise LegacyArchiveError("legacy_repair_historical_display_proofs_invalid")
    historical_all_verified = bool(historical) and all(
        isinstance(row, dict) and row.get("status") == "verified"
        for row in historical
    )
    if historical_all_verified:
        for row in historical:
            validate_recorded_historical_snapshot(plan, display, row)
    if canonical is not None:
        expected_state = "canonical_display_closure_verified"
    elif historical_all_verified:
        expected_state = "historical_display_closure_verified"
    elif not assets:
        expected_state = "explicit_no_display_successor"
    elif all(
        item.get("disposition") == "stable_display_verified" for item in assets
    ):
        expected_state = "stable_display_successor_verified"
    else:
        expected_state = "archived_only_legacy_display_successor"
    if proof.get("state") != expected_state:
        raise LegacyArchiveError("legacy_repair_display_state_claim_invalid")
    if proof.get("claim_boundary") != (
        "archived_only means T9 byte preservation, not current Obsidian display"
    ):
        raise LegacyArchiveError("legacy_repair_display_claim_boundary_invalid")


def verify_legacy_archive_repair_record(plan: dict[str, Any]) -> dict[str, Any]:
    path = repair_record_path(plan)
    if path.is_symlink() or not path.is_file():
        raise LegacyArchiveError("legacy_archive_repair_successor_missing")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyArchiveError("legacy_archive_repair_successor_invalid") from exc
    if not isinstance(record, dict):
        raise LegacyArchiveError("legacy_archive_repair_successor_invalid")
    record_core = {
        key: value
        for key, value in record.items()
        if key not in {"repair_id", "authorization", "recorded_at"}
    }
    expected_id = REPAIR_ID_PREFIX + sha256_value(record_core)[:24]
    expected_authorization = REPAIR_AUTHORIZATION_PREFIX + sha256_value(record_core)
    if (
        record.get("schema_version") != REPAIR_RECORD_SCHEMA
        or record.get("status") != "verified"
        or record.get("repair_id") != expected_id
        or record.get("authorization") != expected_authorization
        or not isinstance(record.get("recorded_at"), str)
        or not record["recorded_at"]
        or path.read_bytes() != canonical_json_bytes(record)
        or record.get("repair_binding") != live_repair_binding(plan)
    ):
        raise LegacyArchiveError("legacy_archive_repair_successor_binding_invalid")
    predecessor = verify_predecessor_archive_surfaces(plan)
    if record.get("predecessor_proof") != predecessor:
        raise LegacyArchiveError("legacy_archive_repair_predecessor_drift")
    display_proof = record.get("display_successor_proof")
    if not isinstance(display_proof, dict):
        raise LegacyArchiveError("legacy_archive_repair_display_proof_missing")
    validate_recorded_display_successor(plan, display_proof)
    if any(
        record.get(key) is not expected
        for key, expected in (
            ("old_intent_overwritten", False),
            ("old_receipt_overwritten", False),
            ("old_pointer_overwritten", False),
            ("old_locator_overwritten", False),
        )
    ) or record.get("t9_write_count") != 0 or record.get("formal_write_count") != 0:
        raise LegacyArchiveError("legacy_archive_repair_mutation_boundary_invalid")
    return {
        "status": "verified",
        "repair_id": record["repair_id"],
        "repair_path": path.relative_to(plan["repo"]).as_posix(),
        "repair_sha256": sha256_file(path),
        "authorization": record["authorization"],
        "predecessor_intent_id": predecessor["intent_id"],
        "predecessor_receipt_id": predecessor["receipt_id"],
        "display_successor_state": display_proof["state"],
        "legacy_package_id": plan["public"]["legacy_package_id"],
        "capture_event_id": plan["public"]["capture_event_id"],
        "raw_archive_relpath": plan["public"]["raw_archive_relpath"],
        "raw_archive_manifest_sha256": plan["public"][
            "raw_archive_manifest_sha256"
        ],
        "raw_archive_package_sha256": plan["public"][
            "raw_archive_package_sha256"
        ],
        "archive_tree_sha256": plan["public"]["archive_tree_sha256"],
        "obsidian_locator_path": predecessor["locator_path"],
        "local_pointer_path": predecessor["pointer_path"],
        "conversation_complete": False,
        "canonical_package": False,
        "contract_resolution": "successor_repair_without_predecessor_overwrite",
    }


def apply_legacy_archive_repair_plan(repair_plan: dict[str, Any]) -> dict[str, Any]:
    legacy_plan = repair_plan["legacy_plan"]
    with ledger_archive_locks(legacy_plan["repo"]):
        current = build_legacy_archive_repair_plan(
            repo=legacy_plan["repo"],
            capture_id=legacy_plan["public"]["capture_event_id"],
            archive_root=legacy_plan["archive_root"],
            subject_relative_root=legacy_plan["subject_relative_root"],
        )
        if current["authorization"] != repair_plan["authorization"]:
            raise LegacyArchiveError("legacy_repair_authorization_state_drift_under_lock")
        path = current["repair_path"]
        if path.parent.is_symlink():
            raise LegacyArchiveError("legacy_repair_root_symlink_forbidden")
        if path.exists():
            verified = verify_legacy_archive_repair_record(current["legacy_plan"])
            return {
                **verified,
                "status": "noop",
                "old_surfaces_preserved": True,
                "t9_write_count": 0,
                "formal_write_count": 0,
            }
        record = {
            **current["record_core"],
            "repair_id": current["repair_id"],
            "authorization": current["authorization"],
            "recorded_at": now_local(),
        }
        atomic_write(path, canonical_json_bytes(record))
        if path.read_bytes() != canonical_json_bytes(record):
            raise LegacyArchiveError("legacy_archive_repair_successor_reread_failed")
        verified = verify_legacy_archive_repair_record(current["legacy_plan"])
        return {
            **verified,
            "status": "recorded",
            "old_surfaces_preserved": True,
            "t9_write_count": 0,
            "formal_write_count": 0,
        }


def repair_legacy_archive_identity(
    *,
    repo: Path,
    capture_id: str,
    apply: bool = False,
    authorization: str | None = None,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
    subject_relative_root: Path = DEFAULT_SUBJECT_RELATIVE_ROOT,
) -> dict[str, Any]:
    repair_plan = build_legacy_archive_repair_plan(
        repo=repo,
        capture_id=capture_id,
        archive_root=archive_root,
        subject_relative_root=subject_relative_root,
    )
    if not apply:
        if authorization is not None:
            raise LegacyArchiveError("repair_authorization_requires_apply")
        return repair_plan["public"]
    if authorization != repair_plan["authorization"]:
        raise LegacyArchiveError("repair_content_authorization_mismatch")
    return apply_legacy_archive_repair_plan(repair_plan)


def load_or_create_intent(plan: dict[str, Any]) -> dict[str, Any]:
    identity = intent_identity(plan)
    intent_id = "MATH-LEGACY-ARCHIVE-INTENT-" + sha256_value(identity)[:24]
    path = intent_path(plan)
    if path.exists():
        try:
            intent = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LegacyArchiveError("legacy_archive_intent_invalid") from exc
    else:
        intent = {
            "schema_version": INTENT_SCHEMA,
            "intent_id": intent_id,
            "archive_verified_at": now_local(),
            **identity,
        }
        atomic_write(path, canonical_json_bytes(intent))
    if (
        not isinstance(intent, dict)
        or intent.get("schema_version") != INTENT_SCHEMA
        or intent.get("intent_id") != intent_id
        or any(intent.get(key) != value for key, value in identity.items())
        or not isinstance(intent.get("archive_verified_at"), str)
        or not intent["archive_verified_at"]
        or json.loads(path.read_text(encoding="utf-8")) != intent
    ):
        raise LegacyArchiveError("legacy_archive_intent_identity_mismatch")
    return intent


def write_staging_tree(staging: Path, plan: dict[str, Any]) -> None:
    staging_relative = staging.relative_to(plan["archive_root"])
    verified_staging = verified_archive_path(
        plan["archive_root"], staging_relative, field="archive_staging"
    )
    if verified_staging != staging or staging.is_symlink() or not staging.is_dir():
        raise LegacyArchiveError("archive_staging_identity_invalid")
    manifest_path = verified_staging / "manifest.json"
    ledger_path = verified_staging / "ledger-events.jsonl"
    manifest_path.write_bytes(plan["manifest_bytes"])
    ledger_path.write_bytes(plan["ledger_bytes"])
    for archive_path, source_path in plan["source_paths"].items():
        relative = safe_relative_path(archive_path, "archive_payload_path")
        destination = verified_staging / relative
        if verified_staging not in destination.resolve(strict=False).parents:
            raise LegacyArchiveError("archive_payload_path_escapes_staging")
        destination.parent.mkdir(parents=True, exist_ok=True)
        current = verified_staging
        for part in relative.parent.parts:
            current = current / part
            if current.is_symlink() or not current.is_dir():
                raise LegacyArchiveError("archive_staging_parent_invalid")
        shutil.copy2(source_path, destination)
    if tree_inventory(verified_staging) != plan["full_inventory"]:
        raise LegacyArchiveError("archive_stage_tree_verify_failed")


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def locator_note_bytes(plan: dict[str, Any], verified_at: str) -> bytes:
    public = plan["public"]
    formal_lines = (
        ["formal_ids: []"]
        if not public["formal_ids"]
        else [
            "formal_ids:",
            *[f"  - {yaml_quote(item)}" for item in public["formal_ids"]],
        ]
    )
    lines = [
        "---",
        f"type: {LOCATOR_TYPE}",
        "subject: math",
        f"package_id: {yaml_quote(public['legacy_package_id'])}",
        f"legacy_package_id: {yaml_quote(public['legacy_package_id'])}",
        f"package_schema: {PACKAGE_SCHEMA}",
        f"capture_event_id: {yaml_quote(public['capture_event_id'])}",
        *formal_lines,
        *(
            []
            if plan["legacy_receipt_contract"]
            else [
                "retrieval_keys:",
                *[
                    f"  - {yaml_quote(item)}"
                    for item in sorted(
                        set(
                            [
                                public["legacy_package_id"],
                                public["capture_event_id"],
                                public["study_date"],
                                public.get("source_bundle_manifest_path") or "",
                                *public["formal_ids"],
                            ]
                        )
                        - {""}
                    )
                ],
            ]
        ),
        f"evidence_mode: {public['evidence_mode']}",
        "conversation_complete: false",
        "canonical_package: false",
        "archive_volume: T9-Data",
        f"raw_archive_relpath: {yaml_quote(public['raw_archive_relpath'])}",
        f"raw_archive_manifest_sha256: {public['raw_archive_manifest_sha256']}",
        f"raw_archive_package_sha256: {public['raw_archive_package_sha256']}",
        f"raw_archive_tree_sha256: {public['archive_tree_sha256']}",
        f"archive_verified_at: {yaml_quote(verified_at)}",
        "archive_status: verified",
        "---",
        "",
        f"历史证据包 `{public['legacy_package_id']}` 已逐文件归档并验证。",
        "",
        "该记录不是完整会话包；未补造任何对话 turn。",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def locator_relative_path(plan: dict[str, Any]) -> Path:
    return LOCATOR_RELATIVE_ROOT / f"{plan['public']['legacy_package_id']}.md"


def build_receipt(
    plan: dict[str, Any], intent: dict[str, Any], locator_sha256: str
) -> dict[str, Any]:
    public = plan["public"]
    identity = {
        "authorization": public["authorization"],
        "legacy_package_id": public["legacy_package_id"],
        "capture_event_id": public["capture_event_id"],
        "closeout_id": public["closeout_id"],
        "archive_intent_id": intent["intent_id"],
        "raw_archive_manifest_sha256": public["raw_archive_manifest_sha256"],
        "raw_archive_package_sha256": public["raw_archive_package_sha256"],
        "archive_tree_sha256": public["archive_tree_sha256"],
        "obsidian_locator_sha256": locator_sha256,
    }
    receipt_id = "MATH-LEGACY-ARCHIVE-" + sha256_value(identity)[:24]
    receipt = {
        "schema_version": (
            RECEIPT_SCHEMA if plan["legacy_receipt_contract"] else RECEIPT_SCHEMA_V2
        ),
        "receipt_id": receipt_id,
        "authorization": public["authorization"],
        "legacy_package_id": public["legacy_package_id"],
        "capture_event_id": public["capture_event_id"],
        "freeze_id": public["freeze_id"],
        "closeout_id": public["closeout_id"],
        "formal_ids": public["formal_ids"],
        "terminal_outcome": public["terminal_outcome"],
        "evidence_mode": public["evidence_mode"],
        "conversation_complete": False,
        "canonical_package": False,
        "archive_intent_id": intent["intent_id"],
        "archive_volume": EXPECTED_VOLUME_NAME,
        "raw_archive_relpath": public["raw_archive_relpath"],
        "raw_archive_manifest_sha256": public["raw_archive_manifest_sha256"],
        "raw_archive_package_sha256": public["raw_archive_package_sha256"],
        "archive_tree_sha256": public["archive_tree_sha256"],
        "archive_verified_at": intent["archive_verified_at"],
        "archive_status": "verified",
        "obsidian_locator_path": locator_relative_path(plan).as_posix(),
        "obsidian_locator_sha256": locator_sha256,
        "obsidian_path_status": "verified",
        "source_bundle_manifest_path": public["source_bundle_manifest_path"],
        "source_bundle_manifest_sha256": public["source_bundle_manifest_sha256"],
        "cleanup_proof": plan["cleanup_proof"],
        "formal_write_count": 0,
        "formal_actions_invoked": [],
    }
    if not plan["legacy_receipt_contract"]:
        receipt.update(
            {
                **(plan["display_closure"] or {}),
                "pending_component": None,
            }
        )
    if not plan["legacy_receipt_contract"]:
        receipt["local_pointer_path"] = public["local_pointer_path"]
    return receipt


def build_pointer(
    plan: dict[str, Any], intent: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    public = plan["public"]
    pointer = {
        "schema_version": (
            POINTER_SCHEMA if plan["legacy_receipt_contract"] else POINTER_SCHEMA_V2
        ),
        "legacy_package_id": public["legacy_package_id"],
        "capture_event_id": public["capture_event_id"],
        "freeze_id": public["freeze_id"],
        "closeout_id": public["closeout_id"],
        "formal_ids": public["formal_ids"],
        "terminal_outcome": public["terminal_outcome"],
        "evidence_mode": public["evidence_mode"],
        "conversation_complete": False,
        "canonical_package": False,
        "archive_volume": EXPECTED_VOLUME_NAME,
        "raw_archive_relpath": public["raw_archive_relpath"],
        "raw_archive_manifest_sha256": public["raw_archive_manifest_sha256"],
        "raw_archive_package_sha256": public["raw_archive_package_sha256"],
        "archive_tree_sha256": public["archive_tree_sha256"],
        "archive_receipt_id": receipt["receipt_id"],
        "archive_intent_id": intent["intent_id"],
        "obsidian_locator_path": receipt["obsidian_locator_path"],
        "obsidian_locator_sha256": receipt["obsidian_locator_sha256"],
        "source_bundle_manifest_path": public["source_bundle_manifest_path"],
        "source_bundle_manifest_sha256": public["source_bundle_manifest_sha256"],
        "cleanup_proof": plan["cleanup_proof"],
        "archive_status": "verified",
        "cleanup_intent": (
            "remove_local_source_artifacts_after_verified_legacy_archive_locator_receipt"
            if public["evidence_mode"] == "source_bundle"
            else "none_ledger_only"
        ),
        "authorization": public["authorization"],
    }
    if not plan["legacy_receipt_contract"]:
        pointer.update(
            {
                **(plan["display_closure"] or {}),
                "pending_component": None,
            }
        )
    if plan["pointer_contract"] != "legacy_single_v1":
        pointer["local_pointer_path"] = public["local_pointer_path"]
    return pointer


def recompute_cleanup_proof(plan: dict[str, Any]) -> dict[str, Any]:
    quick = load_quick_intake(plan["repo"], plan["archive_root"])
    events = quick.load_jsonl(plan["repo"] / LEDGER_RELATIVE_PATH)
    state = quick.replay(events)
    source_bundle = None
    if plan["public"]["evidence_mode"] == "source_bundle":
        source_bundle = {
            "manifest_path": plan["public"]["source_bundle_manifest_path"],
            "manifest_sha256": plan["public"]["source_bundle_manifest_sha256"],
        }
    return build_cleanup_proof(
        quick=quick,
        state=state,
        target_capture_id=plan["public"]["capture_event_id"],
        source_bundle=source_bundle,
        cleanup_candidates=plan["cleanup_candidates"],
    )


def cleanup_local_source_artifacts(
    plan: dict[str, Any], pointer: dict[str, Any]
) -> dict[str, Any]:
    if plan["legacy_receipt_contract"]:
        # Old receipts cannot authorize new deletion. Shared/unprovable bytes
        # can still be verified and retained while finishing a pointer-only retry.
        current_proof = recompute_cleanup_proof(plan)
        if current_proof != plan["cleanup_proof"] or pointer.get("cleanup_proof") != current_proof:
            raise LegacyArchiveError("cleanup_reference_proof_drift")
        proof_by_path = {row["path"]: row for row in current_proof["items"]}
        retained = []
        missing = []
        for row in plan["cleanup_candidates"]:
            proof = proof_by_path.get(row["path"])
            if not isinstance(proof, dict):
                raise LegacyArchiveError("cleanup_pointer_coverage_missing")
            path = plan["repo"] / row["path"]
            if proof["decision"] == "delete_exclusive_reference":
                if path.exists() or path.is_symlink():
                    raise LegacyArchiveError("old_contract_pointer_cannot_authorize_new_cleanup")
                missing.append(row["path"])
                continue
            if not path.is_file() or path.is_symlink():
                raise LegacyArchiveError("retained_source_artifact_missing_or_invalid")
            if path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
                raise LegacyArchiveError("retained_source_artifact_hash_drift")
            retained.append({"path": row["path"], "reason": proof["decision"]})
        return {
            "proof": current_proof,
            "deleted_paths": [],
            "retained": retained,
            "already_missing_exclusive_paths": missing,
        }
    display = load_display_assets(plan["repo"])
    public = plan["public"]
    try:
        current_display = display.verify_closure_for_source(
            repo=plan["repo"],
            manifest_relative=public["source_bundle_manifest_path"],
            expected_manifest_sha256=public["source_bundle_manifest_sha256"],
            expected_package_sha256=None,
            formal_ids=public["formal_ids"],
        )
    except ValueError as exc:
        raise LegacyArchiveError(f"display_asset_closure_required:{exc}") from exc
    if current_display != plan["display_closure"] or any(
        pointer.get(key) != current_display[key]
        for key in (
            "display_closure_receipt_id",
            "display_closure_receipt_sha256",
            "formal_reference_scan_sha256",
            "stable_asset_count",
            "no_display_proof",
        )
    ):
        raise LegacyArchiveError("display_closure_drift_before_cleanup")
    current_proof = recompute_cleanup_proof(plan)
    if current_proof != plan["cleanup_proof"] or pointer.get("cleanup_proof") != current_proof:
        raise LegacyArchiveError("cleanup_reference_proof_drift")
    deleted: list[str] = []
    retained: list[dict[str, str]] = []
    missing: list[str] = []
    proof_by_path = {row["path"]: row for row in current_proof["items"]}
    for row in plan["cleanup_candidates"]:
        proof = proof_by_path.get(row["path"])
        if not isinstance(proof, dict):
            raise LegacyArchiveError("cleanup_pointer_coverage_missing")
        path = plan["repo"] / row["path"]
        if proof["decision"] != "delete_exclusive_reference":
            if not path.is_file() or path.is_symlink():
                raise LegacyArchiveError("retained_source_artifact_missing_or_invalid")
            if path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
                raise LegacyArchiveError("retained_source_artifact_hash_drift")
            retained.append({"path": row["path"], "reason": proof["decision"]})
            continue
        if not path.exists():
            missing.append(row["path"])
            continue
        if path.is_symlink() or not path.is_file():
            raise LegacyArchiveError("local_source_artifact_cleanup_target_invalid")
        if path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise LegacyArchiveError("local_source_artifact_cleanup_hash_drift")
        path.unlink()
        deleted.append(row["path"])
    return {
        "proof": current_proof,
        "deleted_paths": deleted,
        "retained": retained,
        "already_missing_exclusive_paths": missing,
    }


@contextmanager
def ledger_archive_locks(repo: Path):
    lock_paths = [
        repo / "数学一回滚复习系统/.快速入库事件.jsonl.lock",
        repo / LOCK_RELATIVE_PATH,
    ]
    descriptors: list[int] = []
    try:
        for path in lock_paths:
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            descriptors.append(descriptor)
        yield
    finally:
        for descriptor in reversed(descriptors):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def selected_raw_line_fingerprints(plan: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (row["event_id"], row["raw_line_sha256"])
        for row in plan["manifest"]["ledger_events"]
    ]


def _apply_legacy_archive_plan_locked(plan: dict[str, Any]) -> dict[str, Any]:
    public = plan["public"]
    if (
        public["evidence_mode"] == "source_bundle"
        and plan["display_closure"] is None
        and not plan["legacy_receipt_contract"]
    ):
        raise LegacyArchiveError("display_asset_closure_required_before_legacy_archive")
    validate_volume(plan["archive_root"])
    destination = verified_archive_path(
        plan["archive_root"],
        public["raw_archive_relpath"],
        field="archive_destination",
    )
    intent = load_or_create_intent(plan)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (
        verified_archive_path(
            plan["archive_root"],
            public["raw_archive_relpath"],
            field="archive_destination",
        )
        != destination
    ):
        raise LegacyArchiveError("archive_destination_identity_changed")
    status = "recorded"
    if destination.is_symlink():
        raise LegacyArchiveError("archive_destination_symlink_forbidden")
    if destination.exists():
        if not destination.is_dir() or tree_inventory(destination) != plan["full_inventory"]:
            raise LegacyArchiveError("archive_destination_conflict")
        status = "noop"
    else:
        staging_parent_relative = destination.parent.relative_to(plan["archive_root"])
        if (
            verified_archive_path(
                plan["archive_root"],
                staging_parent_relative,
                field="archive_staging_parent",
            )
            != destination.parent
        ):
            raise LegacyArchiveError("archive_staging_parent_identity_changed")
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{public['legacy_package_id']}.", dir=destination.parent
            )
        )
        try:
            staging_relative = staging.relative_to(plan["archive_root"])
            if (
                verified_archive_path(
                    plan["archive_root"], staging_relative, field="archive_staging"
                )
                != staging
            ):
                raise LegacyArchiveError("archive_staging_escaped_t9")
            write_staging_tree(staging, plan)
            if destination.is_symlink() or destination.exists():
                raise LegacyArchiveError("archive_destination_changed_before_publish")
            os.replace(staging, destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    archive_inventory = tree_inventory(destination)
    if archive_inventory != plan["full_inventory"]:
        raise LegacyArchiveError("archive_final_tree_verify_failed")
    manifest_path = destination / "manifest.json"
    if (
        sha256_file(manifest_path) != public["raw_archive_manifest_sha256"]
        or json.loads(manifest_path.read_text(encoding="utf-8")) != plan["manifest"]
        or sha256_value(archive_inventory) != public["archive_tree_sha256"]
    ):
        raise LegacyArchiveError("archive_final_manifest_or_tree_verify_failed")

    verified_at = intent["archive_verified_at"]
    locator_relative = locator_relative_path(plan)
    locator_path = plan["repo"] / locator_relative
    locator_bytes = locator_note_bytes(plan, verified_at)
    if locator_path.exists():
        if locator_path.read_bytes() != locator_bytes:
            raise LegacyArchiveError("obsidian_legacy_locator_conflict")
    else:
        atomic_write(locator_path, locator_bytes)
    if locator_path.read_bytes() != locator_bytes:
        raise LegacyArchiveError("obsidian_legacy_locator_reread_failed")
    locator_sha256 = sha256_bytes(locator_bytes)
    receipt = build_receipt(plan, intent, locator_sha256)
    receipt_id = receipt["receipt_id"]
    receipts_path = plan["repo"] / RECEIPTS_RELATIVE_PATH
    existing = [
        row for row in load_receipts(receipts_path) if row.get("receipt_id") == receipt_id
    ]
    if existing:
        if existing != [receipt]:
            raise LegacyArchiveError("legacy_archive_receipt_conflict")
        status = "noop"
    else:
        append_receipt(receipts_path, receipt)
    reread = [
        row for row in load_receipts(receipts_path) if row.get("receipt_id") == receipt_id
    ]
    if reread != [receipt]:
        raise LegacyArchiveError("legacy_archive_receipt_reread_failed")

    pointer = build_pointer(plan, intent, receipt)
    pointer_bytes = canonical_json_bytes(pointer)
    pointer_path = plan["pointer_path"]
    if pointer_path.exists():
        if pointer_path.read_bytes() != pointer_bytes:
            raise LegacyArchiveError("legacy_archive_pointer_conflict")
    else:
        atomic_write(pointer_path, pointer_bytes)
    if pointer_path.read_bytes() != pointer_bytes:
        raise LegacyArchiveError("legacy_archive_pointer_reread_failed")
    if public["evidence_mode"] == "source_bundle":
        cleanup_report = cleanup_local_source_artifacts(plan, pointer)
        if cleanup_report["retained"]:
            cleanup_state = "source_artifacts_retained_by_reference_gate"
        else:
            cleanup_state = "source_artifacts_removed_manifest_and_pointer_preserved"
    else:
        cleanup_report = {
            "proof": plan["cleanup_proof"],
            "deleted_paths": [],
            "retained": [],
            "already_missing_exclusive_paths": [],
        }
        cleanup_state = "not_applicable_ledger_only"
    return {
        "status": status,
        **receipt,
        "local_pointer_path": str(pointer_path.relative_to(plan["repo"])),
        "local_cleanup": cleanup_state,
        "local_cleanup_report": cleanup_report,
    }


def _verify_completed_legacy_archive_current_contract(
    *,
    repo: Path,
    capture_id: str,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
    subject_relative_root: Path = DEFAULT_SUBJECT_RELATIVE_ROOT,
) -> dict[str, Any]:
    """Strictly rederive and verify every completion surface without writing."""
    plan = build_legacy_archive_plan(
        repo=repo,
        capture_id=capture_id,
        archive_root=archive_root,
        subject_relative_root=subject_relative_root,
    )
    public = plan["public"]
    current_intent_path = intent_path(plan)
    if current_intent_path.is_symlink() or not current_intent_path.is_file():
        raise LegacyArchiveError("legacy_archive_intent_missing")
    try:
        intent = json.loads(current_intent_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyArchiveError("legacy_archive_intent_invalid") from exc
    identity = intent_identity(plan)
    expected_intent_id = "MATH-LEGACY-ARCHIVE-INTENT-" + sha256_value(identity)[:24]
    expected_intent_fields = {
        "schema_version",
        "intent_id",
        "archive_verified_at",
        *identity.keys(),
    }
    if (
        not isinstance(intent, dict)
        or set(intent) != expected_intent_fields
        or intent.get("schema_version") != INTENT_SCHEMA
        or intent.get("intent_id") != expected_intent_id
        or any(intent.get(key) != value for key, value in identity.items())
        or not isinstance(intent.get("archive_verified_at"), str)
        or not intent["archive_verified_at"]
        or current_intent_path.read_bytes() != canonical_json_bytes(intent)
    ):
        raise LegacyArchiveError("legacy_archive_intent_identity_mismatch")

    destination = verified_archive_path(
        plan["archive_root"], public["raw_archive_relpath"], field="archive_destination"
    )
    if destination.is_symlink() or not destination.is_dir():
        raise LegacyArchiveError("legacy_archive_destination_missing")
    inventory = tree_inventory(destination)
    if inventory != plan["full_inventory"] or sha256_value(inventory) != public[
        "archive_tree_sha256"
    ]:
        raise LegacyArchiveError("legacy_archive_tree_mismatch")
    archived_manifest = destination / "manifest.json"
    if (
        archived_manifest.is_symlink()
        or archived_manifest.read_bytes() != plan["manifest_bytes"]
        or sha256_file(archived_manifest) != public["raw_archive_manifest_sha256"]
    ):
        raise LegacyArchiveError("legacy_archive_manifest_mismatch")

    locator_path = plan["repo"] / locator_relative_path(plan)
    locator_bytes = locator_note_bytes(plan, intent["archive_verified_at"])
    if (
        locator_path.is_symlink()
        or not locator_path.is_file()
        or locator_path.read_bytes() != locator_bytes
    ):
        raise LegacyArchiveError("legacy_archive_locator_mismatch")
    locator_sha256 = sha256_bytes(locator_bytes)
    expected_receipt = build_receipt(plan, intent, locator_sha256)
    receipts_path = plan["repo"] / RECEIPTS_RELATIVE_PATH
    if receipts_path.is_symlink():
        raise LegacyArchiveError("legacy_archive_receipt_ledger_symlink_forbidden")
    matching = [
        row
        for row in load_receipts(receipts_path)
        if row.get("receipt_id") == expected_receipt["receipt_id"]
    ]
    if matching != [expected_receipt]:
        raise LegacyArchiveError("legacy_archive_receipt_mismatch")

    pointer_path = plan["pointer_path"]
    expected_pointer = build_pointer(plan, intent, expected_receipt)
    if (
        pointer_path.is_symlink()
        or not pointer_path.is_file()
        or pointer_path.read_bytes() != canonical_json_bytes(expected_pointer)
    ):
        raise LegacyArchiveError("legacy_archive_pointer_mismatch")
    return {
        "status": "verified",
        "legacy_package_id": public["legacy_package_id"],
        "capture_event_id": public["capture_event_id"],
        "authorization": public["authorization"],
        "archive_intent_id": intent["intent_id"],
        "archive_receipt_id": expected_receipt["receipt_id"],
        "raw_archive_relpath": public["raw_archive_relpath"],
        "raw_archive_manifest_sha256": public["raw_archive_manifest_sha256"],
        "raw_archive_package_sha256": public["raw_archive_package_sha256"],
        "archive_tree_sha256": public["archive_tree_sha256"],
        "obsidian_locator_path": expected_receipt["obsidian_locator_path"],
        "local_pointer_path": public["local_pointer_path"],
        "conversation_complete": False,
        "canonical_package": False,
    }


def verify_completed_legacy_archive(
    *,
    repo: Path,
    capture_id: str,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
    subject_relative_root: Path = DEFAULT_SUBJECT_RELATIVE_ROOT,
) -> dict[str, Any]:
    """Verify the current contract, then an explicit immutable successor.

    The successor path is consulted only after the ordinary strict contract
    fails.  It never edits or weakens the predecessor surfaces; it proves their
    exact bytes and the live named T9 tree again.
    """
    try:
        return _verify_completed_legacy_archive_current_contract(
            repo=repo,
            capture_id=capture_id,
            archive_root=archive_root,
            subject_relative_root=subject_relative_root,
        )
    except (LegacyArchiveError, OSError, ValueError, json.JSONDecodeError) as exc:
        original_error = str(exc)
    plan = build_legacy_archive_plan(
        repo=repo,
        capture_id=capture_id,
        archive_root=archive_root,
        subject_relative_root=subject_relative_root,
    )
    path = repair_record_path(plan)
    if not path.is_file() or path.is_symlink():
        raise LegacyArchiveError(original_error)
    repaired = verify_legacy_archive_repair_record(plan)
    return {
        **repaired,
        "predecessor_strict_error": original_error,
    }


def apply_legacy_archive_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Lock ledger and archive, rederive authorization, then permit the first write."""
    with ledger_archive_locks(plan["repo"]):
        current = build_legacy_archive_plan(
            repo=plan["repo"],
            capture_id=plan["public"]["capture_event_id"],
            archive_root=plan["archive_root"],
            subject_relative_root=plan["subject_relative_root"],
        )
        if (
            current["public"]["authorization"] != plan["public"]["authorization"]
            or selected_raw_line_fingerprints(current)
            != selected_raw_line_fingerprints(plan)
        ):
            raise LegacyArchiveError("authorization_state_drift_under_lock")
        return _apply_legacy_archive_plan_locked(current)


def archive_legacy_evidence(
    *,
    repo: Path,
    capture_id: str,
    apply: bool = False,
    authorization: str | None = None,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
    subject_relative_root: Path = DEFAULT_SUBJECT_RELATIVE_ROOT,
) -> dict[str, Any]:
    plan = build_legacy_archive_plan(
        repo=repo,
        capture_id=capture_id,
        archive_root=archive_root,
        subject_relative_root=subject_relative_root,
    )
    if not apply:
        if authorization is not None:
            raise LegacyArchiveError("authorization_requires_apply")
        return plan["public"]
    if authorization != plan["public"]["authorization"]:
        raise LegacyArchiveError("content_authorization_mismatch")
    return apply_legacy_archive_plan(plan)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="预览或归档已正式收口但没有完整会话包的数学历史证据"
    )
    value.add_argument("--repo", required=True)
    value.add_argument("--capture-id", required=True)
    value.add_argument(
        "--repair-identity",
        action="store_true",
        help="只建立旧归档合同的 successor 修复证明；不覆盖旧证据或写 T9",
    )
    value.add_argument("--apply", action="store_true")
    value.add_argument("--authorization")
    value.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    value.add_argument(
        "--subject-relative-root", default=str(DEFAULT_SUBJECT_RELATIVE_ROOT)
    )
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.apply and not args.authorization:
            raise LegacyArchiveError("apply_requires_exact_content_authorization")
        if args.repair_identity:
            result = repair_legacy_archive_identity(
                repo=Path(args.repo),
                capture_id=args.capture_id,
                apply=args.apply,
                authorization=args.authorization,
                archive_root=Path(args.archive_root),
                subject_relative_root=Path(args.subject_relative_root),
            )
        else:
            result = archive_legacy_evidence(
                repo=Path(args.repo),
                capture_id=args.capture_id,
                apply=args.apply,
                authorization=args.authorization,
                archive_root=Path(args.archive_root),
                subject_relative_root=Path(args.subject_relative_root),
            )
    except (LegacyArchiveError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            canonical_json(
                {"status": "error", "error_code": str(exc), "formal_write_count": 0}
            )
        )
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
