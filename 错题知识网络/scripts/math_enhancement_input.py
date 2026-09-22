#!/usr/bin/env python3
"""Verify and stage one supplied Project A math ZIP without formal writes."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from typing import Any


CURRENT_CONTRACT = "math-final-semantics-and-profiles-v2"
PROFILE_SCHEMA = "math-learning-profile-update-v1"
STAGE_SCHEMA = "math-enhancement-prepared-input-v1"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
REFERENCE_FIELDS = {
    "evidence_refs", "source_refs", "evidence_ref", "source_ref",
    "history_evidence_refs", "current_evidence_refs",
}
MAX_FILES = 100_000
MAX_JSON_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_BYTES = 8 * 1024 * 1024 * 1024
CHUNK = 1024 * 1024


class EnhancementInputError(ValueError):
    pass


def fail(code: str, detail: Any = None) -> None:
    message = code if detail is None else f"{code}: {detail}"
    raise EnhancementInputError(message)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or any(ord(char) < 32 for char in value):
        fail("unsafe_path", field)
    path = PurePosixPath(value)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", value) or any(part in {"", ".", ".."} for part in value.split("/")):
        fail("unsafe_path", field)
    return str(path)


def require_file(path: Path, root: Path | None = None) -> Path:
    if not path.is_file() or path.is_symlink():
        fail("missing_or_unsafe_file", str(path))
    if root is not None:
        resolved_root = root.resolve()
        resolved = path.resolve()
        if not resolved.is_relative_to(resolved_root):
            fail("path_escapes_root", str(path))
        cursor = path
        while cursor != root:
            if cursor.is_symlink():
                fail("symlink_source", str(cursor))
            cursor = cursor.parent
    return path


def load_json(path: Path) -> Any:
    require_file(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        fail("json_too_large", str(path))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnhancementInputError(f"invalid_json: {path}") from exc


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(item.is_symlink() for item in (path, *path.parents)):
        fail("symlink_destination", str(path))
    with path.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def copy_new(source: Path, destination: Path) -> None:
    require_file(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if any(item.is_symlink() for item in (destination, *destination.parents)):
        fail("symlink_destination", str(destination))
    with source.open("rb") as inp, destination.open("xb") as out:
        shutil.copyfileobj(inp, out, CHUNK)
        out.flush()
        os.fsync(out.fileno())


def extract_zip(source: Path, destination: Path, max_bytes: int) -> Path:
    require_file(source)
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES:
                fail("archive_file_count_exceeded")
            seen, files, total = set(), set(), 0
            for entry in entries:
                raw = entry.filename.rstrip("/") if entry.is_dir() else entry.filename
                path = safe_relative(raw, "zip_member")
                normalized = unicodedata.normalize("NFC", path).casefold()
                if normalized in seen:
                    fail("duplicate_archive_path", path)
                seen.add(normalized)
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode) or (mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
                    fail("archive_special_file", path)
                if entry.flag_bits & 1:
                    fail("encrypted_archive_unsupported", path)
                if not entry.is_dir():
                    total += entry.file_size
                    files.add(normalized)
                    if total > max_bytes:
                        fail("archive_size_exceeded", max_bytes)
            for path in seen:
                if any(str(parent) in files for parent in PurePosixPath(path).parents if str(parent) != "."):
                    fail("archive_file_directory_collision", path)
            if total + 64 * 1024 * 1024 > shutil.disk_usage(destination.parent).free:
                fail("insufficient_temp_disk", total)
            destination.mkdir(parents=True)
            for entry in entries:
                raw = entry.filename.rstrip("/") if entry.is_dir() else entry.filename
                target = destination / safe_relative(raw, "zip_member")
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                count = 0
                with archive.open(entry) as inp, target.open("xb") as out:
                    while True:
                        block = inp.read(CHUNK)
                        if not block:
                            break
                        count += len(block)
                        if count > entry.file_size:
                            fail("archive_size_mismatch", entry.filename)
                        out.write(block)
                if count != entry.file_size:
                    fail("archive_size_mismatch", entry.filename)
    except (zipfile.BadZipFile, RuntimeError, EOFError) as exc:
        raise EnhancementInputError("invalid_zip") from exc
    return destination


def validate_manifest(root: Path, requested_run_id: str | None) -> tuple[dict[str, Any], str]:
    manifest = load_json(require_file(root / "manifest.json", root))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        fail("invalid_manifest_schema")
    if manifest.get("project") != "A" or manifest.get("subject") != "math":
        fail("not_project_A_math")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not ID_RE.fullmatch(run_id):
        fail("invalid_run_id")
    if requested_run_id is not None and requested_run_id != run_id:
        fail("run_id_mismatch")
    commit = manifest.get("source_commit")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        fail("invalid_source_commit")
    packages = manifest.get("input_packages")
    if not isinstance(packages, list) or not packages:
        fail("input_packages_required")
    package_ids = []
    for row in packages:
        if not isinstance(row, dict) or not {"package_id", "version", "zip_sha256"} <= set(row):
            fail("invalid_input_package_binding")
        if not isinstance(row["package_id"], str) or not ID_RE.fullmatch(row["package_id"]):
            fail("invalid_input_package_id")
        if not HASH_RE.fullmatch(str(row["version"])) or not HASH_RE.fullmatch(str(row["zip_sha256"])):
            fail("invalid_input_package_hash", row["package_id"])
        package_ids.append(row["package_id"])
    if len(package_ids) != len(set(package_ids)):
        fail("duplicate_input_package")
    inventory = manifest.get("files")
    if not isinstance(inventory, list):
        fail("missing_file_inventory")
    declared = {}
    for row in inventory:
        if not isinstance(row, dict):
            fail("invalid_file_inventory_row")
        path = safe_relative(row.get("path"), "manifest.files.path")
        if path == "manifest.json" or path in declared:
            fail("duplicate_file_binding", path)
        if not HASH_RE.fullmatch(str(row.get("sha256"))) or not isinstance(row.get("size"), int) or row["size"] < 0:
            fail("invalid_file_binding", path)
        if not isinstance(row.get("role"), str) or not row["role"]:
            fail("file_role_required", path)
        file = require_file(root / path, root)
        if file.stat().st_size != row["size"] or file_sha256(file) != row["sha256"]:
            fail("output_file_hash_mismatch", path)
        declared[path] = row
    actual = {
        path.relative_to(root).as_posix() for path in root.rglob("*")
        if path.is_file() and path.name != ".DS_Store" and "__MACOSX" not in path.parts
    }
    if set(declared) != actual - {"manifest.json"}:
        fail("manifest_member_coverage_mismatch", sorted((set(declared) ^ (actual - {"manifest.json"}))))
    contract = manifest.get("contract_version")
    if contract == CURRENT_CONTRACT:
        allowed = {
            "schema_version", "project", "subject", "run_id", "source_commit",
            "contract_version", "input_packages", "files", "snapshot_id", "publication_target",
            "batch_binding", "profile_merge_policy",
        }
        if set(manifest) - allowed:
            fail("unexpected_current_manifest_fields", sorted(set(manifest) - allowed))
        if manifest.get("batch_binding") is not None:
            if manifest.get("profile_merge_policy") != "deferred_batch_merge":
                fail("topic_batch_deferred_profile_merge_required")
        elif manifest.get("profile_merge_policy") is not None:
            fail("profile_merge_policy_without_topic_batch")
        if not {"advice.json", "profile_updates.json"} <= set(declared):
            fail("current_contract_business_files_missing")
        generation = "v5_current"
    else:
        if "advice.json" not in declared:
            fail("legacy_advice_missing")
        generation = "legacy_v4"
    return manifest, generation


def collect_references(value: Any, origin: str, pointer: str = "") -> list[dict[str, Any]]:
    result = []
    if isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(collect_references(child, origin, f"{pointer}/{index}"))
    elif isinstance(value, dict):
        for key, child in value.items():
            child_pointer = f"{pointer}/{key}"
            if key in REFERENCE_FIELDS:
                rows = child if isinstance(child, list) else [child]
                if not all(isinstance(row, dict) for row in rows):
                    fail("invalid_evidence_reference", child_pointer)
                for index, row in enumerate(rows):
                    path = safe_relative(row.get("path"), f"{child_pointer}/{index}/path")
                    if not HASH_RE.fullmatch(str(row.get("sha256"))):
                        fail("invalid_evidence_hash", path)
                    result.append({"origin": origin, "pointer": f"{child_pointer}/{index}", "ref": row})
            else:
                result.extend(collect_references(child, origin, child_pointer))
    return result


def validate_business(root: Path, manifest: dict[str, Any], generation: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    advice = load_json(require_file(root / "advice.json", root))
    items = advice.get("items") if isinstance(advice, dict) else None
    if not isinstance(items, list) or not items or not all(isinstance(row, dict) for row in items):
        fail("advice_items_required")
    pairs = []
    for item in items:
        package_id, question_id = item.get("package_id"), item.get("question_id")
        if not isinstance(package_id, str) or not isinstance(question_id, str) or not question_id.strip():
            fail("advice_item_identity_required")
        pairs.append((package_id, question_id))
        if not isinstance(item.get("uncertainties"), list):
            fail("advice_uncertainties_required", question_id)
        recommendation = item.get("recommendation")
        if generation == "v5_current" and (
            not isinstance(recommendation, dict)
            or not isinstance(recommendation.get("formal_card"), dict)
            or not recommendation["formal_card"]
            or not isinstance(recommendation.get("exam_writeup"), str)
            or not recommendation["exam_writeup"].strip()
            or not isinstance(recommendation.get("observations"), list)
            or (not recommendation['observations'] and not (
                recommendation.get('observation_scope') == 'no_observation' and
                isinstance(recommendation.get('no_observation_reason'), str) and
                recommendation['no_observation_reason'].strip()))
        ):
            fail("current_math_final_semantics_required", question_id)
    expected = {row["package_id"] for row in manifest["input_packages"]}
    if len(pairs) != len(set(pairs)) or {pair[0] for pair in pairs} != expected:
        fail("advice_package_coverage_mismatch")
    profiles = None
    profile_path = root / "profile_updates.json"
    if profile_path.is_file():
        profiles = load_json(require_file(profile_path, root))
        updates = profiles.get("updates") if isinstance(profiles, dict) else None
        if profiles.get("schema") != PROFILE_SCHEMA or not isinstance(updates, list) or not updates:
            fail("profile_update_schema_required")
        keys = [row.get("concept_key") for row in updates if isinstance(row, dict)]
        if len(keys) != len(updates) or len(keys) != len(set(keys)):
            fail("profile_concepts_invalid_or_duplicate")
    elif generation == "v5_current":
        fail("current_profile_updates_missing")
    return advice, profiles


def zip_json_member(path: Path, member: str) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            matches = [info for info in archive.infolist() if info.filename == member]
            if len(matches) != 1 or matches[0].file_size > MAX_JSON_BYTES or matches[0].flag_bits & 1:
                fail("quick_pack_manifest_member_invalid", str(path))
            mode = matches[0].external_attr >> 16
            if stat.S_ISLNK(mode):
                fail("quick_pack_manifest_member_invalid", str(path))
            value = json.loads(archive.read(matches[0]).decode("utf-8"))
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        raise EnhancementInputError(f"quick_pack_manifest_member_invalid: {path}") from exc
    if not isinstance(value, dict):
        fail("quick_pack_manifest_member_invalid", str(path))
    return value


def publication_receipt(bridge_root: Path, commit: str, explicit: Path | None) -> tuple[dict[str, Any], Path]:
    candidates = [explicit] if explicit else list((bridge_root / "publication/math/receipts").glob("*.json"))
    matches = []
    for path in candidates:
        if path is None or not path.is_file() or path.is_symlink():
            continue
        row = load_json(path)
        if (
            isinstance(row, dict) and row.get("status") == "PUBLISHED"
            and row.get("subject") == "math" and row.get("branch") == "main"
            and row.get("source_commit") == commit and HASH_RE.fullmatch(str(row.get("manifest_sha256")))
        ):
            matches.append((row, path.resolve()))
    if not matches:
        fail("verified_publication_receipt_missing", commit)
    hashes = {row["manifest_sha256"] for row, _ in matches}
    if len(hashes) != 1:
        fail("publication_receipt_manifest_conflict", commit)
    return matches[0]


class PublishedSnapshot:
    def __init__(self, bridge_root: Path, commit: str, receipt_path: Path | None,
                 published_root: Path | None, temporary: Path):
        self.bridge_root = bridge_root.resolve()
        self.commit = commit
        self.receipt, self.receipt_path = publication_receipt(self.bridge_root, commit, receipt_path)
        self.root = published_root.resolve(strict=True) if published_root else None
        self.checkout = self.bridge_root / "publication/math/checkout"
        if self.root is None and (not self.checkout.is_dir() or self.checkout.is_symlink()):
            fail("publication_checkout_unavailable")
        self.temporary = temporary
        manifest_file = self.materialize_unchecked("PUBLISHED_LIBRARY.json", "root-manifest.json")
        if file_sha256(manifest_file) != self.receipt["manifest_sha256"]:
            fail("published_manifest_hash_mismatch")
        self.library = load_json(manifest_file)
        if (
            self.library.get("subject") != "math"
            or self.library.get("repository") != "YOUR_GITHUB_ACCOUNT/kaoyan-math"
            or self.library.get("branch") != "main"
        ):
            fail("published_library_identity_mismatch")
        rows = list(self.library.get("files", []))
        for number, shard in enumerate(self.library.get("file_inventory", [])):
            path = safe_relative(shard.get("path"), "file_inventory.path")
            if not HASH_RE.fullmatch(str(shard.get("sha256"))):
                fail("invalid_inventory_shard", path)
            file = self.materialize_unchecked(path, f"inventory-{number}.jsonl")
            if file_sha256(file) != shard["sha256"]:
                fail("inventory_shard_hash_mismatch", path)
            try:
                values = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise EnhancementInputError(f"invalid_inventory_shard: {path}") from exc
            if len(values) != shard.get("count"):
                fail("inventory_shard_count_mismatch", path)
            rows.extend(values)
        self.known = {}
        for row in rows:
            if not isinstance(row, dict):
                fail("invalid_published_file_inventory")
            path = safe_relative(row.get("path"), "published_file.path")
            if path in self.known or not HASH_RE.fullmatch(str(row.get("sha256"))):
                fail("invalid_or_duplicate_published_file", path)
            self.known[path] = row
        self.known["PUBLISHED_LIBRARY.json"] = {"path": "PUBLISHED_LIBRARY.json", "sha256": self.receipt["manifest_sha256"]}

    def materialize_unchecked(self, path: str, name: str) -> Path:
        path = safe_relative(path, "published_path")
        destination = self.temporary / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self.root is not None:
            source = require_file(self.root / path, self.root)
            copy_new(source, destination)
            return destination
        with destination.open("xb") as output:
            result = subprocess.run(
                ["git", "-C", str(self.checkout), "show", f"{self.commit}:{path}"],
                stdout=output, stderr=subprocess.DEVNULL, timeout=60, check=False,
            )
        if result.returncode:
            fail("published_source_unavailable", path)
        pointer = destination.read_bytes()[:250]
        if pointer.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
            match = re.search(rb"oid sha256:([0-9a-f]{64})", pointer)
            if not match:
                fail("invalid_lfs_pointer", path)
            digest = match.group(1).decode()
            candidates = [
                self.checkout / ".git/lfs/objects" / digest[:2] / digest[2:4] / digest,
                self.bridge_root / "publication/math/lfs-readback/objects" / digest[:2] / digest[2:4] / digest,
            ]
            originals = [
                candidate for candidate in candidates
                if candidate.is_file() and not candidate.is_symlink() and file_sha256(candidate) == digest
            ]
            if not originals:
                fail("local_lfs_original_unavailable", path)
            destination.unlink()
            copy_new(originals[0], destination)
        return destination

    def source(self, path: str, expected_sha256: str, number: int) -> Path:
        path = safe_relative(path, "published_path")
        row = self.known.get(path)
        if row is None or row.get("sha256") != expected_sha256:
            fail("snapshot_reference_not_in_fixed_commit", path)
        file = self.materialize_unchecked(path, f"source-{number}")
        if file_sha256(file) != expected_sha256:
            fail("snapshot_reference_hash_mismatch", path)
        return file


class QuickPackages:
    def __init__(self, repo: Path, bridge_root: Path, bindings: list[dict[str, Any]]):
        self.repo = repo
        self.bridge_root = bridge_root
        self.bindings = {row["package_id"]: row for row in bindings}
        scripts = repo / "数学一回滚复习系统/scripts"
        sys.path.insert(0, str(scripts))
        import quick_intake
        self.quick = quick_intake
        self.packages: dict[str, dict[str, Any]] = {}
        for package_id, binding in self.bindings.items():
            manifests = list((repo / "数学一回滚复习系统/快速入库来源").glob(f"*/{package_id}/manifest.json"))
            if len(manifests) != 1:
                fail("local_package_manifest_not_unique", package_id)
            manifest_path = manifests[0].resolve()
            manifest = load_json(manifest_path)
            try:
                self.quick.validate_conversation_package_manifest(manifest, manifest_path, "A.enhancement")
            except self.quick.QuickIntakeError as exc:
                raise EnhancementInputError(f"local_package_invalid: {package_id}: {exc}") from exc
            if manifest.get("canonical_sha256") != binding["version"]:
                fail("local_package_version_mismatch", package_id)
            archives = [
                path for path in (bridge_root / "outbox").glob("*/quick-packs/math/*.zip")
                if path.name.endswith(f"_{package_id}.zip") and file_sha256(path) == binding["zip_sha256"]
            ]
            if not archives:
                fail("bridge_quick_pack_zip_binding_missing", package_id)
            bridge_manifests = [zip_json_member(path, "manifest.json") for path in archives]
            if any(value != bridge_manifests[0] for value in bridge_manifests[1:]):
                fail("bridge_quick_pack_manifest_conflict", package_id)
            bridge_manifest = bridge_manifests[0]
            questions = bridge_manifest.get("questions")
            if (
                bridge_manifest.get("kind") != "quick_pack"
                or bridge_manifest.get("subject") != "math"
                or bridge_manifest.get("package_id") != package_id
                or bridge_manifest.get("version") != binding["version"]
                or not isinstance(questions, list) or not questions
                or not all(isinstance(row, dict) and isinstance(row.get("question_id"), str)
                           and row["question_id"].strip() for row in questions)
                or len({row["question_id"] for row in questions}) != len(questions)
            ):
                fail("bridge_quick_pack_manifest_binding_invalid", package_id)
            members = {
                "original/manifest.json": manifest_path,
                "original/receipt.json": manifest_path.parent / "receipt.json",
            }
            for row in manifest["files"].values():
                key = "original/" + Path(row["path"]).name
                if key in members:
                    fail("quick_pack_member_name_conflict", key)
                members[key] = repo / row["path"]
            for row in manifest.get("artifacts", []):
                key = "original/attachments/" + Path(row["path"]).name
                if key in members:
                    fail("quick_pack_member_name_conflict", key)
                members[key] = repo / row["path"]
            self.packages[package_id] = {
                "binding": binding, "manifest_path": manifest_path,
                "manifest_sha256": file_sha256(manifest_path), "members": members,
                "bridge_zip_paths": sorted(str(path.resolve()) for path in archives),
                "question_ids": [row["question_id"] for row in questions],
            }

    def expected_advice_pairs(self) -> set[tuple[str, str]]:
        return {
            (package_id, question_id)
            for package_id, package in self.packages.items()
            for question_id in package["question_ids"]
        }

    def source(self, reference: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        path = safe_relative(reference["path"], "quick_pack_reference")
        parts = PurePosixPath(path).parts
        if len(parts) < 3 or parts[0] != "quick-packs":
            fail("invalid_quick_pack_reference", path)
        package_id = parts[1]
        package = self.packages.get(package_id)
        if package is None:
            fail("quick_pack_not_in_A_manifest", package_id)
        member = "/".join(parts[2:])
        source = package["members"].get(member)
        if source is None:
            fail("quick_pack_member_not_bound", path)
        require_file(source, self.repo)
        if file_sha256(source) != reference["sha256"]:
            fail("quick_pack_member_hash_mismatch", path)
        binding = package["binding"]
        if reference.get("package_id", package_id) != package_id:
            fail("quick_pack_reference_package_mismatch", path)
        if reference.get("package_version", binding["version"]) != binding["version"]:
            fail("quick_pack_reference_version_mismatch", path)
        return source, {
            "source_kind": "current_quick_pack", "package_id": package_id,
            "package_version": binding["version"], "quick_pack_zip_sha256": binding["zip_sha256"],
            "local_manifest_path": str(package["manifest_path"].relative_to(self.repo)),
            "local_manifest_sha256": package["manifest_sha256"],
            "bridge_quick_pack_paths": package["bridge_zip_paths"],
        }


def staged_evidence_path(stage_relative: Path, reference: dict[str, Any]) -> Path:
    suffix = PurePosixPath(reference["path"]).suffix.lower()
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,12}", suffix):
        suffix = ".bin"
    return stage_relative / "evidence" / (reference["sha256"] + suffix)


def replace_profile_refs(profiles: dict[str, Any], mapping: dict[tuple[str, str], str]) -> dict[str, Any]:
    result = json.loads(json.dumps(profiles, ensure_ascii=False))
    for update in result["updates"]:
        replaced = []
        for ref in update["source_refs"]:
            key = (ref["path"], ref["sha256"])
            if key not in mapping:
                fail("profile_reference_mapping_missing", ref["path"])
            replaced.append({**ref, "path": mapping[key], "sha256": ref["sha256"]})
        update["source_refs"] = replaced
    return result


def verify_quote(reference: dict[str, Any], source: Path) -> None:
    quote = reference.get("quote")
    if quote is None:
        return
    if not isinstance(quote, str) or source.stat().st_size > MAX_JSON_BYTES:
        fail("source_quote_unverifiable", reference["path"])
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise EnhancementInputError(f"source_quote_unverifiable: {reference['path']}") from exc
    if quote in text:
        return
    # Conversation quotations refer to decoded turns, not JSON escape syntax.
    # Keep the source bytes/hash intact and require an exact turn substring.
    if source.name == "conversation.json":
        try:
            conversation = json.loads(text)
        except json.JSONDecodeError:
            conversation = None
        turns = conversation.get("turns", []) if isinstance(conversation, dict) else []
        if any(isinstance(turn, dict) and isinstance(turn.get("text"), str)
               and quote in turn["text"] for turn in turns):
            return
    fail("source_quote_mismatch", reference["path"])


def validate_topic_batch(repo: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    binding=manifest.get('batch_binding')
    if binding is None:return None
    if not isinstance(binding,dict) or not ID_RE.fullmatch(str(binding.get('batch_id',''))):
        fail('invalid_topic_batch_binding')
    path=repo/'数学一回滚复习系统/A分包'/binding['batch_id']/'batch-plan.json'
    require_file(path,repo)
    if file_sha256(path)!=binding.get('plan_sha256'):fail('topic_batch_plan_hash_mismatch')
    plan=load_json(path)
    groups=[g for g in plan.get('groups',[]) if g.get('shard_id')==binding.get('shard_id')]
    if len(groups)!=1:fail('topic_batch_shard_unknown')
    group=groups[0]
    if (plan.get('source_commit')!=manifest.get('source_commit')
            or group.get('run_id')!=manifest.get('run_id')
            or group.get('input_packages')!=manifest.get('input_packages')):
        fail('topic_batch_scope_or_snapshot_mismatch')
    return {**binding,'profile_merge_policy':'deferred_batch_merge',
            'group_count':len(plan['groups']),'topic':group.get('topic')}


def stage(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo.expanduser().resolve(strict=True)
    bridge_root = args.bridge_root.expanduser().resolve(strict=True)
    source_zip = args.zip.expanduser().resolve(strict=True)
    require_file(source_zip)
    zip_sha256 = file_sha256(source_zip)
    stage_root = repo / "数学一回滚复习系统/A增强输入"
    stage_root.mkdir(parents=True, exist_ok=True)
    if stage_root.is_symlink() or not stage_root.resolve().is_relative_to(repo):
        fail("unsafe_stage_root")
    lock_path = stage_root / ".lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return _stage_locked(args, repo, bridge_root, source_zip, zip_sha256, stage_root)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _stage_locked(args, repo, bridge_root, source_zip, zip_sha256, stage_root):
    with tempfile.TemporaryDirectory(prefix="math-A-enhancement-") as temporary:
        work = Path(temporary).resolve()
        extracted = extract_zip(source_zip, work / "zip", args.max_unpacked_bytes)
        manifest, generation = validate_manifest(extracted, args.run_id)
        run_id = manifest["run_id"]
        target = stage_root / run_id
        if target.exists():
            receipt_path = require_file(target / "receipt.json", target)
            receipt = load_json(receipt_path)
            if (
                receipt.get("schema_version") != STAGE_SCHEMA
                or receipt.get("run_id") != run_id
                or receipt.get("input_zip_sha256") != zip_sha256
                or receipt.get("source_commit") != manifest["source_commit"]
            ):
                fail("existing_A_stage_conflict", run_id)
            staged_files = receipt.get("staged_files")
            if not isinstance(staged_files, list) or not staged_files:
                fail("existing_A_stage_receipt_incomplete", run_id)
            for row in staged_files:
                path = require_file(repo / safe_relative(row.get("path"), "receipt.staged_files.path"), repo)
                if file_sha256(path) != row.get("sha256") or path.stat().st_size != row.get("size"):
                    fail("existing_A_stage_readback_failed", row.get("path"))
            return response(receipt, receipt_path, "noop")

        advice, profiles = validate_business(extracted, manifest, generation)
        batch_binding=validate_topic_batch(repo,manifest)
        snapshot_root = args.published_root.expanduser().resolve(strict=True) if args.published_root else None
        snapshot = PublishedSnapshot(
            bridge_root, manifest["source_commit"], args.publication_receipt,
            snapshot_root, work / "published",
        )
        if profiles is not None and batch_binding is None:
            # An immutable old snapshot proves provenance, not currentness.
            # Do not bind old web prose to a newly computed current basis.
            sys.path.insert(0, str(repo / '错题知识网络/scripts'))
            import study_personalization_math
            current = study_personalization_math.current_identity(repo)
            published = snapshot.library.get('personalization', {})
            if (current.get('status') != 'ready'
                    or not published.get('version')
                    or published.get('version') != current.get('version')
                    or published.get('formal_version') != current.get('formal_version')):
                fail('A_PROFILE_SNAPSHOT_NOT_CURRENT',
                     {'source_commit':manifest['source_commit'], 'current_status':current.get('status'),
                      'action':'refresh the affected A profile input against the current published math snapshot'})
        if manifest.get("publication_target") not in (None, snapshot.receipt.get("publication_target")):
            fail("publication_target_mismatch")
        if manifest.get("snapshot_id") not in (
            None, manifest["source_commit"], snapshot.receipt.get("snapshot_id")
        ):
            fail("publication_snapshot_id_mismatch")
        quick = QuickPackages(repo, bridge_root, manifest["input_packages"])
        actual_pairs = {(item["package_id"], item["question_id"]) for item in advice["items"]}
        if actual_pairs != quick.expected_advice_pairs():
            fail("advice_question_coverage_mismatch", sorted(quick.expected_advice_pairs() - actual_pairs))
        refs = collect_references(advice, "advice.json")
        if profiles is not None:
            refs.extend(collect_references(profiles, "profile_updates.json"))
        if not refs:
            fail("A_output_has_no_source_references")
        claims, resolved = {}, []
        for number, located in enumerate(refs):
            reference = located["ref"]
            path, digest = reference["path"], reference["sha256"]
            if path in claims and claims[path] != digest:
                fail("source_reference_hash_conflict", path)
            claims[path] = digest
            if reference.get("source_commit", manifest["source_commit"]) != manifest["source_commit"]:
                fail("source_reference_commit_mismatch", path)
            if path.startswith("quick-packs/"):
                source, binding = quick.source(reference)
            else:
                source = snapshot.source(path, digest, number)
                binding = {
                    "source_kind": "fixed_publication_snapshot",
                    "source_commit": manifest["source_commit"],
                    "publication_receipt_path": str(snapshot.receipt_path),
                    "publication_manifest_sha256": snapshot.receipt["manifest_sha256"],
                }
            verify_quote(reference, source)
            resolved.append({**located, "source": source, "binding": binding})

        temporary_stage = Path(tempfile.mkdtemp(prefix=f".{run_id}-", dir=stage_root))
        try:
            stage_relative = temporary_stage.relative_to(repo)
            final_relative = target.relative_to(repo)
            copy_new(source_zip, temporary_stage / "input.zip")
            copy_new(extracted / "manifest.json", temporary_stage / "manifest.json")
            copy_new(extracted / "advice.json", temporary_stage / "advice.json")
            if profiles is not None:
                copy_new(extracted / "profile_updates.json", temporary_stage / "profile_updates.json")
            mapping_rows, mapping = [], {}
            for located in resolved:
                reference, source = located["ref"], located["source"]
                temp_rel = staged_evidence_path(stage_relative, reference)
                final_rel = staged_evidence_path(final_relative, reference)
                destination = repo / temp_rel
                if not destination.exists():
                    copy_new(source, destination)
                elif file_sha256(destination) != reference["sha256"]:
                    fail("staged_evidence_hash_conflict", str(temp_rel))
                if file_sha256(destination) != reference["sha256"]:
                    fail("staged_evidence_copy_failed", reference["path"])
                mapping[(reference["path"], reference["sha256"])] = str(final_rel)
                mapping_rows.append({
                    "origin": located["origin"], "json_pointer": located["pointer"],
                    "original_ref": reference, "staged_path": str(final_rel),
                    **located["binding"],
                })
            mapping_document = {
                "schema_version": "math-enhancement-source-mappings-v1",
                "run_id": run_id, "source_commit": manifest["source_commit"],
                "mappings": mapping_rows,
            }
            write_new(temporary_stage / "source_mappings.json", canonical(mapping_document))

            prepared = None
            gaps = []
            if profiles is None:
                gaps.append({"kind": "legacy_v4_missing_profile_updates", "file": "profile_updates.json"})
            else:
                final_payload = replace_profile_refs(profiles, mapping)
                write_new(temporary_stage / "profile_updates.local.json", canonical(final_payload))
                temp_mapping = {
                    key: str(staged_evidence_path(stage_relative, {"path": key[0], "sha256": key[1]}))
                    for key in mapping
                }
                validation_payload = replace_profile_refs(profiles, temp_mapping)
                if batch_binding:
                    # The old snapshot remains provenance. This is only a
                    # contribution staged for an explicit latest-state merge.
                    validation_payload['web_basis_version']=profiles.get('basis_version')
                    validation_payload['basis_version']=None
                sys.path.insert(0, str(repo / "错题知识网络/scripts"))
                import math_learning_profiles
                try:
                    prepared = math_learning_profiles.prepare_updates(repo, validation_payload)
                except ValueError as exc:
                    reason = str(exc)
                    if reason.startswith("unknown_or_duplicate_profile_concept:"):
                        key = reason.split(":", 1)[1]
                        gaps.append({"kind": "unknown_profile_concept", "concept_key": key})
                    else:
                        raise
                if prepared is not None:
                    if batch_binding:
                        prepared['_deferred_batch_merge']=batch_binding
                    for update in prepared["updates"]:
                        for ref in update["source_refs"]:
                            temporary_prefix = str(stage_relative) + "/"
                            if not ref["path"].startswith(temporary_prefix):
                                fail("prepared_profile_reference_not_staged", ref["path"])
                            ref["path"] = str(final_relative) + "/" + ref["path"][len(temporary_prefix):]
                    write_new(temporary_stage / "prepared_profiles.json", canonical(prepared))

            files = []
            for path in sorted(temporary_stage.rglob("*")):
                if path.is_file():
                    final_path = final_relative / path.relative_to(temporary_stage)
                    files.append({"path": str(final_path), "sha256": file_sha256(path), "size": path.stat().st_size})
            status = (
                "prepared" if prepared is not None
                else "legacy_v4_profile_updates_missing" if profiles is None
                else "profile_concept_mapping_required"
            )
            receipt = {
                "schema_version": STAGE_SCHEMA, "status": status,
                "project": "A", "subject": "math", "run_id": run_id,
                "contract_version": manifest.get("contract_version"),
                "contract_generation": generation, "source_commit": manifest["source_commit"],
                "batch_binding":batch_binding,
                "profile_merge_required":bool(batch_binding),
                "input_zip_sha256": zip_sha256, "input_packages": manifest["input_packages"],
                "advice_item_count": len(advice["items"]),
                "profile_update_count": len(profiles["updates"]) if profiles else 0,
                "prepared_profile_count": len(prepared["updates"]) if prepared else 0,
                "gaps": gaps, "staged_files": files,
                "formal_write_count": 0, "learning_event_count": 0,
            }
            write_new(temporary_stage / "receipt.json", canonical(receipt))
            os.replace(temporary_stage, target)
            directory = os.open(stage_root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            receipt_path = target / "receipt.json"
            return response(receipt, receipt_path, "recorded")
        finally:
            if temporary_stage.exists():
                shutil.rmtree(temporary_stage)


def response(receipt: dict[str, Any], receipt_path: Path, stage_status: str) -> dict[str, Any]:
    root = receipt_path.parent
    prepared = root / "prepared_profiles.json"
    advice = root / "advice.json"
    return {
        "status": receipt["status"], "stage_status": stage_status,
        "run_id": receipt["run_id"], "source_commit": receipt["source_commit"],
        "contract_generation": receipt["contract_generation"],
        "stage_path": str(root), "receipt_path": str(receipt_path),
        "receipt_sha256": file_sha256(receipt_path),
        "advice_path": str(advice),
        "advice_items": [
            {"json_pointer": f"/items/{index}", "package_id": item.get("package_id"),
             "question_id": item.get("question_id")}
            for index, item in enumerate(load_json(advice)["items"])
        ],
        "prepared_profiles_path": str(prepared) if prepared.is_file() else None,
        "prepared_profile_count": receipt["prepared_profile_count"],
        "batch_binding":receipt.get('batch_binding'),
        "profile_merge_required":receipt.get('profile_merge_required',False),
        "gaps": receipt["gaps"], "formal_write_count": 0, "learning_event_count": 0,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--zip", type=Path, required=True, help="Actual downloaded Project A math ZIP")
    value.add_argument("--run-id", help="Optional exact run ID assertion")
    value.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    value.add_argument("--bridge-root", type=Path, default=Path("/Users/your-user/Documents/Study-Pro-Bridge"))
    value.add_argument("--published-root", type=Path, help="Optional already materialized fixed-snapshot root")
    value.add_argument("--publication-receipt", type=Path, help="Optional exact verified publication receipt")
    value.add_argument("--max-unpacked-bytes", type=int, default=DEFAULT_MAX_BYTES)
    return value


def main() -> int:
    try:
        args = parser().parse_args()
        if args.max_unpacked_bytes <= 0:
            fail("invalid_max_unpacked_bytes")
        print(json.dumps(stage(args), ensure_ascii=False, sort_keys=True))
        return 0
    except (EnhancementInputError, OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "error", "error": str(exc),
                          "formal_write_count": 0, "learning_event_count": 0}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
