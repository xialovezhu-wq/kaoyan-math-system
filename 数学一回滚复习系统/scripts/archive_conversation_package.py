#!/usr/bin/env python3
"""Archive one closed math conversation package to the verified T9 volume."""

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
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
QUICK_INTAKE_PATH = REPO_ROOT / "数学一回滚复习系统/scripts/quick_intake.py"
DISPLAY_ASSETS_PATH = REPO_ROOT / "数学一回滚复习系统/scripts/display_assets.py"
DEFAULT_ARCHIVE_ROOT = Path("/Volumes/T9-Data")
DEFAULT_SUBJECT_RELATIVE_ROOT = Path("03_数学/资料库/原始会话资料")
SENTINEL_RELATIVE_PATH = Path("00_迁移管理/状态/volume-sentinel.json")
SENTINEL_SHA256 = "f086b32b29b2b38f1a28dffb8fde4fa850078332d8a23ae269cc8e857a6bd2ca"
EXPECTED_VOLUME_NAME = "T9-Data"
EXPECTED_VOLUME_UUID = "00000000-0000-0000-0000-000000000000"
RECEIPT_SCHEMA = "math-conversation-package-archive-receipt-v1"
POINTER_SCHEMA = "math-conversation-package-archive-pointer-v1"
RECEIPT_SCHEMA_V2 = "math-conversation-package-archive-receipt-v2"
POINTER_SCHEMA_V2 = "math-conversation-package-archive-pointer-v2"
RECEIPTS_PATH = REPO_ROOT / "数学一回滚复习系统/原始会话归档回执.jsonl"
INTENT_ROOT = REPO_ROOT / "数学一回滚复习系统/原始会话归档意图"
LOCK_PATH = REPO_ROOT / "数学一回滚复习系统/.原始会话归档.lock"
LOCATOR_ROOT = REPO_ROOT / "错题知识网络/wiki/sources/raw_archives"
FORMAL_ID_RE = re.compile(r"^(?:GS|LA|PR)-\d{3,}$")
ARCHIVABLE_TERMINAL_OUTCOMES = {
    "curated",
    "created",
    "updated",
    "already_current",
    "skip",
    "noop",
    "duplicate",
}
INCOMPLETE_TERMINAL_OUTCOMES = {"needs_user", "failed"}


class ArchiveError(ValueError):
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


def now_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_quick_intake(repo: Path) -> Any:
    path = repo / "数学一回滚复习系统/scripts/quick_intake.py"
    spec = importlib.util.spec_from_file_location("math_archive_quick_intake", path)
    if spec is None or spec.loader is None:
        raise ArchiveError("quick_intake_import_invalid")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO_ROOT = repo
    module.ROOT = repo / "数学一回滚复习系统"
    module.SOURCE_STAGING_ROOT = module.ROOT / "快速入库来源"
    module.EVENTS_PATH = module.ROOT / "快速入库事件.jsonl"
    module.ARCHIVE_ROOT = DEFAULT_ARCHIVE_ROOT
    module.ARCHIVE_SENTINEL_PATH = DEFAULT_ARCHIVE_ROOT / SENTINEL_RELATIVE_PATH
    module.ARCHIVE_SENTINEL_SHA256 = SENTINEL_SHA256
    module.ARCHIVE_VOLUME_UUID = EXPECTED_VOLUME_UUID
    return module


def load_display_assets(repo: Path) -> Any:
    path = repo / "数学一回滚复习系统/scripts/display_assets.py"
    spec = importlib.util.spec_from_file_location("math_archive_display_assets", path)
    if spec is None or spec.loader is None:
        raise ArchiveError("display_assets_import_invalid")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def validate_formal_commit(
    quick: Any,
    manifest_relative: str,
    closeout_id: str,
    formal_ids: list[str],
    requested_terminal_outcome: str,
) -> tuple[list[str], list[str], str, str]:
    state = quick.replay(quick.load_jsonl(quick.EVENTS_PATH))
    closeout = state.get("closeouts", {}).get(closeout_id)
    if closeout is None or closeout_id in state.get("invalidated_closeouts", set()):
        raise ArchiveError("formal_closeout_not_committed")
    capture_ids = sorted(
        capture_id
        for capture_id, capture in state["captures"].items()
        if isinstance(capture.get("source_bundle"), dict)
        and capture["source_bundle"].get("manifest_path") == manifest_relative
    )
    if not capture_ids or any(state["closed_by"].get(item) != closeout_id for item in capture_ids):
        raise ArchiveError("package_capture_not_closed_by_requested_closeout")
    relevant_results = [
        row
        for row in closeout.get("capture_results", [])
        if isinstance(row, dict) and row.get("capture_event_id") in capture_ids
    ]
    if len(relevant_results) != len(capture_ids):
        raise ArchiveError("closeout_capture_results_incomplete")
    result_formal_ids = sorted(
        {
            row.get("formal_id")
            for row in relevant_results
            if isinstance(row.get("formal_id"), str)
        }
    )
    if result_formal_ids and not formal_ids:
        raise ArchiveError("formal_ids_required_for_closeout_mapping")
    if formal_ids != result_formal_ids:
        raise ArchiveError("formal_ids_do_not_match_closeout")
    raw_outcomes = [row.get("terminal_outcome", row.get("outcome")) for row in relevant_results]
    if any(item in INCOMPLETE_TERMINAL_OUTCOMES for item in raw_outcomes):
        raise ArchiveError("terminal_outcome_not_archivable")
    if len(set(raw_outcomes)) == 1 and raw_outcomes[0] in ARCHIVABLE_TERMINAL_OUTCOMES:
        actual_terminal_outcome = str(raw_outcomes[0])
    else:
        formal_results = {
            row.get("formal_id"): row
            for row in closeout.get("formal_results", [])
            if isinstance(row, dict) and isinstance(row.get("formal_id"), str)
        }
        operations = [
            formal_results[formal_id].get("operation")
            for formal_id in result_formal_ids
            if formal_id in formal_results
        ]
        if operations and len(operations) != len(result_formal_ids):
            raise ArchiveError("closeout_formal_results_incomplete")
        if operations and set(operations) == {"created"}:
            actual_terminal_outcome = "created"
        elif operations and set(operations) == {"updated"}:
            actual_terminal_outcome = "updated"
        elif operations and set(operations) == {"unchanged"}:
            actual_terminal_outcome = (
                "already_current"
                if set(raw_outcomes) == {"representation_already_current"}
                else "curated"
            )
        elif not operations and not result_formal_ids:
            actual_terminal_outcome = "curated"
        else:
            actual_terminal_outcome = "curated"
    if requested_terminal_outcome != actual_terminal_outcome:
        raise ArchiveError("terminal_outcome_does_not_match_closeout")
    closed_at = closeout.get("closed_at")
    if not isinstance(closed_at, str) or not closed_at.strip():
        raise ArchiveError("closeout_closed_at_missing")
    return capture_ids, result_formal_ids, actual_terminal_outcome, closed_at


def validate_volume(archive_root: Path) -> dict[str, Any]:
    root = archive_root.resolve(strict=True)
    if root != DEFAULT_ARCHIVE_ROOT.resolve(strict=True):
        raise ArchiveError("archive_root_must_be_exact_t9_data")
    if Path("/Volumes/T9-Data 1").exists():
        raise ArchiveError("ambiguous_t9_mount_suffix_present")
    sentinel_path = root / SENTINEL_RELATIVE_PATH
    if not sentinel_path.is_file() or sha256_file(sentinel_path) != SENTINEL_SHA256:
        raise ArchiveError("volume_sentinel_sha256_mismatch")
    try:
        sentinel = json.loads(sentinel_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchiveError("volume_sentinel_invalid") from exc
    if (
        sentinel.get("volume_name") != EXPECTED_VOLUME_NAME
        or sentinel.get("volume_uuid") != EXPECTED_VOLUME_UUID
        or Path(str(sentinel.get("expected_mount_point"))).resolve(strict=True) != root
    ):
        raise ArchiveError("volume_sentinel_identity_mismatch")
    return sentinel


def tree_inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ArchiveError("package_tree_contains_symlink")
        if not path.is_file():
            continue
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def locator_note_bytes(
    *,
    package_id: str,
    formal_ids: list[str],
    archive_relpath: str,
    manifest_sha256: str,
    package_sha256: str,
    verified_at: str,
    retrieval_keys: list[str],
) -> bytes:
    formal_lines = (
        ["formal_ids: []"]
        if not formal_ids
        else ["formal_ids:", *[f"  - {yaml_quote(formal_id)}" for formal_id in formal_ids]]
    )
    lines = [
        "---",
        "type: raw_archive_locator",
        "subject: math",
        f"package_id: {yaml_quote(package_id)}",
        *formal_lines,
        "retrieval_keys:",
        *[f"  - {yaml_quote(item)}" for item in retrieval_keys],
        "archive_volume: T9-Data",
        f"raw_archive_relpath: {yaml_quote(archive_relpath)}",
        f"raw_archive_manifest_sha256: {manifest_sha256}",
        f"raw_archive_package_sha256: {package_sha256}",
        f"archive_verified_at: {yaml_quote(verified_at)}",
        "archive_status: verified",
        "---",
        "",
        f"原始会话包 `{package_id}` 已归档并逐文件验证。",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def parse_locator_note(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ArchiveError("raw_archive_locator_unreadable") from exc
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ArchiveError("raw_archive_locator_frontmatter_invalid")
    meta = text[4 : text.find("\n---\n", 4)]
    result: dict[str, Any] = {}
    active_list: str | None = None
    for line in meta.splitlines():
        if line.startswith("  - "):
            if active_list not in {"formal_ids", "retrieval_keys"}:
                raise ArchiveError("raw_archive_locator_list_invalid")
            try:
                value = json.loads(line[4:])
            except json.JSONDecodeError as exc:
                raise ArchiveError("raw_archive_locator_list_invalid") from exc
            result.setdefault(active_list, []).append(value)
            continue
        active_list = None
        if ":" not in line:
            raise ArchiveError("raw_archive_locator_frontmatter_invalid")
        key, raw = line.split(":", 1)
        raw = raw.strip()
        if key in {"formal_ids", "retrieval_keys"}:
            if raw == "[]":
                result[key] = []
            elif raw:
                raise ArchiveError("raw_archive_locator_formal_ids_invalid")
            else:
                result[key] = []
                active_list = key
            continue
        if raw.startswith('"'):
            try:
                result[key] = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ArchiveError("raw_archive_locator_scalar_invalid") from exc
        else:
            result[key] = raw
    expected_old = {
        "type",
        "subject",
        "package_id",
        "formal_ids",
        "archive_volume",
        "raw_archive_relpath",
        "raw_archive_manifest_sha256",
        "raw_archive_package_sha256",
        "archive_verified_at",
        "archive_status",
    }
    expected_new = expected_old | {"retrieval_keys"}
    if frozenset(result) not in {frozenset(expected_old), frozenset(expected_new)}:
        raise ArchiveError("raw_archive_locator_fields_invalid")
    if (
        result.get("type") != "raw_archive_locator"
        or result.get("subject") != "math"
        or result.get("archive_volume") != EXPECTED_VOLUME_NAME
        or result.get("archive_status") != "verified"
        or not isinstance(result.get("formal_ids"), list)
        or not all(FORMAL_ID_RE.fullmatch(item) for item in result["formal_ids"])
        or (
            "retrieval_keys" in result
            and (
                not isinstance(result["retrieval_keys"], list)
                or not result["retrieval_keys"]
                or not all(isinstance(item, str) and item for item in result["retrieval_keys"])
            )
        )
    ):
        raise ArchiveError("raw_archive_locator_identity_invalid")
    return result


def locate_by_retrieval_key(repo: Path, retrieval_key: str) -> dict[str, Any]:
    if not isinstance(retrieval_key, str) or not retrieval_key.strip():
        raise ArchiveError("retrieval_key_required")
    root = (repo / "错题知识网络/wiki/sources/raw_archives").resolve(strict=True)
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.glob("*.md")):
        try:
            locator = parse_locator_note(path)
        except ArchiveError:
            text = path.read_text(encoding="utf-8")
            package_match = re.search(r"(?m)^package_id:\s*(.+)$", text)
            relpath_match = re.search(r"(?m)^raw_archive_relpath:\s*(.+)$", text)
            if not package_match or not relpath_match:
                continue
            def scalar(raw: str) -> str:
                raw = raw.strip()
                try:
                    return str(json.loads(raw)) if raw.startswith('"') else raw
                except json.JSONDecodeError:
                    return raw
            locator = {
                "package_id": scalar(package_match.group(1)),
                "formal_ids": re.findall(
                    r"(?m)^\s+-\s+['\"]?((?:GS|LA|PR)-\d+)['\"]?\s*$", text
                ),
                "raw_archive_relpath": scalar(relpath_match.group(1)),
                "retrieval_keys": [],
                "package_schema": (
                    "math-legacy-evidence-archive-package-v1"
                    if "canonical_package: false" in text
                    else "unknown"
                ),
            }
        keys = locator.get("retrieval_keys") or [locator.get("package_id"), *locator.get("formal_ids", [])]
        if retrieval_key in keys:
            matches.append((path, locator))
    if len(matches) != 1:
        raise ArchiveError("retrieval_key_not_unique")
    path, locator = matches[0]
    return {
        "status": "verified",
        "retrieval_key": retrieval_key,
        "locator_note": path.relative_to(repo).as_posix(),
        "package_id": locator["package_id"],
        "formal_ids": locator["formal_ids"],
        "raw_archive_relpath": locator["raw_archive_relpath"],
        "package_schema": locator.get("package_schema", "math-conversation-package-v1"),
        "formal_write_count": 0,
    }


def safe_archive_relative_path(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ArchiveError("raw_archive_relpath_invalid")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ArchiveError("raw_archive_relpath_invalid")
    subject_parts = DEFAULT_SUBJECT_RELATIVE_ROOT.parts
    if relative.parts[: len(subject_parts)] != subject_parts:
        raise ArchiveError("raw_archive_relpath_wrong_subject_root")
    return relative


def verify_archived_package(
    *,
    archive_root: Path,
    locator: dict[str, Any],
) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    validate_volume(archive_root)
    relative = safe_archive_relative_path(locator.get("raw_archive_relpath"))
    package_dir = (archive_root / relative).resolve(strict=True)
    root = archive_root.resolve(strict=True)
    if root not in package_dir.parents or not package_dir.is_dir():
        raise ArchiveError("raw_archive_package_path_invalid")
    manifest_path = package_dir / "manifest.json"
    if (
        not manifest_path.is_file()
        or sha256_file(manifest_path) != locator.get("raw_archive_manifest_sha256")
    ):
        raise ArchiveError("raw_archive_manifest_sha256_mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchiveError("raw_archive_manifest_invalid") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "math-conversation-package-v1"
        or manifest.get("subject") != "math"
        or manifest.get("package_id") != locator.get("package_id")
        or manifest.get("canonical_sha256") != locator.get("raw_archive_package_sha256")
    ):
        raise ArchiveError("raw_archive_manifest_identity_mismatch")
    files = manifest.get("files")
    artifacts = manifest.get("artifacts")
    if not isinstance(files, dict) or set(files) != {"conversation", "source"}:
        raise ArchiveError("raw_archive_manifest_files_invalid")
    if not isinstance(artifacts, list):
        raise ArchiveError("raw_archive_manifest_artifacts_invalid")
    expected_paths = {"manifest.json", "receipt.json"}
    for key, expected_name in (("conversation", "conversation.json"), ("source", "source.json")):
        descriptor = files.get(key)
        if not isinstance(descriptor, dict):
            raise ArchiveError("raw_archive_manifest_file_descriptor_invalid")
        child = package_dir / expected_name
        if (
            Path(str(descriptor.get("path"))).name != expected_name
            or not child.is_file()
            or sha256_file(child) != descriptor.get("sha256")
            or child.stat().st_size != descriptor.get("size")
        ):
            raise ArchiveError("raw_archive_declared_file_mismatch")
        expected_paths.add(expected_name)
    verified_artifacts: list[dict[str, Any]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise ArchiveError("raw_archive_artifact_descriptor_invalid")
        name = Path(str(item.get("path"))).name
        child = package_dir / "attachments" / name
        if (
            not child.is_file()
            or sha256_file(child) != item.get("sha256")
            or child.stat().st_size != item.get("size")
        ):
            raise ArchiveError("raw_archive_artifact_mismatch")
        expected_paths.add(f"attachments/{name}")
        verified_artifacts.append({**item, "archive_path": child})
    actual_paths = {row["path"] for row in tree_inventory(package_dir)}
    if actual_paths != expected_paths:
        raise ArchiveError("raw_archive_tree_mismatch")
    canonical_core = {
        "schema_version": manifest["schema_version"],
        "package_id": manifest["package_id"],
        "subject": manifest["subject"],
        "study_date": manifest["study_date"],
        "timezone": manifest["timezone"],
        "source_locator": manifest["source_locator"],
        "files": files,
        "artifacts": artifacts,
        "missing_fields": manifest["missing_fields"],
        "formal_write_count": 0,
        "background_processing": "none",
    }
    if sha256_bytes(canonical_json(canonical_core).encode("utf-8")) != manifest.get(
        "canonical_sha256"
    ):
        raise ArchiveError("raw_archive_package_sha256_mismatch")
    receipt = json.loads((package_dir / "receipt.json").read_text(encoding="utf-8"))
    if (
        receipt.get("package_id") != manifest["package_id"]
        or receipt.get("canonical_sha256") != manifest["canonical_sha256"]
        or receipt.get("formal_write_count") != 0
        or receipt.get("background_processing") != "none"
    ):
        raise ArchiveError("raw_archive_package_receipt_mismatch")
    return manifest, package_dir, verified_artifacts


def reopen_from_locator(
    *,
    repo: Path,
    locator_relative: str,
    read_kind: str,
    attachment_role: str | None = None,
    attachment_index: int | None = None,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    locator_path = (repo / locator_relative).resolve(strict=True)
    locator_root = (repo / "错题知识网络/wiki/sources/raw_archives").resolve(strict=True)
    if locator_path.parent != locator_root or locator_path.suffix != ".md":
        raise ArchiveError("raw_archive_locator_path_invalid")
    locator = parse_locator_note(locator_path)
    if locator_path.stem != locator.get("package_id"):
        raise ArchiveError("raw_archive_locator_filename_mismatch")
    manifest, package_dir, artifacts = verify_archived_package(
        archive_root=archive_root,
        locator=locator,
    )
    result: dict[str, Any] = {
        "status": "verified",
        "package_id": manifest["package_id"],
        "formal_ids": locator["formal_ids"],
        "raw_archive_relpath": locator["raw_archive_relpath"],
        "raw_archive_manifest_sha256": locator["raw_archive_manifest_sha256"],
        "raw_archive_package_sha256": locator["raw_archive_package_sha256"],
        "read_kind": read_kind,
        "formal_write_count": 0,
    }
    if read_kind == "verify":
        result["verified_artifact_count"] = len(artifacts)
        return result
    if read_kind == "conversation":
        conversation_path = package_dir / "conversation.json"
        result["conversation"] = json.loads(conversation_path.read_text(encoding="utf-8"))
        result["conversation_sha256"] = sha256_file(conversation_path)
        return result
    if read_kind != "attachment":
        raise ArchiveError("raw_archive_read_kind_invalid")
    if not isinstance(attachment_role, str) or not attachment_role:
        raise ArchiveError("attachment_role_required")
    if isinstance(attachment_index, bool) or not isinstance(attachment_index, int) or attachment_index < 1:
        raise ArchiveError("attachment_index_invalid")
    selected = [row for row in artifacts if row.get("role") == attachment_role]
    if attachment_index > len(selected):
        raise ArchiveError("attachment_selection_not_found")
    item = selected[attachment_index - 1]
    child = item.pop("archive_path")
    result["attachment"] = {
        **item,
        "index": attachment_index,
        "archive_path": str(child),
    }
    if str(item.get("media_type", "")).startswith("text/"):
        result["attachment"]["text"] = child.read_text(encoding="utf-8")
    return result


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
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ArchiveError("archive_receipt_ledger_invalid")
            rows.append(value)
    return rows


def append_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(receipt))
        handle.flush()
        os.fsync(handle.fileno())


def load_or_create_archive_intent(
    *,
    repo: Path,
    package_id: str,
    capture_ids: list[str],
    formal_ids: list[str],
    closeout_id: str,
    closeout_closed_at: str,
    terminal_outcome: str,
    manifest_sha256: str,
    package_sha256: str,
    display_closure: dict[str, Any],
) -> dict[str, Any]:
    identity = {
        "package_id": package_id,
        "capture_ids": capture_ids,
        "formal_ids": formal_ids,
        "closeout_id": closeout_id,
        "closeout_closed_at": closeout_closed_at,
        "terminal_outcome": terminal_outcome,
        "manifest_sha256": manifest_sha256,
        "package_sha256": package_sha256,
        "display_closure_receipt_id": display_closure["display_closure_receipt_id"],
        "display_closure_receipt_sha256": display_closure["display_closure_receipt_sha256"],
        "formal_reference_scan_sha256": display_closure["formal_reference_scan_sha256"],
    }
    intent_id = "MATH-ARCHIVE-INTENT-" + sha256_bytes(canonical_json_bytes(identity))[:24]
    intent_path = repo / INTENT_ROOT.relative_to(REPO_ROOT) / f"{package_id}.json"
    if intent_path.exists():
        try:
            intent = json.loads(intent_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ArchiveError("archive_intent_invalid") from exc
        if not isinstance(intent, dict):
            raise ArchiveError("archive_intent_invalid")
    else:
        intent = {
            "schema_version": "math-conversation-package-archive-intent-v1",
            "intent_id": intent_id,
            "archive_verified_at": now_local(),
            **identity,
        }
        atomic_write(intent_path, canonical_json_bytes(intent))
    if (
        intent.get("schema_version") != "math-conversation-package-archive-intent-v1"
        or intent.get("intent_id") != intent_id
        or any(intent.get(key) != value for key, value in identity.items())
        or not isinstance(intent.get("archive_verified_at"), str)
        or not intent["archive_verified_at"].strip()
    ):
        raise ArchiveError("archive_intent_identity_mismatch")
    if json.loads(intent_path.read_text(encoding="utf-8")) != intent:
        raise ArchiveError("archive_intent_reread_failed")
    return intent


def cleanup_local_heavy_files(
    package_dir: Path,
    *,
    pointer: dict[str, Any],
    repo: Path,
    manifest_relative: str,
    expected_manifest_sha256: str,
    expected_package_sha256: str,
    formal_ids: list[str],
    expected_display_closure: dict[str, Any],
) -> None:
    display = load_display_assets(repo)
    current_display_closure = display.verify_closure_for_source(
        repo=repo,
        manifest_relative=manifest_relative,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_package_sha256=expected_package_sha256,
        formal_ids=formal_ids,
    )
    if current_display_closure != expected_display_closure:
        raise ArchiveError("display_closure_drift_before_cleanup")
    if (
        pointer.get("display_closure_receipt_id")
        != current_display_closure["display_closure_receipt_id"]
        or pointer.get("display_closure_receipt_sha256")
        != current_display_closure["display_closure_receipt_sha256"]
        or pointer.get("formal_reference_scan_sha256")
        != current_display_closure["formal_reference_scan_sha256"]
    ):
        raise ArchiveError("archive_pointer_display_closure_mismatch")
    pointer_path = package_dir / "archive-pointer.json"
    pointer_bytes = canonical_json_bytes(pointer)
    if pointer_path.exists():
        if pointer_path.read_bytes() != pointer_bytes:
            raise ArchiveError("archive_pointer_conflict")
    else:
        atomic_write(pointer_path, pointer_bytes)
    if pointer_path.read_bytes() != pointer_bytes:
        raise ArchiveError("archive_pointer_reread_failed")
    attachments = package_dir / "attachments"
    if attachments.exists():
        if attachments.is_symlink() or not attachments.is_dir():
            raise ArchiveError("local_attachments_invalid")
        shutil.rmtree(attachments)


def archive_package(
    *,
    repo: Path,
    manifest_relative: str,
    expected_manifest_sha256: str,
    expected_package_sha256: str,
    formal_ids: list[str],
    closeout_id: str,
    terminal_outcome: str,
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
    subject_relative_root: Path = DEFAULT_SUBJECT_RELATIVE_ROOT,
) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    if archive_root.resolve(strict=True) != DEFAULT_ARCHIVE_ROOT.resolve(strict=True):
        raise ArchiveError("archive_root_must_be_exact_t9_data")
    if subject_relative_root != DEFAULT_SUBJECT_RELATIVE_ROOT:
        raise ArchiveError("subject_relative_root_mismatch")
    validate_volume(archive_root)
    quick = load_quick_intake(repo)
    manifest_path = (repo / manifest_relative).resolve(strict=True)
    try:
        manifest_path.relative_to(repo)
    except ValueError as exc:
        raise ArchiveError("manifest_outside_repo") from exc
    if sha256_file(manifest_path) != expected_manifest_sha256:
        raise ArchiveError("local_manifest_sha256_mismatch")
    document, _, _ = quick.validate_source_bundle_manifest(
        manifest_relative,
        "archive.manifest",
        expected_hash=expected_manifest_sha256,
    )
    if document.get("schema_version") != quick.CONVERSATION_PACKAGE_SCHEMA:
        raise ArchiveError("archive_requires_conversation_package_v1")
    if document.get("canonical_sha256") != expected_package_sha256:
        raise ArchiveError("local_package_sha256_mismatch")
    package_id = str(document["package_id"])
    study_date = str(document["study_date"])
    formal_ids = sorted(set(formal_ids))
    if not all(FORMAL_ID_RE.fullmatch(item) for item in formal_ids):
        raise ArchiveError("formal_ids_invalid")
    if terminal_outcome not in ARCHIVABLE_TERMINAL_OUTCOMES:
        raise ArchiveError("terminal_outcome_not_archivable")
    capture_ids, resolved_formal_ids, actual_terminal_outcome, closeout_closed_at = validate_formal_commit(
        quick,
        manifest_relative,
        closeout_id,
        formal_ids,
        terminal_outcome,
    )
    formal_ids = resolved_formal_ids
    terminal_outcome = actual_terminal_outcome
    package_dir = manifest_path.parent
    pointer_path = package_dir / "archive-pointer.json"
    if pointer_path.exists():
        try:
            old_pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ArchiveError("archive_pointer_invalid") from exc
        if old_pointer.get("schema_version") == POINTER_SCHEMA:
            receipts_path = repo / RECEIPTS_PATH.relative_to(REPO_ROOT)
            matching = [
                row
                for row in load_receipts(receipts_path)
                if row.get("receipt_id") == old_pointer.get("archive_receipt_id")
            ]
            if len(matching) != 1:
                raise ArchiveError("old_contract_archive_receipt_missing")
            old_receipt = matching[0]
            locator = repo / str(old_receipt.get("obsidian_locator_path"))
            if (
                old_receipt.get("schema_version") != RECEIPT_SCHEMA
                or old_receipt.get("package_id") != package_id
                or old_receipt.get("formal_ids") != formal_ids
                or old_receipt.get("capture_ids") != capture_ids
                or old_receipt.get("closeout_id") != closeout_id
                or old_receipt.get("archive_status") != "verified"
                or old_receipt.get("obsidian_path_status") != "verified"
                or not locator.is_file()
                or sha256_file(locator) != old_receipt.get("obsidian_locator_sha256")
            ):
                raise ArchiveError("old_contract_archive_binding_mismatch")
            if (package_dir / "attachments").exists():
                raise ArchiveError("old_contract_pointer_cannot_authorize_new_cleanup")
            return {
                "status": "noop",
                **old_receipt,
                "local_cleanup": "old_contract_already_cleaned_readonly_compatible",
                "pending_component": None,
            }
    display = load_display_assets(repo)
    try:
        display_closure = display.verify_closure_for_source(
            repo=repo,
            manifest_relative=manifest_relative,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_package_sha256=expected_package_sha256,
            formal_ids=formal_ids,
        )
    except ValueError as exc:
        raise ArchiveError(f"display_asset_closure_required:{exc}") from exc
    intent = load_or_create_archive_intent(
        repo=repo,
        package_id=package_id,
        capture_ids=capture_ids,
        formal_ids=formal_ids,
        closeout_id=closeout_id,
        closeout_closed_at=closeout_closed_at,
        terminal_outcome=terminal_outcome,
        manifest_sha256=expected_manifest_sha256,
        package_sha256=expected_package_sha256,
        display_closure=display_closure,
    )
    source_inventory = tree_inventory(package_dir)
    if any(row["path"] == "archive-pointer.json" for row in source_inventory):
        pointer = json.loads((package_dir / "archive-pointer.json").read_text(encoding="utf-8"))
        receipts_path = repo / RECEIPTS_PATH.relative_to(REPO_ROOT)
        matching = [
            row
            for row in load_receipts(receipts_path)
            if row.get("receipt_id") == pointer.get("archive_receipt_id")
        ]
        if len(matching) != 1:
            raise ArchiveError("archived_pointer_receipt_missing")
        receipt = matching[0]
        if (
            receipt.get("package_id") != package_id
            or receipt.get("formal_ids") != formal_ids
            or receipt.get("capture_ids") != capture_ids
            or receipt.get("closeout_id") != closeout_id
            or receipt.get("terminal_outcome") != terminal_outcome
            or receipt.get("archive_intent_id") != intent["intent_id"]
            or receipt.get("raw_archive_manifest_sha256") != expected_manifest_sha256
            or receipt.get("raw_archive_package_sha256") != expected_package_sha256
            or receipt.get("archive_status") != "verified"
            or receipt.get("obsidian_path_status") != "verified"
        ):
            raise ArchiveError("archived_pointer_receipt_mismatch")
        locator = repo / str(receipt.get("obsidian_locator_path"))
        if not locator.is_file() or sha256_file(locator) != receipt.get("obsidian_locator_sha256"):
            raise ArchiveError("archived_pointer_locator_mismatch")
        if pointer.get("schema_version") != POINTER_SCHEMA_V2:
            raise ArchiveError("archive_pointer_schema_invalid")
        if any(
            pointer.get(key) != display_closure[key]
            for key in (
                "display_closure_receipt_id",
                "display_closure_receipt_sha256",
                "formal_reference_scan_sha256",
                "stable_asset_count",
                "no_display_proof",
            )
        ):
            raise ArchiveError("archived_pointer_display_closure_mismatch")
        cleanup_local_heavy_files(
            package_dir,
            pointer=pointer,
            repo=repo,
            manifest_relative=manifest_relative,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_package_sha256=expected_package_sha256,
            formal_ids=formal_ids,
            expected_display_closure=display_closure,
        )
        return {
            "status": "noop",
            **receipt,
            "local_cleanup": "attachments_removed_pointer_written",
            "pending_component": None,
        }

    relative_destination = subject_relative_root / study_date / package_id
    destination = archive_root / relative_destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    status = "recorded"
    if destination.exists():
        if not destination.is_dir() or tree_inventory(destination) != source_inventory:
            raise ArchiveError("archive_destination_conflict")
        status = "noop"
    else:
        staging = Path(tempfile.mkdtemp(prefix=f".{package_id}.", dir=destination.parent))
        try:
            shutil.copytree(package_dir, staging, dirs_exist_ok=True, copy_function=shutil.copy2)
            if tree_inventory(staging) != source_inventory:
                raise ArchiveError("archive_stage_tree_verify_failed")
            staged_manifest = staging / "manifest.json"
            if sha256_file(staged_manifest) != expected_manifest_sha256:
                raise ArchiveError("archive_stage_manifest_verify_failed")
            os.replace(staging, destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    archive_inventory = tree_inventory(destination)
    if archive_inventory != source_inventory:
        raise ArchiveError("archive_final_tree_verify_failed")
    if (
        sha256_file(destination / "manifest.json") != expected_manifest_sha256
        or json.loads((destination / "manifest.json").read_text(encoding="utf-8")).get(
            "canonical_sha256"
        )
        != expected_package_sha256
    ):
        raise ArchiveError("archive_final_manifest_verify_failed")

    verified_at = str(intent["archive_verified_at"])
    archive_relpath = relative_destination.as_posix()
    locator_path = repo / f"错题知识网络/wiki/sources/raw_archives/{package_id}.md"
    note_bytes = locator_note_bytes(
        package_id=package_id,
        formal_ids=formal_ids,
        archive_relpath=archive_relpath,
        manifest_sha256=expected_manifest_sha256,
        package_sha256=expected_package_sha256,
        verified_at=verified_at,
        retrieval_keys=sorted(
            set([package_id, study_date, str(document.get("source_locator") or ""), *capture_ids, *formal_ids])
            - {""}
        ),
    )
    if locator_path.exists():
        if locator_path.read_bytes() != note_bytes:
            raise ArchiveError("obsidian_locator_conflict")
    else:
        atomic_write(locator_path, note_bytes)
    if locator_path.read_bytes() != note_bytes:
        raise ArchiveError("obsidian_locator_reread_failed")
    locator_sha256 = sha256_bytes(note_bytes)
    receipt_identity = {
        "package_id": package_id,
        "capture_ids": capture_ids,
        "closeout_id": closeout_id,
        "terminal_outcome": terminal_outcome,
        "archive_intent_id": intent["intent_id"],
        "manifest_sha256": expected_manifest_sha256,
        "package_sha256": expected_package_sha256,
        "archive_relpath": archive_relpath,
        "locator_sha256": locator_sha256,
        "display_closure_receipt_id": display_closure["display_closure_receipt_id"],
        "display_closure_receipt_sha256": display_closure["display_closure_receipt_sha256"],
        "formal_reference_scan_sha256": display_closure["formal_reference_scan_sha256"],
    }
    receipt_id = "MATH-ARCHIVE-" + sha256_bytes(canonical_json_bytes(receipt_identity))[:24]
    receipt = {
        "schema_version": RECEIPT_SCHEMA_V2,
        "receipt_id": receipt_id,
        "package_id": package_id,
        "formal_ids": formal_ids,
        "capture_ids": capture_ids,
        "closeout_id": closeout_id,
        "terminal_outcome": terminal_outcome,
        "archive_intent_id": intent["intent_id"],
        "archive_volume": EXPECTED_VOLUME_NAME,
        "raw_archive_relpath": archive_relpath,
        "raw_archive_manifest_sha256": expected_manifest_sha256,
        "raw_archive_package_sha256": expected_package_sha256,
        "archive_tree_sha256": sha256_bytes(canonical_json_bytes(archive_inventory)),
        "archive_verified_at": verified_at,
        "archive_status": "verified",
        "obsidian_locator_path": str(locator_path.relative_to(repo)),
        "obsidian_locator_sha256": locator_sha256,
        "obsidian_path_status": "verified",
        **display_closure,
        "pending_component": None,
        "formal_write_count": 0,
    }
    receipts_path = repo / RECEIPTS_PATH.relative_to(REPO_ROOT)
    lock_path = repo / LOCK_PATH.relative_to(REPO_ROOT)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        existing = [row for row in load_receipts(receipts_path) if row.get("receipt_id") == receipt_id]
        if existing:
            if existing != [receipt]:
                raise ArchiveError("archive_receipt_conflict")
            status = "noop"
        else:
            append_receipt(receipts_path, receipt)
        reread = [row for row in load_receipts(receipts_path) if row.get("receipt_id") == receipt_id]
        if reread != [receipt]:
            raise ArchiveError("archive_receipt_reread_failed")
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
    pointer = {
        "schema_version": POINTER_SCHEMA_V2,
        "package_id": package_id,
        "archive_volume": EXPECTED_VOLUME_NAME,
        "raw_archive_relpath": archive_relpath,
        "raw_archive_manifest_sha256": expected_manifest_sha256,
        "raw_archive_package_sha256": expected_package_sha256,
        "archive_receipt_id": receipt_id,
        "archive_intent_id": intent["intent_id"],
        "obsidian_locator_path": receipt["obsidian_locator_path"],
        "obsidian_locator_sha256": locator_sha256,
        "archive_status": "verified",
        **display_closure,
        "pending_component": None,
        "cleanup_intent": "remove_local_attachments_after_verified_display_archive_locator_receipt",
    }
    cleanup_local_heavy_files(
        package_dir,
        pointer=pointer,
        repo=repo,
        manifest_relative=manifest_relative,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_package_sha256=expected_package_sha256,
        formal_ids=formal_ids,
        expected_display_closure=display_closure,
    )
    return {
        "status": status,
        **receipt,
        "local_cleanup": "attachments_removed_pointer_written",
        "pending_component": None,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="归档或精确重开数学完整会话包")
    value.add_argument("--mode", choices=("archive", "reopen", "locate"), default="archive")
    value.add_argument("--repo", required=True)
    value.add_argument("--manifest")
    value.add_argument("--manifest-sha256")
    value.add_argument("--package-sha256")
    value.add_argument("--formal-id", action="append", default=[])
    value.add_argument("--closeout-id")
    value.add_argument("--terminal-outcome")
    value.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    value.add_argument("--subject-relative-root", default=str(DEFAULT_SUBJECT_RELATIVE_ROOT))
    value.add_argument("--locator-note")
    value.add_argument(
        "--read-kind",
        choices=("verify", "conversation", "attachment"),
        default="verify",
    )
    value.add_argument("--attachment-role")
    value.add_argument("--attachment-index", type=int)
    value.add_argument("--retrieval-key")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.mode == "locate":
            result = locate_by_retrieval_key(Path(args.repo).resolve(strict=True), args.retrieval_key)
        elif args.mode == "reopen":
            if not args.locator_note:
                raise ArchiveError("locator_note_required")
            result = reopen_from_locator(
                repo=Path(args.repo),
                locator_relative=args.locator_note,
                read_kind=args.read_kind,
                attachment_role=args.attachment_role,
                attachment_index=args.attachment_index,
                archive_root=Path(args.archive_root),
            )
        else:
            if not all(
                isinstance(item, str) and item
                for item in (
                    args.manifest,
                    args.manifest_sha256,
                    args.package_sha256,
                    args.closeout_id,
                    args.terminal_outcome,
                )
            ):
                raise ArchiveError("archive_arguments_incomplete")
            result = archive_package(
                repo=Path(args.repo),
                manifest_relative=args.manifest,
                expected_manifest_sha256=args.manifest_sha256,
                expected_package_sha256=args.package_sha256,
                formal_ids=args.formal_id,
                closeout_id=args.closeout_id,
                terminal_outcome=args.terminal_outcome,
                archive_root=Path(args.archive_root),
                subject_relative_root=Path(args.subject_relative_root),
            )
    except (ArchiveError, OSError, ValueError, json.JSONDecodeError) as exc:
        code = str(exc)
        component = (
            "display_assets"
            if "display" in code or "formal_reference" in code
            else "locator"
            if "locator" in code
            else "cleanup"
            if "cleanup" in code or "pointer" in code
            else "archive"
        )
        print(
            canonical_json(
                {
                    "status": "error",
                    "error_code": code,
                    "pending_component": component,
                    "formal_write_count": 0,
                }
            )
        )
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
