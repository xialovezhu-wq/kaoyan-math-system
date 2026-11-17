#!/usr/bin/env python3
"""Describe the complete saved math library for the shared publisher.

This entry refreshes existing deterministic learning-state projections before
binding source bytes. It never commits, pushes, updates learning facts, scores
or schedules, or repairs an archive. Historical incompleteness remains explicit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "错题知识网络/scripts"))
import study_personalization_math
import math_runtime_paths
import math_learning_state
import math_workflow_storage

ARCHIVE_ROOT = Path("/Volumes/T9-Data")
ARCHIVE_PREFIX = "03_数学/资料库/原始会话资料"
FORMAL_RE = re.compile(r"^(?:GS|LA|PR)-\d{3,}$")
SUFFIXES = {".md", ".json", ".jsonl", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".txt", ".csv", ".tsv", ".xlsx", ".docx", ".pdf", ".html", ".mmd", ".base"}
TREES = {
    "错题知识网络/错题卡": "formal_card",
    "错题知识网络/可视化错题详情": "visual_reference",
    "错题知识网络/assets": "source_asset",
    "错题知识网络/raw_sources": "raw_source",
    "错题知识网络/批量导入": "raw_source",
    "错题知识网络/wiki": "knowledge_history",
    "错题知识网络/生成": "library_index",
    "错题知识网络/教学投影": "personal_projection",
    "错题知识网络/方法论库": "method_reference",
    "错题知识网络/知识树": "knowledge_reference",
    "错题知识网络/学习记录": "study_history",
    "错题知识网络/复习队列": "review_history",
    "数学一回滚复习系统/快速入库来源": "conversation_package",
    "数学一回滚复习系统/历史证据归档指针": "archive_pointer",
    "数学一回滚复习系统/学习记录": "study_history",
    "数学一回滚复习系统/生成": "review_queue_history",
    "数学一回滚复习系统/复盘来源": "review_source",
    "数学一回滚复习系统/A建议裁决": "advice_decisions",
    "高数讲义": "saved_reference_material",
    "线代讲义": "saved_reference_material",
    "概率论讲义": "saved_reference_material",
    "kaoyan_math_project_v2": "saved_reference_material",
    "真题数据库": "exam_reference",
    "错题知识网络/个人知识点索引/做题方法/公式结论": "formula_reference",
}
SINGLE_FILES = {
    "错题知识网络/知识点库.md": "knowledge_reference",
    "数学一回滚复习系统/复习单元.json": "review_state",
    "数学一回滚复习系统/复习记录.jsonl": "review_events",
    "数学一回滚复习系统/学习前5题记录.jsonl": "delivery_events",
    "数学一回滚复习系统/学习进度.json": "review_configuration",
    "数学一回滚复习系统/公式记忆配置.json": "review_configuration",
    "数学一回滚复习系统/快速入库事件.jsonl": "capture_history",
    "数学一回滚复习系统/原始会话归档回执.jsonl": "archive_receipts",
}
EXCLUDED_PARTS = {"__pycache__", "scripts", "tools", "node_modules", ".git", ".obsidian", ".codex_tmp", ".pytest_cache", "backups", "backup", "正式提交后续", "operation_center", "agent_operation_center"}
A_BATCH_DIRECTORY = "数学一回滚复习系统/A分包"
STUDY_CONTEXT = "support/cmath/learning-context.json"


class DescriptorError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def safe_relative(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not value or "\\" in value:
        raise DescriptorError("unsafe_relative_path")
    return path.as_posix()


def file_stamp(path: Path) -> dict[str, int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise DescriptorError("source_not_regular:" + str(path))
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns, "inode": info.st_ino}


def symlink_stamp(path: Path) -> tuple[Any, ...]:
    info = path.lstat()
    if not stat.S_ISLNK(info.st_mode):
        raise DescriptorError("source_not_compat_symlink:" + str(path))
    return (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, path.readlink())


def safe_under(path: Path, root: Path) -> Path:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DescriptorError("source_outside_allowed_root") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise DescriptorError("source_symlink_forbidden:" + str(path))
    file_stamp(path)
    return path


def business_file(path: Path) -> bool:
    return (path.suffix.lower() in SUFFIXES and not any(part in EXCLUDED_PARTS for part in path.parts)
            and path.name not in {"AGENTS.md", "SKILL.md", ".DS_Store"}
            and not path.name.startswith(".") and "GOAL提示词" not in path.name
            and not path.name.endswith((".bak", ".backup", ".lock")))


def ledger_context(path: Path, *, capture: bool = False) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "not_present"}
    checksum = hashlib.sha256()
    counts, schemas = Counter(), Counter()
    rows = [] if capture else None
    invalid, total, size = 0, 0, 0
    with path.open("rb") as handle:
        for line in handle:
            checksum.update(line)
            size += len(line)
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("expected object")
            except (UnicodeError, ValueError):
                invalid += 1
                continue
            total += 1
            counts[str(row.get("event_type") or "unlabeled")[:80]] += 1
            schemas[str(row.get("schema_version") or "unlabeled")[:100]] += 1
            if rows is not None:
                rows.append(row)
    result = {"status": "complete_at_eof" if not invalid else "invalid_rows_at_eof",
              "valid_rows": total, "invalid_rows": invalid, "by_event_type": dict(counts),
              "by_schema": dict(schemas), "sha256": checksum.hexdigest(), "bytes": size}
    if rows is not None and not invalid:
        import quick_intake
        try:
            state = quick_intake.replay(rows)
            result["capture_counts"] = {"recorded": len(state["captures"]),
                                        "closed": len(state["closed_by"]),
                                        "pending": len(state["captures"].keys() - state["closed_by"].keys()),
                                        "basis": "native_replay_of_all_capture_events"}
        except (quick_intake.QuickIntakeError, ValueError, TypeError, KeyError):
            result["capture_counts"] = {"status": "native_replay_unavailable"}
    return result


def maintenance_summary(root, event_id, generation, scene_paths):
    import math_postcommit as stages

    if re.fullmatch(r"MATH-ENGINEERING-[0-9a-f]{64}", event_id):
        # An engineering publication has no committed learning transaction.
        # The descriptor has already checked scene dependencies and bytes.
        recipe_ids = {Path(path).stem for path in scene_paths}
        ready = {"riemann-signed-area", "gradient-direction"} <= recipe_ids
        record = {"event_id": event_id, "handoff_kind": "engineering", "native_generation": generation,
                  "required_components": ["concept_index", "study_recipes"],
                  "concept_index": {"status": "ready", "native_generation": generation, "version": generation},
                  "study_recipes": {"status": "ready" if ready else "pending", "native_generation": generation},
                  "publication_event_id": event_id, "publication": {"status": "PENDING"}}
        return stages.summarize_handoff(record, generation, publishing_snapshot=True)
    if not stages.OPAQUE.fullmatch(event_id):
        return stages.summarize_handoff({}, generation)
    matches = []
    if event_id.startswith("MATH-DERIVED-"):
        # These existing receipts bind a one-way derived publication identity
        # to the immutable learning event. No receipt bytes are exported.
        for path in (root / stages.RECEIPTS).glob("*.json"):
            if path.is_symlink():
                continue
            try:
                row = json.loads(path.read_bytes())
            except (OSError, ValueError):
                continue
            if not isinstance(row, dict):
                continue
            origin = row.get("event_id")
            if (row.get("publication_event_id") == event_id and stages._safe_id(origin)
                    and path == stages.receipt_path(root, origin)):
                matches.append(row)
    elif record := stages.read_handoff(root, event_id):
        matches.append(record)
    if len(matches) != 1:
        return stages.summarize_handoff({}, generation)
    return stages.summarize_handoff(matches[0], generation, publishing_snapshot=True)


def describe(repo: Path | str, event_id: str, *, archive_root: Path = ARCHIVE_ROOT) -> dict[str, Any]:
    root = Path(repo).resolve()
    archive_root = archive_root.resolve()
    if not event_id.strip() or len(event_id) > 200 or any(ord(c) < 32 for c in event_id):
        raise DescriptorError("invalid_event_id")
    card_root = root / "错题知识网络/错题卡"
    cards = sorted(p for p in card_root.glob("*.md") if FORMAL_RE.fullmatch(p.stem.split("_", 1)[0]))
    formal_ids = [p.stem.split("_", 1)[0] for p in cards]
    if not cards or len(formal_ids) != len(set(formal_ids)):
        raise DescriptorError("formal_library_missing_or_duplicate_ids")
    # A shared Wiki cluster may change when another card is ingested. The old
    # card's persisted state can then differ from load_state's live projection
    # even though its own learning facts did not change. Refresh only state
    # files already in this descriptor's formal-card scope, before recording
    # their bytes/stamps; missing historical projections remain explicit gaps.
    projection_ids = [identity for identity in formal_ids
                      if math_learning_state.state_path(root, identity).is_file()]
    if projection_ids:
        math_learning_state.refresh_states(root, projection_ids)
    sources: dict[str, dict[str, Any]] = {}
    stamps: dict[str, dict[str, int]] = {}
    gaps: list[dict[str, Any]] = []
    original_mappings: list[dict[str, Any]] = []

    def add(path: Path, published: str, kind: str, *, identities: list[str] | None = None,
            expected_hash: str | None = None, original: str | None = None, role: str | None = None) -> None:
        published = safe_relative(published)
        stamp = file_stamp(path)
        key = str(path)
        if key in stamps and stamps[key] != stamp:
            raise DescriptorError("source_changed_during_description:" + key)
        stamps[key] = stamp
        row: dict[str, Any] = {"source_path": key, "publish_path": published, "kind": kind, "required": True,
                               "visibility": "private_learning", "bytes": stamp["size"]}
        if stamp["size"] > 100 * 1024 * 1024:
            row["storage"] = "git-lfs"
        if identities:
            row["formal_ids"] = sorted(set(identities))
        if expected_hash:
            row["expected_sha256"] = expected_hash
        if original:
            row["original_reference"] = original
        if role:
            row["role"] = role
        if path.name == "learning-state.json":
            value = json.loads(path.read_text())
            identity = value.get("formal_id")
            if (identity not in formal_ids
                    or path != math_learning_state.state_path(root, identity)
                    or value != math_learning_state.load_state(root, identity)):
                raise DescriptorError("learning_state_projection_not_current:" + published)
            row["kind"] = "learning_state"
            row["state_source_version"] = value["source_version"]
        previous = sources.get(published)
        if previous:
            if previous["source_path"] != key:
                # A present local immutable package remains the ordinary path;
                # its archived version also has a separate complete tree.
                if expected_hash:
                    old = previous.get("expected_sha256")
                    if old and old != expected_hash:
                        raise DescriptorError("immutable_source_hash_conflict:" + published)
                    previous["expected_sha256"] = expected_hash
                return
            if expected_hash:
                previous["expected_sha256"] = expected_hash
            return
        sources[published] = row

    # Produce only explicitly reviewed, question-only corrections. Candidate
    # calculation itself never writes materials or learner state.
    import math_morning_ten
    import math_teaching_visual as study_visual
    if math_morning_ten.config(root).get("enabled") is True:
        math_morning_ten.prepare_exam_surfaces(root)
    for relative, kind in TREES.items():
        directory = root / relative
        if directory.is_symlink():
            raise DescriptorError("business_directory_symlink")
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise DescriptorError("business_source_symlink:" + str(path))
            if not path.is_file() or not business_file(path):
                continue
            if path.relative_to(root).is_relative_to(study_visual.STUDY_ASSETS):
                continue
            safe_under(path, root)
            identity = path.stem.split("_", 1)[0]
            ids = [identity] if FORMAL_RE.fullmatch(identity) else []
            if path.parent.name in formal_ids:
                ids = [path.parent.name]
            add(path, path.relative_to(root).as_posix(), kind, identities=ids)
    scene_paths = []
    for scene_id in study_visual.STUDY_MATCH:
        checked = study_visual.checked_study_recipe(root, scene_id, "direct")
        if checked is None:
            gaps.append({"kind": "synthetic_study_scene_not_current", "scene_id": scene_id})
            continue
        scene, _ = checked
        add(safe_under(root / scene["path"], root), scene["path"], "synthetic_study_scene",
            expected_hash=scene["sha256"], role="synthetic_example")
        scene_paths.append(scene["path"])
    scene_manifest_path = (study_visual.STUDY_ASSETS / "manifest.json").as_posix()
    if scene_paths:
        file = safe_under(root / scene_manifest_path, root)
        add(file, scene_manifest_path, "synthetic_study_scene_manifest",
            expected_hash=hashlib.sha256(file.read_bytes()).hexdigest(), role="synthetic_example")
    for relative, kind in SINGLE_FILES.items():
        path = root / relative
        if path.exists():
            add(safe_under(path, root), relative, kind)

    # C handoffs cite the original A batch plan. Publish exactly those immutable
    # plans, not the entire exporter workspace or generated prompts.
    batch_alias = root / A_BATCH_DIRECTORY
    batch_directory = batch_alias
    batch_link_stamp = None
    if batch_alias.is_symlink():
        # This named cold-workflow directory is the only compatibility link
        # accepted here. The shared guard checks the actual mount, UUID, device
        # and math subject boundary without creating or registering any files.
        # Keep the old publication identity, but bind the physical T9 source so
        # the publisher never needs to follow a local compatibility symlink.
        batch_link_stamp = symlink_stamp(batch_alias)
        batch_directory = math_workflow_storage.ensure_cold_output(batch_alias)
        if batch_alias.readlink() != batch_directory:
            raise DescriptorError("A_batch_compat_target_not_canonical")
        if not batch_directory.is_dir():
            raise DescriptorError("A_batch_compat_target_not_directory")
    for path in sorted(batch_directory.glob("A-BATCH-*/batch-plan.json")):
        safe_under(path, math_workflow_storage.T9 if batch_link_stamp else root)
        raw = path.read_bytes()
        plan = json.loads(raw)
        if (plan.get("batch_id") != path.parent.name
                or plan.get("schema") != "math-A-topic-batch-plan-v1"):
            raise DescriptorError("invalid_A_batch_plan:" + str(path))
        published = (Path(A_BATCH_DIRECTORY) / path.relative_to(batch_directory)).as_posix()
        add(path, published, "A_batch_plan", expected_hash=hashlib.sha256(raw).hexdigest())

    receipt_path = root / "数学一回滚复习系统/原始会话归档回执.jsonl"
    receipts = [json.loads(line) for line in receipt_path.read_text().splitlines() if line.strip()] if receipt_path.exists() else []
    if receipts and archive_root == ARCHIVE_ROOT:
        import archive_conversation_package
        archive_conversation_package.validate_volume(archive_root)
    for receipt in receipts:
        relative = safe_relative(receipt["raw_archive_relpath"])
        if not relative.startswith(ARCHIVE_PREFIX + "/"):
            raise DescriptorError("archive_outside_math_subject")
        package = archive_root / relative
        manifest_path = safe_under(package / "manifest.json", archive_root)
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("subject") != "math":
            raise DescriptorError("archive_subject_mismatch")
        ids = receipt.get("formal_ids", [])
        prefix = "published-originals/t9/" + relative
        add(manifest_path, prefix + "/manifest.json", "archive_manifest", identities=ids,
            expected_hash=receipt.get("raw_archive_manifest_sha256"), original=str(manifest_path))
        legacy = "legacy" in receipt["schema_version"]
        if legacy:
            gaps.append({"kind": "historical_conversation_incomplete", "capture_id": receipt.get("capture_event_id"),
                         "formal_ids": ids, "evidence_mode": receipt.get("evidence_mode"), "conversation_complete": False,
                         "canonical_package": False, "preserved_archive": prefix})
            descriptors = manifest.get("payload_files", [])
        else:
            descriptors = [{"archive_path": Path(v["path"]).name, "original_path": v["path"], **v}
                           for v in manifest.get("files", {}).values()]
            descriptors += [{"archive_path": "attachments/" + Path(v["path"]).name, "original_path": v["path"], **v}
                            for v in manifest.get("artifacts", [])]
            archived_receipt = safe_under(package / "receipt.json", archive_root)
            add(archived_receipt, prefix + "/receipt.json", "archive_receipt", identities=ids)
        for descriptor in descriptors:
            child_relative = safe_relative(descriptor["archive_path"])
            path = safe_under(package / child_relative, archive_root)
            if descriptor.get("size") is not None and file_stamp(path)["size"] != descriptor["size"]:
                raise DescriptorError("archive_size_mismatch:" + str(path))
            published = prefix + "/" + child_relative
            original = descriptor.get("original_path")
            add(path, published, "archived_original", identities=ids, expected_hash=descriptor.get("sha256"), original=original or str(path), role=descriptor.get("role"))
            if original and descriptor.get("kind") != "ledger_events":
                local_relative = safe_relative(original)
                original_mappings.append({"original_reference": local_relative, "publish_path": published, "archive_receipt_id": receipt["receipt_id"]})
                if not (root / local_relative).is_file():
                    add(path, local_relative, "restored_published_original", identities=ids, expected_hash=descriptor.get("sha256"), original=str(path), role=descriptor.get("role"))

    # Only explicit references can introduce files outside the business trees.
    # Do not crawl the user's attachment store, visualizations or data disk.
    external_roots = [math_runtime_paths.codex_home() / "attachments", math_runtime_paths.codex_home() / "visualizations"]
    texts = [Path(row["source_path"]) for row in sources.values() if Path(row["source_path"]).suffix.lower() in {".md", ".json"} and Path(row["source_path"]).is_relative_to(root)]
    for path in sorted(set(texts)):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(/Users/[^\n\]\"`<>]+?/\.codex/(?:attachments|visualizations)/[^\n\]\"`<>]+?\.(?:svg|png|jpg|jpeg|webp|txt|pdf))", text):
            original = match.group(1)
            candidate = Path(original)
            allowed = next((p for p in external_roots if candidate.is_relative_to(p)), None)
            if allowed is None:
                continue
            if not candidate.is_file():
                gaps.append({"kind": "missing_external_reference", "source": str(path.relative_to(root)), "reference": original})
                continue
            safe_under(candidate, allowed)
            published = "published-originals/external/" + hashlib.sha256(original.encode()).hexdigest()[:20] + "/" + candidate.name
            add(candidate, published, "external_original", original=original)
            original_mappings.append({"original_reference": original, "publish_path": published})
        for match in re.finditer(r"((?:高数讲义|线代讲义|概率论讲义|kaoyan_math_project_v2)/[^\n\]\"`<>]+?\.(?:pdf|md|json|xlsx|docx))", text):
            relative = match.group(1)
            candidate = root / relative
            if candidate.is_file():
                add(safe_under(candidate, root), relative, "referenced_original")

    for identity in formal_ids:
        relative = f"错题知识网络/教学投影/{identity}/learning-state.json"
        if relative not in sources:
            gaps.append({"kind": "latest_learning_state_projection_missing", "formal_id": identity})
    media: dict[str, set[str]] = {identity: set() for identity in formal_ids}
    visual_manifest = root / "错题知识网络/可视化错题详情/manifest.json"
    if visual_manifest.is_file():
        visual = json.loads(visual_manifest.read_text())
        for record in visual.get("records", []):
            identity = record.get("wrongnet_id")
            if identity not in media:
                continue
            for field, role in (("question_assets", "question"), ("solution_assets", "solution")):
                for reference in record.get(field, []):
                    if isinstance(reference, str) and reference in sources:
                        media[identity].add(role)
                        row = sources[reference]
                        row["formal_ids"] = sorted(set(row.get("formal_ids", []) + [identity]))
                        row.setdefault("role", role + "_image")
    for published, row in sources.items():
        name = Path(published).name.lower()
        role = row.get("role", "")
        if role in {"question", "question_image"} or name.startswith("question_"):
            normalized = "question"
        elif role in {"solution", "solution_image", "explanation_image"} or name.startswith(("solution_", "explanation_")):
            normalized = "solution"
        else:
            continue
        for identity in row.get("formal_ids", []):
            if identity in media:
                media[identity].add(normalized)
    missing_question_images = sorted(identity for identity, roles in media.items() if "question" not in roles)
    if missing_question_images:
        gaps.append({"kind": "question_image_declaration_missing", "formal_ids": missing_question_images,
                     "meaning": "No saved image declaration was resolved; existing text/source files remain published. Do not invent an image or infer that no text question exists."})
    identity = study_personalization_math.current_identity(root)
    if identity["status"] != "ready":
        raise DescriptorError("math_personalization_" + identity["status"])
    import math_formal_quality
    binding = math_formal_quality.publication_binding(root, event_id)
    export_generation = identity["version"] + ("-" + binding["generation_sha256"] if binding else "")
    export_root = root / study_personalization_math.EXPORT_ROOT / export_generation
    personalization = study_personalization_math.export_snapshot(
        root, export_root, formal_quality=binding)
    for row in personalization["files"]:
        add(Path(row["source_path"]), row["publish_path"], row["kind"],
            original=row.get("original_reference"), expected_hash=row.get("expected_sha256"))

    # C executes the installed selector only against these exact published
    # inputs. Bind the complete index source table, hot stores and implementation;
    # source refs in the selected subset alone cannot prove catalog completeness.
    native = study_personalization_math.native
    with sqlite3.connect((root / native.INDEX).as_uri() + "?mode=ro", uri=True) as conn:
        input_hashes = dict(conn.execute("SELECT path,sha256 FROM sources ORDER BY path"))
    # Bind the installed database without exporting a live SQLite binary.
    # The published personalization JSON above comes from one read transaction.
    index_path = safe_under(root / native.INDEX, root)
    index_binding = {"path": str(native.INDEX), "sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
                     "published": False}
    stamps[str(index_path)] = file_stamp(index_path)
    for relative in [*(str(p) for p in native.STORES),
                     "数学一回滚复习系统/学习进度.json", "数学一回滚复习系统/学习前5题记录.jsonl"]:
        path = root / relative
        if path.is_file():
            input_hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    import math_morning_ten
    for relative in math_morning_ten.extra_input_paths(root):
        path = safe_under(root / relative, root)
        input_hashes[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    exam_index_binding = None
    if math_morning_ten.config(root).get("enabled") is True:
        exam_index_path = safe_under(root / math_morning_ten.EXAM_DB, root)
        exam_index_binding = {"path": str(math_morning_ten.EXAM_DB),
                              "sha256": hashlib.sha256(exam_index_path.read_bytes()).hexdigest(),
                              "published": False}
        stamps[str(exam_index_path)] = file_stamp(exam_index_path)
    for relative, expected in input_hashes.items():
        path = safe_under(root / safe_relative(relative), root)
        add(path, relative, "native_math_workflow_input", expected_hash=expected)
    components = []
    component_directories = ["数学一回滚复习系统/scripts", "错题知识网络/scripts"]
    for directory in component_directories:
        for path in sorted((root / directory).glob("*.py")):
            relative = path.relative_to(root).as_posix()
            expected = hashlib.sha256(safe_under(path, root).read_bytes()).hexdigest()
            add(path, relative, "native_math_workflow_component", expected_hash=expected)
            components.append({"path": relative, "sha256": expected})
    workflow = {"schema": "native-math-workflow-bindings-v1",
                "installed_index": index_binding,
                "personalization": {key: identity[key] for key in ("version", "formal_version")},
                "inputs": [{"path": p, "sha256": sha} for p, sha in sorted(input_hashes.items())],
                "components": components, "component_directories": component_directories}
    if exam_index_binding is not None:
        workflow["installed_exam_index"] = exam_index_binding
        workflow["morning_formula_inputs"] = [str(p) for p in math_morning_ten.extra_input_paths(root)]
    workflow["version"] = hashlib.sha256(canonical(workflow)).hexdigest()
    workflow_path = export_root / "workflow-bindings.json"
    study_personalization_math._write(workflow_path, canonical(workflow))
    workflow_published = "support/cmath/manifest.json"
    workflow_hash = hashlib.sha256(canonical(workflow)).hexdigest()
    add(workflow_path, workflow_published, "native_math_workflow_manifest", expected_hash=workflow_hash)
    workflow_entry = {"schema": workflow["schema"], "version": workflow["version"],
                      "path": workflow_published, "sha256": workflow_hash}
    event_roles = {
        "capture_history": "数学一回滚复习系统/快速入库事件.jsonl",
        "review_events": "数学一回滚复习系统/复习记录.jsonl",
        "delivery_events": "数学一回滚复习系统/学习前5题记录.jsonl",
    }
    event_coverage = {}
    for role, relative in event_roles.items():
        path = root / relative
        summary = ledger_context(safe_under(path, root) if path.is_file() else path,
                                 capture=role == "capture_history")
        event_coverage[role] = {"path": relative, **summary}
        if summary.get("sha256"):
            add(path, relative, role, expected_hash=summary["sha256"])
    role_files: dict[str, dict[str, int]] = {}
    for row in sources.values():
        grouped = role_files.setdefault(row["kind"], {"files": 0, "bytes": 0})
        grouped["files"] += 1
        grouped["bytes"] += row["bytes"]
    context = {
        "schema": "native-math-study-context-v1", "subject": "math",
        "scope": "declared_saved_math_sources_not_whole_machine",
        "source_versions": {**workflow["personalization"], "native_workflow": workflow["version"]},
        "formal_card_count": {"count": len(formal_ids), "basis": "unique_formal_filenames"},
        "question_asset_coverage": {"formal_cards_with_declaration": len(formal_ids) - len(missing_question_images),
                                    "formal_cards_without_declaration": len(missing_question_images)},
        "archive_receipt_count": len(receipts),
        "events": event_coverage, "descriptor_file_roles": role_files,
        "synthetic_scene_paths": scene_paths,
        "synthetic_scene_manifest": scene_manifest_path if scene_paths else None,
        "coverage_gaps_by_kind": dict(Counter(row["kind"] for row in gaps)),
        "count_semantics": "files_are_source_files; events_are_valid_rows_at_eof; captures_use_native_replay",
        "display_assets_do_not_record_independent_mastery": True,
        "maintenance_summary": maintenance_summary(root, event_id, identity["version"], scene_paths),
    }
    content = canonical(context)
    context_hash = hashlib.sha256(content).hexdigest()
    context_path = export_root / "learning-context" / (context_hash + ".json")
    study_personalization_math._write(context_path, content)
    add(context_path, STUDY_CONTEXT, "math_study_context_manifest", expected_hash=context_hash,
        role="source_structure_metadata")
    if study_personalization_math.current_identity(root) != identity:
        raise DescriptorError("math_personalization_changed_during_workflow_binding")
    if maintenance_summary(root, event_id, identity["version"], scene_paths) != context["maintenance_summary"]:
        raise DescriptorError("math_maintenance_summary_changed_during_description")

    for key, previous in stamps.items():
        if file_stamp(Path(key)) != previous:
            raise DescriptorError("source_changed_during_description:" + key)
    if batch_link_stamp is not None:
        if (not batch_alias.is_symlink()
                or symlink_stamp(batch_alias) != batch_link_stamp
                or batch_alias.resolve(strict=True) != batch_directory):
            raise DescriptorError("A_batch_compat_link_changed_during_description")
    # Detect additions/removals at formal and event boundaries without relying
    # on tracked Git files as the library denominator.
    if [p.stem.split("_", 1)[0] for p in sorted(card_root.glob("*.md")) if FORMAL_RE.fullmatch(p.stem.split("_", 1)[0])] != formal_ids:
        raise DescriptorError("formal_card_set_changed_during_description")
    ordered = [sources[key] for key in sorted(sources)]
    version = hashlib.sha256(canonical([{**row, "source_stamp": stamps[row["source_path"]]} for row in ordered])).hexdigest()
    return {
        "subject": "math", "event_id": event_id, "local_version": version, "sources": ordered,
        "entrypoints": {"formal_cards": "错题知识网络/错题卡/", "history_index": "错题知识网络/生成/wrong_questions.json",
                        "review_events": "数学一回滚复习系统/复习记录.jsonl", "capture_events": "数学一回滚复习系统/快速入库事件.jsonl",
                        "personal_state": "错题知识网络/教学投影/",
                        "personalization": personalization["entrypoint"],
                        "study_context": STUDY_CONTEXT},
        "personalization": {k: personalization[k] for k in ("version", "formal_version", "entrypoint")},
        "native_math_workflow": workflow_entry,
        "history_index": "错题知识网络/生成/wrong_questions.json",
        "counts": {"formal_cards": len(formal_ids), "source_files": len(ordered), "archive_receipts": len(receipts), "question_image_declaration_missing": len(missing_question_images)},
        "formal_ids": formal_ids, "gaps": gaps, "original_mappings": original_mappings,
        "source_stability": {"method": "read_before_after_metadata_plus_publisher_content_hash", "consistent": True,
                             "publication_lock_owned_by_shared_publisher": True,
                             "subject_writer_locks": ["数学一回滚复习系统/.正式层写入.lock", "数学一回滚复习系统/.延迟复习评分.lock"]},
        "excluded": ["credentials", "machine configuration", "global instructions", "Computer History", "real backups",
                     "locks", "temporary prompts", "postcommit runtime receipts", "unrelated files outside explicit references"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("describe",))
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--event-id", required=True)
    args = parser.parse_args()
    try:
        result = describe(args.repo, args.event_id)
    except DescriptorError as exc:
        print(json.dumps({"subject": "math", "status": "invalid", "reason": str(exc)}, ensure_ascii=False))
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"subject": "math", "status": "unavailable", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
