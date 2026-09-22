#!/usr/bin/env python3
"""Seal project-B math evidence, commit a GPT-6 audit, and emit a gated C handoff."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
SYSTEM_SCRIPTS = ROOT / "数学一回滚复习系统/scripts"
BASE = Path("数学一回滚复习系统/知识点复盘")
EVIDENCE = BASE / "B原始会话"
AUDITS = BASE / "B审核"
HANDOFFS = BASE / "C交接"
CACHE = Path("数学一回滚复习系统/.math_session_index")
EVIDENCE_SCHEMA = "math-b-review-evidence-v1"
AUDIT_SCHEMA = "math-review-audit-v1"
HANDOFF_SCHEMA = "math-c-handoff-v1"
PROFILE_SCHEMA = "math-learning-profile-update-v1"
EVIDENCE_PREFIX = "B-REVIEW-EVIDENCE-"
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_id(session_id: str) -> str:
    return EVIDENCE_PREFIX + digest(["math", "project-B", session_id])[:32]


def _text(value: object, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError("invalid_" + name)
    return value


def _timestamp(value: object, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, name).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("invalid_" + name) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(name + "_requires_timezone")
    return parsed


def safe_repo_path(root: Path, path: Path | str) -> Path:
    root = root.resolve()
    candidate = Path(path)
    candidate = candidate if candidate.is_absolute() else root / candidate
    candidate = candidate.absolute()
    if not candidate.is_relative_to(root):
        raise ValueError("path_outside_repository")
    current = root
    for part in candidate.relative_to(root).parts:
        if part in {".", ".."}:
            raise ValueError("unsafe_repository_path")
        current /= part
        if current.is_symlink():
            raise ValueError("repository_symlink_forbidden")
    return candidate


def _safe_member(name: str) -> str:
    member = PurePosixPath(name)
    if not name or "\\" in name or member.is_absolute() or ".." in member.parts or member.as_posix() != name or ":" in name:
        raise ValueError("unsafe_package_member:" + name)
    return name


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.read_bytes() != raw:
            raise ValueError("immutable_file_conflict:" + str(path))
        return
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".state-", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(canonical(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_dir(path.parent)


def _load_artifact_spec(path: Path | None) -> tuple[dict[tuple[int, int], dict], dict[tuple[int, int], dict], dict | None]:
    specification = json.loads(path.read_text()) if path else {}
    if not isinstance(specification, dict) or set(specification) - {"artifacts", "missing_attachments"}:
        raise ValueError("invalid_artifacts_json")
    mappings: dict[tuple[int, int], dict] = {}
    missing: dict[tuple[int, int], dict] = {}
    for field, target in (("artifacts", mappings), ("missing_attachments", missing)):
        values = specification.get(field, [])
        if not isinstance(values, list):
            raise ValueError("invalid_artifacts_json")
        for item in values:
            if not isinstance(item, dict):
                raise ValueError("invalid_artifact_mapping")
            key = (item.get("message_line"), item.get("block_index"))
            if not all(type(value) is int for value in key) or key in target:
                raise ValueError("duplicate_or_invalid_artifact_mapping")
            if field == "artifacts":
                if set(item) != {"message_line", "block_index", "role", "path"}:
                    raise ValueError("invalid_artifact_mapping_fields")
                _text(item["role"], "artifact_role")
                _text(item["path"], "artifact_path")
            elif set(item) != {"message_line", "block_index", "reason"}:
                raise ValueError("invalid_missing_attachment_fields")
            else:
                _text(item["reason"], "missing_attachment_reason")
            target[key] = item
    if mappings.keys() & missing.keys():
        raise ValueError("attachment_present_and_missing")
    source = ({"path": str(path.expanduser().resolve()), "sha256": file_hash(path.expanduser().resolve())}
              if path else None)
    return mappings, missing, source


def _local_image(value: object) -> Path | None:
    if isinstance(value, dict):
        value = value.get("url") or value.get("path")
    if not isinstance(value, str):
        return None
    if value.startswith("file://"):
        value = value[7:]
    path = Path(value)
    if path.is_absolute() and path.suffix.lower() in IMAGE_SUFFIXES and path.is_file() and not path.is_symlink():
        return path.resolve()
    return None


def _extract_transcript(root: Path, args: argparse.Namespace) -> dict:
    if str(SYSTEM_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SYSTEM_SCRIPTS))
    import math_session_io as session_io

    source = Path(args.rollout).expanduser().resolve(strict=True)
    session = session_io.open_session(source, root / CACHE, args.session_id)
    finish = args.end_assistant_line or args.end_user_line
    if not 1 <= args.start_line <= args.end_user_line <= finish:
        raise ValueError("invalid_inclusive_message_boundaries")
    start = session.message(args.start_line)
    end_user = session.message(args.end_user_line)
    tail = session.message(finish)
    if not start or not start["visible"]:
        raise ValueError("start_line_must_be_visible_message")
    if not end_user or not end_user["visible"] or end_user["role"] != "user":
        raise ValueError("end_user_line_must_be_visible_user_message")
    if args.end_assistant_line and (not tail or not tail["visible"] or tail["role"] != "assistant"):
        raise ValueError("end_assistant_line_must_be_visible_assistant_message")
    for line in range(args.end_user_line + 1, finish):
        message = session.message(line)
        if message and message["visible"] and message["role"] == "user":
            raise ValueError("cannot_cross_user_after_closing_request")
    rows, raw = session.read_range(args.start_line, finish)
    mappings, missing_map, specification_source = _load_artifact_spec(args.artifacts_json)
    conversation: list[dict] = []
    boundaries: list[dict] = []
    artifacts: list[dict] = []
    missing: list[dict] = []
    used: set[tuple[int, int]] = set()
    seen_paths: set[str] = set()

    def add_artifact(role: str, path: Path) -> None:
        resolved = str(path.resolve())
        if resolved not in seen_paths:
            raw_artifact = path.read_bytes()
            artifacts.append({"role": role, "source_path": resolved, "sha256": hashlib.sha256(raw_artifact).hexdigest(),
                              "size": len(raw_artifact), "_bytes": raw_artifact})
            seen_paths.add(resolved)

    for line_no, row in enumerate(rows, args.start_line):
        message = row.get("payload", {}) if row.get("type") == "response_item" else {}
        if (not isinstance(message, dict) or message.get("type") != "message"
                or message.get("role") not in {"user", "assistant"}
                or message.get("phase") in {"analysis", "reasoning"}
                or message.get("channel") in {"analysis", "reasoning"}
                or message.get("recipient") not in {None, "all"}):
            continue
        blocks = message.get("content")
        if not isinstance(blocks, list):
            raise ValueError("message_content_must_be_typed_blocks")
        texts: list[str] = []
        lengths: list[int] = []
        for block_index, block in enumerate(blocks):
            key = (line_no, block_index)
            if not isinstance(block, dict):
                raise ValueError("invalid_message_block")
            is_text = block.get("type") in {"input_text", "output_text", "text"}
            if is_text:
                text = block.get("text")
                if not isinstance(text, str):
                    raise ValueError("text_block_lacks_exact_text")
                texts.append(text)
                lengths.append(len(text))
                for reference in re.findall(r"!\[[^\]]*\]\(<?([^\n)]+?)>?\)", text):
                    image = _local_image(reference)
                    if image:
                        role = mappings.get(key, {}).get("role") or ("explanation_image" if image.suffix.lower() == ".svg" else "other_attachment")
                        add_artifact(role, image)
                    elif key not in mappings and key not in missing_map:
                        raise ValueError(f"unresolved_image_reference:{line_no}:{block_index}")
            if key in mappings:
                item = mappings[key]
                mapped = Path(item["path"]).expanduser()
                if not mapped.is_absolute() or not mapped.is_file() or mapped.is_symlink():
                    raise ValueError("artifact_path_must_be_absolute_regular_file")
                add_artifact(item["role"], mapped)
                used.add(key)
            elif key in missing_map:
                missing.append({"message_line": line_no, "block_index": block_index,
                                "reason": missing_map[key]["reason"]})
                used.add(key)
            elif not is_text:
                image = _local_image(block.get("image_url") or block.get("url") or block.get("path"))
                if image:
                    add_artifact("explanation_image" if image.suffix.lower() == ".svg" else "other_attachment", image)
                else:
                    raise ValueError(f"unresolved_non_text_block:{line_no}:{block_index}")
        conversation.append({"role": message["role"], "text": "".join(texts)})
        boundaries.append({"line": line_no, "text_block_lengths": lengths,
                           "block_types": [block.get("type") for block in blocks]})
    if used != mappings.keys() | missing_map.keys():
        raise ValueError("artifact_mapping_outside_selected_messages")
    if not conversation:
        raise ValueError("complete_conversation_required")
    return {"conversation": conversation, "message_boundaries": boundaries, "raw": raw,
            "rollout": {"path": str(source), "session_id": args.session_id,
                        "start_line": args.start_line, "end_user_line": args.end_user_line,
                        "end_assistant_line": args.end_assistant_line, "finish_line": finish,
                        "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)},
            "artifacts": artifacts, "missing_attachments": missing,
            "artifacts_specification": specification_source}


def _read_package(source: Path) -> tuple[dict[str, bytes], dict]:
    source = source.expanduser().resolve(strict=True)
    files: dict[str, bytes] = {}
    source_sha = None
    source_size = 0
    if source.is_symlink():
        raise ValueError("review_package_symlink_forbidden")
    if source.is_file():
        source_raw = source.read_bytes()
        source_sha = hashlib.sha256(source_raw).hexdigest()
        source_size = len(source_raw)
        try:
            with zipfile.ZipFile(source) as archive:
                if sum(item.file_size for item in archive.infolist()) > MAX_PACKAGE_BYTES:
                    raise ValueError("review_package_over_512MiB")
                for item in archive.infolist():
                    name = item.filename.rstrip("/") if item.is_dir() else item.filename
                    _safe_member(name)
                    if stat.S_ISLNK(item.external_attr >> 16):
                        raise ValueError("review_package_symlink_forbidden")
                    if item.is_dir():
                        continue
                    if name in files:
                        raise ValueError("duplicate_package_member:" + name)
                    files[name] = archive.read(item)
        except zipfile.BadZipFile as exc:
            raise ValueError("review_package_must_be_zip_or_directory") from exc
        kind = "zip"
    elif source.is_dir():
        total = 0
        for path in source.rglob("*"):
            if path.is_symlink():
                raise ValueError("review_package_symlink_forbidden")
            if path.is_file():
                raw = path.read_bytes()
                total += len(raw)
                if total > MAX_PACKAGE_BYTES:
                    raise ValueError("review_package_over_512MiB")
                files[_safe_member(path.relative_to(source).as_posix())] = raw
        kind = "directory"
        source_size = total
    else:
        raise ValueError("review_package_must_be_zip_or_directory")
    required = {"manifest.json", "START_HERE.md", "review_plan.json", "student/questions.jsonl"}
    if required - files.keys():
        raise ValueError("review_package_missing:" + ",".join(sorted(required - files.keys())))
    manifest = json.loads(files["manifest.json"])
    if not isinstance(manifest, dict) or manifest.get("project") != "B" or manifest.get("subject") != "math":
        raise ValueError("review_package_must_be_project_B_math")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("review_package_manifest_files_required")
    declared: set[str] = set()
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError("invalid_review_package_manifest_entry")
        name = _safe_member(row.get("path", ""))
        if name == "manifest.json" or name in declared or name not in files:
            raise ValueError("invalid_review_package_member:" + name)
        raw = files[name]
        if type(row.get("size")) is not int or row["size"] != len(raw) or row.get("sha256") != hashlib.sha256(raw).hexdigest():
            raise ValueError("review_package_hash_or_size_mismatch:" + name)
        declared.add(name)
    if declared != set(files) - {"manifest.json"}:
        raise ValueError("review_package_undeclared_members")
    plan = json.loads(files["review_plan.json"])
    if not isinstance(plan, dict):
        raise ValueError("review_package_plan_must_be_object")
    questions = [json.loads(line) for line in files["student/questions.jsonl"].decode("utf-8").splitlines() if line.strip()]
    question_ids = [row.get("question_id") for row in questions if isinstance(row, dict)]
    if (not question_ids or len(question_ids) != len(questions)
            or any(not isinstance(value, str) or not value for value in question_ids)
            or len(question_ids) != len(set(question_ids))):
        raise ValueError("review_package_unique_question_ids_required")
    description = {"path": str(source), "kind": kind, "size": source_size, "sha256": source_sha,
                   "manifest_sha256": hashlib.sha256(files["manifest.json"]).hexdigest(),
                   "run_id": manifest.get("run_id"), "source_commit": manifest.get("source_commit"),
                   "file_count": len(files), "question_ids": question_ids}
    return files, description


def preserve_evidence(repo_root: Path | str, args: argparse.Namespace) -> dict:
    root = Path(repo_root).resolve()
    session_id = _text(args.session_id, "session_id")
    if len(session_id) > 128 or session_id != session_id.strip() or any(ord(char) < 32 for char in session_id):
        raise ValueError("invalid_session_id")
    started = _timestamp(args.started_at, "started_at")
    ended = _timestamp(args.ended_at, "ended_at")
    try:
        study_day = date.fromisoformat(args.study_date)
    except (TypeError, ValueError):
        raise ValueError("invalid_study_date") from None
    if study_day.isoformat() != args.study_date or started.astimezone(ZoneInfo("Asia/Shanghai")).date() != study_day:
        raise ValueError("study_date_must_match_session_start_shanghai")
    if ended < started:
        raise ValueError("session_end_before_start")
    transcript = _extract_transcript(root, args)
    package_files, package_source = _read_package(args.review_package)
    identity = evidence_id(session_id)
    archive: dict[str, bytes] = {
        "source/rollout-slice.jsonl": transcript["raw"],
        "conversation.json": canonical(transcript["conversation"]),
    }
    if package_source["kind"] == "zip":
        archive["source/review-package.zip"] = Path(package_source["path"]).read_bytes()
    for name, raw in package_files.items():
        archive["review-package/" + name] = raw
    manifest_artifacts = []
    for number, item in enumerate(transcript["artifacts"]):
        suffix = Path(item["source_path"]).suffix[:16]
        archive_path = f"artifacts/{number:04d}-{item['sha256']}{suffix}"
        archive[archive_path] = item["_bytes"]
        manifest_artifacts.append({key: value for key, value in item.items() if key != "_bytes"} | {"path": archive_path})
    inventory = [{"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
                 for path, raw in sorted(archive.items())]
    core = {"schema": EVIDENCE_SCHEMA, "project": "B", "subject": "math", "evidence_id": identity,
            "session_id": session_id, "study_date": args.study_date, "started_at": args.started_at,
            "ended_at": args.ended_at, "source_manifest": {"rollout": transcript["rollout"],
            "review_package": package_source, "artifacts_specification": transcript["artifacts_specification"]},
            "message_boundaries": transcript["message_boundaries"], "conversation_path": "conversation.json",
            "conversation_turn_count": len(transcript["conversation"]), "artifacts": manifest_artifacts,
            "missing_attachments": transcript["missing_attachments"], "archive_files": inventory,
            "write_scope": "raw_evidence_only_no_capture_no_formal_observations"}
    manifest = {**core, "content_sha256": digest(core)}
    base = safe_repo_path(root, root / EVIDENCE)
    base.mkdir(parents=True, exist_ok=True)
    target = safe_repo_path(root, base / identity)
    lock_path = safe_repo_path(root, root / BASE / "b-evidence.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    status = "recorded"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.exists():
            previous = load_evidence(root, identity)
            if previous["content_sha256"] != manifest["content_sha256"]:
                raise ValueError("B_evidence_session_conflict")
            status = "noop"
        else:
            staging = Path(tempfile.mkdtemp(prefix=".B-evidence-", dir=base))
            try:
                for path, raw in archive.items():
                    _write_new(staging / path, raw)
                _write_new(staging / "manifest.json", canonical(manifest))
                for directory in sorted({path.parent for path in staging.rglob("*") if path.is_file()}, key=lambda path: len(path.parts), reverse=True):
                    _fsync_dir(directory)
                os.rename(staging, target)
                _fsync_dir(base)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
    verified = load_evidence(root, identity)
    manifest_path = target / "manifest.json"
    return {"status": status, "evidence_id": identity, "session_id": session_id,
            "manifest_path": manifest_path.relative_to(root).as_posix(), "manifest_sha256": file_hash(manifest_path),
            "content_sha256": verified["content_sha256"], "conversation_turn_count": verified["conversation_turn_count"],
            "archive_file_count": len(verified["archive_files"]), "capture_write_count": 0,
            "formal_write_count": 0, "semantic_observation_count": 0}


def load_evidence(repo_root: Path | str, identity: str) -> dict:
    root = Path(repo_root).resolve()
    if not re.fullmatch(re.escape(EVIDENCE_PREFIX) + r"[0-9a-f]{32}", identity):
        raise ValueError("invalid_B_evidence_id")
    directory = safe_repo_path(root, root / EVIDENCE / identity)
    manifest_path = safe_repo_path(root, directory / "manifest.json")
    value = json.loads(manifest_path.read_bytes())
    core = {key: item for key, item in value.items() if key != "content_sha256"}
    if value.get("schema") != EVIDENCE_SCHEMA or value.get("evidence_id") != identity or value.get("content_sha256") != digest(core):
        raise ValueError("B_evidence_manifest_mismatch")
    if evidence_id(value.get("session_id", "")) != identity:
        raise ValueError("B_evidence_identity_mismatch")
    inventory = value.get("archive_files")
    if not isinstance(inventory, list):
        raise ValueError("B_evidence_inventory_required")
    seen: set[str] = set()
    for row in inventory:
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "size"}:
            raise ValueError("invalid_B_evidence_inventory")
        name = _safe_member(row["path"])
        if name in seen:
            raise ValueError("duplicate_B_evidence_inventory")
        seen.add(name)
        path = safe_repo_path(root, directory / name)
        raw = path.read_bytes()
        if path.is_symlink() or len(raw) != row["size"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("B_evidence_archive_mismatch:" + name)
    return value


def read_evidence(repo_root: Path | str, *, session_id: str | None = None, identity: str | None = None) -> dict:
    root = Path(repo_root).resolve()
    identity = identity or evidence_id(_text(session_id, "session_id"))
    manifest = load_evidence(root, identity)
    directory = root / EVIDENCE / identity
    conversation = json.loads((directory / manifest["conversation_path"]).read_bytes())
    rollout_source = manifest["source_manifest"]["rollout"]
    source_status = "missing"
    source = Path(rollout_source["path"])
    if source.is_file() and not source.is_symlink():
        try:
            if str(SYSTEM_SCRIPTS) not in sys.path:
                sys.path.insert(0, str(SYSTEM_SCRIPTS))
            import math_session_io as session_io
            opened = session_io.open_session(source, root / CACHE, manifest["session_id"])
            _, raw = opened.read_range(rollout_source["start_line"], rollout_source["finish_line"])
            source_status = "exact" if hashlib.sha256(raw).hexdigest() == rollout_source["sha256"] else "changed"
        except (OSError, ValueError):
            source_status = "unavailable"
    package_source = manifest["source_manifest"]["review_package"]
    package_status = "missing"
    package_path = Path(package_source["path"])
    if package_path.exists() and not package_path.is_symlink():
        try:
            _, current = _read_package(package_path)
            comparable = (current["kind"], current["manifest_sha256"], current.get("sha256"), current["file_count"])
            expected = (package_source["kind"], package_source["manifest_sha256"], package_source.get("sha256"), package_source["file_count"])
            package_status = "exact" if comparable == expected else "changed"
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            package_status = "unavailable"
    manifest_path = directory / "manifest.json"
    return {"status": "verified", "project": "B", "subject": "math", "evidence_id": identity,
            "session_id": manifest["session_id"], "source_manifest": {**manifest["source_manifest"],
            "current_rollout_status": source_status, "current_review_package_status": package_status},
            "archive_manifest": {"path": manifest_path.relative_to(root).as_posix(),
            "sha256": file_hash(manifest_path), "content_sha256": manifest["content_sha256"],
            "files": manifest["archive_files"]}, "conversation": conversation,
            "message_boundaries": manifest["message_boundaries"], "artifacts": manifest["artifacts"],
            "missing_attachments": manifest["missing_attachments"]}


def _validate_audit(root: Path, evidence: dict, payload: dict) -> tuple[dict, dict]:
    required = {"schema", "subject", "evidence_session_id", "audit_summary", "observations", "assistant_mistakes", "profile_updates"}
    if not isinstance(payload, dict) or set(payload) != required or payload.get("schema") != AUDIT_SCHEMA or payload.get("subject") != "math":
        raise ValueError("invalid_math_review_audit_fields")
    if payload["evidence_session_id"] != evidence["session_id"]:
        raise ValueError("audit_evidence_session_mismatch")
    _text(payload["audit_summary"], "audit_summary")
    if not isinstance(payload["observations"], list) or not payload["observations"]:
        raise ValueError("audit_observations_required")
    conversation_path = root / EVIDENCE / evidence["evidence_id"] / evidence["conversation_path"]
    conversation = json.loads(conversation_path.read_bytes())
    mistakes = payload["assistant_mistakes"]
    if not isinstance(mistakes, list):
        raise ValueError("assistant_mistakes_must_be_list")
    seen: set[str] = set()
    for row in mistakes:
        fields = {"mistake_id", "assistant_turn_indices", "finding", "correction"}
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("invalid_assistant_mistake_fields")
        identity = _text(row["mistake_id"], "mistake_id")
        if identity in seen:
            raise ValueError("duplicate_assistant_mistake_id")
        seen.add(identity)
        indices = row["assistant_turn_indices"]
        if not isinstance(indices, list) or not indices or any(type(index) is not int or not 0 <= index < len(conversation) or conversation[index]["role"] != "assistant" for index in indices):
            raise ValueError("invalid_assistant_mistake_evidence")
        _text(row["finding"], "assistant_mistake_finding")
        _text(row["correction"], "assistant_mistake_correction")
    profile = payload["profile_updates"]
    if not isinstance(profile, dict) or profile.get("schema") != PROFILE_SCHEMA or not isinstance(profile.get("updates"), list):
        raise ValueError("invalid_profile_updates")
    manifest_path = root / EVIDENCE / evidence["evidence_id"] / "manifest.json"
    evidence_ref = {"path": manifest_path.relative_to(root).as_posix(), "sha256": file_hash(manifest_path)}
    profile = json.loads(json.dumps(profile, ensure_ascii=False))
    for update in profile["updates"]:
        if not isinstance(update, dict) or not isinstance(update.get("source_refs"), list):
            raise ValueError("profile_update_source_refs_required")
        if evidence_ref not in update["source_refs"]:
            update["source_refs"].append(evidence_ref)
    observation_keys = {row.get("concept_key") for row in payload["observations"] if isinstance(row, dict)}
    profile_keys = {row.get("concept_key") for row in profile["updates"] if isinstance(row, dict)}
    if len(profile_keys) != len(profile["updates"]) or profile_keys != observation_keys:
        raise ValueError("profile_updates_must_match_observed_concepts")
    formal_conversation = []
    for index, turn in enumerate(conversation):
        text = turn["text"]
        if not text:
            source_line = evidence["message_boundaries"][index]["line"]
            text = f"[non-text message preserved verbatim in B evidence source line {source_line}]"
        formal_conversation.append({"role": turn["role"], "text": text})
    concept_payload = {"schema": "concept-review-session-v1", "subject": "math",
                       "session_id": evidence["session_id"], "study_date": evidence["study_date"],
                       "started_at": evidence["started_at"], "ended_at": evidence["ended_at"],
                       "conversation": formal_conversation,
                       "artifacts": [{"path": evidence_ref["path"], "sha256": evidence_ref["sha256"],
                                      "role": "B_raw_evidence_manifest", "name": evidence["evidence_id"]}],
                       "observations": payload["observations"]}
    return concept_payload, profile


def _load_module(name: str, path: Path):
    module_name = "_math_review_handoff_" + name
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError("module_unavailable:" + str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    previous = list(sys.path)
    try:
        sys.path.insert(0, str(path.parent))
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        sys.path[:] = previous
    return module


def _audit_directory(root: Path, identity: str) -> Path:
    return safe_repo_path(root, root / AUDITS / identity)


def _verified_audit_state(root: Path, identity: str) -> dict:
    directory = _audit_directory(root, identity)
    state_path = safe_repo_path(root, directory / "state.json")
    if not state_path.is_file() or state_path.is_symlink():
        raise ValueError("audit_not_prepared")
    state = json.loads(state_path.read_bytes())
    if (not isinstance(state, dict) or state.get("schema") != "math-review-audit-state-v1"
            or state.get("evidence_id") != identity):
        raise ValueError("audit_state_identity_mismatch")
    bindings = (
        ("audit_input_path", "audit_input_sha256"),
        ("concept_session_path", "concept_session_sha256"),
        ("prepared_profile_path", "prepared_profile_sha256"),
    )
    for path_field, hash_field in bindings:
        path = safe_repo_path(root, _text(state.get(path_field), path_field))
        if not path.is_file() or path.is_symlink() or file_hash(path) != state.get(hash_field):
            raise ValueError("frozen_audit_file_mismatch:" + path_field)
    return state


def _verified_completed_handoff(root: Path, identity: str, state: dict) -> dict:
    handoff = state.get("c_handoff")
    if not isinstance(handoff, dict) or handoff.get("status") != "ready":
        raise ValueError("completed_audit_handoff_missing")
    path = safe_repo_path(root, _text(handoff.get("path"), "c_handoff_path"))
    if not path.is_file() or path.is_symlink() or file_hash(path) != handoff.get("sha256"):
        raise ValueError("completed_audit_handoff_hash_mismatch")
    try:
        with zipfile.ZipFile(path) as archive:
            names = {item.filename for item in archive.infolist() if not item.is_dir()}
            if names != {"START_HERE.md", "handoff.json", "refs.json"}:
                raise ValueError("completed_audit_handoff_members_mismatch")
            payload = json.loads(archive.read("handoff.json"))
    except zipfile.BadZipFile as exc:
        raise ValueError("completed_audit_handoff_invalid_zip") from exc
    if (payload.get("schema") != HANDOFF_SCHEMA or payload.get("source_evidence_id") != identity
            or payload.get("formal_event_id") != state.get("commit_result", {}).get("event_id")):
        raise ValueError("completed_audit_handoff_identity_mismatch")
    return handoff


def prepare_audit(repo_root: Path | str, payload: dict) -> dict:
    root = Path(repo_root).resolve()
    identity = evidence_id(_text(payload.get("evidence_session_id") if isinstance(payload, dict) else None, "evidence_session_id"))
    evidence = load_evidence(root, identity)
    directory = _audit_directory(root, identity)
    state_path = directory / "state.json"
    if state_path.is_file():
        state = _verified_audit_state(root, identity)
        if state.get("session_id") != evidence.get("session_id"):
            raise ValueError("audit_state_session_mismatch")
        frozen = safe_repo_path(root, state["audit_input_path"])
        if frozen.read_bytes() != canonical(payload):
            return {**state, "status": "required_correction_unsupported",
                    "reason": "audit_input_conflict",
                    "resolution": "keep_immutable_event_and_prepare_an_explicit_supported_revision",
                    "formal_learning_event_count_added": 0,
                    "c_handoff": {"status": "not_ready"}}
        return advance_audit(root, identity)
    concept_payload, profile = _validate_audit(root, evidence, payload)
    profiles = _load_module("profiles", root / "错题知识网络/scripts/math_learning_profiles.py")
    prepared = profiles.prepare_updates(root, profile)
    review = _load_module("concept_review", root / "错题知识网络/scripts/math_concept_review.py")
    review.validate_session(root, concept_payload)
    directory.mkdir(parents=True, exist_ok=True)
    _write_new(directory / "audit-input.json", canonical(payload))
    _write_new(directory / "concept-session.json", canonical(concept_payload))
    _write_new(directory / "prepared-profile.json", canonical(prepared))
    if state_path.exists():
        state = json.loads(state_path.read_bytes())
        expected = {"audit_input_sha256": file_hash(directory / "audit-input.json"),
                    "concept_session_sha256": file_hash(directory / "concept-session.json"),
                    "prepared_profile_sha256": file_hash(directory / "prepared-profile.json")}
        if any(state.get(key) != value for key, value in expected.items()):
            raise ValueError("audit_receipt_conflict")
    else:
        state = {"schema": "math-review-audit-state-v1", "status": "prepared", "evidence_id": identity,
                 "session_id": evidence["session_id"],
                 "audit_input_path": (directory / "audit-input.json").relative_to(root).as_posix(),
                 "concept_session_path": (directory / "concept-session.json").relative_to(root).as_posix(),
                 "prepared_profile_path": (directory / "prepared-profile.json").relative_to(root).as_posix(),
                 "audit_input_sha256": file_hash(directory / "audit-input.json"),
                 "concept_session_sha256": file_hash(directory / "concept-session.json"),
                 "prepared_profile_sha256": file_hash(directory / "prepared-profile.json")}
        _replace_json(state_path, state)
    return advance_audit(root, identity)


def _verify_publication_current() -> dict:
    script = Path("/Users/your-user/Documents/Study-Pro-Bridge/study_publication.py")
    if not script.is_file():
        return {"status": "SYNC_PENDING", "reason": "publication_reader_unavailable"}
    try:
        return _load_module("publication", script).verify_current("math")
    except Exception as exc:
        return {"status": "SYNC_PENDING", "reason": type(exc).__name__}


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    with tempfile.NamedTemporaryFile(prefix="math-c-handoff-", suffix=".zip") as handle:
        with zipfile.ZipFile(handle.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in sorted(files.items()):
                info = zipfile.ZipInfo(_safe_member(name), date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, raw)
        return Path(handle.name).read_bytes()


def _emit_c_handoff(root: Path, identity: str, state: dict) -> dict:
    directory = _audit_directory(root, identity)
    audit = json.loads((directory / "audit-input.json").read_bytes())
    prepared = json.loads((directory / "prepared-profile.json").read_bytes())
    evidence_manifest = root / EVIDENCE / identity / "manifest.json"
    refs = {"schema": "math-c-handoff-refs-v1", "latest_snapshot": state["publication_current"],
            "sources": sorted({(row["path"], row["sha256"]) for update in prepared["updates"] for row in update["source_refs"]})}
    refs["sources"] = [{"path": path, "sha256": sha} for path, sha in refs["sources"]]
    basis = {"schema": HANDOFF_SCHEMA, "project": "C", "subject": "math", "source_project": "B",
             "source_session_id": state["session_id"], "source_evidence_id": identity,
             "formal_event_id": state["commit_result"]["event_id"],
             "concept_keys": state["profile_result"]["concept_keys"], "audit_summary": audit["audit_summary"],
             "observations": audit["observations"], "assistant_mistakes": audit["assistant_mistakes"],
             "profile_updates": prepared["updates"],
             "profile_updates_semantics": {"status": "audit_as_of_event_not_claimed_as_latest_profile",
                                            "formal_event_id": state["commit_result"]["event_id"]},
             "latest_mcp_snapshot": state["publication_current"],
             "formal_readback": state["commit_result"],
             "profile_receipt": state["profile_result"],
             "evidence_manifest": {"path": evidence_manifest.relative_to(root).as_posix(),
                                   "sha256": file_hash(evidence_manifest)},
             "publication_current": state["publication_current"],
             "constraints": {"questions": "existing_formal_cards_only", "answer_protection": True,
                             "generated_B_questions_are_not_formal_cards": True,
                             "do_not_score_source_or_generated_B_questions": True}}
    lines = ["# 项目 C 数学交接", "", audit["audit_summary"], "",
             "以下摘要固定在本次 B 审核事件；当前状态以 handoff.json 的 latest_mcp_snapshot 为准。", "",
             "## 审核时知识点摘要", ""]
    for update in prepared["updates"]:
        lines.extend([f"### {update['concept_key']}", "", update["short_summary"], "", f"下一次检查：{update['next_check']}", ""])
    lines.extend(["## 使用边界", "", "只从现有正式错题卡选择真实旧题，并继续保护未公开答案。项目 B 的生成题只作为本场证据，不能建立正式错题卡，也不能冒充复做记录。", ""])
    lines.extend(["本地学习前预处理整组题目。逐题复用question-worker讲解和wrong-intake完整Capture；当场不评分、不更新长期调度，保存后继续下一题，晚间再正式入库。", ""])
    files = {"START_HERE.md": "\n".join(lines).encode(), "handoff.json": canonical(basis), "refs.json": canonical(refs)}
    raw = _zip_bytes(files)
    identity_suffix = digest({"basis": basis, "refs": refs})[:32]
    path = safe_repo_path(root, root / HANDOFFS / ("C-MATH-HANDOFF-" + identity_suffix + ".zip"))
    _write_new(path, raw)
    return {"status": "ready", "path": path.relative_to(root).as_posix(), "sha256": file_hash(path),
            "schema": HANDOFF_SCHEMA, "files": sorted(files)}


def advance_audit(repo_root: Path | str, identity: str) -> dict:
    root = Path(repo_root).resolve()
    evidence = load_evidence(root, identity)
    directory = _audit_directory(root, identity)
    state_path = safe_repo_path(root, directory / "state.json")
    state = _verified_audit_state(root, identity)
    if state.get("session_id") != evidence.get("session_id"):
        raise ValueError("audit_state_session_mismatch")
    if state.get("status") == "completed":
        state["c_handoff"] = _verified_completed_handoff(root, identity, state)
        return state
    if state.get("status") == "required_correction_unsupported":
        return {**state, "formal_learning_event_count_added": 0,
                "c_handoff": {"status": "not_ready"}}
    concept_payload = json.loads((directory / "concept-session.json").read_bytes())
    prepared = json.loads((directory / "prepared-profile.json").read_bytes())
    review = _load_module("concept_review", root / "错题知识网络/scripts/math_concept_review.py")
    profiles = _load_module("profiles", root / "错题知识网络/scripts/math_learning_profiles.py")
    postcommit = _load_module("postcommit", root / "数学一回滚复习系统/scripts/math_postcommit.py")
    commit_result = state.get("commit_result")
    if not isinstance(commit_result, dict):
        try:
            commit_result = review.commit_session(root, concept_payload, postcommit=False)
        except ValueError as exc:
            if str(exc) == "concept_review_session_conflict":
                state.update(status="required_correction_unsupported", reason=str(exc),
                             resolution="keep_immutable_event_and_prepare_an_explicit_supported_revision")
                _replace_json(state_path, state)
                return {**state, "formal_learning_event_count_added": 0,
                        "c_handoff": {"status": "not_ready"}}
            raise
        state.update(status="formal_committed", commit_result=commit_result,
                     duplicate_learning_event_created=False,
                     formal_learning_event_count_added=int(commit_result.get("status") == "recorded"))
        _replace_json(state_path, state)
    committed = review.committed_event(root, commit_result["event_id"])
    if committed["content_sha256"] != commit_result["content_sha256"]:
        raise ValueError("committed_concept_event_readback_mismatch")
    profile_result = state.get("profile_result")
    if not isinstance(profile_result, dict):
        profile_result = profiles.accept_updates(root, prepared, commit_result["event_id"])
        state.update(status="profiles_accepted", profile_result=profile_result)
        _replace_json(state_path, state)
    elif profile_result.get("status") not in {"accepted", "noop"}:
        raise ValueError("saved_profile_acceptance_not_complete")
    continuation = state.get("postcommit")
    local_ready = (isinstance(continuation, dict)
                   and continuation.get("local_refresh", {}).get("status") == "refreshed"
                   and continuation.get("concept_index", {}).get("status") in {"ready", "noop"})
    current = _verify_publication_current() if local_ready else {"status": "SYNC_PENDING"}
    if not local_ready or current.get("status") != "PUBLISHED_CURRENT":
        continuation = postcommit.run_after_commit(root, commit_result["event_id"])
        state.update(status="postcommit_finished", postcommit=continuation)
        _replace_json(state_path, state)
        current = _verify_publication_current()
    state["publication_current"] = current
    profile_ready = profile_result.get("status") in {"accepted", "noop"}
    local_ready = continuation.get("local_refresh", {}).get("status") == "refreshed" and continuation.get("concept_index", {}).get("status") in {"ready", "noop"}
    if not (profile_ready and local_ready and current.get("status") == "PUBLISHED_CURRENT"):
        state["status"] = "publication_pending"
        state["c_handoff"] = {"status": "not_ready", "reason": "formal_profiles_or_publication_not_current"}
        _replace_json(state_path, state)
        return {**state, "resume_command": f"python3 错题知识网络/scripts/math_review_handoff.py resume --evidence-id {identity}"}
    handoff = _emit_c_handoff(root, identity, state)
    state.update(status="completed", c_handoff=handoff)
    _replace_json(state_path, state)
    return state


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    preserve = commands.add_parser("preserve", help="Seal one exact B learning session as raw evidence only")
    for name in ("rollout", "session-id", "study-date", "started-at", "ended-at", "start-line", "end-user-line", "review-package"):
        options = {"required": True}
        if name in {"start-line", "end-user-line"}:
            options["type"] = int
        elif name in {"rollout", "review-package"}:
            options["type"] = Path
        preserve.add_argument("--" + name, **options)
    preserve.add_argument("--end-assistant-line", type=int)
    preserve.add_argument("--artifacts-json", type=Path)
    read = commands.add_parser("read", help="Verify and return the exact source and archive manifests")
    selector = read.add_mutually_exclusive_group(required=True)
    selector.add_argument("--session-id")
    selector.add_argument("--evidence-id")
    audit = commands.add_parser("audit", help="Prepare, commit and publish one GPT-6 evidence audit")
    audit.add_argument("--input", type=Path, required=True)
    resume = commands.add_parser("resume", help="Resume only the post-prepare stages of one audit")
    resume.add_argument("--evidence-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "preserve":
            result = preserve_evidence(args.repo, args)
        elif args.command == "read":
            result = read_evidence(args.repo, session_id=args.session_id, identity=args.evidence_id)
        elif args.command == "audit":
            result = prepare_audit(args.repo, json.loads(args.input.read_bytes()))
        else:
            result = advance_audit(args.repo, args.evidence_id)
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": str(exc), "error_type": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") not in {"error", "required_correction_unsupported"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
