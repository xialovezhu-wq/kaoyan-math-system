#!/usr/bin/env python3
"""Promote math intake images to stable Obsidian assets and prove closure.

The immutable intake package remains the evidence source.  This writer creates
only a deterministic display projection under the vault, then records a
sidecar receipt outside the package.  Archive cleanup may trust that receipt
only after :func:`verify_closure_for_source` reopens every referenced byte.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_SCHEMA = "math-display-asset-plan-v1"
CLOSURE_SCHEMA = "math-display-asset-closure-receipt-v1"
HISTORICAL_PLAN_SCHEMA = "math-display-asset-historical-repair-plan-v1"
HISTORICAL_RECEIPT_SCHEMA = "math-display-asset-historical-repair-receipt-v1"
HISTORICAL_SUPPLEMENT_SCHEMA = "math-display-asset-historical-closure-supplement-v1"
CONVERSATION_PACKAGE_SCHEMA = "math-conversation-package-v1"
SOURCE_BUNDLE_SCHEMA = "math-fast-intake-source-bundle-v1"
PLAN_ROOT = Path("数学一回滚复习系统/展示资产闭环")
HISTORICAL_RECEIPT_ROOT = Path("数学一回滚复习系统/展示资产历史修复回执")
CARD_ROOT = Path("错题知识网络/错题卡")
DETAIL_ROOT = Path("错题知识网络/可视化错题详情")
ASSET_ROOT = Path("错题知识网络/assets/visual_wrong_questions")
LOCATOR_ROOT = Path("错题知识网络/wiki/sources/raw_archives")
LOCK_RELATIVE_PATH = Path("数学一回滚复习系统/.展示资产闭环.lock")
BRIDGE_REFRESH_RELATIVE_PATH = Path("错题知识网络/scripts/refresh_obsidian_bridge_snapshot.py")
BRIDGE_MANIFEST_RELATIVE_PATH = Path("错题知识网络/可视化错题详情/manifest.json")
DEFAULT_ARCHIVE_ROOT = Path("/Volumes/T9-Data")
SUBJECT_ARCHIVE_ROOT = Path("03_数学/资料库/原始会话资料")
SENTINEL_RELATIVE_PATH = Path("00_迁移管理/状态/volume-sentinel.json")
SENTINEL_SHA256 = "f086b32b29b2b38f1a28dffb8fde4fa850078332d8a23ae269cc8e857a6bd2ca"
EXPECTED_VOLUME_NAME = "T9-Data"
EXPECTED_VOLUME_UUID = "00000000-0000-0000-0000-000000000000"
FORMAL_ID_RE = re.compile(r"^(?:GS|LA|PR)-\d{3,}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
DISPLAY_DISPOSITIONS = {"promoted", "already_stable"}
MANAGED_START = "<!-- math-display-assets:start -->"
MANAGED_END = "<!-- math-display-assets:end -->"


class DisplayAssetError(ValueError):
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


def safe_repo_path(repo: Path, relative: str | Path, field: str, *, must_exist: bool = True) -> Path:
    value = Path(relative)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise DisplayAssetError(f"{field}_unsafe")
    candidate = repo / value
    try:
        resolved = candidate.resolve(strict=must_exist)
        resolved.relative_to(repo.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise DisplayAssetError(f"{field}_outside_repo") from exc
    if candidate.is_symlink():
        raise DisplayAssetError(f"{field}_symlink_forbidden")
    return candidate


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


def validate_archive_root(archive_root: Path) -> Path:
    if archive_root.is_symlink():
        raise DisplayAssetError("archive_root_symlink_forbidden")
    try:
        root = archive_root.resolve(strict=True)
        expected = DEFAULT_ARCHIVE_ROOT.resolve(strict=True)
    except OSError as exc:
        raise DisplayAssetError("archive_root_unavailable") from exc
    if root != expected or root.name != EXPECTED_VOLUME_NAME:
        raise DisplayAssetError("archive_root_must_be_exact_t9_data")
    if Path("/Volumes/T9-Data 1").exists() or root.with_name(f"{root.name} 1").exists():
        raise DisplayAssetError("ambiguous_t9_mount_suffix_present")
    sentinel = root / SENTINEL_RELATIVE_PATH
    if sentinel.is_symlink() or not sentinel.is_file() or sha256_file(sentinel) != SENTINEL_SHA256:
        raise DisplayAssetError("volume_sentinel_sha256_mismatch")
    try:
        value = json.loads(sentinel.read_text(encoding="utf-8"))
        expected_mount = Path(str(value.get("expected_mount_point"))).resolve(strict=True)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DisplayAssetError("volume_sentinel_invalid") from exc
    if (
        value.get("volume_name") != EXPECTED_VOLUME_NAME
        or value.get("volume_uuid") != EXPECTED_VOLUME_UUID
        or expected_mount != root
    ):
        raise DisplayAssetError("volume_sentinel_identity_mismatch")
    return root


def exact_archive_package(archive_root: Path, relative: str) -> Path:
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts or value.parts[: len(SUBJECT_ARCHIVE_ROOT.parts)] != SUBJECT_ARCHIVE_ROOT.parts:
        raise DisplayAssetError("raw_archive_relpath_invalid")
    root = validate_archive_root(archive_root)
    current = root
    for part in value.parts:
        current = current / part
        if current.is_symlink():
            raise DisplayAssetError("raw_archive_component_symlink_forbidden")
    try:
        package = (root / value).resolve(strict=True)
        package.relative_to(root)
    except (OSError, ValueError) as exc:
        raise DisplayAssetError("raw_archive_package_invalid") from exc
    if not package.is_dir():
        raise DisplayAssetError("raw_archive_package_invalid")
    return package


def exact_archive_file(package: Path, relative: str) -> Path:
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts or not value.parts:
        raise DisplayAssetError("raw_archive_file_relpath_invalid")
    current = package
    for part in value.parts:
        current = current / part
        if current.is_symlink():
            raise DisplayAssetError("raw_archive_file_component_symlink_forbidden")
    try:
        file_path = (package / value).resolve(strict=True)
        file_path.relative_to(package.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise DisplayAssetError("raw_archive_file_outside_package") from exc
    if not file_path.is_file():
        raise DisplayAssetError("raw_archive_file_missing")
    return file_path


def refresh_bridge_membership(repo: Path, source_id: str, formal_ids: list[str]) -> dict[str, Any]:
    script = safe_repo_path(repo, BRIDGE_REFRESH_RELATIVE_PATH, "bridge_refresh_script")
    safe_repo_path(repo, BRIDGE_MANIFEST_RELATIVE_PATH, "bridge_visual_manifest")
    snapshot = repo / PLAN_ROOT / source_id / "bridge-records.json"
    result = subprocess.run(
        [
            os.environ.get("PYTHON", "python3"),
            str(script),
            "--project-root",
            str(repo),
            "--snapshot",
            str(snapshot),
            "--no-ping",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not snapshot.is_file():
        raise DisplayAssetError("bridge_snapshot_refresh_failed")
    try:
        document = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DisplayAssetError("bridge_snapshot_invalid") from exc
    records = document.get("records") if isinstance(document, dict) else None
    if not isinstance(records, list):
        raise DisplayAssetError("bridge_snapshot_records_invalid")
    membership: list[dict[str, str]] = []
    for formal_id in sorted(formal_ids):
        # Merged source notes retain their historical formal ID, but they are
        # not additional current routes. Require one unmerged route, preserving
        # both records in the bridge snapshot and rejecting true ambiguity.
        matches = [row for row in records if isinstance(row, dict)
                   and row.get("wrongnet_id") == formal_id
                   and row.get("link_status") != "merged_into_wrongnet"]
        if len(matches) != 1 or not matches[0].get("detail_note"):
            raise DisplayAssetError("bridge_membership_missing_or_ambiguous")
        membership.append(
            {
                "formal_id": formal_id,
                "detail_note": str(matches[0]["detail_note"]),
                "link_status": str(matches[0].get("link_status") or ""),
            }
        )
    return {
        "snapshot_path": snapshot.relative_to(repo).as_posix(),
        "snapshot_sha256": sha256_file(snapshot),
        "membership": membership,
        "status": "verified",
    }


def load_quick_intake(repo: Path) -> Any:
    path = repo / "数学一回滚复习系统/scripts/quick_intake.py"
    spec = importlib.util.spec_from_file_location("math_display_quick_intake", path)
    if spec is None or spec.loader is None:
        raise DisplayAssetError("quick_intake_import_invalid")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    module.REPO_ROOT = repo
    module.ROOT = repo / "数学一回滚复习系统"
    module.EVENTS_PATH = module.ROOT / "快速入库事件.jsonl"
    module.SOURCE_STAGING_ROOT = module.ROOT / "快速入库来源"
    return module


@contextmanager
def display_lock(repo: Path):
    path = repo / LOCK_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _frontmatter_bounds(text: str) -> tuple[int, int]:
    if text.startswith("---\r\n"):
        start = 5
        end = text.find("\r\n---\r\n", start)
    elif text.startswith("---\n"):
        start = 4
        end = text.find("\n---\n", start)
    else:
        raise DisplayAssetError("markdown_frontmatter_missing")
    if end < 0:
        raise DisplayAssetError("markdown_frontmatter_unclosed")
    return start, end


def frontmatter_scalar(text: str, key: str) -> str:
    start, end = _frontmatter_bounds(text)
    match = re.search(rf"(?m)^{re.escape(key)}:\s*['\"]?([^'\"\n]+)", text[start:end])
    return match.group(1).strip() if match else ""


def frontmatter_list(text: str, key: str) -> list[str]:
    start, end = _frontmatter_bounds(text)
    meta = text[start:end]
    values: list[str] = []
    active = False
    for line in meta.splitlines():
        if re.fullmatch(rf"{re.escape(key)}:\s*", line):
            active = True
            continue
        if active and re.match(r"^[A-Za-z_][A-Za-z0-9_]*:", line):
            break
        if active:
            match = re.match(r"^\s*-\s+(.*)$", line)
            if match:
                values.append(match.group(1).strip().strip("'\""))
    return values


def replace_frontmatter_list(text: str, key: str, values: Iterable[str]) -> str:
    start, end = _frontmatter_bounds(text)
    meta = text[start:end]
    lines = meta.splitlines(keepends=True)
    field_indexes = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(rf"{re.escape(key)}:[ \t]*(?:\r?\n)?", line)
    ]
    if len(field_indexes) > 1:
        raise DisplayAssetError("frontmatter_list_field_duplicate")
    rendered = [
        key + ":\n",
        *[f"  - {json.dumps(value, ensure_ascii=False)}\n" for value in values],
    ]
    if field_indexes:
        field_start = field_indexes[0]
        field_end = field_start + 1
        while field_end < len(lines) and re.match(
            r"^[ \t]*-[ \t]+[^\r\n]*(?:\r?\n)?$", lines[field_end]
        ):
            field_end += 1
        lines[field_start:field_end] = rendered
        meta = "".join(lines)
    else:
        if meta and not meta.endswith("\n"):
            meta += "\n"
        meta += "".join(rendered)
    return text[:start] + meta + text[end:]


def replace_frontmatter_list_values(
    text: str,
    key: str,
    replacements: dict[str, str],
) -> str:
    """Replace exact list scalar values while preserving every other byte."""
    if not replacements:
        return text
    start, end = _frontmatter_bounds(text)
    meta = text[start:end]
    lines = meta.splitlines(keepends=True)
    field_indexes = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(rf"{re.escape(key)}:[ \t]*(?:\r?\n)?", line)
    ]
    if len(field_indexes) != 1:
        raise DisplayAssetError("frontmatter_list_field_not_unique")
    field_end = field_indexes[0] + 1
    counts = {old: 0 for old in replacements}
    while field_end < len(lines):
        line = lines[field_end]
        match = re.fullmatch(
            r"([ \t]*-[ \t]+)([^\r\n]*)(\r?\n)?", line
        )
        if match is None:
            break
        prefix, payload, newline = match.group(1), match.group(2), match.group(3) or ""
        value: str | None = None
        suffix = ""
        quote = ""
        if payload.startswith('"'):
            try:
                decoded, offset = json.JSONDecoder().raw_decode(payload)
            except json.JSONDecodeError as exc:
                raise DisplayAssetError("frontmatter_double_quoted_item_invalid") from exc
            if not isinstance(decoded, str):
                raise DisplayAssetError("frontmatter_list_item_not_string")
            value, suffix, quote = decoded, payload[offset:], '"'
        elif payload.startswith("'"):
            cursor = 1
            decoded_chars: list[str] = []
            while cursor < len(payload):
                if payload[cursor] != "'":
                    decoded_chars.append(payload[cursor])
                    cursor += 1
                    continue
                if cursor + 1 < len(payload) and payload[cursor + 1] == "'":
                    decoded_chars.append("'")
                    cursor += 2
                    continue
                value = "".join(decoded_chars)
                suffix = payload[cursor + 1 :]
                quote = "'"
                break
            if value is None:
                raise DisplayAssetError("frontmatter_single_quoted_item_invalid")
        else:
            for old in sorted(replacements, key=len, reverse=True):
                if not payload.startswith(old):
                    continue
                possible_suffix = payload[len(old) :]
                if not possible_suffix or re.fullmatch(r"[ \t]*(?:#.*)?", possible_suffix):
                    value, suffix = old, possible_suffix
                    break
        if value in replacements:
            counts[value] += 1
            replacement = replacements[value]
            if quote == '"':
                rendered_value = json.dumps(replacement, ensure_ascii=False)
            elif quote == "'":
                rendered_value = "'" + replacement.replace("'", "''") + "'"
            else:
                rendered_value = replacement
            lines[field_end] = prefix + rendered_value + suffix + newline
        field_end += 1
    invalid = [old for old, count in counts.items() if count != 1]
    if invalid:
        raise DisplayAssetError(
            "frontmatter_list_value_not_unique:" + ",".join(sorted(invalid))
        )
    return text[:start] + "".join(lines) + text[end:]


def formal_card_path(repo: Path, formal_id: str) -> Path:
    if not FORMAL_ID_RE.fullmatch(formal_id):
        raise DisplayAssetError("formal_id_invalid")
    root = safe_repo_path(repo, CARD_ROOT, "formal_card_root")
    matches = sorted(root.glob(f"{formal_id}_*.md"))
    if len(matches) != 1:
        raise DisplayAssetError("formal_card_not_unique")
    return matches[0]


def detail_path_for_card(repo: Path, formal_id: str, card: Path, card_text: str) -> Path:
    root = repo / DETAIL_ROOT
    matches = sorted(root.rglob(f"{formal_id}_*.md")) if root.exists() else []
    if len(matches) > 1:
        raise DisplayAssetError("visual_detail_not_unique")
    if matches:
        return matches[0]
    subject = frontmatter_scalar(card_text, "subject") or "高等数学"
    if subject not in {"高等数学", "线性代数", "概率论与数理统计"}:
        raise DisplayAssetError("formal_card_subject_invalid")
    return repo / DETAIL_ROOT / subject / card.name


def _artifact_role(raw: str) -> tuple[str, str, str]:
    mapping = {
        "question_image": ("question", "practice_safe", "promoted"),
        "question": ("question", "practice_safe", "promoted"),
        "source_article_image": ("source_article", "practice_safe", "promoted"),
        "solution_image": ("solution", "protected", "promoted"),
        "solution": ("solution", "protected", "promoted"),
        "explanation_image": ("explanation", "protected", "promoted"),
        "reference": ("explanation", "protected", "promoted"),
        "user_work_image": ("user_work", "protected", "promoted"),
        "user_work": ("user_work", "protected", "promoted"),
        "other_attachment": ("other", "protected", "archive_only"),
        "solution_text": ("solution_text", "protected", "archive_only"),
    }
    return mapping.get(raw, ("other", "protected", "archive_only"))


def allocate_stable_asset_paths(
    repo: Path, formal_id: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Allocate stable paths without overwriting or renumbering existing bytes."""
    asset_dir = repo / ASSET_ROOT / formal_id
    used_slots: dict[str, set[int]] = {}
    existing_by_hash: dict[tuple[str, str], list[tuple[int, Path]]] = {}
    role_pattern = re.compile(
        r"^(question|source_article|solution|explanation|user_work)_(\d+)"
        r"(?:\.png|\.jpe?g|\.webp|\.gif|\.svg)$",
        flags=re.IGNORECASE,
    )
    if asset_dir.exists():
        if asset_dir.is_symlink() or not asset_dir.is_dir():
            raise DisplayAssetError("stable_display_asset_directory_invalid")
        for child in sorted(asset_dir.iterdir(), key=lambda item: item.name):
            if child.is_symlink():
                raise DisplayAssetError("stable_display_asset_symlink_forbidden")
            if not child.is_file():
                continue
            match = role_pattern.fullmatch(child.name)
            if not match:
                continue
            role = match.group(1).lower()
            index = int(match.group(2))
            used_slots.setdefault(role, set()).add(index)
            digest = sha256_file(child)
            existing_by_hash.setdefault((role, digest), []).append((index, child))
    planned_by_hash: dict[tuple[str, str], str] = {}
    allocated: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        if row.get("disposition") != "promoted":
            row["stable_vault_relative_path"] = None
            allocated.append(row)
            continue
        role = str(row["display_role"])
        source_sha = str(row["source_sha256"])
        key = (role, source_sha)
        existing = sorted(
            existing_by_hash.get(key, []),
            key=lambda item: (item[0], item[1].name),
        )
        if existing:
            target = existing[0][1]
            row["stable_vault_relative_path"] = target.relative_to(repo).as_posix()
            row["stable_role_index"] = existing[0][0]
            row["disposition"] = "already_stable"
            allocated.append(row)
            continue
        if key in planned_by_hash:
            target_relative = planned_by_hash[key]
            row["stable_vault_relative_path"] = target_relative
            row["stable_role_index"] = int(
                re.search(r"_(\d+)\.", Path(target_relative).name).group(1)  # type: ignore[union-attr]
            )
            allocated.append(row)
            continue
        used = used_slots.setdefault(role, set())
        index = 1
        while index in used:
            index += 1
        used.add(index)
        target = ASSET_ROOT / formal_id / f"{role}_{index:02d}{row['suffix']}"
        target_relative = target.as_posix()
        planned_by_hash[key] = target_relative
        row["stable_vault_relative_path"] = target_relative
        row["stable_role_index"] = index
        allocated.append(row)
    return allocated


def load_source_manifest(
    repo: Path,
    manifest_relative: str,
    expected_sha256: str | None = None,
    *,
    allow_missing_artifacts: bool = False,
) -> tuple[dict[str, Any], Path, str, str, str | None, list[dict[str, Any]]]:
    manifest_path = safe_repo_path(repo, manifest_relative, "source_manifest")
    actual_sha = sha256_file(manifest_path)
    if expected_sha256 is not None and actual_sha != expected_sha256:
        raise DisplayAssetError("source_manifest_sha256_mismatch")
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DisplayAssetError("source_manifest_invalid") from exc
    if not isinstance(document, dict) or document.get("schema_version") not in {
        CONVERSATION_PACKAGE_SCHEMA,
        SOURCE_BUNDLE_SCHEMA,
    }:
        raise DisplayAssetError("source_manifest_schema_invalid")
    schema = str(document["schema_version"])
    source_id = (
        str(document.get("package_id"))
        if schema == CONVERSATION_PACKAGE_SCHEMA
        else "MATHSRC-" + actual_sha[:24]
    )
    if not source_id or source_id == "None":
        raise DisplayAssetError("source_identity_missing")
    package_sha = document.get("canonical_sha256") if schema == CONVERSATION_PACKAGE_SCHEMA else None
    rows: list[dict[str, Any]] = []
    role_counts: dict[str, int] = {}
    for index, item in enumerate(document.get("artifacts", []), start=1):
        if not isinstance(item, dict):
            raise DisplayAssetError("source_artifact_descriptor_invalid")
        raw_role = item.get("role")
        path_value = item.get("path")
        if not isinstance(raw_role, str) or not isinstance(path_value, str):
            raise DisplayAssetError("source_artifact_binding_missing")
        expected_hash = item.get("sha256")
        expected_size = item.get("size")
        if not isinstance(expected_hash, str) or not HASH_RE.fullmatch(expected_hash) or not isinstance(expected_size, int):
            raise DisplayAssetError("source_artifact_descriptor_invalid")
        try:
            source_path = safe_repo_path(repo, path_value, f"source_artifact_{index}")
        except DisplayAssetError:
            if not allow_missing_artifacts:
                raise
            source_path = safe_repo_path(
                repo, path_value, f"source_artifact_{index}", must_exist=False
            )
        if source_path.is_file():
            actual = sha256_file(source_path)
            if actual != expected_hash or source_path.stat().st_size != expected_size:
                raise DisplayAssetError("source_artifact_hash_mismatch")
        elif allow_missing_artifacts:
            actual = expected_hash
        else:
            raise DisplayAssetError("source_artifact_missing")
        role, visibility, disposition = _artifact_role(raw_role)
        role_counts[role] = role_counts.get(role, 0) + 1
        suffix = source_path.suffix.lower()
        if disposition == "promoted" and suffix not in IMAGE_SUFFIXES:
            raise DisplayAssetError("display_artifact_not_supported_image")
        rows.append(
            {
                "attachment_role": raw_role,
                "display_role": role,
                "role_index": role_counts[role],
                "package_relative_path": path_value,
                "media_type": str(item.get("media_type") or mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"),
                "size": expected_size,
                "source_sha256": actual,
                "suffix": suffix,
                "visibility": visibility,
                "disposition": disposition,
            }
        )
    return document, manifest_path, actual_sha, source_id, package_sha, rows


def _is_forbidden_binary_ref(value: str) -> bool:
    suffix = Path(value.split("#", 1)[0]).suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        return False
    normalized = value.replace("\\", "/")
    return (
        "数学一回滚复习系统/快速入库来源/" in normalized
        or "/attachments/" in normalized
        or normalized.startswith("/Volumes/")
        or normalized.startswith("/private/")
        or normalized.startswith("/var/")
        or normalized.startswith("/tmp/")
    )


def _markdown_binary_embeds(text: str) -> list[str]:
    values = re.findall(r"!\[\[([^\]|#]+)", text)
    values.extend(re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", text))
    return list(dict.fromkeys(value for value in values if _is_forbidden_binary_ref(value)))


def _detail_candidate(
    *, formal_id: str, card_text: str, detail_text: str | None, asset_rows: list[dict[str, Any]], study_date: str
) -> str:
    # One formal card can accumulate more than one immutable source manifest.
    # Replacing the managed block with only the newest manifest's assets makes
    # every earlier display-closure receipt stale.  Preserve the card's already
    # published stable assets and render the deterministic union so every
    # source-specific closure can bind the same current Markdown surface.
    display_rows: dict[str, dict[str, Any]] = {
        str(row["stable_vault_relative_path"]): row
        for row in asset_rows
        if row.get("stable_vault_relative_path")
    }
    stable_prefix = (ASSET_ROOT / formal_id).as_posix() + "/"
    role_pattern = re.compile(
        r"^(question|source_article|solution|explanation|user_work)_\d+"
        r"(?:\.png|\.jpe?g|\.webp|\.gif|\.svg)$",
        flags=re.IGNORECASE,
    )
    for value in frontmatter_list(card_text, "lecture_refs"):
        normalized = value.replace("\\", "/")
        if not normalized.startswith(stable_prefix):
            continue
        match = role_pattern.fullmatch(Path(normalized).name)
        if match is None:
            continue
        role = match.group(1).lower()
        display_rows.setdefault(
            normalized,
            {
                "display_role": role,
                "stable_vault_relative_path": normalized,
                "visibility": (
                    "practice_safe"
                    if role in {"question", "source_article"}
                    else "protected"
                ),
            },
        )
    role_order = {
        "question": 0,
        "source_article": 1,
        "solution": 2,
        "explanation": 3,
        "user_work": 4,
    }
    ordered_rows = sorted(
        display_rows.values(),
        key=lambda row: (
            role_order.get(str(row.get("display_role")), 99),
            str(row["stable_vault_relative_path"]),
        ),
    )
    safe = [row for row in ordered_rows if row["visibility"] == "practice_safe"]
    protected = [row for row in ordered_rows if row["visibility"] == "protected"]
    lines = [MANAGED_START, "## 稳定展示资产", ""]
    if safe:
        lines.extend(["### 题目与来源", ""])
        lines.extend(f"![[{row['stable_vault_relative_path']}]]" for row in safe)
        lines.append("")
    if protected:
        lines.extend(["> [!answer]- 解析与作答证据"])
        for row in protected:
            lines.append(f"> ![[{row['stable_vault_relative_path']}]]")
        lines.append("")
    if not safe and not protected:
        lines.extend(["本来源没有需要在 Obsidian 中展示的图片。", ""])
    lines.append(MANAGED_END)
    block = "\n".join(lines) + "\n"
    if detail_text is None:
        subject = frontmatter_scalar(card_text, "subject") or "高等数学"
        title = frontmatter_scalar(card_text, "title") or formal_id
        return (
            "---\n"
            f"visual_id: {json.dumps('VIS-' + formal_id, ensure_ascii=False)}\n"
            f"wrongnet_id: {json.dumps(formal_id, ensure_ascii=False)}\n"
            "source_app: math-formal-intake\n"
            f"subject: {json.dumps(subject, ensure_ascii=False)}\n"
            "status: imported\n"
            "link_status: linked_wrongnet\n"
            f"last_updated: {json.dumps(study_date, ensure_ascii=False)}\n"
            "---\n\n"
            f"# {formal_id}｜{title}\n\n"
            + block
            + "\n## 连线\n\n"
            + f"- [[{CARD_ROOT.as_posix()}/{formal_id}|{formal_id}]]\n"
        )
    if MANAGED_START in detail_text or MANAGED_END in detail_text:
        if detail_text.count(MANAGED_START) != 1 or detail_text.count(MANAGED_END) != 1:
            raise DisplayAssetError("visual_detail_managed_block_invalid")
        start = detail_text.index(MANAGED_START)
        end = detail_text.index(MANAGED_END, start) + len(MANAGED_END)
        return detail_text[:start] + block.rstrip("\n") + detail_text[end:]
    return detail_text.rstrip() + "\n\n" + block


def build_plan(
    *, repo: Path, manifest_relative: str, formal_ids: list[str], expected_manifest_sha256: str | None = None
) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    document, manifest_path, manifest_sha, source_id, package_sha, artifacts = load_source_manifest(
        repo, manifest_relative, expected_manifest_sha256, allow_missing_artifacts=True
    )
    formal_ids = sorted(set(formal_ids))
    if not all(FORMAL_ID_RE.fullmatch(item) for item in formal_ids):
        raise DisplayAssetError("formal_ids_invalid")
    missing = [row for row in artifacts if not safe_repo_path(
        repo, row["package_relative_path"], "display_source", must_exist=False
    ).is_file()]
    if missing:
        # Cleaned raw packages may only reuse a previously verified publication.
        # The candidate proves current surfaces without publishing anything.
        base = _receipt_path(repo, source_id, formal_ids)
        if not base.is_file() or base.is_symlink():
            raise DisplayAssetError("source_artifact_missing_without_display_receipt")
        _, candidate = _card_surface_successor(repo, base)
        verify_closure_for_source(
            repo=repo, manifest_relative=manifest_relative,
            expected_manifest_sha256=manifest_sha, expected_package_sha256=package_sha,
            formal_ids=formal_ids, _candidate=candidate,
        )
        for row in missing:
            for formal_id in formal_ids or [None]:
                if not any(
                    item.get("formal_id") == formal_id
                    and all(item.get(key) == row[key] for key in (
                        "package_relative_path", "source_sha256", "size", "attachment_role"
                    ))
                    for item in candidate["assets"]
                ):
                    raise DisplayAssetError("source_artifact_missing_receipt_binding_mismatch")
    study_date = str(document.get("study_date") or "")
    cards: list[dict[str, Any]] = []
    plan_assets: list[dict[str, Any]] = []
    if not formal_ids:
        for artifact in artifacts:
            row = dict(artifact)
            row.update(
                {
                    "formal_id": None,
                    "stable_vault_relative_path": None,
                    "disposition": "archive_only",
                }
            )
            plan_assets.append(row)
    for formal_id in formal_ids:
        card = formal_card_path(repo, formal_id)
        card_text = card.read_text(encoding="utf-8")
        detail = detail_path_for_card(repo, formal_id, card, card_text)
        detail_text = detail.read_text(encoding="utf-8") if detail.exists() else None
        unallocated_assets: list[dict[str, Any]] = []
        for artifact in artifacts:
            row = dict(artifact)
            row["formal_id"] = formal_id
            unallocated_assets.append(row)
        formal_assets = allocate_stable_asset_paths(
            repo, formal_id, unallocated_assets
        )
        plan_assets.extend(formal_assets)
        old_refs = frontmatter_list(card_text, "lecture_refs")
        kept_refs = [value for value in old_refs if not _is_forbidden_binary_ref(value)]
        display_refs = [
            str(detail.relative_to(repo).as_posix()),
            *[
                row["stable_vault_relative_path"]
                for row in formal_assets
                if row["disposition"] in DISPLAY_DISPOSITIONS
            ],
        ]
        new_refs = list(dict.fromkeys([*kept_refs, *display_refs]))
        candidate_card = replace_frontmatter_list(card_text, "lecture_refs", new_refs)
        candidate_detail = _detail_candidate(
            formal_id=formal_id,
            card_text=card_text,
            detail_text=detail_text,
            asset_rows=[
                row
                for row in formal_assets
                if row["disposition"] in DISPLAY_DISPOSITIONS
            ],
            study_date=study_date,
        )
        cards.append(
            {
                "formal_id": formal_id,
                "card_path": card.relative_to(repo).as_posix(),
                "card_preimage_sha256": sha256_bytes(card_text.encode("utf-8")),
                "card_candidate_sha256": sha256_bytes(candidate_card.encode("utf-8")),
                "lecture_refs": new_refs,
                "visual_detail_path": detail.relative_to(repo).as_posix(),
                "visual_detail_preimage_sha256": (
                    sha256_bytes(detail_text.encode("utf-8")) if detail_text is not None else None
                ),
                "visual_detail_candidate_sha256": sha256_bytes(candidate_detail.encode("utf-8")),
            }
        )
    core = {
        "schema_version": PLAN_SCHEMA,
        "subject": "math",
        "source_manifest_path": manifest_path.relative_to(repo).as_posix(),
        "source_manifest_sha256": manifest_sha,
        "source_schema_version": document["schema_version"],
        "package_id": source_id,
        "package_sha256": package_sha,
        "study_date": study_date,
        "formal_ids": formal_ids,
        "assets": plan_assets,
        "cards": cards,
    }
    plan_sha = sha256_bytes(canonical_json_bytes(core))
    return {
        **core,
        "plan_id": "MATH-DISPLAY-PLAN-" + plan_sha[:24],
        "plan_sha256": plan_sha,
        "authorization": "MATH-DISPLAY-ASSET-APPLY-" + plan_sha,
        "preview_write_count": 0,
    }


def _rebuild_candidates(repo: Path, plan: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    card_candidates: dict[str, str] = {}
    detail_candidates: dict[str, str] = {}
    assets_by_formal: dict[str, list[dict[str, Any]]] = {}
    for row in plan["assets"]:
        assets_by_formal.setdefault(row["formal_id"], []).append(row)
    for card_row in plan["cards"]:
        card = safe_repo_path(repo, card_row["card_path"], "formal_card")
        card_text = card.read_text(encoding="utf-8")
        card_hash = sha256_bytes(card_text.encode("utf-8"))
        if card_hash not in {
            card_row["card_preimage_sha256"],
            card_row["card_candidate_sha256"],
        }:
            raise DisplayAssetError("formal_card_preimage_drift")
        candidate = replace_frontmatter_list(card_text, "lecture_refs", card_row["lecture_refs"])
        if sha256_bytes(candidate.encode("utf-8")) != card_row["card_candidate_sha256"]:
            raise DisplayAssetError("formal_card_candidate_drift")
        detail = safe_repo_path(
            repo, card_row["visual_detail_path"], "visual_detail", must_exist=False
        )
        detail_text = detail.read_text(encoding="utf-8") if detail.exists() else None
        actual_preimage = sha256_bytes(detail_text.encode("utf-8")) if detail_text is not None else None
        if actual_preimage not in {
            card_row["visual_detail_preimage_sha256"],
            card_row["visual_detail_candidate_sha256"],
        }:
            raise DisplayAssetError("visual_detail_preimage_drift")
        detail_candidate = _detail_candidate(
            formal_id=card_row["formal_id"],
            card_text=card_text,
            detail_text=detail_text,
            asset_rows=[
                row for row in assets_by_formal.get(card_row["formal_id"], [])
                if row["disposition"] in DISPLAY_DISPOSITIONS
            ],
            study_date=plan["study_date"],
        )
        if sha256_bytes(detail_candidate.encode("utf-8")) != card_row["visual_detail_candidate_sha256"]:
            raise DisplayAssetError("visual_detail_candidate_drift")
        card_candidates[card_row["card_path"]] = candidate
        detail_candidates[card_row["visual_detail_path"]] = detail_candidate
    return card_candidates, detail_candidates


def resolve_markdown_embed_path(
    repo: Path, carrier: Path, reference: str
) -> Path | None:
    """Resolve explicit dot-relative embeds from their note; others from vault root."""
    relative = Path(reference)
    if relative.is_absolute() or not relative.parts:
        return None
    base = (
        carrier.parent
        if reference.startswith("./") or reference.startswith("../")
        else repo
    )
    try:
        root = repo.resolve(strict=True)
        candidate = (base / relative).resolve(strict=False)
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if candidate.is_symlink() or not candidate.is_file():
        return None
    return candidate


def scan_formal_references(repo: Path, formal_ids: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    forbidden: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    for formal_id in sorted(formal_ids):
        card = formal_card_path(repo, formal_id)
        card_text = card.read_text(encoding="utf-8")
        refs = frontmatter_list(card_text, "lecture_refs")
        for ref in refs:
            if _is_forbidden_binary_ref(ref):
                forbidden.append({"formal_id": formal_id, "surface": card.relative_to(repo).as_posix(), "reference": ref})
            suffix = Path(ref).suffix.lower()
            if suffix in IMAGE_SUFFIXES and resolve_markdown_embed_path(repo, card, ref) is None:
                missing.append({"formal_id": formal_id, "surface": card.relative_to(repo).as_posix(), "reference": ref})
        details = sorted((repo / DETAIL_ROOT).rglob(f"{formal_id}_*.md"))
        for detail in details:
            text = detail.read_text(encoding="utf-8")
            for ref in re.findall(r"!\[\[([^\]|#]+)", text):
                if _is_forbidden_binary_ref(ref):
                    forbidden.append({"formal_id": formal_id, "surface": detail.relative_to(repo).as_posix(), "reference": ref})
                if (
                    Path(ref).suffix.lower() in IMAGE_SUFFIXES
                    and resolve_markdown_embed_path(repo, detail, ref) is None
                ):
                    missing.append({"formal_id": formal_id, "surface": detail.relative_to(repo).as_posix(), "reference": ref})
        rows.append({"formal_id": formal_id, "card_path": card.relative_to(repo).as_posix(), "lecture_refs": refs})
    core = {"formal_ids": sorted(formal_ids), "surfaces": rows, "forbidden_binary_refs": forbidden, "missing_binary_refs": missing}
    return {
        "schema_version": "math-formal-reference-scan-v1",
        **core,
        "status": "passed" if not forbidden and not missing else "failed",
        "formal_reference_scan_sha256": sha256_bytes(canonical_json_bytes(core)),
    }


def _binding_directory(repo: Path, source_id: str, formal_ids: list[str]) -> Path:
    binding = sha256_bytes(canonical_json_bytes(sorted(set(formal_ids))))[:16]
    return repo / PLAN_ROOT / source_id / f"binding-{binding}"


def _receipt_path(repo: Path, source_id: str, formal_ids: list[str]) -> Path:
    return _binding_directory(repo, source_id, formal_ids) / "display-asset-closure-receipt.json"


def _plan_path(repo: Path, source_id: str, formal_ids: list[str]) -> Path:
    return _binding_directory(repo, source_id, formal_ids) / "display-asset-plan.json"


def publish_plan(*, repo: Path, plan: dict[str, Any], authorization: str) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    expected_core = {key: value for key, value in plan.items() if key not in {"plan_id", "plan_sha256", "authorization", "preview_write_count"}}
    expected_sha = sha256_bytes(canonical_json_bytes(expected_core))
    if (
        plan.get("schema_version") != PLAN_SCHEMA
        or plan.get("plan_sha256") != expected_sha
        or plan.get("plan_id") != "MATH-DISPLAY-PLAN-" + expected_sha[:24]
        or plan.get("authorization") != "MATH-DISPLAY-ASSET-APPLY-" + expected_sha
        or authorization != plan.get("authorization")
    ):
        raise DisplayAssetError("display_plan_authorization_mismatch")
    existing_receipt = _receipt_path(
        repo, str(plan.get("package_id")), plan.get("formal_ids") or []
    )
    if existing_receipt.is_file():
        try:
            verified = verify_closure_for_source(
                repo=repo,
                manifest_relative=plan["source_manifest_path"],
                expected_manifest_sha256=plan["source_manifest_sha256"],
                expected_package_sha256=plan["package_sha256"],
                formal_ids=plan["formal_ids"],
            )
            return {"status": "noop", **verified}
        except DisplayAssetError as exc:
            if str(exc) != "display_closure_markdown_surface_drift":
                raise
            return publish_card_surface_successor(repo, plan, existing_receipt)
    with display_lock(repo):
        load_source_manifest(
            repo, plan["source_manifest_path"], plan["source_manifest_sha256"]
        )
        plan_path = _plan_path(repo, plan["package_id"], plan["formal_ids"])
        plan_bytes = canonical_json_bytes(plan)
        if plan_path.exists() and plan_path.read_bytes() != plan_bytes:
            raise DisplayAssetError("display_plan_sidecar_conflict")
        if not plan_path.exists():
            atomic_write(plan_path, plan_bytes)
        if plan_path.read_bytes() != plan_bytes:
            raise DisplayAssetError("display_plan_sidecar_reread_failed")
        card_candidates, detail_candidates = _rebuild_candidates(repo, plan)
        copy_targets: dict[str, dict[str, Any]] = {}
        for row in plan["assets"]:
            disposition = row["disposition"]
            if disposition not in DISPLAY_DISPOSITIONS:
                continue
            source = safe_repo_path(repo, row["package_relative_path"], "display_source")
            if sha256_file(source) != row["source_sha256"]:
                raise DisplayAssetError("display_source_hash_drift")
            target = safe_repo_path(
                repo, row["stable_vault_relative_path"], "stable_display_asset", must_exist=False
            )
            if disposition == "already_stable":
                if (
                    target.is_symlink()
                    or not target.is_file()
                    or sha256_file(target) != row["source_sha256"]
                ):
                    raise DisplayAssetError("already_stable_asset_drift")
                continue
            if target.exists():
                raise DisplayAssetError("stable_display_asset_race_conflict")
            existing_copy = copy_targets.get(row["stable_vault_relative_path"])
            if existing_copy is not None and existing_copy["source_sha256"] != row["source_sha256"]:
                raise DisplayAssetError("planned_stable_asset_collision")
            copy_targets[row["stable_vault_relative_path"]] = {
                "source": source,
                "target": target,
                "source_sha256": row["source_sha256"],
            }
        for copy in copy_targets.values():
            source = copy["source"]
            target = copy["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{target.name}.", dir=target.parent
            )
            os.close(descriptor)
            temp_path = Path(temp_name)
            try:
                shutil.copy2(source, temp_path)
                if sha256_file(temp_path) != copy["source_sha256"]:
                    raise DisplayAssetError("stable_display_asset_stage_hash_mismatch")
                try:
                    os.link(temp_path, target)
                except FileExistsError as exc:
                    raise DisplayAssetError(
                        "stable_display_asset_race_conflict"
                    ) from exc
            finally:
                if temp_path.exists():
                    temp_path.unlink()
        for relative, candidate in detail_candidates.items():
            atomic_write(repo / relative, candidate.encode("utf-8"))
        for relative, candidate in card_candidates.items():
            atomic_write(repo / relative, candidate.encode("utf-8"))
        bridge = (
            refresh_bridge_membership(
                repo,
                f"{plan['package_id']}/binding-{sha256_bytes(canonical_json_bytes(plan['formal_ids']))[:16]}",
                plan["formal_ids"],
            )
            if plan["formal_ids"]
            else {"status": "not_applicable", "membership": []}
        )
        scan = scan_formal_references(repo, plan["formal_ids"])
        if scan["status"] != "passed":
            raise DisplayAssetError("formal_reference_scan_failed")
        asset_receipts: list[dict[str, Any]] = []
        markdown_sha = {
            **{path: sha256_file(repo / path) for path in card_candidates},
            **{path: sha256_file(repo / path) for path in detail_candidates},
        }
        for row in plan["assets"]:
            item = {key: value for key, value in row.items() if key != "suffix"}
            stable = row.get("stable_vault_relative_path")
            if stable:
                target = repo / stable
                if not target.is_file() or sha256_file(target) != row["source_sha256"]:
                    raise DisplayAssetError("stable_display_asset_reread_failed")
                detail_path = next(
                    card["visual_detail_path"] for card in plan["cards"] if card["formal_id"] == row["formal_id"]
                )
                if f"![[{stable}]]" not in (repo / detail_path).read_text(encoding="utf-8"):
                    raise DisplayAssetError("stable_display_asset_embed_missing")
                item.update(
                    {
                        "stable_file_sha256": row["source_sha256"],
                        "markdown_path": detail_path,
                        "markdown_sha256": markdown_sha[detail_path],
                        "embed_resolved": True,
                        "obsidian_reread_status": "verified",
                    }
                )
            asset_receipts.append(item)
        stable_count = sum(1 for row in asset_receipts if row.get("stable_vault_relative_path"))
        receipt_core = {
            "schema_version": CLOSURE_SCHEMA,
            "subject": "math",
            "plan_id": plan["plan_id"],
            "plan_sha256": plan["plan_sha256"],
            "package_id": plan["package_id"],
            "package_sha256": plan["package_sha256"],
            "source_manifest_path": plan["source_manifest_path"],
            "source_manifest_sha256": plan["source_manifest_sha256"],
            "formal_ids": plan["formal_ids"],
            "assets": asset_receipts,
            "markdown_surfaces": [
                {"path": path, "sha256": digest} for path, digest in sorted(markdown_sha.items())
            ],
            "stable_asset_count": stable_count,
            "no_display_proof": stable_count == 0,
            "formal_reference_scan": scan,
            "formal_reference_scan_sha256": scan["formal_reference_scan_sha256"],
            "bridge_membership": bridge,
            "pending_component": None,
            "status": "verified",
        }
        receipt_id = "MATH-DISPLAY-CLOSE-" + sha256_bytes(canonical_json_bytes(receipt_core))[:24]
        receipt = {**receipt_core, "receipt_id": receipt_id}
        receipt_path = _receipt_path(repo, plan["package_id"], plan["formal_ids"])
        receipt_bytes = canonical_json_bytes(receipt)
        for path, data, error in (
            (plan_path, plan_bytes, "display_plan_sidecar_conflict"),
            (receipt_path, receipt_bytes, "display_closure_receipt_conflict"),
        ):
            if path.exists() and path.read_bytes() != data:
                raise DisplayAssetError(error)
            if not path.exists():
                atomic_write(path, data)
            if path.read_bytes() != data:
                raise DisplayAssetError(error + "_reread")
        verified = verify_closure_for_source(
            repo=repo,
            manifest_relative=plan["source_manifest_path"],
            expected_manifest_sha256=plan["source_manifest_sha256"],
            expected_package_sha256=plan["package_sha256"],
            formal_ids=plan["formal_ids"],
        )
        return {"status": "recorded", **verified}


def _card_surface_successor(repo: Path, base_path: Path) -> tuple[Path, dict[str, Any]]:
    """Prove a monotonic display extension without changing its base receipt."""
    def reject_symlink_components(path: Path) -> None:
        for component in (path, *path.parents):
            if component == repo:
                break
            if component.is_symlink():
                raise DisplayAssetError("display_successor_symlink")

    reject_symlink_components(base_path)
    if base_path.is_symlink():
        raise DisplayAssetError("display_successor_base_symlink")
    original = json.loads(base_path.read_text(encoding="utf-8"))
    core = {k: v for k, v in original.items() if k != "receipt_id"}
    if original.get("receipt_id") != "MATH-DISPLAY-CLOSE-" + sha256_bytes(canonical_json_bytes(core))[:24]:
        raise DisplayAssetError("display_closure_receipt_id_mismatch")
    assets = []
    for old in original["assets"]:
        item = dict(old)
        stable = item.get("stable_vault_relative_path")
        if stable is not None:
            target = safe_repo_path(repo, stable, "stable_display_asset")
            reject_symlink_components(target)
            if (not target.is_file() or sha256_file(target) != item.get("source_sha256")
                    or item.get("stable_file_sha256") != item.get("source_sha256")):
                raise DisplayAssetError("display_closure_stable_asset_mismatch")
            markdown = safe_repo_path(repo, item["markdown_path"], "display_markdown")
            if f"![[{stable}]]" not in markdown.read_text(encoding="utf-8"):
                raise DisplayAssetError("display_closure_embed_mismatch")
            item["markdown_sha256"] = sha256_file(markdown)
        assets.append(item)
    surfaces = []
    for old in original["markdown_surfaces"]:
        path = safe_repo_path(repo, old["path"], "display_successor_surface")
        digest = sha256_file(path)
        surfaces.append({"path": old["path"], "sha256": digest})
    scan = scan_formal_references(repo, original["formal_ids"])
    if scan["status"] != "passed":
        raise DisplayAssetError("display_successor_reference_drift")
    old_rows = {row["formal_id"]: row for row in original["formal_reference_scan"]["surfaces"]}
    for row in scan["surfaces"]:
        old = old_rows[row["formal_id"]]
        if (row["card_path"] != old["card_path"]
                or not set(old["lecture_refs"]).issubset(row["lecture_refs"])):
            raise DisplayAssetError("display_successor_reference_drift")
        for ref in set(row["lecture_refs"]) - set(old["lecture_refs"]):
            target = safe_repo_path(repo, ref, "display_successor_reference")
            reject_symlink_components(target)
            if not target.is_file():
                raise DisplayAssetError("display_successor_reference_invalid")
            if Path(ref).suffix.lower() in IMAGE_SUFFIXES:
                try:
                    target.resolve().relative_to((repo / ASSET_ROOT).resolve())
                except ValueError as exc:
                    raise DisplayAssetError("display_successor_reference_not_stable") from exc
        for detail in (repo / DETAIL_ROOT).rglob(f"{row['formal_id']}_*.md"):
            reject_symlink_components(detail)
            text = detail.read_text(encoding="utf-8")
            refs = re.findall(r"!\[\[([^\]|#]+)", text)
            refs.extend(re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", text))
            for ref in refs:
                if Path(ref).suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                reject_symlink_components(
                    (detail.parent if ref.startswith(("./", "../")) else repo) / ref
                )
                target = resolve_markdown_embed_path(repo, detail, ref)
                if target is None or _is_forbidden_binary_ref(ref):
                    raise DisplayAssetError("display_successor_reference_invalid")
                try:
                    target.relative_to((repo / ASSET_ROOT).resolve())
                except ValueError as exc:
                    raise DisplayAssetError("display_successor_reference_not_stable") from exc
    core["assets"] = assets
    core["markdown_surfaces"] = surfaces
    core["formal_reference_scan"] = scan
    core["formal_reference_scan_sha256"] = scan["formal_reference_scan_sha256"]
    core["card_surface_predecessor"] = {
        "path": base_path.relative_to(repo).as_posix(),
        "sha256": sha256_file(base_path),
        "receipt_id": original["receipt_id"],
    }
    result = {**core, "receipt_id": "MATH-DISPLAY-CLOSE-" + sha256_bytes(canonical_json_bytes(core))[:24]}
    digest = sha256_bytes(canonical_json_bytes(result))
    candidate = base_path.parent / "card-surface-successors" / (digest + ".json")
    for parent in (candidate, *candidate.parents):
        if parent == repo:
            break
        if parent.is_symlink():
            raise DisplayAssetError("display_successor_symlink")
    safe_repo_path(repo, candidate.relative_to(repo).as_posix(), "display_successor", must_exist=False)
    return candidate, result


def publish_card_surface_successor(repo: Path, plan: dict[str, Any], base_path: Path) -> dict[str, Any]:
    """Append a deterministic successor under the exact fresh plan authorization."""
    with display_lock(repo):
        fresh = build_plan(repo=repo, manifest_relative=plan["source_manifest_path"],
                           formal_ids=plan["formal_ids"],
                           expected_manifest_sha256=plan["source_manifest_sha256"])
        if fresh != plan:
            raise DisplayAssetError("display_successor_plan_drift")
        successor_path, successor = _card_surface_successor(repo, base_path)
        # Verify every unchanged condition before creating the successor file.
        verify_closure_for_source(repo=repo, manifest_relative=plan["source_manifest_path"],
                                  expected_manifest_sha256=plan["source_manifest_sha256"],
                                  expected_package_sha256=plan["package_sha256"],
                                  formal_ids=plan["formal_ids"], _candidate=successor)
        data = canonical_json_bytes(successor)
        if successor_path.is_symlink():
            raise DisplayAssetError("display_successor_symlink")
        if successor_path.exists() and successor_path.read_bytes() != data:
            raise DisplayAssetError("display_successor_conflict")
        if not successor_path.exists():
            atomic_write(successor_path, data)
        verified = verify_closure_for_source(repo=repo, manifest_relative=plan["source_manifest_path"],
                                            expected_manifest_sha256=plan["source_manifest_sha256"],
                                            expected_package_sha256=plan["package_sha256"],
                                            formal_ids=plan["formal_ids"])
        return {"status": "recorded", "card_surface_successor": True, **verified}


def verify_closure_for_source(
    *,
    repo: Path,
    manifest_relative: str,
    expected_manifest_sha256: str,
    expected_package_sha256: str | None,
    formal_ids: list[str],
    _candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    document, _, manifest_sha, source_id, package_sha, _ = load_source_manifest(
        repo,
        manifest_relative,
        expected_manifest_sha256,
        allow_missing_artifacts=True,
    )
    if expected_package_sha256 is not None and package_sha != expected_package_sha256:
        raise DisplayAssetError("display_closure_package_sha256_mismatch")
    path = _receipt_path(repo, source_id, formal_ids)
    if path.is_symlink() or not path.is_file():
        raise DisplayAssetError("display_closure_receipt_missing")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DisplayAssetError("display_closure_receipt_invalid") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != CLOSURE_SCHEMA
        or receipt.get("status") != "verified"
        or receipt.get("subject") != "math"
        or receipt.get("package_id") != source_id
        or receipt.get("package_sha256") != package_sha
        or receipt.get("source_manifest_path") != manifest_relative
        or receipt.get("source_manifest_sha256") != manifest_sha
        or receipt.get("formal_ids") != sorted(set(formal_ids))
        or receipt.get("pending_component") is not None
    ):
        raise DisplayAssetError("display_closure_receipt_binding_mismatch")
    if _candidate is not None:
        _, expected = _card_surface_successor(repo, path)
        if _candidate != expected:
            raise DisplayAssetError("display_successor_candidate_mismatch")
        receipt = _candidate
    elif any(sha256_file(safe_repo_path(repo, surface["path"], "display_markdown_surface"))
             != surface["sha256"] for surface in receipt.get("markdown_surfaces", [])):
        successor_path, expected = _card_surface_successor(repo, path)
        if successor_path.is_symlink():
            raise DisplayAssetError("display_successor_symlink")
        if successor_path.is_file():
            if successor_path.read_bytes() != canonical_json_bytes(expected):
                raise DisplayAssetError("display_successor_bytes_mismatch")
            path, receipt = successor_path, expected
        else:
            raise DisplayAssetError("display_closure_markdown_surface_drift")
    stable_count = 0
    for item in receipt.get("assets", []):
        if not isinstance(item, dict):
            raise DisplayAssetError("display_closure_asset_invalid")
        stable = item.get("stable_vault_relative_path")
        if stable is None:
            if item.get("disposition") not in {"archive_only", "no_display"}:
                raise DisplayAssetError("display_closure_disposition_invalid")
            continue
        target = safe_repo_path(repo, stable, "stable_display_asset")
        if (
            not target.is_file()
            or sha256_file(target) != item.get("stable_file_sha256")
            or item.get("stable_file_sha256") != item.get("source_sha256")
            or item.get("embed_resolved") is not True
            or item.get("obsidian_reread_status") != "verified"
        ):
            raise DisplayAssetError("display_closure_stable_asset_mismatch")
        markdown = safe_repo_path(repo, item.get("markdown_path"), "display_markdown")
        if sha256_file(markdown) != item.get("markdown_sha256") or f"![[{stable}]]" not in markdown.read_text(encoding="utf-8"):
            raise DisplayAssetError("display_closure_embed_mismatch")
        stable_count += 1
    for surface in receipt.get("markdown_surfaces", []):
        path_value = surface.get("path") if isinstance(surface, dict) else None
        digest = surface.get("sha256") if isinstance(surface, dict) else None
        surface_path = safe_repo_path(repo, path_value, "display_markdown_surface")
        if sha256_file(surface_path) != digest:
            raise DisplayAssetError("display_closure_markdown_surface_drift")
    scan = scan_formal_references(repo, formal_ids)
    if scan["status"] != "passed" or scan != receipt.get("formal_reference_scan"):
        raise DisplayAssetError("display_closure_formal_reference_scan_drift")
    if (
        receipt.get("stable_asset_count") != stable_count
        or receipt.get("no_display_proof") is not (stable_count == 0)
        or receipt.get("formal_reference_scan_sha256") != scan["formal_reference_scan_sha256"]
    ):
        raise DisplayAssetError("display_closure_count_or_scan_mismatch")
    bridge = receipt.get("bridge_membership")
    if not isinstance(bridge, dict) or bridge.get("status") not in {
        "verified",
        "not_applicable",
    }:
        raise DisplayAssetError("display_closure_bridge_proof_missing")
    bridge_ids: set[str] = set()
    if formal_ids:
        bridge_path = safe_repo_path(repo, bridge.get("snapshot_path"), "bridge_snapshot")
        if sha256_file(bridge_path) != bridge.get("snapshot_sha256"):
            raise DisplayAssetError("display_closure_bridge_snapshot_drift")
        try:
            bridge_document = json.loads(bridge_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DisplayAssetError("display_closure_bridge_snapshot_invalid") from exc
        bridge_ids = {
            row.get("wrongnet_id")
            for row in bridge_document.get("records", [])
            if isinstance(row, dict)
        }
    membership_ids = {
        row.get("formal_id")
        for row in bridge.get("membership", [])
        if isinstance(row, dict)
    }
    if set(formal_ids) != membership_ids or not set(formal_ids).issubset(bridge_ids):
        raise DisplayAssetError("display_closure_bridge_membership_drift")
    core = {key: value for key, value in receipt.items() if key != "receipt_id"}
    if receipt.get("receipt_id") != "MATH-DISPLAY-CLOSE-" + sha256_bytes(canonical_json_bytes(core))[:24]:
        raise DisplayAssetError("display_closure_receipt_id_mismatch")
    return {
        "display_closure_receipt_id": receipt["receipt_id"],
        "display_closure_receipt_path": path.relative_to(repo).as_posix(),
        "display_closure_receipt_sha256": sha256_file(path),
        "formal_reference_scan_sha256": scan["formal_reference_scan_sha256"],
        "stable_asset_count": stable_count,
        "no_display_proof": stable_count == 0,
        "pending_component": None,
    }


def verify_closure_for_formal(
    *,
    repo: Path,
    manifest_relative: str,
    expected_manifest_sha256: str,
    formal_id: str,
) -> dict[str, Any]:
    """Resolve the sidecar's formal-ID set, then require one exact member.

    A package may legitimately map to more than one formal card, so callers
    linting one card must not weaken the receipt by pretending the package had
    only that one target.
    """
    repo = repo.resolve(strict=True)
    _, _, _, source_id, package_sha, _ = load_source_manifest(
        repo,
        manifest_relative,
        expected_manifest_sha256,
        allow_missing_artifacts=True,
    )
    candidates = sorted((repo / PLAN_ROOT / source_id).glob("binding-*/display-asset-closure-receipt.json"))
    matching: list[tuple[Path, list[str]]] = []
    for path in candidates:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        receipt_formal_ids = receipt.get("formal_ids") if isinstance(receipt, dict) else None
        if isinstance(receipt_formal_ids, list) and formal_id in receipt_formal_ids:
            matching.append((path, receipt_formal_ids))
    if len(matching) != 1:
        raise DisplayAssetError("display_closure_formal_id_not_uniquely_bound")
    _, receipt_formal_ids = matching[0]
    return verify_closure_for_source(
        repo=repo,
        manifest_relative=manifest_relative,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_package_sha256=package_sha,
        formal_ids=receipt_formal_ids,
    )


def _parse_locator(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("package_id", "raw_archive_relpath", "raw_archive_manifest_sha256", "raw_archive_package_sha256"):
        match = re.search(rf"(?m)^{key}:\s*(.+)$", text)
        if match:
            raw = match.group(1).strip()
            try:
                result[key] = json.loads(raw) if raw.startswith('"') else raw
            except json.JSONDecodeError:
                result[key] = raw
    result["formal_ids"] = [
        value for value in re.findall(r"(?m)^\s+-\s+['\"]?((?:GS|LA|PR)-\d+)['\"]?\s*$", text)
    ]
    return result


def historical_preview(
    *, repo: Path, archive_root: Path, formal_ids: list[str] | None = None
) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    archive_root = validate_archive_root(archive_root)
    selected = set(formal_ids or [])
    cards: list[dict[str, Any]] = []
    recoverable_count = 0
    broken_count = 0
    locator_index: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for locator_path in sorted((repo / LOCATOR_ROOT).glob("*.md")):
        parsed = _parse_locator(locator_path.read_text(encoding="utf-8"))
        for formal_id in parsed.get("formal_ids", []):
            locator_index.setdefault(formal_id, []).append((locator_path, parsed))
    for card in sorted((repo / CARD_ROOT).glob("*.md")):
        text = card.read_text(encoding="utf-8")
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            continue
        formal_id = frontmatter_scalar(text, "id")
        if selected and formal_id not in selected:
            continue
        lecture_broken = [
            ref for ref in frontmatter_list(text, "lecture_refs")
            if _is_forbidden_binary_ref(ref) and not (repo / ref).is_file()
        ]
        card_embed_broken = [
            ref for ref in _markdown_binary_embeds(text) if not (repo / ref).is_file()
        ]
        detail_matches = sorted((repo / DETAIL_ROOT).rglob(f"{formal_id}_*.md"))
        detail_embed_broken: list[str] = []
        for candidate in detail_matches:
            candidate_text = candidate.read_text(encoding="utf-8")
            detail_embed_broken.extend(
                ref
                for ref in _markdown_binary_embeds(candidate_text)
                if not (repo / ref).is_file()
            )
        detail_embed_broken = list(dict.fromkeys(detail_embed_broken))
        if not lecture_broken and not card_embed_broken and not detail_embed_broken:
            continue
        if len(detail_matches) > 1:
            raise DisplayAssetError("visual_detail_not_unique")
        detail_path = (
            detail_matches[0]
            if detail_matches
            else detail_path_for_card(repo, formal_id, card, text)
        )
        detail_text = detail_path.read_text(encoding="utf-8") if detail_path.is_file() else ""
        broken = list(
            dict.fromkeys(
                [*lecture_broken, *card_embed_broken, *detail_embed_broken]
            )
        )
        broken_count += len(broken)
        items: list[dict[str, Any]] = []
        locators = locator_index.get(formal_id, [])
        for ref in broken:
            matches: list[dict[str, Any]] = []
            for locator_path, locator in locators:
                rel = locator.get("raw_archive_relpath")
                if not isinstance(rel, str):
                    continue
                try:
                    package_dir = exact_archive_package(archive_root, rel)
                except DisplayAssetError:
                    continue
                manifest = package_dir / "manifest.json"
                if (
                    manifest.is_symlink()
                    or not manifest.is_file()
                    or sha256_file(manifest) != locator.get("raw_archive_manifest_sha256")
                ):
                    continue
                try:
                    document = json.loads(manifest.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    continue
                for payload in document.get("payload_files", document.get("artifacts", [])):
                    if not isinstance(payload, dict):
                        continue
                    original = payload.get("original_path") or payload.get("path")
                    archived = payload.get("archive_path")
                    if original != ref or not isinstance(archived, str):
                        continue
                    try:
                        archive_path = exact_archive_file(package_dir, archived)
                    except DisplayAssetError:
                        continue
                    if (
                        archive_path.is_file()
                        and sha256_file(archive_path) == payload.get("sha256")
                        and archive_path.stat().st_size == payload.get("size")
                    ):
                        role, visibility, _ = _artifact_role(str(payload.get("role") or "other_attachment"))
                        matches.append(
                            {
                                "locator_path": locator_path.relative_to(repo).as_posix(),
                                "package_id": locator.get("package_id"),
                                "raw_archive_relpath": rel,
                                "archive_relative_file": archived,
                                "source_sha256": payload["sha256"],
                                "size": payload["size"],
                                "display_role": role,
                                "visibility": visibility,
                                "suffix": Path(ref).suffix.lower(),
                            }
                        )
            if len(matches) == 1:
                match = matches[0]
                items.append(
                    {
                        "broken_reference": ref,
                        "reference_surfaces": sorted(
                            [
                                *(["card_lecture_refs"] if ref in lecture_broken else []),
                                *(["card_embed"] if ref in card_embed_broken else []),
                                *(["visual_detail_embed"] if ref in detail_embed_broken else []),
                            ]
                        ),
                        "status": "recoverable",
                        "disposition": "promoted",
                        **match,
                    }
                )
                recoverable_count += 1
            else:
                items.append(
                    {
                        "broken_reference": ref,
                        "status": "needs_user",
                        "reason": "no_unique_exact_archive_match" if not matches else "multiple_exact_archive_matches",
                    }
                )
        recoverable_indexes = [
            index for index, item in enumerate(items) if item["status"] == "recoverable"
        ]
        allocated = allocate_stable_asset_paths(
            repo, formal_id, [items[index] for index in recoverable_indexes]
        )
        for index, item in zip(recoverable_indexes, allocated):
            items[index] = item
        cards.append(
            {
                "formal_id": formal_id,
                "card_path": card.relative_to(repo).as_posix(),
                "card_preimage_sha256": sha256_file(card),
                "visual_detail_path": detail_path.relative_to(repo).as_posix(),
                "visual_detail_preimage_sha256": (
                    sha256_file(detail_path)
                    if detail_path.is_file()
                    else None
                ),
                "items": items,
            }
        )
    core = {
        "schema_version": HISTORICAL_PLAN_SCHEMA,
        "subject": "math",
        "archive_root": str(archive_root),
        "cards": cards,
        "card_count": len(cards),
        "broken_reference_count": broken_count,
        "recoverable_reference_count": recoverable_count,
        "needs_user_reference_count": broken_count - recoverable_count,
    }
    digest = sha256_bytes(canonical_json_bytes(core))
    return {
        **core,
        "plan_id": "MATH-DISPLAY-HIST-" + digest[:24],
        "plan_sha256": digest,
        "authorization": "MATH-DISPLAY-HISTORICAL-APPLY-" + digest,
        "preview_write_count": 0,
    }


def apply_historical_plan(
    *, repo: Path, plan: dict[str, Any], authorization: str, apply: bool
) -> dict[str, Any]:
    """Apply only an exact preview; default invocation remains zero-write."""
    core = {
        key: value
        for key, value in plan.items()
        if key not in {"plan_id", "plan_sha256", "authorization", "preview_write_count"}
    }
    digest = sha256_bytes(canonical_json_bytes(core))
    expected_authorization = "MATH-DISPLAY-HISTORICAL-APPLY-" + digest
    if (
        plan.get("schema_version") != HISTORICAL_PLAN_SCHEMA
        or plan.get("plan_sha256") != digest
        or plan.get("plan_id") != "MATH-DISPLAY-HIST-" + digest[:24]
        or plan.get("authorization") != expected_authorization
        or authorization != expected_authorization
    ):
        raise DisplayAssetError("historical_repair_authorization_mismatch")
    if not apply:
        return {**plan, "status": "preview", "preview_write_count": 0}
    repo = repo.resolve(strict=True)
    archive_root = validate_archive_root(Path(plan["archive_root"]))
    # Validate every byte and preimage before the first write.  A card/archive
    # identity mismatch is safety contamination, not an ordinary per-card gap.
    prepared: list[dict[str, Any]] = []
    with display_lock(repo):
        for card_row in plan["cards"]:
            card = safe_repo_path(repo, card_row["card_path"], "historical_formal_card")
            card_text = card.read_text(encoding="utf-8")
            if sha256_file(card) != card_row["card_preimage_sha256"]:
                raise DisplayAssetError("historical_formal_card_preimage_drift")
            detail = safe_repo_path(
                repo, card_row["visual_detail_path"], "historical_visual_detail", must_exist=False
            )
            detail_text = detail.read_text(encoding="utf-8") if detail.exists() else None
            detail_preimage = sha256_bytes(detail_text.encode("utf-8")) if detail_text is not None else None
            if detail_preimage != card_row["visual_detail_preimage_sha256"]:
                raise DisplayAssetError("historical_visual_detail_preimage_drift")
            promoted: list[dict[str, Any]] = []
            refs = frontmatter_list(card_text, "lecture_refs")
            lecture_ref_replacements: dict[str, str] = {}
            for item in card_row["items"]:
                if item["status"] != "recoverable":
                    continue
                package = exact_archive_package(archive_root, item["raw_archive_relpath"])
                archive_file = exact_archive_file(package, item["archive_relative_file"])
                if (
                    archive_file.is_symlink()
                    or not archive_file.is_file()
                    or archive_file.stat().st_size != item["size"]
                    or sha256_file(archive_file) != item["source_sha256"]
                ):
                    raise DisplayAssetError("historical_archive_byte_mismatch")
                target = safe_repo_path(
                    repo, item["stable_vault_relative_path"], "historical_stable_asset", must_exist=False
                )
                if item["disposition"] == "already_stable":
                    if (
                        target.is_symlink()
                        or not target.is_file()
                        or sha256_file(target) != item["source_sha256"]
                    ):
                        raise DisplayAssetError("historical_already_stable_asset_drift")
                elif target.exists():
                    raise DisplayAssetError("historical_stable_asset_race_conflict")
                promoted.append({**item, "archive_file": archive_file, "target": target})
                surfaces = set(item.get("reference_surfaces") or [])
                if "card_lecture_refs" in surfaces or (
                    not surfaces and item["broken_reference"] in refs
                ):
                    existing = lecture_ref_replacements.get(item["broken_reference"])
                    if (
                        existing is not None
                        and existing != item["stable_vault_relative_path"]
                    ):
                        raise DisplayAssetError(
                            "historical_lecture_ref_replacement_conflict"
                        )
                    lecture_ref_replacements[item["broken_reference"]] = item[
                        "stable_vault_relative_path"
                    ]
            candidate_card = replace_frontmatter_list_values(
                card_text,
                "lecture_refs",
                lecture_ref_replacements,
            )
            detail_assets = [
                {
                    "stable_vault_relative_path": item["stable_vault_relative_path"],
                    "visibility": item["visibility"],
                    "disposition": item["disposition"],
                }
                for item in promoted
            ]
            stable_embeds_already_present = (
                detail_text is not None
                and bool(promoted)
                and all(
                    f"![[{item['stable_vault_relative_path']}]]" in detail_text
                    for item in promoted
                )
            )
            candidate_detail = (
                detail_text
                if stable_embeds_already_present
                else _detail_candidate(
                    formal_id=card_row["formal_id"],
                    card_text=card_text,
                    detail_text=detail_text,
                    asset_rows=detail_assets,
                    study_date=frontmatter_scalar(card_text, "date") or "unknown",
                )
            )
            for item in promoted:
                surfaces = set(item.get("reference_surfaces") or [])
                if "card_embed" in surfaces:
                    candidate_card = candidate_card.replace(
                        item["broken_reference"],
                        item["stable_vault_relative_path"],
                    )
                if "visual_detail_embed" in surfaces:
                    candidate_detail = candidate_detail.replace(
                        item["broken_reference"],
                        item["stable_vault_relative_path"],
                    )
            prepared.append(
                {
                    "row": card_row,
                    "card": card,
                    "detail": detail,
                    "candidate_card": candidate_card,
                    "candidate_detail": candidate_detail,
                    "promoted": promoted,
                }
            )
        historical_copy_targets: dict[str, dict[str, Any]] = {}
        for entry in prepared:
            for item in entry["promoted"]:
                target = item["target"]
                if item["disposition"] == "promoted":
                    existing = historical_copy_targets.get(
                        item["stable_vault_relative_path"]
                    )
                    if existing is not None and existing["source_sha256"] != item["source_sha256"]:
                        raise DisplayAssetError("historical_planned_asset_collision")
                    historical_copy_targets[item["stable_vault_relative_path"]] = item
        for item in historical_copy_targets.values():
            target = item["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{target.name}.", dir=target.parent
            )
            os.close(descriptor)
            temp_path = Path(temp_name)
            try:
                shutil.copy2(item["archive_file"], temp_path)
                if sha256_file(temp_path) != item["source_sha256"]:
                    raise DisplayAssetError("historical_stable_asset_stage_mismatch")
                try:
                    os.link(temp_path, target)
                except FileExistsError as exc:
                    raise DisplayAssetError(
                        "historical_stable_asset_race_conflict"
                    ) from exc
            finally:
                if temp_path.exists():
                    temp_path.unlink()
        for entry in prepared:
            atomic_write(entry["detail"], entry["candidate_detail"].encode("utf-8"))
            atomic_write(entry["card"], entry["candidate_card"].encode("utf-8"))
        bridge = refresh_bridge_membership(
            repo, plan["plan_id"], [entry["row"]["formal_id"] for entry in prepared]
        )
        receipts: list[dict[str, Any]] = []
        for entry in prepared:
            card_row = entry["row"]
            unresolved = [item for item in card_row["items"] if item["status"] != "recoverable"]
            receipt_core = {
                "schema_version": HISTORICAL_RECEIPT_SCHEMA,
                "plan_id": plan["plan_id"],
                "plan_sha256": plan["plan_sha256"],
                "formal_id": card_row["formal_id"],
                "card_path": card_row["card_path"],
                "card_preimage_sha256": card_row["card_preimage_sha256"],
                "card_postimage_sha256": sha256_file(entry["card"]),
                "visual_detail_path": card_row["visual_detail_path"],
                "visual_detail_postimage_sha256": sha256_file(entry["detail"]),
                "promoted_assets": [
                    {
                        "broken_reference": item["broken_reference"],
                        "stable_vault_relative_path": item["stable_vault_relative_path"],
                        "source_sha256": item["source_sha256"],
                        "locator_path": item["locator_path"],
                        "disposition": item["disposition"],
                        "reference_surfaces": item.get("reference_surfaces", []),
                    }
                    for item in entry["promoted"]
                ],
                "unresolved": unresolved,
                "bridge_membership": {
                    **bridge,
                    "membership": [
                        item
                        for item in bridge["membership"]
                        if item["formal_id"] == card_row["formal_id"]
                    ],
                },
                "status": "verified" if not unresolved else "needs_user",
            }
            receipt = {
                **receipt_core,
                "receipt_id": "MATH-DISPLAY-HIST-RECEIPT-"
                + sha256_bytes(canonical_json_bytes(receipt_core))[:24],
            }
            path = repo / HISTORICAL_RECEIPT_ROOT / f"{plan['plan_id']}-{card_row['formal_id']}.json"
            data = canonical_json_bytes(receipt)
            if path.exists() and path.read_bytes() != data:
                raise DisplayAssetError("historical_repair_receipt_conflict")
            if not path.exists():
                atomic_write(path, data)
            receipts.append({**receipt, "receipt_path": path.relative_to(repo).as_posix()})
        return {
            "status": "verified" if all(row["status"] == "verified" for row in receipts) else "needs_user",
            "plan_id": plan["plan_id"],
            "receipts": receipts,
            "formal_write_count": 0,
        }


def _historical_repair_receipt(repo: Path, formal_id: str) -> tuple[Path, dict[str, Any]]:
    matches = sorted((repo / HISTORICAL_RECEIPT_ROOT).glob(f"*-{formal_id}.json"))
    if len(matches) != 1:
        raise DisplayAssetError("historical_repair_receipt_not_unique")
    path = matches[0]
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DisplayAssetError("historical_repair_receipt_invalid") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != HISTORICAL_RECEIPT_SCHEMA
        or receipt.get("formal_id") != formal_id
        or receipt.get("status") != "verified"
        or receipt.get("unresolved") != []
    ):
        raise DisplayAssetError("historical_repair_receipt_binding_invalid")
    return path, receipt


def _historical_supplement_path(receipt_path: Path) -> Path:
    return receipt_path.with_name(receipt_path.stem + "-closure-supplement.json")


def _render_frontmatter_list_candidate(
    text: str,
    key: str,
    values: list[str],
    style: str,
) -> str:
    start, end = _frontmatter_bounds(text)
    meta = text[start:end]
    lines = meta.splitlines(keepends=True)
    field_indexes = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(rf"{re.escape(key)}:[ \t]*(?:\r?\n)?", line)
    ]
    if len(field_indexes) != 1:
        raise DisplayAssetError("historical_preimage_list_field_not_unique")
    field_start = field_indexes[0]
    field_end = field_start + 1
    while field_end < len(lines) and re.fullmatch(
        r"[ \t]*-[ \t]+[^\r\n]*(?:\r?\n)?", lines[field_end]
    ):
        field_end += 1
    newline = "\r\n" if text.startswith("---\r\n") else "\n"
    if style == "raw":
        rendered_values = values
    elif style == "single":
        rendered_values = ["'" + value.replace("'", "''") + "'" for value in values]
    elif style == "double":
        rendered_values = [json.dumps(value, ensure_ascii=False) for value in values]
    else:
        raise DisplayAssetError("historical_preimage_quote_style_invalid")
    rendered = [
        key + ":" + newline,
        *[f"  - {value}{newline}" for value in rendered_values],
    ]
    lines[field_start:field_end] = rendered
    return text[:start] + "".join(lines) + text[end:]


def _ordered_interleavings(left: list[str], right: list[str]) -> Iterable[list[str]]:
    if not left:
        yield list(right)
        return
    if not right:
        yield list(left)
        return
    for tail in _ordered_interleavings(left[1:], right):
        yield [left[0], *tail]
    for tail in _ordered_interleavings(left, right[1:]):
        yield [right[0], *tail]


def reconstruct_historical_card_preimage(
    *, card_text: str, receipt: dict[str, Any]
) -> str:
    trusted_sha = receipt.get("card_preimage_sha256")
    if not isinstance(trusted_sha, str) or not HASH_RE.fullmatch(trusted_sha):
        raise DisplayAssetError("historical_trusted_preimage_sha_invalid")
    current_refs = frontmatter_list(card_text, "lecture_refs")
    promoted = receipt.get("promoted_assets")
    if not isinstance(promoted, list) or not promoted:
        raise DisplayAssetError("historical_repair_promoted_assets_missing")
    lecture_assets: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    for item in promoted:
        if not isinstance(item, dict):
            raise DisplayAssetError("historical_repair_asset_invalid")
        broken = item.get("broken_reference")
        stable = item.get("stable_vault_relative_path")
        surfaces = set(item.get("reference_surfaces") or [])
        if "card_lecture_refs" not in surfaces and surfaces:
            continue
        if not isinstance(broken, str) or not isinstance(stable, str):
            raise DisplayAssetError("historical_repair_lecture_ref_binding_invalid")
        previous = mapping.get(broken)
        if previous is not None and previous != stable:
            raise DisplayAssetError("historical_repair_lecture_ref_mapping_conflict")
        mapping[broken] = stable
        lecture_assets.append(item)
    if not lecture_assets:
        raise DisplayAssetError("historical_repair_has_no_lecture_assets")
    stable_targets = set(mapping.values())
    if not stable_targets.issubset(set(current_refs)):
        raise DisplayAssetError("historical_repair_stable_refs_missing")
    broken_sequence = [str(item["broken_reference"]) for item in lecture_assets]
    non_promoted_sequence = [
        value for value in current_refs if value not in stable_targets
    ]

    def forward(original_refs: list[str]) -> list[str]:
        mapped = [mapping.get(value, value) for value in original_refs]
        return list(dict.fromkeys(mapped))

    candidates: dict[str, str] = {}
    seen_sequences: set[tuple[str, ...]] = set()
    for sequence in _ordered_interleavings(
        broken_sequence, non_promoted_sequence
    ):
        sequence_key = tuple(sequence)
        if sequence_key in seen_sequences:
            continue
        seen_sequences.add(sequence_key)
        if forward(sequence) != current_refs:
            continue
        for style in ("raw", "single", "double"):
            candidate = _render_frontmatter_list_candidate(
                card_text, "lecture_refs", sequence, style
            )
            digest = sha256_bytes(candidate.encode("utf-8"))
            if digest == trusted_sha:
                candidates[candidate] = style
    if len(candidates) != 1:
        raise DisplayAssetError(
            "historical_preimage_candidate_"
            + ("missing" if not candidates else "ambiguous")
        )
    return next(iter(candidates))


def historical_detail_bridge_membership(
    *, repo: Path, detail: Path, detail_text: str, formal_id: str, expected_sha256: str
) -> dict[str, str]:
    # The repair receipt freezes the detail postimage produced by that repair,
    # but a later canonical package may legitimately refresh only the managed
    # display block.  The supplement below rebinds the current detail hash and
    # separately proves every promoted asset against both T9 and its current
    # stable embed, so the old whole-file postimage is not current authority.
    # Keep the expected value required and well-formed to reject malformed old
    # receipts; current-byte and embed verification happens in the supplement.
    if not isinstance(expected_sha256, str) or not HASH_RE.fullmatch(expected_sha256):
        raise DisplayAssetError("historical_visual_detail_binding_invalid")
    detail_note = detail.relative_to(repo).as_posix()
    if detail_text.startswith(("---\n", "---\r\n")):
        if frontmatter_scalar(detail_text, "wrongnet_id") != formal_id:
            raise DisplayAssetError("historical_visual_detail_binding_invalid")
        return {
            "formal_id": formal_id,
            "detail_note": detail_note,
            "visual_id": frontmatter_scalar(detail_text, "visual_id"),
            "link_status": frontmatter_scalar(detail_text, "link_status"),
            "status": "verified_visual_detail_surface",
        }
    if not detail.name.startswith(formal_id + "_"):
        raise DisplayAssetError("historical_legacy_detail_filename_mismatch")
    return {
        "formal_id": formal_id,
        "detail_note": detail_note,
        "identity_basis": "receipt_postimage_sha256_and_formal_id_filename",
        "status": "verified_legacy_path_surface",
    }


def build_historical_closure_supplement(
    *, repo: Path, formal_id: str
) -> dict[str, Any]:
    """Reprove a legacy image repair without treating it as a canonical package."""
    repo = repo.resolve(strict=True)
    receipt_path, receipt = _historical_repair_receipt(repo, formal_id)
    card = safe_repo_path(repo, receipt.get("card_path"), "historical_closure_card")
    card_text = card.read_text(encoding="utf-8")
    promoted = receipt.get("promoted_assets")
    if not isinstance(promoted, list) or not promoted:
        raise DisplayAssetError("historical_repair_promoted_assets_missing")
    reconstructed = reconstruct_historical_card_preimage(
        card_text=card_text,
        receipt=receipt,
    )
    trusted_preimage_sha = receipt.get("card_preimage_sha256")
    detail = safe_repo_path(
        repo, receipt.get("visual_detail_path"), "historical_closure_visual_detail"
    )
    detail_text = detail.read_text(encoding="utf-8")
    bridge_membership = historical_detail_bridge_membership(
        repo=repo,
        detail=detail,
        detail_text=detail_text,
        formal_id=formal_id,
        expected_sha256=str(receipt.get("visual_detail_postimage_sha256") or ""),
    )
    grouped_sources: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, item in enumerate(promoted):
        broken = item.get("broken_reference") if isinstance(item, dict) else None
        if not isinstance(broken, str):
            raise DisplayAssetError("historical_repair_asset_invalid")
        manifest_relative = (Path(broken).parent / "manifest.json").as_posix()
        grouped_sources.setdefault(manifest_relative, []).append((index, item))
    quick = load_quick_intake(repo)
    multiple_sources = len(grouped_sources) > 1
    asset_proof_index: dict[int, dict[str, Any]] = {}
    source_proofs: list[dict[str, Any]] = []
    single_source_fields: dict[str, Any] = {}
    for manifest_relative in sorted(grouped_sources):
        source_items = grouped_sources[manifest_relative]
        manifest_path = safe_repo_path(
            repo, manifest_relative, "historical_closure_source_manifest"
        )
        manifest_sha = sha256_file(manifest_path)
        try:
            manifest, _, source_children = quick.validate_source_bundle_manifest(
                manifest_relative,
                "historical_display_closure.source_manifest",
                expected_hash=manifest_sha,
                require_question=False,
            )
        except ValueError as exc:
            raise DisplayAssetError(
                f"historical_legacy_pointer_chain_invalid:{exc}"
            ) from exc
        descriptors = manifest.get("artifacts")
        if not isinstance(descriptors, list) or len(descriptors) != len(source_children):
            raise DisplayAssetError("historical_source_artifact_set_invalid")
        archived_by_original = {
            descriptor.get("path"): child
            for descriptor, child in zip(descriptors, source_children)
            if isinstance(descriptor, dict)
        }
        locator_paths = {
            str(item.get("locator_path")) for _, item in source_items
        }
        if len(locator_paths) != 1:
            raise DisplayAssetError("historical_archive_locator_not_unique_per_source")
        locator_relative = next(iter(locator_paths))
        locator = safe_repo_path(
            repo, locator_relative, "historical_closure_archive_locator"
        )
        pointer_candidates = [manifest_path.parent / "legacy-archive-pointer.json"]
        pointer_dir = manifest_path.parent / "legacy-archive-pointers"
        if pointer_dir.is_dir() and not pointer_dir.is_symlink():
            pointer_candidates.extend(sorted(pointer_dir.glob("*.json")))
        pointer_matches: list[tuple[Path, dict[str, Any]]] = []
        for pointer_candidate in pointer_candidates:
            if pointer_candidate.is_symlink() or not pointer_candidate.is_file():
                continue
            try:
                value = json.loads(pointer_candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(value, dict)
                and value.get("obsidian_locator_path") == locator_relative
                and value.get("source_bundle_manifest_path") == manifest_relative
                and value.get("source_bundle_manifest_sha256") == manifest_sha
            ):
                pointer_matches.append((pointer_candidate, value))
        if len(pointer_matches) != 1:
            raise DisplayAssetError("historical_legacy_pointer_not_unique_per_source")
        pointer, pointer_document = pointer_matches[0]
        if (
            pointer_document.get("obsidian_locator_sha256") != sha256_file(locator)
        ):
            raise DisplayAssetError("historical_pointer_locator_mismatch")
        archive_package = exact_archive_package(
            DEFAULT_ARCHIVE_ROOT,
            str(pointer_document.get("raw_archive_relpath") or ""),
        )
        source_core = {
            "source_manifest_path": manifest_relative,
            "source_manifest_sha256": manifest_sha,
            "legacy_pointer_path": pointer.relative_to(repo).as_posix(),
            "legacy_pointer_sha256": sha256_file(pointer),
            "archive_locator_path": locator_relative,
            "archive_locator_sha256": sha256_file(locator),
        }
        source_proof_id = "MATH-DISPLAY-SOURCE-" + sha256_bytes(
            canonical_json_bytes(source_core)
        )[:24]
        for item_index, item in source_items:
            stable = safe_repo_path(
                repo,
                item["stable_vault_relative_path"],
                "historical_closure_stable_asset",
            )
            archived = archived_by_original.get(item["broken_reference"])
            if not isinstance(archived, Path) or not archived.is_file():
                raise DisplayAssetError("historical_archived_source_not_found")
            try:
                archived.resolve(strict=True).relative_to(
                    archive_package.resolve(strict=True)
                )
            except ValueError as exc:
                raise DisplayAssetError(
                    "historical_archived_source_outside_named_t9_package"
                ) from exc
            expected_sha = item.get("source_sha256")
            if (
                sha256_file(stable) != expected_sha
                or sha256_file(archived) != expected_sha
                or f"![[{item['stable_vault_relative_path']}]]" not in detail_text
            ):
                raise DisplayAssetError("historical_asset_three_way_hash_mismatch")
            asset_proof = {
                "broken_reference": item["broken_reference"],
                "stable_vault_relative_path": item["stable_vault_relative_path"],
                "stable_sha256": expected_sha,
                "archived_path": str(archived),
                "archived_sha256": expected_sha,
                "embed_resolved": True,
            }
            if multiple_sources:
                asset_proof["source_proof_id"] = source_proof_id
            asset_proof_index[item_index] = asset_proof
        if multiple_sources:
            source_proofs.append(
                {
                    "source_proof_id": source_proof_id,
                    **source_core,
                    "asset_count": len(source_items),
                }
            )
        else:
            single_source_fields = source_core
    if set(asset_proof_index) != set(range(len(promoted))):
        raise DisplayAssetError("historical_asset_source_ownership_incomplete")
    asset_proofs = [asset_proof_index[index] for index in range(len(promoted))]
    scan = scan_formal_references(repo, [formal_id])
    if scan["status"] != "passed":
        raise DisplayAssetError("historical_formal_reference_scan_failed")
    core = {
        "schema_version": HISTORICAL_SUPPLEMENT_SCHEMA,
        "subject": "math",
        "formal_id": formal_id,
        "repair_receipt_id": receipt["receipt_id"],
        "repair_receipt_path": receipt_path.relative_to(repo).as_posix(),
        "repair_receipt_sha256": sha256_file(receipt_path),
        "trusted_card_preimage_sha256": trusted_preimage_sha,
        "reconstructed_card_preimage_sha256": sha256_bytes(
            reconstructed.encode("utf-8")
        ),
        "current_card_path": card.relative_to(repo).as_posix(),
        "current_card_sha256": sha256_file(card),
        "allowed_card_mutation": "lecture_refs_only",
        "supersedes_invalid_card_postimage_sha256": receipt.get(
            "card_postimage_sha256"
        ),
        "visual_detail_path": detail.relative_to(repo).as_posix(),
        "visual_detail_sha256": sha256_file(detail),
        "bridge_membership": bridge_membership,
        **(
            {"source_proofs": source_proofs}
            if multiple_sources
            else single_source_fields
        ),
        "asset_proofs": asset_proofs,
        "formal_reference_scan": scan,
        "formal_reference_scan_sha256": scan[
            "formal_reference_scan_sha256"
        ],
        "stable_asset_count": len(asset_proofs),
        "no_display_proof": False,
        "canonical_package": False,
        "conversation_complete": False,
        "pending_component": None,
        "status": "verified",
    }
    return {
        **core,
        "supplement_id": "MATH-DISPLAY-HIST-CLOSE-"
        + sha256_bytes(canonical_json_bytes(core))[:24],
    }


def write_historical_closure_supplement(
    *, repo: Path, formal_id: str
) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    receipt_path, _ = _historical_repair_receipt(repo, formal_id)
    supplement = build_historical_closure_supplement(
        repo=repo, formal_id=formal_id
    )
    path = _historical_supplement_path(receipt_path)
    data = canonical_json_bytes(supplement)
    if path.exists() and path.read_bytes() != data:
        raise DisplayAssetError("historical_closure_supplement_conflict")
    if not path.exists():
        atomic_write(path, data)
    if path.read_bytes() != data:
        raise DisplayAssetError("historical_closure_supplement_reread_failed")
    return {
        "status": "recorded",
        "historical_closure_supplement_id": supplement["supplement_id"],
        "historical_closure_supplement_path": path.relative_to(repo).as_posix(),
        "historical_closure_supplement_sha256": sha256_file(path),
        "formal_reference_scan_sha256": supplement[
            "formal_reference_scan_sha256"
        ],
        "stable_asset_count": supplement["stable_asset_count"],
        "no_display_proof": supplement["no_display_proof"],
        "pending_component": None,
    }


def verify_historical_closure_for_formal(
    *, repo: Path, formal_id: str
) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    receipt_path, _ = _historical_repair_receipt(repo, formal_id)
    path = _historical_supplement_path(receipt_path)
    if path.is_symlink() or not path.is_file():
        raise DisplayAssetError("historical_closure_supplement_missing")
    expected = build_historical_closure_supplement(
        repo=repo, formal_id=formal_id
    )
    if path.read_bytes() != canonical_json_bytes(expected):
        raise DisplayAssetError("historical_closure_supplement_drift")
    return {
        "historical_closure_supplement_id": expected["supplement_id"],
        "historical_closure_supplement_path": path.relative_to(repo).as_posix(),
        "historical_closure_supplement_sha256": sha256_file(path),
        "formal_reference_scan_sha256": expected[
            "formal_reference_scan_sha256"
        ],
        "stable_asset_count": expected["stable_asset_count"],
        "no_display_proof": expected["no_display_proof"],
        "pending_component": None,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="数学 Obsidian 稳定展示资产闭环")
    value.add_argument(
        "mode",
        choices=(
            "plan",
            "publish",
            "verify",
            "scan",
            "historical-preview",
            "historical-apply",
            "historical-supplement",
        ),
    )
    value.add_argument("--repo", required=True)
    value.add_argument("--manifest")
    value.add_argument("--manifest-sha256")
    value.add_argument("--package-sha256")
    value.add_argument("--formal-id", action="append", default=[])
    value.add_argument("--plan-file")
    value.add_argument("--authorization")
    value.add_argument("--archive-root", default="/Volumes/T9-Data")
    value.add_argument("--apply", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        repo = Path(args.repo)
        if args.mode == "plan":
            if not args.manifest:
                raise DisplayAssetError("manifest_required")
            result = build_plan(
                repo=repo,
                manifest_relative=args.manifest,
                formal_ids=args.formal_id,
                expected_manifest_sha256=args.manifest_sha256,
            )
        elif args.mode == "publish":
            if not args.plan_file or not args.authorization:
                raise DisplayAssetError("publish_plan_and_authorization_required")
            plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
            result = publish_plan(repo=repo, plan=plan, authorization=args.authorization)
        elif args.mode == "verify":
            if not args.manifest or not args.manifest_sha256:
                raise DisplayAssetError("verify_manifest_binding_required")
            result = verify_closure_for_source(
                repo=repo,
                manifest_relative=args.manifest,
                expected_manifest_sha256=args.manifest_sha256,
                expected_package_sha256=args.package_sha256,
                formal_ids=args.formal_id,
            )
            result = {"status": "verified", **result}
        elif args.mode == "scan":
            result = scan_formal_references(repo.resolve(strict=True), args.formal_id)
        elif args.mode == "historical-preview":
            result = historical_preview(
                repo=repo,
                archive_root=Path(args.archive_root),
                formal_ids=args.formal_id or None,
            )
        elif args.mode == "historical-apply":
            if not args.plan_file or not args.authorization:
                raise DisplayAssetError("historical_plan_and_authorization_required")
            plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
            result = apply_historical_plan(
                repo=repo,
                plan=plan,
                authorization=args.authorization,
                apply=args.apply,
            )
        else:
            if len(args.formal_id) != 1 or not args.apply:
                raise DisplayAssetError(
                    "historical_supplement_requires_one_formal_id_and_apply"
                )
            result = write_historical_closure_supplement(
                repo=repo, formal_id=args.formal_id[0]
            )
    except (DisplayAssetError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(canonical_json({"status": "error", "error_code": str(exc), "pending_component": "display_assets", "formal_write_count": 0}))
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
