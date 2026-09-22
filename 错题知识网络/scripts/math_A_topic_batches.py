#!/usr/bin/env python3
"""Inspect pending math packages and export immutable Project-A topic shards."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import zipfile
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
SYSTEM_SCRIPTS = ROOT / "数学一回滚复习系统/scripts"
BRIDGE_ROOT = Path("/Users/your-user/Documents/Study-Pro-Bridge")
PLAN_SCHEMA = "math-A-topic-plan-v1"
INVENTORY_SCHEMA = "math-A-topic-inventory-v1"
BATCH_PLAN_SCHEMA = "math-A-topic-batch-plan-v1"
EXPORT_SCHEMA = "math-A-topic-export-v1"
EXPORT_REVISION = "all-pending-with-current-contracts-v2"
CONTAINER_KIND = "math_topic_batch"
HASH = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
DEFAULT_MAX_QUESTIONS = 6
DEFAULT_MAX_DIALOGUE_CHARS = 35_000
DEFAULT_MAX_UNPACKED_BYTES = 80 * 1024 * 1024
OVERHEAD_RESERVE = 256 * 1024


class TopicBatchError(ValueError):
    pass


def fail(code: str, detail: Any = None) -> None:
    raise TopicBatchError(code if detail is None else f"{code}: {detail}")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_json(path: Path) -> Any:
    if not path.is_file() or path.is_symlink():
        fail("missing_or_unsafe_json", str(path))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TopicBatchError(f"invalid_json: {path}") from exc


def write_immutable(path: Path, raw: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        fail("unsafe_output_path", str(path))
    if path.exists():
        if not path.is_file() or path.read_bytes() != raw:
            fail("immutable_output_conflict", str(path))
        return False
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    return True


def module_at(name: str, path: Path):
    spec = importlib.util.spec_from_file_location("_math_A_topic_" + name, path)
    if spec is None or spec.loader is None:
        fail("module_unavailable", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    previous = list(sys.path)
    try:
        sys.path.insert(0, str(path.parent))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous
    return module


def quick_module():
    return module_at("quick_intake", SYSTEM_SCRIPTS / "quick_intake.py")


def pending_snapshot(qi, start: str | None, through: str | None) -> tuple[dict, str, str]:
    last = qi.validate_date(through) if through else (
        qi.validate_date(start) if start else datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    with qi.exclusive_lock(qi.LOCK_PATH):
        events = qi.load_jsonl(qi.EVENTS_PATH)
        ledger_hash = qi.ledger_hash()
    status = qi.status_document(events, None, snapshot_hash=ledger_hash)
    dates = [row.get("study_date", "") for row in status["pending"]
             if row.get("study_date") and row["study_date"] <= last]
    first = qi.validate_date(start) if start else min(dates, default=last)
    if last < first:
        fail("through_date_before_date")
    status["pending"] = [row for row in status["pending"] if first <= row.get("study_date", "") <= last]
    status["closed"] = [row for row in status["closed"]
                        if row.get("event_id") in {event["event_id"] for event in events
                                                  if first <= event.get("study_date", "") <= last}]
    selected_ids = {row["event_id"] for row in status["pending"]}
    status["active_freezes"] = [row for row in status["active_freezes"]
                                if selected_ids & set(row.get("capture_event_ids", []))]
    return status, first, last


def preview(text: str, limit: int) -> str:
    return text.replace("\x00", "")[:limit]


def package_details(qi, row: dict) -> tuple[dict | None, dict | None]:
    package = row.get("conversation_package") or row.get("source_bundle")
    if not isinstance(package, dict) or not package.get("manifest_path"):
        return None, {"kind": "legacy_or_missing_complete_package", "capture_id": row.get("event_id"),
                      "reason": "conversation_package_manifest_missing"}
    relative = Path(package["manifest_path"])
    if relative.is_absolute() or ".." in relative.parts:
        return None, {"kind": "invalid_package_manifest_path", "capture_id": row.get("event_id")}
    path = (ROOT / relative).resolve()
    try:
        manifest = load_json(path)
        qi.validate_conversation_package_manifest(manifest, path, "topic_batch.inspect",
                                                  expected_hash=package.get("manifest_hash"))
        conversation_path = ROOT / manifest["files"]["conversation"]["path"]
        conversation = load_json(conversation_path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, {"kind": "package_validation_failed", "capture_id": row.get("event_id"),
                      "package_id": package.get("package_id"), "reason": str(exc)}
    turns = conversation.get("turns")
    if not isinstance(turns, list) or not all(isinstance(turn, dict) for turn in turns):
        return None, {"kind": "package_conversation_invalid", "capture_id": row.get("event_id"),
                      "package_id": manifest.get("package_id")}
    texts = [turn.get("text", "") for turn in turns]
    if any(not isinstance(text, str) for text in texts):
        return None, {"kind": "package_conversation_text_invalid", "capture_id": row.get("event_id"),
                      "package_id": manifest.get("package_id")}
    first_user = next((turn["text"] for turn in turns if turn.get("role") == "user" and turn.get("text")), "")
    long_assistant = next((turn["text"] for turn in turns
                           if turn.get("role") == "assistant" and len(turn.get("text", "")) >= 200), "")
    artifact_bytes = sum(item.get("size", 0) for item in manifest.get("artifacts", []))
    declared_bytes = sum(item.get("size", 0) for item in manifest["files"].values()) + artifact_bytes
    receipt = path.parent / "receipt.json"
    package_bytes = declared_bytes + path.stat().st_size + (receipt.stat().st_size if receipt.is_file() else 0)
    identity = manifest.get("source_identity", {})
    return {
        "package_id": manifest["package_id"], "capture_ids": [row["event_id"]],
        "attempt_ids": [row.get("attempt_id")], "study_date": row["study_date"],
        "question_id": identity.get("question_id"), "formal_id": row.get("formal_id") or identity.get("formal_id"),
        "source_locator": identity.get("source_locator") or manifest.get("source_locator") or row.get("source_locator"),
        "supplements_capture_id": row.get("supplements_capture_id"),
        "manifest_path": relative.as_posix(), "manifest_hash": file_hash(path),
        "package_sha256": manifest["canonical_sha256"],
        "conversation_chars": sum(len(text) for text in texts),
        "conversation_turns": len(turns), "artifact_bytes": artifact_bytes,
        "package_unpacked_bytes": package_bytes,
        "first_user_preview": preview(first_user.split("## My request:")[-1].strip(), 400),
        "first_long_assistant_preview": preview(long_assistant, 320),
    }, None


def basic_unit(row: dict, detail: dict | None) -> str:
    formal = (detail or {}).get("formal_id") or row.get("formal_id")
    if formal:
        return "formal:" + str(formal)
    question = (detail or {}).get("question_id")
    if question:
        return "question:" + str(question)
    source = (detail or {}).get("source_locator") or row.get("source_locator")
    if source:
        return "source:" + str(source)
    return "attempt:" + str(row.get("attempt_id") or row.get("event_id"))


def inspect_inventory(start: str | None = None, through: str | None = None) -> dict:
    qi = quick_module()
    status, first, last = pending_snapshot(qi, start, through)
    by_capture = {row["event_id"]: row for row in status["pending"]}
    details: list[tuple[dict, dict | None, dict | None]] = []
    for row in status["pending"]:
        detail, issue = package_details(qi, row)
        details.append((row, detail, issue))
    preliminary = {row["event_id"]: basic_unit(row, detail) for row, detail, _ in details}

    def root_unit(row: dict) -> str:
        parent = row.get("supplements_capture_id")
        seen = set()
        while parent in by_capture and parent not in seen:
            seen.add(parent)
            row = by_capture[parent]
            parent = row.get("supplements_capture_id")
        return preliminary.get(row["event_id"], basic_unit(row, None))

    items_by_package: dict[str, dict] = {}
    issues = []
    bad_units = set()
    staged = []
    for row, detail, issue in details:
        unit = root_unit(row)
        if row.get("active_freeze_ids"):
            issue = {"kind": "active_freeze", "capture_id": row["event_id"],
                     "freeze_ids": row["active_freeze_ids"]}
        if issue:
            issue.update(study_date=row.get("study_date"), unit_key=unit)
            issues.append(issue)
            bad_units.add(unit)
            continue
        detail["unit_key"] = unit
        staged.append(detail)
    for detail in staged:
        if detail["unit_key"] in bad_units:
            issues.append({"kind": "unit_has_ineligible_capture", "package_id": detail["package_id"],
                           "unit_key": detail["unit_key"], "study_date": detail["study_date"]})
            continue
        existing = items_by_package.get(detail["package_id"])
        if existing is None:
            items_by_package[detail["package_id"]] = detail
        else:
            stable = {key for key in detail if key not in {"capture_ids", "attempt_ids"}}
            if any(existing.get(key) != detail.get(key) for key in stable):
                issues.append({"kind": "duplicate_package_binding_conflict", "package_id": detail["package_id"],
                               "unit_key": detail["unit_key"]})
                items_by_package.pop(detail["package_id"], None)
                bad_units.add(detail["unit_key"])
            else:
                existing["capture_ids"] = sorted(set(existing["capture_ids"] + detail["capture_ids"]))
                existing["attempt_ids"] = sorted(set(existing["attempt_ids"] + detail["attempt_ids"]))
    if bad_units:
        for package_id, detail in list(items_by_package.items()):
            if detail["unit_key"] in bad_units:
                issues.append({"kind": "unit_has_ineligible_capture", "package_id": package_id,
                               "unit_key": detail["unit_key"], "study_date": detail["study_date"]})
                del items_by_package[package_id]
    items = sorted(items_by_package.values(), key=lambda row: (row["study_date"], row["package_id"]))
    units = defaultdict(list)
    for item in items:
        units[item["unit_key"]].append(item["package_id"])
    for item in items:
        item["unit_capture_ids"] = sorted({capture for package in units[item["unit_key"]]
                                           for capture in items_by_package[package]["capture_ids"]})
        item["unit_package_ids"] = sorted(units[item["unit_key"]])
    core = {"schema": INVENTORY_SCHEMA, "date": first, "through_date": last,
            "scope": "date_range" if start else "all_pending",
            "ledger_hash": status["ledger_hash"], "eligible": items,
            "issues": sorted(issues, key=lambda row: (row.get("study_date", ""), row.get("capture_id", ""), row.get("package_id", "")))}
    return {**core, "inventory_sha256": digest(core), "eligible_count": len(items),
            "eligible_capture_count": sum(len(item["capture_ids"]) for item in items),
            "pending_capture_count": len(status["pending"]),
            "issue_count": len(issues), "plan_schema": PLAN_SCHEMA}


def exact_concepts() -> tuple[set[str], set[str]]:
    path = ROOT / "错题知识网络/个人知识点索引/index.sqlite3"
    if not path.is_file():
        fail("concept_index_missing")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT key,label FROM concepts").fetchall()
    return {row[0] for row in rows}, {row[1] for row in rows}


def validate_plan(value: Any, inventory: dict) -> list[dict]:
    required = {"assignments"}
    allowed = required | {"schema", "scope", "date", "cutoff_date", "through_date", "inventory_sha256", "classification_basis",
                          "max_questions", "max_dialogue_chars", "max_unpacked_bytes"}
    if (not isinstance(value, dict) or not required <= set(value) or set(value) - allowed
            or value.get("schema", PLAN_SCHEMA) != PLAN_SCHEMA):
        fail("invalid_topic_plan_fields")
    scope = value.get("scope", "all_pending")
    if scope not in {"all_pending", "date_range"} or scope != inventory["scope"]:
        fail("invalid_topic_plan_scope")
    if scope == "date_range" and (value.get("date"), value.get("through_date", value.get("date"))) != (
            inventory["date"], inventory["through_date"]):
        fail("topic_plan_date_range_changed")
    if value.get("inventory_sha256", inventory["inventory_sha256"]) != inventory["inventory_sha256"]:
        fail("topic_plan_inventory_binding_changed")
    assignments = value["assignments"]
    if not isinstance(assignments, list) or not all(isinstance(row, dict) for row in assignments):
        fail("topic_assignments_required")
    keys, labels = exact_concepts()
    seen = set()
    for row in assignments:
        if set(row) != {"package_id", "topic", "concepts", "rationale"}:
            fail("invalid_topic_assignment_fields")
        package_id = row["package_id"]
        if not isinstance(package_id, str) or package_id in seen:
            fail("duplicate_or_invalid_topic_package", package_id)
        seen.add(package_id)
        if not isinstance(row["topic"], str) or not row["topic"].strip():
            fail("topic_required", package_id)
        if not isinstance(row["rationale"], str) or not row["rationale"].strip():
            fail("topic_rationale_required", package_id)
        concepts = row["concepts"]
        if (not isinstance(concepts, list) or not concepts or len(concepts) != len(set(concepts))
                or any(not isinstance(item, str) or item not in keys | labels for item in concepts)):
            fail("unknown_or_invalid_exact_concept", package_id)
    eligible = {row["package_id"] for row in inventory["eligible"]}
    if seen != eligible:
        fail("topic_plan_package_coverage_mismatch", {"missing": sorted(eligible - seen),
                                                      "extra": sorted(seen - eligible)})
    unit_by_package = {row["package_id"]: row["unit_key"] for row in inventory["eligible"]}
    topics = defaultdict(set)
    for row in assignments:
        topics[unit_by_package[row["package_id"]]].add(row["topic"])
    conflicts = {unit: sorted(values) for unit, values in topics.items() if len(values) != 1}
    if conflicts:
        fail("same_unit_must_share_topic", conflicts)
    return assignments


def bridge_modules(bridge_root: Path):
    if not bridge_root.is_dir():
        fail("bridge_root_missing", str(bridge_root))
    # Bridge operations import their sibling modules lazily as well as at load.
    if str(bridge_root) not in sys.path:
        sys.path.insert(0, str(bridge_root))
    bridge = module_at("study_bridge", bridge_root / "study_bridge.py")
    archives = sys.modules.get("bridge_archives") or module_at("bridge_archives", bridge_root / "bridge_archives.py")
    publication = sys.modules.get("study_publication") or module_at("study_publication", bridge_root / "study_publication.py")
    return bridge, archives, publication


def freeze_snapshot(bridge_root: Path, bridge, publication) -> dict:
    reader = bridge.Published(bridge_root / "publication")
    latest = reader.latest("math")
    commit = latest.get("source_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        fail("math_publication_source_commit_missing")
    receipt, library = reader.inspect_version("math", commit, resolve_inventory=False)
    current = publication.verify_current("math")
    freshness = "current" if current.get("status") == "PUBLISHED_CURRENT" and current.get("source_commit") == commit else "missing"
    if freshness != "current":
        fail("math_publication_not_current", {"latest": commit, "verification": current})
    return {"freshness": freshness, "source_commit": commit,
            "snapshot_id": receipt.get("snapshot_id", commit),
            "publication_target": receipt.get("publication_target"),
            "manifest_sha256": receipt.get("manifest_sha256"),
            "local_version": library.get("local_version"),
            "publication_event_id": current.get("publication_event_id")}


def slug(text: str) -> str:
    value = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", text).strip("-").lower()
    return value[:36] or "topic-" + hashlib.sha256(text.encode()).hexdigest()[:12]


def pack_inner_packages(inventory: dict, bridge, bridge_root: Path) -> dict[str, dict]:
    result = {}
    for item in inventory["eligible"]:
        package_dir = (ROOT / item["manifest_path"]).parent
        question_id = item.get("question_id") or item.get("formal_id") or item["package_id"]
        # Native source IDs (for example ID:59092) can contain punctuation that
        # the transport contract forbids. Keep them intact in the native pack
        # and use the existing package-locator identity for transport instead.
        if not SAFE_ID.fullmatch(question_id):
            question_id = item["package_id"]
        packed = bridge.pack("math", package_dir, ROOT, base=bridge_root,
                             question_id=question_id)
        path = Path(packed["path"]).resolve()
        if file_hash(path) != packed["zip_sha256"]:
            fail("inner_quick_pack_readback_failed", item["package_id"])
        with zipfile.ZipFile(path) as archive:
            unpacked_bytes = sum(entry.file_size for entry in archive.infolist() if not entry.is_dir())
        result[item["package_id"]] = {"path": path, "package_id": item["package_id"],
                                      "version": packed["version"], "zip_sha256": packed["zip_sha256"],
                                      "zip_bytes": path.stat().st_size, "unpacked_bytes": unpacked_bytes}
    return result


def make_groups(assignments: list[dict], inventory: dict, packed: dict[str, dict], limits: dict) -> list[dict]:
    details = {row["package_id"]: row for row in inventory["eligible"]}
    assignment = {row["package_id"]: row for row in assignments}
    topic_units: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    order = []
    for row in assignments:
        if row["topic"] not in order:
            order.append(row["topic"])
        unit = details[row["package_id"]]["unit_key"]
        topic_units[row["topic"]][unit].append(row["package_id"])
    groups = []
    for topic in order:
        current: list[str] = []
        current_chars = current_bytes = 0
        for unit, package_ids in topic_units[topic].items():
            package_ids = sorted(package_ids)
            unit_chars = sum(details[package]["conversation_chars"] for package in package_ids)
            unit_bytes = sum(packed[package]["zip_bytes"] + packed[package]["unpacked_bytes"] for package in package_ids)
            unit_oversized = unit_chars > limits["max_dialogue_chars"] or unit_bytes + OVERHEAD_RESERVE > limits["max_unpacked_bytes"]
            would_exceed = current and (
                len({details[package]["unit_key"] for package in current}) + 1 > limits["max_questions"]
                or current_chars + unit_chars > limits["max_dialogue_chars"]
                or current_bytes + unit_bytes + OVERHEAD_RESERVE > limits["max_unpacked_bytes"]
            )
            if would_exceed:
                groups.append({"topic": topic, "package_ids": current, "dialogue_chars": current_chars,
                               "archive_budget_bytes": current_bytes, "oversized": False})
                current, current_chars, current_bytes = [], 0, 0
            if unit_oversized:
                groups.append({"topic": topic, "package_ids": package_ids, "dialogue_chars": unit_chars,
                               "archive_budget_bytes": unit_bytes, "oversized": True})
            else:
                current.extend(package_ids)
                current_chars += unit_chars
                current_bytes += unit_bytes
        if current:
            groups.append({"topic": topic, "package_ids": current, "dialogue_chars": current_chars,
                           "archive_budget_bytes": current_bytes, "oversized": False})
    for group in groups:
        group["inner_zip_bytes"] = sum(packed[package]["zip_bytes"] for package in group["package_ids"])
        group["question_count"] = len({details[package]["unit_key"] for package in group["package_ids"]})
        group["assignments"] = [assignment[package] for package in group["package_ids"]]
    return groups


def web_prompt(group: dict, batch_id: str, plan_sha: str, snapshot: dict, inventory: dict) -> str:
    details = {row["package_id"]: row for row in inventory["eligible"]}
    binding = {"batch_id": batch_id, "shard_id": group["shard_id"], "plan_sha256": plan_sha}
    rows = [f"- 来源题号 {details[p].get('question_id') or details[p].get('formal_id') or '见原包'}；"
            f"原学习日期 {details[p]['study_date']}；package_id={p}" for p in group["package_ids"]]
    return ("请按数学项目 A 的现行指令处理我上传的这一个分包，完成正式增强成稿。\n\n"
            f"本包主题：{group['topic']}\n分包：{group['shard_id']}\n"
            f"批次：{batch_id}\nrun_id：{group['run_id']}\n\n"
            "本批来自本地全部尚未正式入库的快速包，可能跨多个学习日期。"
            "“今天打包”指本次导出，不把旧日期材料排除，也不把原学习日期改成今天。"
            "本对话仅负责以下清单，其他分包由独立对话处理：\n" + "\n".join(rows) + "\n\n"
            "先读随包 PROJECT_INSTRUCTIONS.txt、FORMAL_RENDERING_SCHEMA.md、manifest.json、batch_plan.json 和各内层 quick-pack 清单；"
            "使用随包现行交付合同，不从固定历史快照重新寻找旧合同。根目录必须交付advice.json和profile_updates.json；"
            "recommendation固定使用formal_card、exam_writeup字符串与observations，不用其他别名替代。完整读取本包原始会话、题干、解析和附件，"
            "核对数学与原助手讲解，区分本人首答、提示后修复、独立正确和助手错误。"
            "按现行合同交付逐题最终题卡、卷面写法、逐点观察及知识点概况贡献，不留待本地补写的语义。\n\n"
            f"MCP 历史固定 source_commit={snapshot['source_commit']}，snapshot_id={snapshot['snapshot_id']}。"
            "调用 library 核对版本；仅查询本包相关历史。若该固定版本已成历史，显式使用 allow_historical=true 并保留版本来源，"
            "不切到另一基线，不把旧版本称为最新。若无法读到固定版本，保留已完成工作并报告阻碍。\n\n"
            f"返回 advice_{group['shard_id']}.zip，manifest.run_id 使用上述值，input_packages 原样保留本包清单，"
            "batch_binding=" + json.dumps(binding, ensure_ascii=False, separators=(",", ":")) + "。\n"
            'profile_merge_policy="deferred_batch_merge"：概况仅表示共同基线加本包证据的贡献；'
            "不声称已合入其他分包，本地会汇合所有相关贡献后统一接受。\n\n"
            "无论是否全部成功，都交付执行报告，列明已完成、未完成及失败原因；每完成一个单元就保存成果。"
            "MCP/代码出错时保留检查点、成稿和原始错误，能继续的独立部分继续完成。"
            "ZIP不可用则交付独立文件或聊天中的可保存内容，不能空手结束。\n")


def build_batches(args: argparse.Namespace) -> dict:
    plan = load_json(args.plan.expanduser().resolve(strict=True))
    inventory = inspect_inventory(plan.get("date") if plan.get("scope") == "date_range" else None,
                                  plan.get("cutoff_date") or plan.get("through_date"))
    assignments = validate_plan(plan, inventory)
    bridge_root = args.bridge_root.expanduser().resolve(strict=True)
    contract_files = {name: bridge_root / "web-projects/A" / name
                      for name in ("PROJECT_INSTRUCTIONS.txt", "FORMAL_RENDERING_SCHEMA.md")}
    for path in contract_files.values():
        if not path.is_file() or path.is_symlink():
            fail("current_A_contract_missing", str(path))
    contract_hashes = {name: file_hash(path) for name, path in contract_files.items()}
    bridge, archives, publication = bridge_modules(bridge_root)
    snapshot = freeze_snapshot(bridge_root, bridge, publication)
    limits = {"max_questions": args.max_questions, "max_dialogue_chars": args.max_dialogue_chars,
              "max_unpacked_bytes": args.max_unpacked_bytes}
    if any(type(value) is not int or value <= 0 for value in limits.values()):
        fail("invalid_positive_batch_limit")
    for key, value in limits.items():
        if key in plan and plan[key] != value:
            fail("plan_and_cli_limit_mismatch", key)
    packed = pack_inner_packages(inventory, bridge, bridge_root)
    seed = {"plan": plan, "snapshot": snapshot, "limits": limits,
            "export_revision": EXPORT_REVISION, "web_contracts": contract_hashes,
            "inventory_sha256": inventory["inventory_sha256"],
            "inner_packages": {key: {field: value[field] for field in ("version", "zip_sha256")}
                               for key, value in sorted(packed.items())}}
    batch_id = f"A-BATCH-{inventory['through_date']}-{digest(seed)[:16]}"
    groups = make_groups(assignments, inventory, packed, limits)
    if not groups:
        fail("no_eligible_topic_groups")
    group_rows = []
    for number, group in enumerate(groups, 1):
        shard_id = f"S{number:02d}"
        group_id = "TOPIC-" + hashlib.sha256(group["topic"].encode()).hexdigest()[:12]
        package_ids = sorted(group["package_ids"])
        group_rows.append({"group_id": group_id, "shard_id": shard_id,
                           "run_id": f"{batch_id}-{shard_id}", "topic": group["topic"],
                           "package_ids": package_ids,
                           "input_packages": [{key: packed[package][key] for key in ("package_id", "version", "zip_sha256")}
                                              for package in package_ids],
                           "question_count": group["question_count"],
                           "dialogue_chars": group["dialogue_chars"],
                           "inner_zip_bytes": group["inner_zip_bytes"],
                           "archive_budget_bytes": group["archive_budget_bytes"],
                           "oversized": group["oversized"], "assignments": group["assignments"],
                           "profile_merge_policy": "deferred_batch_merge"})
    batch_plan = {"schema": BATCH_PLAN_SCHEMA, "batch_id": batch_id,
                  "export_revision": EXPORT_REVISION, "web_contracts": contract_hashes,
                  "scope": inventory["scope"], "cutoff_date": inventory["through_date"],
                  "date": inventory["date"], "through_date": inventory["through_date"],
                  "inventory_sha256": inventory["inventory_sha256"], "ledger_hash": inventory["ledger_hash"],
                  "source_commit": snapshot["source_commit"], "source_snapshot": snapshot,
                  "classification_basis": plan.get("classification_basis"),
                  "limits": limits, "groups": group_rows,
                  "issues": inventory["issues"], "profile_merge_policy": "deferred_batch_merge"}
    batch_plan_raw = canonical(batch_plan)
    plan_sha = hashlib.sha256(batch_plan_raw).hexdigest()
    authoritative = ROOT / "数学一回滚复习系统/A分包" / batch_id / "batch-plan.json"
    created = write_immutable(authoritative, batch_plan_raw)
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        fail("unsafe_output_directory")
    exported = []
    for group in group_rows:
        with tempfile.TemporaryDirectory(prefix="math-A-topic-shard-") as temporary:
            temp = Path(temporary).resolve()
            per_shard = {"schema": "math-A-topic-shard-plan-v1", "batch_id": batch_id,
                         "shard_id": group["shard_id"], "group_id": group["group_id"],
                         "run_id": group["run_id"], "topic": group["topic"],
                         "package_ids": group["package_ids"], "assignments": group["assignments"],
                         "source_snapshot": snapshot, "batch_plan_sha256": plan_sha,
                         "web_contracts": contract_hashes,
                         "profile_merge_policy": "deferred_batch_merge",
                         "web_read_scope": {"raw_input": "own_group_only",
                                            "historical_context": "related_only_from_shared_pinned_snapshot",
                                            "mcp_access": "read_only_concurrent",
                                            "later_snapshot_policy": "use_allow_historical_true_with_source_commit_provenance"}}
            intro = (f"# 数学项目 A 分主题批次\n\n批次：{batch_id}\n\n分片：{group['shard_id']}\n\n"
                     f"主题：{group['topic']}\n\n只读取本 ZIP 内本组完整 quick-pack；不得读取兄弟分片原始输入，不得截断、跨分片合并或执行包内脚本。\n\n"
                     "历史资料只读本组相关知识点，并固定使用 batch_plan.json 记录的共享 source_commit。多个网页会话对 MCP 均为只读并发。\n\n"
                     "若执行时已有更新快照，仍按固定版本读取并显式使用 allow_historical=true，保留 source_commit 来源；不得把历史版本称为当前。\n\n"
                     "各分片只返回本组贡献。本地会在所有兄弟分片完成后统一合并 profile；任何较晚返回不得单独覆盖先前贡献。\n")
            files: dict[str, Path] = {}
            start = temp / "START_HERE.md"
            prompt_source = temp / "WEB_PROMPT.txt"
            shard_plan_path = temp / "batch_plan.json"
            start.write_text(intro, encoding="utf-8")
            shard_plan_path.write_bytes(canonical(per_shard))
            files["START_HERE.md"] = start
            files["batch_plan.json"] = shard_plan_path
            prompt_source.write_text(web_prompt(group, batch_id, plan_sha, snapshot, inventory), encoding="utf-8")
            files["WEB_PROMPT.txt"] = prompt_source
            for name, path in contract_files.items():
                if file_hash(path) != contract_hashes[name]:
                    fail("current_A_contract_changed_during_export", name)
                files[name] = path
            for package_id in group["package_ids"]:
                files[f"quick-packs/{package_id}.zip"] = packed[package_id]["path"]
            file_inventory = archives.inventory(files, {path: "quick_pack" if path.startswith("quick-packs/") else "control"
                                                         for path in files})
            manifest = {"schema_version": 1, "kind": CONTAINER_KIND, "project": "A", "subject": "math",
                        "group_id": group["group_id"], "shard_id": group["shard_id"],
                        "run_id": group["run_id"], "batch_id": batch_id,
                        "source_commit": snapshot["source_commit"], "snapshot_id": snapshot["snapshot_id"],
                        "publication_target": snapshot["publication_target"],
                        "input_packages": group["input_packages"],
                        "subpackages": [f"quick-packs/{package}.zip" for package in group["package_ids"]],
                        "batch_binding": {"batch_id": batch_id, "shard_id": group["shard_id"],
                                          "plan_sha256": plan_sha}, "oversized": group["oversized"],
                        "profile_merge_policy": "deferred_batch_merge",
                        "files": file_inventory}
            manifest_path = temp / "manifest.json"
            manifest_path.write_bytes(canonical(manifest))
            files["manifest.json"] = manifest_path
            name = f"{batch_id}-{group['shard_id']}-{slug(group['topic'])}.zip"
            target = output / name
            prompt_target = target.with_suffix(".提示词.txt")
            prompt_created = write_immutable(prompt_target, prompt_source.read_bytes())
            existed = target.exists()
            archives.write_zip(files, target)
            actual_unpacked = (sum(path.stat().st_size for path in files.values())
                               + sum(packed[package]["unpacked_bytes"] for package in group["package_ids"]))
            if actual_unpacked > args.max_unpacked_bytes and not group["oversized"]:
                fail("non_oversized_shard_exceeds_unpacked_limit", group["shard_id"])
            exported.append({"group_id": group["group_id"], "shard_id": group["shard_id"],
                             "run_id": group["run_id"], "topic": group["topic"],
                             "path": str(target), "sha256": file_hash(target), "size": target.stat().st_size,
                             "question_count": group["question_count"], "prompt_path": str(prompt_target),
                             "prompt_sha256": file_hash(prompt_target),
                             "unpacked_bytes": actual_unpacked, "oversized": group["oversized"],
                             "status": "available"})
            created = created or not existed or prompt_created
    receipt = {"schema": EXPORT_SCHEMA, "batch_id": batch_id, "batch_plan_path": str(authoritative),
               "batch_plan_sha256": plan_sha, "source_snapshot": snapshot, "outputs": exported,
               "combined_zip": None, "profile_merge_policy": "deferred_batch_merge"}
    receipt_path = ROOT / "数学一回滚复习系统/A分包" / batch_id / "export-receipt.json"
    created = write_immutable(receipt_path, canonical(receipt)) or created
    index_lines = ["# 数学 A 分主题批次", "", f"批次：{batch_id}", "", f"固定版本：{snapshot['source_commit']}", ""]
    for row in exported:
        marker = "（超限单题专包）" if row["oversized"] else ""
        index_lines.append(f"- {row['shard_id']}｜{row['topic']}{marker}｜{row['question_count']}题｜"
                           f"[压缩包]({Path(row['path']).name})｜[提示词]({Path(row['prompt_path']).name})")
    index_path = output / f"{batch_id}-目录.md"
    created = write_immutable(index_path, ("\n".join(index_lines) + "\n").encode()) or created
    return {"status": "recorded" if created else "noop", "batch_id": batch_id,
            "batch_plan_path": str(authoritative), "batch_plan_sha256": plan_sha,
            "export_receipt_path": str(receipt_path), "index_path": str(index_path),
            "source_snapshot": snapshot, "shards": exported, "combined_zip": None,
            "formal_write_count": 0, "web_task_count": 0}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Read pending complete packages without writing")
    inspect.add_argument("--date", help="Explicitly restrict to this date or the beginning of a requested range")
    inspect.add_argument("--through-date", help="Include all pending captures through this date; default is today in Shanghai")
    build = commands.add_parser("build", help="Build immutable flat topic shard ZIPs from an explicit plan")
    build.add_argument("--plan", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--bridge-root", type=Path, default=BRIDGE_ROOT)
    build.add_argument("--max-questions", type=int, default=DEFAULT_MAX_QUESTIONS)
    build.add_argument("--max-dialogue-chars", type=int, default=DEFAULT_MAX_DIALOGUE_CHARS)
    build.add_argument("--max-unpacked-bytes", type=int, default=DEFAULT_MAX_UNPACKED_BYTES)
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "inspect":
            result = inspect_inventory(args.date, args.through_date)
            raw = canonical(result)
            print(raw.decode(), end="")
        else:
            print(json.dumps(build_batches(args), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": str(exc), "error_type": type(exc).__name__,
                          "formal_write_count": 0, "web_task_count": 0}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
