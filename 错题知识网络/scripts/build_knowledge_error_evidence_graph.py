#!/usr/bin/env python3
"""Build an evidence-aware knowledge-to-error graph for the math wrong bank.

The formal cards stay authoritative.  This compiler reads every formal card,
the visual manifest, discoverable visual detail notes, and image assets.  It
then emits a derived graph and a per-card evidence index without modifying
formal ``related`` fields.

The important safety rule is that a knowledge/error co-occurrence is not, by
itself, proof of a learner-specific cause.  ``training_evidence`` is therefore
used to keep user-confirmed, historical, model-derived, and pending evidence in
separate lanes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_ROOT / "错题知识网络"
CARDS_DIR = BASE_DIR / "错题卡"
VISUAL_DIR = BASE_DIR / "可视化错题详情"
VISUAL_ASSETS_DIR = BASE_DIR / "assets" / "visual_wrong_questions"
MANIFEST_PATH = VISUAL_DIR / "manifest.json"
SYNTHESIS_DIR = BASE_DIR / "wiki" / "synthesis"
REVIEW_DIR = BASE_DIR / "wiki" / "review"
GRAPH_MD_PATH = SYNTHESIS_DIR / "MATHWIKI-SYNTHESIS-002_知识点错因证据图谱.md"
CARD_INDEX_MD_PATH = SYNTHESIS_DIR / "MATHWIKI-SYNTHESIS-003_逐题内容与视觉证据索引.md"
GRAPH_JSON_PATH = SYNTHESIS_DIR / "MATHWIKI-SYNTHESIS-002_知识点错因证据图谱.json"
REVIEW_RECEIPT_PATH = SYNTHESIS_DIR / "MATHWIKI-SYNTHESIS-002_语义复核边界回执.json"
SEMANTIC_REVIEW_BATCH_GLOB = "MATHWIKI-REVIEW-*_全库逐题语义复核第*批*题.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import training_evidence  # noqa: E402
import wrongnet  # noqa: E402


SCHEMA_VERSION = "1.0"
QUESTION_SECTION_MARKERS = ("题目", "题干", "问题", "原题")
ANALYSIS_SECTION_MARKERS = (
    "标准答案",
    "答案解析",
    "解析",
    "解法",
    "正确入口",
    "具体错点",
    "第一个断点",
    "方法断点",
    "必要提示",
    "复做提醒",
    "复述",
    "入库判断",
)
DETAIL_ANALYSIS_MARKERS = (
    "复述",
    "入库判断",
    "解析",
    "错点",
    "断点",
    "复做",
    "方法",
)
PLACEHOLDER_MARKERS = {
    "",
    "待补充",
    "待确认",
    "暂无",
    "无",
    "未记录",
    "题图待补充",
    "解析待补充",
}
VISUAL_WARNING_STATUSES = {
    "visual_gap_registered",
    "suspect_wrongnet_mismatch",
    "needs_card_decision",
    "needs_manual_relink",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tiff", ".tif"}
QUESTION_ASSET_MARKERS = ("question", "题目", "题干")
SOLUTION_ASSET_MARKERS = ("solution", "answer", "解析", "答案")
EVIDENCE_TIER_ORDER = {
    "confirmed_personal": 0,
    "legacy_unclassified": 1,
    "confirmed_origin_without_specific_failure": 2,
    "model_inferred_from_solution": 3,
    "pending_user_confirmation": 4,
    "missing": 5,
}
EVIDENCE_TIER_LABELS = {
    "confirmed_personal": "用户确认的个人错因",
    "legacy_unclassified": "历史结构化字段，来源未分类",
    "confirmed_origin_without_specific_failure": "声明为用户确认，但缺少可定位失败动作",
    "model_inferred_from_solution": "根据解析推导的复做入口",
    "pending_user_confirmation": "待用户确认",
    "missing": "具体错因证据缺失",
}
HISTORICAL_REVIEW_LABELS = {
    "exact_sha_carry_forward": "旧逐题复核与当前文件 SHA 完全一致",
    "field_level_semantic_carry_forward_candidate": "字段级语义未漂移，可暂时承接",
    "target_level_semantic_review_gap": "仍需逐题语义复核",
    "unclassified": "未纳入历史复核差异口径",
}
CURRENT_REVIEW_LABELS = {
    "batch_verified_current_assets": "本轮逐题题面与全部当前图片哈希已复核",
    "batch_review_stale": "本轮复核后来源已变化，需重核",
    "not_reviewed_in_current_campaign": "尚未进入本轮逐题复核",
}
FIRST_REVIEW_BATCH_GROUP_LABELS = {
    "historical_M192_next_batch": "历史 M192 下一批",
    "new_q_plus_s": "新增且题图解析图齐全",
    "stale_review_with_semantic_drift": "旧复核后语义字段漂移",
    "identity_adjudication_exception": "需先裁决题目身份",
}
RESOLVED_FINDING_STATUSES = {"resolved_formal_closeout"}
ALLOWED_AGGREGATE_EDGE_POLICIES = {"allow", "block_until_relinked"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def project_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def normalize_ref(value: Any) -> str:
    text = str(value or "").strip().strip('"').strip("'")
    return text.replace("\\", "/")


def resolve_project_ref(value: Any) -> Path | None:
    ref = normalize_ref(value)
    if not ref or ref in wrongnet.PLACEHOLDERS:
        return None
    path = Path(ref).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def unique_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def split_markdown_sections(body: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current_title = "正文"
    current_lines: list[str] = []
    for line in body.splitlines():
        match = re.match(r"^#{2,6}\s+(.+?)\s*$", line)
        if match:
            sections.append({"title": current_title, "text": "\n".join(current_lines).strip()})
            current_title = match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    sections.append({"title": current_title, "text": "\n".join(current_lines).strip()})
    return [section for section in sections if section["title"] or section["text"]]


def plain_markdown_excerpt(text: str, limit: int = 220) -> str:
    value = re.sub(r"!\[\[[^\]]+\]\]", " ", text)
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"^\s*>\s*\[![^\]]+\][+-]?[^\n]*", " ", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*>\s?", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*[-*+]\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def meaningful_text(text: str) -> bool:
    value = plain_markdown_excerpt(text, 10000).strip(" ：:。.;；-")
    if not value or value in PLACEHOLDER_MARKERS:
        return False
    if any(value == marker or value.startswith(f"{marker}，") for marker in PLACEHOLDER_MARKERS if marker):
        return False
    return len(value) >= 6


def selected_section_text(sections: list[dict[str, str]], markers: tuple[str, ...]) -> str:
    selected = [
        section["text"]
        for section in sections
        if any(marker in section["title"] for marker in markers) and meaningful_text(section["text"])
    ]
    return "\n\n".join(selected)


def evidence_tier(evidence: dict[str, Any]) -> str:
    if evidence.get("personal_confirmed") is True:
        return "confirmed_personal"
    origin = str(evidence.get("origin") or "missing")
    if origin == "user_confirmed":
        return "confirmed_origin_without_specific_failure"
    if origin in EVIDENCE_TIER_LABELS:
        return origin
    return "missing"


def asset_kind(path: Path) -> str:
    folded = path.name.casefold()
    if any(marker in folded for marker in QUESTION_ASSET_MARKERS):
        return "question"
    if any(marker in folded for marker in SOLUTION_ASSET_MARKERS):
        return "solution"
    return "reference"


def file_descriptor(path: Path) -> dict[str, Any]:
    descriptor: dict[str, Any] = {
        "path": project_relpath(path),
        "exists": path.is_file(),
    }
    if not path.is_file():
        return descriptor
    stat = path.stat()
    descriptor.update(
        {
            "bytes": stat.st_size,
            "sha256": sha256_file(path),
            "kind": asset_kind(path),
        }
    )
    return descriptor


def load_manifest() -> tuple[
    dict[str, Any],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, set[Path]]],
]:
    if not MANIFEST_PATH.is_file():
        return {}, {}, {}
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    by_card: dict[str, list[dict[str, Any]]] = defaultdict(list)
    exclusions_by_card: dict[str, dict[str, set[Path]]] = defaultdict(
        lambda: {"details": set(), "assets": set()}
    )
    for record in manifest.get("records", []):
        if not isinstance(record, dict):
            continue
        card_id = str(record.get("wrongnet_id") or "").strip()
        if card_id:
            by_card[card_id].append(record)
        excluded_card_ids = unique_strings(
            wrongnet.as_list(record.get("excluded_wrongnet_ids"))
        )
        if not excluded_card_ids:
            continue
        detail = resolve_project_ref(record.get("detail_note"))
        assets: list[Path] = []
        for key in ("question_assets", "solution_assets", "reference_assets", "assets"):
            for ref in wrongnet.as_list(record.get(key)):
                if path := resolve_project_ref(ref):
                    assets.append(path.resolve())
        for excluded_card_id in excluded_card_ids:
            if detail:
                exclusions_by_card[excluded_card_id]["details"].add(detail.resolve())
            exclusions_by_card[excluded_card_id]["assets"].update(assets)
    return manifest, dict(by_card), dict(exclusions_by_card)


def load_review_receipt() -> dict[str, Any]:
    if not REVIEW_RECEIPT_PATH.is_file():
        return {}
    value = json.loads(REVIEW_RECEIPT_PATH.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def load_semantic_review_batches() -> list[dict[str, Any]]:
    """Load human, hash-bound target-level review receipts.

    These files are semantic inputs, not generated projections.  A card may
    appear in only one current-campaign batch so that coverage cannot be
    inflated by duplicate receipts.
    """

    batches: list[dict[str, Any]] = []
    seen_review_ids: set[str] = set()
    seen_card_ids: dict[str, str] = {}
    if not REVIEW_DIR.is_dir():
        return batches
    for path in sorted(REVIEW_DIR.glob(SEMANTIC_REVIEW_BATCH_GLOB)):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"semantic review batch must be an object: {project_relpath(path)}")
        review_id = str(value.get("review_id") or "").strip()
        if not review_id:
            raise ValueError(f"semantic review batch missing review_id: {project_relpath(path)}")
        if review_id in seen_review_ids:
            raise ValueError(f"duplicate semantic review id: {review_id}")
        seen_review_ids.add(review_id)
        cards = value.get("cards")
        if not isinstance(cards, list) or not cards:
            raise ValueError(f"semantic review batch has no cards: {project_relpath(path)}")
        for item in cards:
            if not isinstance(item, dict):
                raise ValueError(f"semantic review card must be an object: {project_relpath(path)}")
            card_id = str(item.get("card_id") or "").strip()
            if not card_id:
                raise ValueError(f"semantic review card missing card_id: {project_relpath(path)}")
            if card_id in seen_card_ids:
                raise ValueError(
                    f"semantic review card {card_id} appears in both {seen_card_ids[card_id]} "
                    f"and {project_relpath(path)}"
                )
            seen_card_ids[card_id] = project_relpath(path)
        batch = dict(value)
        batch["_path"] = project_relpath(path)
        batch["_sha256"] = sha256_file(path)
        batches.append(batch)
    return batches


def semantic_review_snapshot(record: dict[str, Any], item: dict[str, Any], batch: dict[str, Any]) -> dict[str, Any]:
    card_id = str(item.get("card_id") or "").strip()
    aggregate_edge_policy = str(item.get("aggregate_edge_policy") or "allow").strip()
    later_revalidation = item.get("later_batch_revalidation")
    if isinstance(later_revalidation, dict):
        current_policy = str(
            later_revalidation.get("current_aggregate_edge_policy") or ""
        ).strip()
        if current_policy:
            aggregate_edge_policy = current_policy
    if aggregate_edge_policy not in ALLOWED_AGGREGATE_EDGE_POLICIES:
        raise ValueError(
            f"semantic review receipt has invalid aggregate_edge_policy for {card_id}: "
            f"{aggregate_edge_policy}"
        )

    current_assets = [asset for asset in record["visual"]["assets"] if asset.get("exists")]
    exclusion_policy = item.get("snapshot_exclusion_policy")
    normalized_exclusion_policy: dict[str, Any] | None = None
    excluded_asset_keys: set[tuple[str, str]] = set()
    exclusion_mismatches: list[str] = []
    if exclusion_policy is not None:
        if not isinstance(exclusion_policy, dict):
            raise ValueError(f"snapshot_exclusion_policy must be an object for {card_id}")
        unknown_policy_keys = set(exclusion_policy) - {"status", "excluded_current_assets"}
        if unknown_policy_keys:
            raise ValueError(
                f"snapshot_exclusion_policy has unknown keys for {card_id}: "
                f"{sorted(unknown_policy_keys)}"
            )
        if aggregate_edge_policy != "block_until_relinked":
            raise ValueError(
                f"snapshot_exclusion_policy requires block_until_relinked for {card_id}"
            )
        status = str(exclusion_policy.get("status") or "").strip()
        if status != "intentional_identity_exclusion":
            raise ValueError(
                f"snapshot_exclusion_policy has invalid status for {card_id}: {status}"
            )
        entries = exclusion_policy.get("excluded_current_assets")
        if not isinstance(entries, list) or not entries:
            raise ValueError(
                f"snapshot_exclusion_policy requires excluded_current_assets for {card_id}"
            )
        normalized_entries: list[dict[str, str]] = []
        seen_entries: set[tuple[str, str]] = set()
        current_asset_keys = {
            (str(asset.get("path") or ""), str(asset.get("sha256") or ""))
            for asset in current_assets
        }
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"snapshot exclusion entry must be an object for {card_id}")
            unknown_entry_keys = set(entry) - {"path", "sha256", "reason"}
            if unknown_entry_keys:
                raise ValueError(
                    f"snapshot exclusion entry has unknown keys for {card_id}: "
                    f"{sorted(unknown_entry_keys)}"
                )
            path = str(entry.get("path") or "").strip()
            digest = str(entry.get("sha256") or "").strip()
            reason = str(entry.get("reason") or "").strip()
            if not path or not re.fullmatch(r"[0-9a-f]{64}", digest) or not reason:
                raise ValueError(
                    f"snapshot exclusion entry requires path, sha256, and reason for {card_id}"
                )
            path_parts = Path(path).parts
            if (
                path.startswith("/")
                or "\\" in path
                or any(part in {"", ".", ".."} for part in path_parts)
                or any(marker in path for marker in ("*", "?", "[", "]"))
                or not path.startswith("错题知识网络/assets/visual_wrong_questions/")
                or Path(path).as_posix() != path
            ):
                raise ValueError(f"snapshot exclusion path is not canonical for {card_id}: {path}")
            key = (path, digest)
            if key in seen_entries:
                raise ValueError(f"duplicate snapshot exclusion entry for {card_id}: {path}")
            seen_entries.add(key)
            normalized_entries.append({"path": path, "sha256": digest, "reason": reason})
            if key in current_asset_keys:
                excluded_asset_keys.add(key)
            else:
                exclusion_mismatches.append("intentional_excluded_asset_not_current")
        normalized_exclusion_policy = {
            "status": status,
            "excluded_current_assets": normalized_entries,
        }

    comparable_current_assets = [
        asset
        for asset in current_assets
        if (str(asset.get("path") or ""), str(asset.get("sha256") or ""))
        not in excluded_asset_keys
    ]
    current_asset_hashes = sorted(
        {
            str(asset.get("sha256") or "")
            for asset in comparable_current_assets
            if asset.get("sha256")
        }
    )
    reviewed_asset_hashes = sorted(set(wrongnet.as_list(item.get("reviewed_unique_asset_sha256"))))
    reviewed_asset_role_by_path: dict[str, str] = {}
    role_path_conflicts: list[str] = []
    raw_reviewed_paths_by_role = item.get("reviewed_asset_paths_by_role")
    if isinstance(raw_reviewed_paths_by_role, dict):
        for role in ("question", "solution", "reference"):
            for path in wrongnet.as_list(raw_reviewed_paths_by_role.get(role)):
                prior_role = reviewed_asset_role_by_path.get(path)
                if prior_role and prior_role != role:
                    role_path_conflicts.append(path)
                    continue
                reviewed_asset_role_by_path[path] = role
    current_detail_hashes = {
        str(detail.get("sha256") or "")
        for detail in record["visual"]["details"]
        if detail.get("exists") and detail.get("sha256")
    }
    reviewed_detail_hashes = sorted(set(wrongnet.as_list(item.get("reviewed_detail_sha256"))))
    physical_asset_path_count = len(comparable_current_assets)
    mismatches: list[str] = list(exclusion_mismatches)
    if role_path_conflicts:
        mismatches.append("reviewed_asset_role_path_conflict")
    if str(item.get("card_sha256") or "").strip() != record["card_sha256"]:
        mismatches.append("formal_card_sha256_changed")
    if reviewed_asset_hashes != current_asset_hashes:
        mismatches.append("visual_asset_sha256_set_changed")
    if any(digest not in current_detail_hashes for digest in reviewed_detail_hashes):
        mismatches.append("reviewed_detail_sha256_missing")
    expected_physical_count = item.get("physical_asset_path_count")
    if not isinstance(expected_physical_count, int) or expected_physical_count != physical_asset_path_count:
        mismatches.append("physical_asset_path_count_changed")
    content_status = str(item.get("content_review_status") or "").strip()
    snapshot_status = "current" if not mismatches else "stale"
    current_status = (
        "batch_verified_current_assets"
        if snapshot_status == "current" and content_status == "verified"
        else "batch_review_stale"
    )
    findings = item.get("quality_findings") if isinstance(item.get("quality_findings"), list) else []
    relations = item.get("relation_decisions") if isinstance(item.get("relation_decisions"), list) else []
    return {
        "review_id": str(batch.get("review_id") or "").strip(),
        "batch_number": int(batch.get("batch_number") or 0),
        "batch_path": str(batch.get("_path") or ""),
        "batch_sha256": str(batch.get("_sha256") or ""),
        "reviewed_on": str(batch.get("reviewed_on") or "").strip(),
        "content_review_status": content_status,
        "snapshot_status": snapshot_status,
        "current_target_level_review_status": current_status,
        "snapshot_mismatches": mismatches,
        "reviewed_unique_asset_sha256": reviewed_asset_hashes,
        "reviewed_unique_asset_count": len(reviewed_asset_hashes),
        "reviewed_asset_role_by_path": reviewed_asset_role_by_path,
        "physical_asset_path_count": physical_asset_path_count,
        "current_physical_asset_path_count_before_exclusions": len(current_assets),
        "snapshot_exclusion_policy": normalized_exclusion_policy,
        "reviewed_detail_sha256": reviewed_detail_hashes,
        "question_summary": str(item.get("question_summary") or "").strip(),
        "asked_output": str(item.get("asked_output") or "").strip(),
        "answer": str(item.get("answer") or "").strip(),
        "solution_outline": unique_strings(wrongnet.as_list(item.get("solution_outline"))),
        "knowledge_nodes": unique_strings(wrongnet.as_list(item.get("knowledge_nodes"))),
        "first_action": str(item.get("first_action") or "").strip(),
        "personal_error": item.get("personal_error") if isinstance(item.get("personal_error"), dict) else {},
        "consistency": item.get("consistency") if isinstance(item.get("consistency"), dict) else {},
        "quality_findings": [finding for finding in findings if isinstance(finding, dict)],
        "relation_decisions": [decision for decision in relations if isinstance(decision, dict)],
        "aggregate_edge_policy": aggregate_edge_policy,
    }


def apply_semantic_review_batches(
    records: list[dict[str, Any]], batches: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_card = {record["card_id"]: record for record in records}
    for record in records:
        record["semantic_review"]["current_campaign"] = {
            "current_target_level_review_status": "not_reviewed_in_current_campaign"
        }
    for batch in batches:
        for item in batch["cards"]:
            card_id = str(item.get("card_id") or "").strip()
            if card_id not in by_card:
                raise ValueError(f"semantic review receipt references unknown formal card: {card_id}")
            record = by_card[card_id]
            snapshot = semantic_review_snapshot(record, item, batch)
            record["semantic_review"]["current_campaign"] = snapshot
            current_verified = snapshot["current_target_level_review_status"] == "batch_verified_current_assets"
            if current_verified:
                record["issues"] = [
                    issue
                    for issue in record["issues"]
                    if issue not in {"target_level_semantic_review_gap", "target_level_review_batch_1"}
                ]
                record["visual"]["semantic_review_status"] = "human_reviewed_current_hashes"
                record["semantic_review_priority"] = max(0, record["semantic_review_priority"] - 6)
            else:
                record["issues"] = unique_strings([*record["issues"], "semantic_review_snapshot_stale"])
                record["semantic_review_priority"] += 10
            severity_weight = {"critical": 12, "high": 8, "medium": 4, "low": 1}
            for finding in snapshot["quality_findings"]:
                if str(finding.get("resolution_status") or "").strip() in RESOLVED_FINDING_STATUSES:
                    continue
                code = str(finding.get("code") or "").strip()
                if code:
                    record["issues"] = unique_strings([*record["issues"], code])
                record["semantic_review_priority"] += severity_weight.get(
                    str(finding.get("severity") or "").strip().lower(), 0
                )
            if snapshot["aggregate_edge_policy"] == "block_until_relinked":
                record["semantic_edge_blocked"] = True
                record["semantic_review"]["block_from_aggregate_edges"] = True
                record["semantic_review"]["current_campaign"]["aggregate_edge_blocked"] = True
    return records


def review_context(receipt: dict[str, Any], card_id: str) -> dict[str, Any]:
    coverage = receipt.get("coverage_findings") if isinstance(receipt.get("coverage_findings"), dict) else {}
    holds = receipt.get("semantic_holds") if isinstance(receipt.get("semantic_holds"), dict) else {}
    history = (
        receipt.get("historical_target_level_review_coverage")
        if isinstance(receipt.get("historical_target_level_review_coverage"), dict)
        else {}
    )
    direct = receipt.get("direct_visual_findings") if isinstance(receipt.get("direct_visual_findings"), list) else []
    identity = set(wrongnet.as_list(holds.get("confirmed_identity_or_content_mismatches")))
    solution_defects = set(wrongnet.as_list(holds.get("known_solution_or_detail_content_defects")))
    visual_gaps = set(wrongnet.as_list(holds.get("known_visual_identity_gaps_or_mismatches")))
    question_gaps = set(wrongnet.as_list(coverage.get("effective_question_evidence_gap_ids")))
    solution_gaps = set(wrongnet.as_list(coverage.get("visual_solution_evidence_gap_ids")))
    broad_knowledge = set(wrongnet.as_list(coverage.get("knowledge_broad_only_or_placeholder_ids")))
    exact_review_carry_forward = set(wrongnet.as_list(history.get("exact_sha_carry_forward_ids")))
    field_review_carry_forward = set(
        wrongnet.as_list(history.get("field_level_semantic_carry_forward_candidate_ids"))
    )
    semantic_review_gap = set(wrongnet.as_list(history.get("current_semantic_review_gap_ids")))
    first_review_batch = set(wrongnet.as_list(history.get("first_batch_30_ids")))
    first_batch_groups = history.get("first_batch_groups") if isinstance(history.get("first_batch_groups"), dict) else {}
    card_first_batch_groups = [
        group_name
        for group_name, group_ids in first_batch_groups.items()
        if card_id in set(wrongnet.as_list(group_ids))
    ]
    broken_ref = holds.get("definitive_broken_local_reference")
    broken_card_id = str(broken_ref.get("card_id") or "").strip() if isinstance(broken_ref, dict) else ""
    direct_findings = [item for item in direct if isinstance(item, dict) and item.get("card_id") == card_id]
    categories: list[str] = []
    if card_id in identity:
        categories.append("confirmed_identity_or_content_mismatch")
    if card_id in solution_defects:
        categories.append("known_solution_or_detail_content_defect")
    if card_id in visual_gaps:
        categories.append("known_visual_identity_gap_or_mismatch")
    if card_id in question_gaps:
        categories.append("effective_question_evidence_gap")
    if card_id in solution_gaps:
        categories.append("visual_solution_evidence_gap")
    if card_id in broad_knowledge:
        categories.append("knowledge_broad_only_or_placeholder")
    if card_id == broken_card_id:
        categories.append("definitive_broken_local_reference")
    if card_id in semantic_review_gap:
        categories.append("target_level_semantic_review_gap")
    if card_id in first_review_batch:
        categories.append("target_level_review_batch_1")
    if card_id in exact_review_carry_forward:
        historical_review_status = "exact_sha_carry_forward"
    elif card_id in field_review_carry_forward:
        historical_review_status = "field_level_semantic_carry_forward_candidate"
    elif card_id in semantic_review_gap:
        historical_review_status = "target_level_semantic_review_gap"
    else:
        historical_review_status = "unclassified"
    return {
        "review_id": str(receipt.get("review_id") or "").strip(),
        "categories": categories,
        "block_from_aggregate_edges": card_id in identity,
        "effective_question_evidence": card_id not in question_gaps,
        "visual_solution_evidence": card_id not in solution_gaps,
        "knowledge_needs_refinement": card_id in broad_knowledge,
        "historical_target_level_review_status": historical_review_status,
        "first_review_batch": card_id in first_review_batch,
        "first_review_batch_groups": card_first_batch_groups,
        "direct_findings": direct_findings,
    }


def discover_detail_paths(
    card_id: str,
    manifest_records: list[dict[str, Any]],
    meta: dict[str, Any],
    excluded_paths: set[Path],
) -> list[Path]:
    candidates: list[Path] = []
    for record in manifest_records:
        if path := resolve_project_ref(record.get("detail_note")):
            candidates.append(path)
    for ref in wrongnet.as_list(meta.get("lecture_refs")):
        path = resolve_project_ref(ref)
        if path and path.suffix.lower() == ".md" and "可视化错题详情" in path.as_posix():
            candidates.append(path)
    candidates.extend(VISUAL_DIR.glob(f"*/{card_id}_*.md"))
    return sorted(
        {path.resolve() for path in candidates if path.resolve() not in excluded_paths},
        key=lambda item: item.as_posix(),
    )


def discover_asset_paths(
    card_id: str,
    manifest_records: list[dict[str, Any]],
    meta: dict[str, Any],
    excluded_paths: set[Path],
) -> list[Path]:
    candidates: list[Path] = []
    for record in manifest_records:
        for key in ("question_assets", "solution_assets", "reference_assets", "assets"):
            for ref in wrongnet.as_list(record.get(key)):
                if path := resolve_project_ref(ref):
                    candidates.append(path)
    for ref in wrongnet.as_list(meta.get("lecture_refs")):
        path = resolve_project_ref(ref)
        if path and path.suffix.lower() in IMAGE_SUFFIXES:
            candidates.append(path)
    direct_dir = VISUAL_ASSETS_DIR / card_id
    if direct_dir.is_dir():
        candidates.extend(path for path in direct_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
    return sorted(
        {path.resolve() for path in candidates if path.resolve() not in excluded_paths},
        key=lambda item: item.as_posix(),
    )


def detail_descriptor(path: Path) -> dict[str, Any]:
    descriptor: dict[str, Any] = {"path": project_relpath(path), "exists": path.is_file()}
    if not path.is_file():
        return descriptor
    raw = path.read_text(encoding="utf-8")
    meta, body = wrongnet.split_front_matter(raw)
    sections = split_markdown_sections(body)
    analysis_text = selected_section_text(sections, DETAIL_ANALYSIS_MARKERS)
    descriptor.update(
        {
            "sha256": sha256_bytes(raw.encode("utf-8")),
            "link_status": str(meta.get("link_status") or "").strip(),
            "headings": [section["title"] for section in sections if section["title"] != "正文"],
            "has_semantic_analysis_text": meaningful_text(analysis_text),
            "analysis_excerpt": plain_markdown_excerpt(analysis_text),
        }
    )
    return descriptor


def visual_record(
    card_id: str,
    manifest_records: list[dict[str, Any]],
    meta: dict[str, Any],
    identity_exclusions: dict[str, set[Path]],
) -> dict[str, Any]:
    excluded_detail_paths = identity_exclusions.get("details", set())
    excluded_asset_paths = identity_exclusions.get("assets", set())
    detail_paths = discover_detail_paths(
        card_id, manifest_records, meta, excluded_detail_paths
    )
    asset_paths = discover_asset_paths(
        card_id, manifest_records, meta, excluded_asset_paths
    )
    details = [detail_descriptor(path) for path in detail_paths]
    assets = [file_descriptor(path) for path in asset_paths]
    existing_assets = [asset for asset in assets if asset.get("exists")]
    question_assets = [asset for asset in existing_assets if asset.get("kind") == "question"]
    solution_assets = [asset for asset in existing_assets if asset.get("kind") == "solution"]
    reference_assets = [asset for asset in existing_assets if asset.get("kind") == "reference"]
    statuses = unique_strings(record.get("link_status") for record in manifest_records)
    detail_statuses = unique_strings(detail.get("link_status") for detail in details)
    warning_statuses = sorted((set(statuses) | set(detail_statuses)) & VISUAL_WARNING_STATUSES)
    manifest_asset_refs: set[str] = set()
    manifest_detail_refs: set[str] = set()
    for record in manifest_records:
        if detail := resolve_project_ref(record.get("detail_note")):
            manifest_detail_refs.add(project_relpath(detail))
        for key in ("question_assets", "solution_assets", "reference_assets", "assets"):
            for ref in wrongnet.as_list(record.get(key)):
                if path := resolve_project_ref(ref):
                    manifest_asset_refs.add(project_relpath(path))
    discovered_existing_assets = {asset["path"] for asset in existing_assets}
    registry_scoped_existing_assets = {
        asset["path"]
        for asset in existing_assets
        if asset.get("kind") in {"question", "solution"}
    }
    discovered_existing_details = {detail["path"] for detail in details if detail.get("exists")}
    unregistered_assets = sorted(registry_scoped_existing_assets - manifest_asset_refs)
    unregistered_reference_assets = sorted(
        discovered_existing_assets - registry_scoped_existing_assets - manifest_asset_refs
    )
    unregistered_details = sorted(discovered_existing_details - manifest_detail_refs)
    missing_references = sorted(
        [item["path"] for item in assets + details if not item.get("exists")]
    )
    if question_assets and solution_assets:
        asset_coverage = "question_and_solution"
    elif question_assets:
        asset_coverage = "question_only"
    elif solution_assets:
        asset_coverage = "solution_only"
    elif reference_assets:
        asset_coverage = "reference_only"
    else:
        asset_coverage = "none"
    semantic_detail_count = sum(1 for detail in details if detail.get("has_semantic_analysis_text"))
    if warning_statuses:
        registration_state = "warning"
    elif manifest_records and not missing_references and not unregistered_assets and not unregistered_details:
        registration_state = "registered"
    elif manifest_records:
        registration_state = "registered_with_drift"
    elif existing_assets or discovered_existing_details:
        registration_state = "unregistered_discovery"
    else:
        registration_state = "none"
    return {
        "manifest_record_count": len(manifest_records),
        "manifest_visual_ids": unique_strings(record.get("visual_id") for record in manifest_records),
        "manifest_statuses": statuses,
        "warning_statuses": warning_statuses,
        "registration_state": registration_state,
        "asset_coverage": asset_coverage,
        "question_asset_count": len(question_assets),
        "solution_asset_count": len(solution_assets),
        "reference_asset_count": len(reference_assets),
        "semantic_detail_count": semantic_detail_count,
        "semantic_review_status": "not_proven",
        "details": details,
        "assets": assets,
        "unregistered_assets": unregistered_assets,
        "unregistered_reference_assets": unregistered_reference_assets,
        "unregistered_details": unregistered_details,
        "missing_references": missing_references,
        "identity_excluded_detail_paths": sorted(
            project_relpath(path) for path in excluded_detail_paths
        ),
        "identity_excluded_asset_paths": sorted(
            project_relpath(path) for path in excluded_asset_paths
        ),
    }


def source_summary_path(card_id: str) -> Path:
    return BASE_DIR / "wiki" / "sources" / "wrong_cards" / f"SRC-WQ-{card_id}.md"


def card_record(
    card: dict[str, Any],
    manifest_records: list[dict[str, Any]],
    identity_exclusions: dict[str, set[Path]],
    review: dict[str, Any],
) -> dict[str, Any]:
    meta = card["meta"]
    card_id = card["id"]
    evidence = training_evidence.extract_error_evidence(meta, card_id)
    tier = evidence_tier(evidence)
    sections = split_markdown_sections(card.get("body", ""))
    question_text = selected_section_text(sections, QUESTION_SECTION_MARKERS)
    analysis_text = selected_section_text(sections, ANALYSIS_SECTION_MARKERS)
    formal_knowledge = unique_strings(wrongnet.clean_items(meta.get("knowledge")))
    edge_knowledge = unique_strings(wrongnet.signal_items(meta.get("knowledge")))
    fine_knowledge = [item for item in edge_knowledge if item not in wrongnet.BROAD_KNOWLEDGE]
    raw_error_causes = unique_strings(wrongnet.clean_items(meta.get("error_causes")))
    edge_error_causes = unique_strings(wrongnet.evidence_items(meta.get("error_causes")))
    specific_error_causes = [item for item in edge_error_causes if item not in wrongnet.GENERIC_ERROR_CAUSES]
    visual = visual_record(card_id, manifest_records, meta, identity_exclusions)
    summary_path = source_summary_path(card_id)
    method_gap = evidence.get("method_gap") if isinstance(evidence.get("method_gap"), dict) else {}
    issues: list[str] = []
    if not formal_knowledge:
        issues.append("formal_knowledge_missing")
    if not edge_knowledge:
        issues.append("usable_knowledge_missing")
    if not edge_error_causes:
        issues.append("usable_error_cause_missing")
    if tier != "confirmed_personal":
        issues.append("personal_error_not_confirmed")
    if tier == "confirmed_personal" and not edge_error_causes:
        issues.append("personal_confirmed_but_no_error_taxonomy")
    if not meaningful_text(question_text):
        issues.append("formal_question_text_missing")
    if not meaningful_text(analysis_text):
        issues.append("formal_analysis_text_missing")
    if visual["question_asset_count"] == 0:
        issues.append("question_image_missing")
    if visual["solution_asset_count"] == 0:
        issues.append("solution_image_missing")
    if visual["semantic_detail_count"] == 0:
        issues.append("visual_detail_analysis_missing")
    if visual["registration_state"] in {"warning", "registered_with_drift", "unregistered_discovery"}:
        issues.append(f"visual_{visual['registration_state']}")
    if not summary_path.is_file():
        issues.append("source_summary_missing")
    issues.extend(review.get("categories", []))
    priority_score = 0
    priority_score += 8 if visual["warning_statuses"] else 0
    priority_score += 6 if visual["registration_state"] in {"registered_with_drift", "unregistered_discovery"} else 0
    priority_score += 5 if not meaningful_text(question_text) and visual["question_asset_count"] == 0 else 0
    priority_score += 5 if not meaningful_text(analysis_text) and visual["solution_asset_count"] == 0 else 0
    priority_score += 3 if tier in {"model_inferred_from_solution", "pending_user_confirmation", "missing"} else 0
    priority_score += 2 if tier == "legacy_unclassified" else 0
    priority_score += 1 if visual["semantic_detail_count"] == 0 else 0
    priority_score += 12 if review.get("block_from_aggregate_edges") else 0
    priority_score += 6 if "known_solution_or_detail_content_defect" in review.get("categories", []) else 0
    priority_score += 5 if "known_visual_identity_gap_or_mismatch" in review.get("categories", []) else 0
    priority_score += 2 if review.get("historical_target_level_review_status") == "target_level_semantic_review_gap" else 0
    priority_score += 4 if review.get("first_review_batch") is True else 0
    card_path = Path(card["path"])
    body = card.get("body", "")
    return {
        "card_id": card_id,
        "title": str(meta.get("title") or "").strip(),
        "subject": str(meta.get("subject") or "").strip(),
        "chapter": str(meta.get("chapter") or "").strip(),
        "status": str(meta.get("status") or "").strip(),
        "date": str(meta.get("date") or "").strip(),
        "card_path": project_relpath(card_path),
        "card_sha256": sha256_file(card_path),
        "body_sha256": sha256_bytes(body.encode("utf-8")),
        "source_summary_path": project_relpath(summary_path),
        "source_summary_exists": summary_path.is_file(),
        "formal_knowledge": formal_knowledge,
        "edge_knowledge": edge_knowledge,
        "fine_knowledge": fine_knowledge,
        "inferred_knowledge_candidates": unique_strings(wrongnet.as_list(meta.get("inferred_knowledge_candidates"))),
        "raw_error_causes": raw_error_causes,
        "edge_error_causes": edge_error_causes,
        "specific_error_causes": specific_error_causes,
        "wrong_point": str(evidence.get("wrong_point") or "").strip(),
        "missed_action": str(method_gap.get("missed_action") or "").strip(),
        "expected_first_action": str(method_gap.get("expected_first_action") or "").strip(),
        "method_trigger": str(method_gap.get("method_trigger") or "").strip(),
        "action_gap_type": str(method_gap.get("action_gap_type") or "").strip(),
        "related_method_card_id": str(method_gap.get("related_method_card_id") or "").strip(),
        "evidence_id": evidence.get("evidence_id"),
        "evidence_source_version": evidence.get("source_version"),
        "gap_key": evidence.get("gap_key"),
        "evidence_origin": evidence.get("origin"),
        "evidence_origin_declared": evidence.get("origin_declared") is True,
        "personal_confirmed": evidence.get("personal_confirmed") is True,
        "structured_targetable": evidence.get("structured_targetable") is True,
        "needs_confirmation": evidence.get("needs_confirmation") is True,
        "model_derived": evidence.get("model_derived") is True,
        "has_observed_failure": evidence.get("has_observed_failure") is True,
        "specific_fields": evidence.get("specific_fields") if isinstance(evidence.get("specific_fields"), dict) else {},
        "evidence_tier": tier,
        "evidence_tier_label": EVIDENCE_TIER_LABELS[tier],
        "formal_content": {
            "headings": [section["title"] for section in sections if section["title"] != "正文"],
            "has_question_text": meaningful_text(question_text),
            "question_excerpt": plain_markdown_excerpt(question_text),
            "has_analysis_text": meaningful_text(analysis_text),
            "analysis_excerpt": plain_markdown_excerpt(analysis_text),
        },
        "visual": visual,
        "semantic_review": review,
        "semantic_edge_blocked": review.get("block_from_aggregate_edges") is True,
        "issues": unique_strings(issues),
        "semantic_review_priority": priority_score,
    }


def edge_id(prefix: str, *parts: str) -> str:
    payload = "\u241f".join(parts).encode("utf-8")
    return f"{prefix}-{sha256_bytes(payload)[:16]}"


def aggregate_taxonomy_edges(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        for knowledge in unique_strings(record["edge_knowledge"]):
            for error_cause in unique_strings(record["edge_error_causes"]):
                key = (knowledge, error_cause)
                bucket = buckets.setdefault(
                    key,
                    {
                        "edge_id": edge_id("KE", knowledge, error_cause),
                        "knowledge": knowledge,
                        "error_cause": error_cause,
                        "knowledge_specific": knowledge not in wrongnet.BROAD_KNOWLEDGE,
                        "error_cause_specific": error_cause not in wrongnet.GENERIC_ERROR_CAUSES,
                        "cards": [],
                        "eligible_cards": [],
                        "blocked_cards": [],
                        "confirmed_personal_cards": [],
                        "evidence_tiers": Counter(),
                        "evidence_origins": Counter(),
                        "subjects": Counter(),
                        "action_gap_types": Counter(),
                    },
                )
                card_id = record["card_id"]
                bucket["cards"].append(card_id)
                if record["semantic_edge_blocked"]:
                    bucket["blocked_cards"].append(card_id)
                else:
                    bucket["eligible_cards"].append(card_id)
                if record["personal_confirmed"] and not record["semantic_edge_blocked"]:
                    bucket["confirmed_personal_cards"].append(card_id)
                bucket["evidence_tiers"][record["evidence_tier"]] += 1
                bucket["evidence_origins"][record["evidence_origin"]] += 1
                bucket["subjects"][record["subject"]] += 1
                if record["action_gap_type"]:
                    bucket["action_gap_types"][record["action_gap_type"]] += 1
    result: list[dict[str, Any]] = []
    for bucket in buckets.values():
        bucket["cards"] = sorted(set(bucket["cards"]))
        bucket["eligible_cards"] = sorted(set(bucket["eligible_cards"]))
        bucket["blocked_cards"] = sorted(set(bucket["blocked_cards"]))
        bucket["confirmed_personal_cards"] = sorted(set(bucket["confirmed_personal_cards"]))
        bucket["card_count"] = len(bucket["cards"])
        bucket["eligible_card_count"] = len(bucket["eligible_cards"])
        bucket["blocked_card_count"] = len(bucket["blocked_cards"])
        bucket["confirmed_personal_count"] = len(bucket["confirmed_personal_cards"])
        for field in ("evidence_tiers", "evidence_origins", "subjects", "action_gap_types"):
            bucket[field] = dict(sorted(bucket[field].items()))
        result.append(bucket)
    return sorted(
        result,
        key=lambda edge: (
            -edge["confirmed_personal_count"],
            -edge["card_count"],
            edge["knowledge"],
            edge["error_cause"],
        ),
    )


def aggregate_action_edges(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        action_gap = record["action_gap_type"]
        if not action_gap:
            continue
        for knowledge in unique_strings(record["edge_knowledge"]):
            key = (knowledge, action_gap)
            bucket = buckets.setdefault(
                key,
                {
                    "edge_id": edge_id("KA", knowledge, action_gap),
                    "knowledge": knowledge,
                    "action_gap_type": action_gap,
                    "knowledge_specific": knowledge not in wrongnet.BROAD_KNOWLEDGE,
                    "cards": [],
                    "eligible_cards": [],
                    "blocked_cards": [],
                    "confirmed_personal_cards": [],
                    "evidence_tiers": Counter(),
                },
            )
            bucket["cards"].append(record["card_id"])
            if record["semantic_edge_blocked"]:
                bucket["blocked_cards"].append(record["card_id"])
            else:
                bucket["eligible_cards"].append(record["card_id"])
            if record["personal_confirmed"] and not record["semantic_edge_blocked"]:
                bucket["confirmed_personal_cards"].append(record["card_id"])
            bucket["evidence_tiers"][record["evidence_tier"]] += 1
    result: list[dict[str, Any]] = []
    for bucket in buckets.values():
        bucket["cards"] = sorted(set(bucket["cards"]))
        bucket["eligible_cards"] = sorted(set(bucket["eligible_cards"]))
        bucket["blocked_cards"] = sorted(set(bucket["blocked_cards"]))
        bucket["confirmed_personal_cards"] = sorted(set(bucket["confirmed_personal_cards"]))
        bucket["card_count"] = len(bucket["cards"])
        bucket["eligible_card_count"] = len(bucket["eligible_cards"])
        bucket["blocked_card_count"] = len(bucket["blocked_cards"])
        bucket["confirmed_personal_count"] = len(bucket["confirmed_personal_cards"])
        bucket["evidence_tiers"] = dict(sorted(bucket["evidence_tiers"].items()))
        result.append(bucket)
    return sorted(
        result,
        key=lambda edge: (
            -edge["confirmed_personal_count"],
            -edge["card_count"],
            edge["knowledge"],
            edge["action_gap_type"],
        ),
    )


def aggregate_breakpoint_edges(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in records:
        if not record["wrong_point"] and not record["missed_action"]:
            continue
        for knowledge in unique_strings(record["edge_knowledge"]):
            result.append(
                {
                    "edge_id": edge_id("KB", record["card_id"], knowledge),
                    "card_id": record["card_id"],
                    "knowledge": knowledge,
                    "wrong_point": record["wrong_point"],
                    "missed_action": record["missed_action"],
                    "expected_first_action": record["expected_first_action"],
                    "evidence_origin": record["evidence_origin"],
                    "evidence_tier": record["evidence_tier"],
                    "personal_confirmed": record["personal_confirmed"],
                    "semantic_edge_blocked": record["semantic_edge_blocked"],
                }
            )
    return sorted(
        result,
        key=lambda edge: (
            EVIDENCE_TIER_ORDER.get(edge["evidence_tier"], 99),
            edge["card_id"],
            edge["knowledge"],
        ),
    )


def annotate_duplicate_question_assets(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocked_ids = {record["card_id"] for record in records if record["semantic_edge_blocked"]}
    by_hash: dict[str, dict[str, Any]] = {}
    for record in records:
        for asset in record["visual"]["assets"]:
            if not asset.get("exists") or asset.get("kind") != "question" or not asset.get("sha256"):
                continue
            digest = str(asset["sha256"])
            bucket = by_hash.setdefault(digest, {"card_ids": set(), "asset_paths": set()})
            bucket["card_ids"].add(record["card_id"])
            bucket["asset_paths"].add(asset["path"])
    groups: list[dict[str, Any]] = []
    memberships: dict[str, list[str]] = defaultdict(list)
    for digest, bucket in by_hash.items():
        card_ids = sorted(bucket["card_ids"])
        if len(card_ids) < 2:
            continue
        group_id = f"QIMG-{digest[:16]}"
        groups.append(
            {
                "group_id": group_id,
                "question_asset_sha256": digest,
                "card_ids": card_ids,
                "card_count": len(card_ids),
                "asset_paths": sorted(bucket["asset_paths"]),
                "identity_blocked_card_ids": sorted(set(card_ids) & blocked_ids),
                "already_covered_by_identity_blocklist": set(card_ids).issubset(blocked_ids),
                "decision": "duplicate_or_recurrence_review_before_ordinary_semantic_linking",
            }
        )
        for card_id in card_ids:
            memberships[card_id].append(group_id)
    for record in records:
        group_ids = sorted(memberships.get(record["card_id"], []))
        record["visual"]["duplicate_question_asset_groups"] = group_ids
        if group_ids:
            record["issues"] = unique_strings(record["issues"] + ["cross_id_duplicate_question_asset"])
    return sorted(groups, key=lambda group: (-group["card_count"], group["group_id"]))


def build_graph() -> dict[str, Any]:
    manifest, manifest_by_card, manifest_exclusions_by_card = load_manifest()
    receipt = load_review_receipt()
    semantic_review_batches = load_semantic_review_batches()
    cards = wrongnet.read_cards()
    records = [
        card_record(
            card,
            manifest_by_card.get(card["id"], []),
            manifest_exclusions_by_card.get(card["id"], {}),
            review_context(receipt, card["id"]),
        )
        for card in cards
    ]
    records.sort(key=lambda record: record["card_id"])
    apply_semantic_review_batches(records, semantic_review_batches)
    duplicate_question_groups = annotate_duplicate_question_assets(records)
    unresolved_duplicate_question_groups = [
        group for group in duplicate_question_groups if not group["already_covered_by_identity_blocklist"]
    ]
    taxonomy_edges = aggregate_taxonomy_edges(records)
    action_edges = aggregate_action_edges(records)
    breakpoint_edges = aggregate_breakpoint_edges(records)
    tier_counts = Counter(record["evidence_tier"] for record in records)
    origin_counts = Counter(record["evidence_origin"] for record in records)
    subject_counts = Counter(record["subject"] for record in records)
    prefix_counts = Counter(record["card_id"].split("-", 1)[0] for record in records)
    registration_counts = Counter(record["visual"]["registration_state"] for record in records)
    asset_coverage_counts = Counter(record["visual"]["asset_coverage"] for record in records)
    issue_counts = Counter(issue for record in records for issue in record["issues"])
    reviewed_coverage = receipt.get("coverage_findings") if isinstance(receipt.get("coverage_findings"), dict) else {}
    historical_review_coverage = (
        receipt.get("historical_target_level_review_coverage")
        if isinstance(receipt.get("historical_target_level_review_coverage"), dict)
        else {}
    )
    ocr_validation = receipt.get("ocr_validation") if isinstance(receipt.get("ocr_validation"), dict) else {}
    unique_assets: dict[str, dict[str, Any]] = {}
    for record in records:
        for asset in record["visual"]["assets"]:
            if asset.get("exists"):
                unique_assets[asset["path"]] = asset
    unique_asset_role_counts = Counter(asset.get("kind", "reference") for asset in unique_assets.values())
    all_physical_asset_paths = sorted(
        path.resolve()
        for path in VISUAL_ASSETS_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    all_physical_assets = [file_descriptor(path) for path in all_physical_asset_paths]
    unbound_physical_assets = [
        asset for asset in all_physical_assets if asset["path"] not in unique_assets
    ]
    all_physical_role_counts = Counter(asset.get("kind", "reference") for asset in all_physical_assets)
    current_campaign_records = [
        record
        for record in records
        if record["semantic_review"]["current_campaign"].get("current_target_level_review_status")
        != "not_reviewed_in_current_campaign"
    ]
    current_verified_records = [
        record
        for record in current_campaign_records
        if record["semantic_review"]["current_campaign"].get("current_target_level_review_status")
        == "batch_verified_current_assets"
    ]
    current_stale_records = [
        record
        for record in current_campaign_records
        if record["semantic_review"]["current_campaign"].get("current_target_level_review_status")
        == "batch_review_stale"
    ]
    campaign_quality_counts = Counter(
        str(finding.get("code") or "").strip()
        for record in current_campaign_records
        for finding in record["semantic_review"]["current_campaign"].get("quality_findings", [])
        if str(finding.get("code") or "").strip()
        and str(finding.get("resolution_status") or "").strip() not in RESOLVED_FINDING_STATUSES
    )
    current_reviewed_assets_by_hash: dict[str, dict[str, Any]] = {}
    for record in current_verified_records:
        campaign = record["semantic_review"]["current_campaign"]
        reviewed_hashes = set(campaign.get("reviewed_unique_asset_sha256", []))
        reviewed_asset_role_by_path = campaign.get("reviewed_asset_role_by_path", {})
        for asset in record["visual"]["assets"]:
            digest = str(asset.get("sha256") or "")
            if asset.get("exists") and digest in reviewed_hashes:
                reviewed_asset = dict(asset)
                reviewed_asset["kind"] = reviewed_asset_role_by_path.get(
                    str(asset.get("path") or ""),
                    asset.get("kind", "reference"),
                )
                current_reviewed_assets_by_hash.setdefault(digest, reviewed_asset)
    current_reviewed_asset_role_counts = Counter(
        asset.get("kind", "reference") for asset in current_reviewed_assets_by_hash.values()
    )
    semantic_review_relation_decisions: list[dict[str, Any]] = []
    for record in current_campaign_records:
        campaign = record["semantic_review"]["current_campaign"]
        for decision in campaign.get("relation_decisions", []):
            semantic_review_relation_decisions.append(
                {
                    "source_card_id": record["card_id"],
                    "review_id": campaign.get("review_id", ""),
                    **decision,
                }
            )
    semantic_review_batch_descriptors = [
        {
            "review_id": str(batch.get("review_id") or "").strip(),
            "batch_number": int(batch.get("batch_number") or 0),
            "reviewed_on": str(batch.get("reviewed_on") or "").strip(),
            "path": str(batch.get("_path") or ""),
            "sha256": str(batch.get("_sha256") or ""),
            "card_count": len(batch.get("cards", [])),
        }
        for batch in semantic_review_batches
    ]
    dated_inputs = [
        record["date"]
        for record in records
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["date"])
    ]
    receipt_date = str(receipt.get("reviewed_on") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", receipt_date):
        dated_inputs.append(receipt_date)
    latest_date = max(dated_inputs, default="")
    summary = {
        "formal_card_count": len(records),
        "subject_counts": dict(sorted(subject_counts.items())),
        "id_prefix_counts": dict(sorted(prefix_counts.items())),
        "formal_knowledge_node_count": len({item for record in records for item in record["formal_knowledge"]}),
        "edge_knowledge_node_count": len({item for record in records for item in record["edge_knowledge"]}),
        "error_cause_node_count": len({item for record in records for item in record["edge_error_causes"]}),
        "taxonomy_edge_count": len(taxonomy_edges),
        "action_edge_count": len(action_edges),
        "breakpoint_edge_count": len(breakpoint_edges),
        "evidence_tier_counts": dict(sorted(tier_counts.items())),
        "evidence_origin_counts": dict(sorted(origin_counts.items())),
        "personal_confirmed_card_count": sum(1 for record in records if record["personal_confirmed"]),
        "structured_targetable_card_count": sum(1 for record in records if record["structured_targetable"]),
        "semantic_edge_blocked_card_count": sum(1 for record in records if record["semantic_edge_blocked"]),
        "effective_question_evidence_count": sum(
            1 for record in records if record["semantic_review"].get("effective_question_evidence") is True
        ),
        "visual_solution_evidence_count": sum(
            1 for record in records if record["semantic_review"].get("visual_solution_evidence") is True
        ),
        "knowledge_needs_refinement_card_count": sum(
            1 for record in records if record["semantic_review"].get("knowledge_needs_refinement") is True
        ),
        "target_level_review_exact_sha_carry_forward_count": sum(
            1
            for record in records
            if record["semantic_review"].get("historical_target_level_review_status") == "exact_sha_carry_forward"
        ),
        "target_level_review_field_level_carry_forward_candidate_count": sum(
            1
            for record in records
            if record["semantic_review"].get("historical_target_level_review_status")
            in {"exact_sha_carry_forward", "field_level_semantic_carry_forward_candidate"}
        ),
        "target_level_semantic_review_gap_count": sum(
            1
            for record in records
            if record["semantic_review"].get("historical_target_level_review_status")
            == "target_level_semantic_review_gap"
        ),
        "target_level_review_first_batch_count": sum(
            1 for record in records if record["semantic_review"].get("first_review_batch") is True
        ),
        "semantic_review_batch_count": len(semantic_review_batches),
        "semantic_review_campaign_current_card_count": len(current_campaign_records),
        "semantic_review_campaign_verified_card_count": len(current_verified_records),
        "semantic_review_campaign_stale_card_count": len(current_stale_records),
        "semantic_review_campaign_remaining_card_count": len(records) - len(current_verified_records),
        "semantic_review_current_historical_gap_remaining_count": sum(
            1
            for record in records
            if record["semantic_review"].get("historical_target_level_review_status")
            == "target_level_semantic_review_gap"
            and record["semantic_review"]["current_campaign"].get("current_target_level_review_status")
            != "batch_verified_current_assets"
        ),
        "semantic_review_campaign_quality_finding_card_count": sum(
            1
            for record in current_campaign_records
            if any(
                str(finding.get("resolution_status") or "").strip()
                not in RESOLVED_FINDING_STATUSES
                for finding in record["semantic_review"]["current_campaign"].get(
                    "quality_findings", []
                )
            )
        ),
        "semantic_review_campaign_quality_finding_counts": dict(sorted(campaign_quality_counts.items())),
        "semantic_review_campaign_physical_asset_path_count": sum(
            int(record["semantic_review"]["current_campaign"].get("physical_asset_path_count") or 0)
            for record in current_verified_records
        ),
        "semantic_review_campaign_unique_asset_count": len(current_reviewed_assets_by_hash),
        "semantic_review_campaign_unique_asset_role_counts": dict(
            sorted(current_reviewed_asset_role_counts.items())
        ),
        "semantic_review_relation_decision_count": len(semantic_review_relation_decisions),
        "formal_question_text_count": sum(1 for record in records if record["formal_content"]["has_question_text"]),
        "formal_analysis_text_count": sum(1 for record in records if record["formal_content"]["has_analysis_text"]),
        "reviewed_question_text_substantive_count": int(reviewed_coverage.get("question_text_substantive") or 0),
        "reviewed_answer_text_nonplaceholder_count": int(reviewed_coverage.get("answer_text_nonplaceholder") or 0),
        "question_image_card_count": sum(1 for record in records if record["visual"]["question_asset_count"] > 0),
        "solution_image_card_count": sum(1 for record in records if record["visual"]["solution_asset_count"] > 0),
        "question_solution_image_card_count": sum(
            1
            for record in records
            if record["visual"]["question_asset_count"] > 0 and record["visual"]["solution_asset_count"] > 0
        ),
        "semantic_visual_detail_card_count": sum(1 for record in records if record["visual"]["semantic_detail_count"] > 0),
        "manifest_registered_card_count": sum(1 for record in records if record["visual"]["manifest_record_count"] > 0),
        "visual_registration_counts": dict(sorted(registration_counts.items())),
        "visual_asset_coverage_counts": dict(sorted(asset_coverage_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "latest_formal_card_date": latest_date,
        "manifest_record_count": len(manifest.get("records", [])) if isinstance(manifest, dict) else 0,
        "manifest_sha256": sha256_file(MANIFEST_PATH) if MANIFEST_PATH.is_file() else "",
        "semantic_review_receipt_sha256": sha256_file(REVIEW_RECEIPT_PATH) if REVIEW_RECEIPT_PATH.is_file() else "",
        "historical_review_coverage_schema_version": str(
            historical_review_coverage.get("schema_version") or ""
        ).strip(),
        "unique_image_asset_count": len(unique_assets),
        "unique_image_asset_role_counts": dict(sorted(unique_asset_role_counts.items())),
        "physical_image_asset_count": len(all_physical_assets),
        "physical_image_asset_role_counts": dict(sorted(all_physical_role_counts.items())),
        "unbound_physical_image_asset_count": len(unbound_physical_assets),
        "ocr_image_assets_processed": int(ocr_validation.get("image_assets_processed") or 0),
        "ocr_total_recognized_characters": int(ocr_validation.get("total_recognized_characters") or 0),
        "ocr_processing_errors": int(ocr_validation.get("processing_errors") or 0),
        "all_cross_id_duplicate_question_asset_group_count": len(duplicate_question_groups),
        "cross_id_duplicate_question_asset_group_count": len(unresolved_duplicate_question_groups),
        "cards_in_cross_id_duplicate_question_asset_groups": len(
            {card_id for group in unresolved_duplicate_question_groups for card_id in group["card_ids"]}
        ),
    }
    graph: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "derived_evidence_graph",
        "formal_related_write": False,
        "relation_policy": "Co-membership is a navigational edge, not causal proof. Personal-error claims require personal_confirmed=true.",
        "semantic_review_receipt": project_relpath(REVIEW_RECEIPT_PATH),
        "semantic_review_batches": semantic_review_batch_descriptors,
        "summary": summary,
        "taxonomy_edges": taxonomy_edges,
        "action_gap_edges": action_edges,
        "observed_breakpoint_edges": breakpoint_edges,
        "question_asset_duplicate_groups": duplicate_question_groups,
        "semantic_review_relation_decisions": sorted(
            semantic_review_relation_decisions,
            key=lambda item: (
                str(item.get("source_card_id") or ""),
                str(item.get("target_card_id") or ""),
                str(item.get("decision") or ""),
            ),
        ),
        "unbound_physical_image_assets": unbound_physical_assets,
        "cards": records,
    }
    canonical = json.dumps(graph, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    graph["source_state_sha256"] = sha256_bytes(canonical.encode("utf-8"))
    return graph


def markdown_escape(value: Any) -> str:
    text = str(value or "").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text.replace("|", "\\|")


def local_open_link(card_id: str, label: str | None = None) -> str:
    return f"[{markdown_escape(label or card_id)}](http://127.0.0.1:8765/open/{card_id})"


def compact_card_links(card_ids: list[str], limit: int = 8) -> str:
    shown = card_ids[:limit]
    links = "、".join(local_open_link(card_id) for card_id in shown)
    if len(card_ids) > limit:
        links += f" 等 {len(card_ids)} 张"
    return links or "—"


def render_graph_markdown(graph: dict[str, Any]) -> str:
    summary = graph["summary"]
    latest_date = summary["latest_formal_card_date"] or "2026-07-22"
    lines = [
        "---",
        "wiki_id: MATHWIKI-SYNTHESIS-002",
        "type: evidence_graph",
        "title: 知识点与错因证据图谱",
        "subject: 数学一",
        "knowledge:",
        "  - 知识点错因连线",
        "  - 错因证据分层",
        "  - 视觉证据覆盖",
        "source_refs:",
        "  - 错题知识网络/错题卡/",
        "  - 错题知识网络/可视化错题详情/manifest.json",
        "  - 错题知识网络/assets/visual_wrong_questions/",
        "  - 错题知识网络/wiki/synthesis/MATHWIKI-SYNTHESIS-002_语义复核边界回执.json",
        "  - 错题知识网络/wiki/review/MATHWIKI-REVIEW-*_全库逐题语义复核第*批*题.json",
        "status: active",
        f"last_updated: {latest_date}",
        "---",
        "",
        "# 知识点与错因证据图谱",
        "",
        "## 定位",
        "",
        "本页是全量正式错题卡的派生证据图。它把同一张题卡中的知识点、错因标签和动作断点连起来，同时保留题目正文、解析正文、视觉详情与图片资产的覆盖状态。正式错题卡仍是唯一事实源。",
        "",
        "这里的连线表示同题共现和复盘导航，不自动表示因果。只有 `personal_confirmed=true` 的记录才可称为用户已确认的个人错因；历史字段、解析推导和待确认内容分别展示，不混入该口径。",
        "",
        "本派生图本身不写回正式卡的 `related` 字段；逐批已经授权并完成的关系变更以对应正式收口回执为准。",
        "",
        "## 全库覆盖",
        "",
        "| 检查项 | 数量 |",
        "|---|---:|",
        f"| 正式错题卡 | {summary['formal_card_count']} |",
        f"| 正式知识点节点 | {summary['formal_knowledge_node_count']} |",
        f"| 可参与派生边的知识点节点 | {summary['edge_knowledge_node_count']} |",
        f"| 可用错因节点 | {summary['error_cause_node_count']} |",
        f"| 知识点—错因分类边 | {summary['taxonomy_edge_count']} |",
        f"| 知识点—动作断点边 | {summary['action_edge_count']} |",
        f"| 知识点—具体失败动作边 | {summary['breakpoint_edge_count']} |",
        f"| 正文有题目段落文本 | {summary['formal_question_text_count']} |",
        f"| 经语义规则判为实质题目文本 | {summary['reviewed_question_text_substantive_count']} |",
        f"| 正文有解析/断点段落文本 | {summary['formal_analysis_text_count']} |",
        f"| 经语义规则判为非占位答案文本 | {summary['reviewed_answer_text_nonplaceholder_count']} |",
        f"| 有题图的正式卡 | {summary['question_image_card_count']} |",
        f"| 有解析图的正式卡 | {summary['solution_image_card_count']} |",
        f"| 同时有题图和解析图 | {summary['question_solution_image_card_count']} |",
        f"| 详情页存在分析性文字 | {summary['semantic_visual_detail_card_count']} |",
        f"| 旧逐题复核与当前文件 SHA 完全一致 | {summary['target_level_review_exact_sha_carry_forward_count']} |",
        f"| 字段级语义未漂移、可暂时承接旧复核 | {summary['target_level_review_field_level_carry_forward_candidate_count']} |",
        f"| 当前仍缺逐题语义复核 | {summary['target_level_semantic_review_gap_count']} |",
        f"| 第一批逐题语义复核冻结输入 | {summary['target_level_review_first_batch_count']} |",
        f"| 本轮哈希绑定逐题复核批次 | {summary['semantic_review_batch_count']} |",
        f"| 本轮已逐题核完 | {summary['semantic_review_campaign_verified_card_count']} |",
        f"| 本轮来源变化后待重核 | {summary['semantic_review_campaign_stale_card_count']} |",
        f"| 本轮全库剩余待逐题核对 | {summary['semantic_review_campaign_remaining_card_count']} |",
        f"| 本轮已核物理图片路径 | {summary['semantic_review_campaign_physical_asset_path_count']} |",
        f"| 本轮已核唯一图片内容 | {summary['semantic_review_campaign_unique_asset_count']} |",
        f"| 本轮关系裁决 | {summary['semantic_review_relation_decision_count']} |",
        f"| 排除错绑与缺口后的有效题面或重述 | {summary['effective_question_evidence_count']} |",
        f"| 排除错绑与缺口后的视觉解答证据 | {summary['visual_solution_evidence_count']} |",
        f"| 已进入 manifest 的正式卡 | {summary['manifest_registered_card_count']} |",
        f"| 语义身份阻断卡 | {summary['semantic_edge_blocked_card_count']} |",
        f"| 需继续细化知识点的卡 | {summary['knowledge_needs_refinement_card_count']} |",
        f"| 已扫描的物理图片资产 | {summary['physical_image_asset_count']} |",
        f"| 已绑定到正式卡的唯一图片资产 | {summary['unique_image_asset_count']} |",
        f"| 尚未绑定到正式卡的物理图片资产 | {summary['unbound_physical_image_asset_count']} |",
        f"| OCR 处理图片 | {summary['ocr_image_assets_processed']} |",
        f"| OCR 识别字符 | {summary['ocr_total_recognized_characters']} |",
        f"| OCR 处理错误 | {summary['ocr_processing_errors']} |",
        f"| 跨编号重复题图簇 | {summary['cross_id_duplicate_question_asset_group_count']} |",
        f"| 涉及重复题图簇的正式卡 | {summary['cards_in_cross_id_duplicate_question_asset_groups']} |",
        "",
        "## 错因证据分层",
        "",
        "| 证据层 | 卡片数 | 可否直接称为个人错因 |",
        "|---|---:|---|",
    ]
    for tier in sorted(EVIDENCE_TIER_LABELS, key=lambda item: EVIDENCE_TIER_ORDER[item]):
        count = summary["evidence_tier_counts"].get(tier, 0)
        allowed = "可以" if tier == "confirmed_personal" else "不可以，需保留来源边界"
        lines.append(f"| {EVIDENCE_TIER_LABELS[tier]} | {count} | {allowed} |")
    lines.extend(
        [
            "",
            "## 有个人错因证据支撑的精细同卡共现",
            "",
            "下表只保留至少一张 `personal_confirmed=true` 且未被身份阻断的卡，并优先显示精细知识点与具体错因标签。它表示该卡存在用户确认的具体失败，同时这些标签在同卡出现；不表示用户逐项确认了每个标签，更不表示知识点导致了错因。",
            "",
            "| 知识点 | 错因 | 已确认卡 | 未阻断卡 | 证据入口 |",
            "|---|---|---:|---:|---|",
        ]
    )
    precise_edges = [
        edge
        for edge in graph["taxonomy_edges"]
        if edge["confirmed_personal_count"] > 0 and edge["knowledge_specific"] and edge["error_cause_specific"]
    ]
    if not precise_edges:
        lines.append("| — | — | 0 | 0 | — |")
    for edge in precise_edges[:80]:
        lines.append(
            "| {knowledge} | {error} | {confirmed} | {total} | {cards} |".format(
                knowledge=markdown_escape(edge["knowledge"]),
                error=markdown_escape(edge["error_cause"]),
                confirmed=edge["confirmed_personal_count"],
                total=edge["eligible_card_count"],
                cards=compact_card_links(edge["confirmed_personal_cards"]),
            )
        )
    lines.extend(
        [
            "",
            "## 用户已确认的知识点—具体失败动作",
            "",
            "这一层不用宽泛错因标签代替行为证据，直接回到 `wrong_point` 与 `missed_action`。",
            "",
            "| 错题 | 精细知识点 | 已确认首断点 | 漏掉动作 | 下次第一动作 |",
            "|---|---|---|---|---|",
        ]
    )
    confirmed_records = [
        record
        for record in graph["cards"]
        if record["personal_confirmed"] and not record["semantic_edge_blocked"]
    ]
    for record in confirmed_records:
        knowledge_text = "、".join(record["fine_knowledge"] or record["edge_knowledge"])
        lines.append(
            "| {card} | {knowledge} | {wrong} | {missed} | {expected} |".format(
                card=local_open_link(record["card_id"]),
                knowledge=markdown_escape(knowledge_text),
                wrong=markdown_escape(plain_markdown_excerpt(record["wrong_point"], 160)) or "—",
                missed=markdown_escape(plain_markdown_excerpt(record["missed_action"], 160)) or "—",
                expected=markdown_escape(plain_markdown_excerpt(record["expected_first_action"], 160)) or "—",
            )
        )
    lines.extend(
        [
            "",
            "## 高频知识点—动作断点",
            "",
            "| 知识点 | 动作断点 | 已确认卡 | 未阻断卡 | 入口 |",
            "|---|---|---:|---:|---|",
        ]
    )
    action_edges = [edge for edge in graph["action_gap_edges"] if edge["knowledge_specific"]]
    for edge in action_edges[:50]:
        lines.append(
            "| {knowledge} | {gap} | {confirmed} | {total} | {cards} |".format(
                knowledge=markdown_escape(edge["knowledge"]),
                gap=markdown_escape(edge["action_gap_type"]),
                confirmed=edge["confirmed_personal_count"],
                total=edge["eligible_card_count"],
                cards=compact_card_links(edge["eligible_cards"]),
            )
        )
    lines.extend(
        [
            "",
            "## 当前不能越过的证据边界",
            "",
            f"- 只有 {summary['personal_confirmed_card_count']} 张卡达到用户确认的个人错因口径；其他卡的标签仍可导航，但不能据此断言用户为什么做错。",
            f"- 历史 M192 的逐题目标级来源中，{summary['target_level_review_exact_sha_carry_forward_count']} 张与当前文件 SHA 完全一致；按字段级语义差异最多可暂时承接 {summary['target_level_review_field_level_carry_forward_candidate_count']} 张。后者只是保守的差异启发式，不是新的逐题复核 receipt。",
            f"- 历史缺口仍为 {summary['target_level_semantic_review_gap_count']} 张；本轮已对其中 {summary['semantic_review_campaign_verified_card_count']} 张完成题面、答案、解析和当前图片哈希绑定复核，故历史缺口中当前还剩 {summary['semantic_review_current_historical_gap_remaining_count']} 张。自动审计、OCR 和图片可读性检查均不计入该完成口径。",
            f"- 本轮新复核活动以 831 张当前正式卡为总盘，已完成 {summary['semantic_review_campaign_verified_card_count']} 张，剩余 {summary['semantic_review_campaign_remaining_card_count']} 张；复核覆盖 {summary['semantic_review_campaign_physical_asset_path_count']} 个物理图片路径、{summary['semantic_review_campaign_unique_asset_count']} 个唯一图片内容。",
            f"- 有题图的正式卡为 {summary['question_image_card_count']} 张，有解析图的只有 {summary['solution_image_card_count']} 张；没有解析图的卡不能被描述为已经逐张核对了解析图片。",
            f"- manifest 已登记 {summary['manifest_registered_card_count']} 张正式卡。物理文件存在但登记漂移、身份疑似错配或缺图的对象已在逐题索引中单独标记。",
            f"- 已确认 {summary['semantic_edge_blocked_card_count']} 张卡存在题图身份或内容错位；这些卡仍保留在逐卡审计中，但已经从汇总连线计数中排除。",
            f"- 题面图片哈希发现 {summary['cross_id_duplicate_question_asset_group_count']} 个跨编号重复簇，涉及 {summary['cards_in_cross_id_duplicate_question_asset_groups']} 张卡；它们必须先判定为重复题、复发或身份合并，不能直接当普通相似关系。",
            "- 图片文件哈希与详情页语义复述是两种证据：前者证明资产被扫描，后者才提供可检索的解释文字。普通 OCR 也不能单独证明数学语义判断正确。",
            "- 所有视觉记录的 `semantic_review_status` 默认仍是 `not_proven`；没有绑定图片哈希的逐题语义复核 receipt，就不把自动扫描冒充成人工逐图结论。",
            "- 已由本轮 receipt 绑定当前正式卡、详情页与全部当前图片哈希的记录标为 `human_reviewed_current_hashes`；任一来源 SHA 或图片集合变化后会自动降为待重核。",
            "",
            "## 全量入口",
            "",
            "- 每张正式卡的知识点、错因、第一断点、正文覆盖、图片哈希和视觉登记状态：[[MATHWIKI-SYNTHESIS-003_逐题内容与视觉证据索引]]。",
            "- 全量机器可读边表与逐卡证据：`错题知识网络/wiki/synthesis/MATHWIKI-SYNTHESIS-002_知识点错因证据图谱.json`。",
            "- 语义阻断、视觉缺口与覆盖口径：`错题知识网络/wiki/synthesis/MATHWIKI-SYNTHESIS-002_语义复核边界回执.json`。",
            "- 本轮逐题题意、答案、解析、错因边界与关系裁决：`错题知识网络/wiki/review/` 下的全库逐题语义复核批次。",
            f"- 当前输入状态哈希：`{graph['source_state_sha256']}`。",
            "",
            "## 重建",
            "",
            "```bash",
            "python3 错题知识网络/scripts/build_knowledge_error_evidence_graph.py build",
            "python3 错题知识网络/scripts/build_knowledge_error_evidence_graph.py check",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def visual_cell(record: dict[str, Any]) -> str:
    visual = record["visual"]
    parts = [
        f"题图 {visual['question_asset_count']}",
        f"解析图 {visual['solution_asset_count']}",
        f"详情复述 {visual['semantic_detail_count']}",
        visual["registration_state"],
    ]
    if visual["warning_statuses"]:
        parts.append("/".join(visual["warning_statuses"]))
    return "；".join(parts)


def render_card_index_markdown(graph: dict[str, Any]) -> str:
    summary = graph["summary"]
    latest_date = summary["latest_formal_card_date"] or "2026-07-22"
    lines = [
        "---",
        "wiki_id: MATHWIKI-SYNTHESIS-003",
        "type: per_card_evidence_index",
        "title: 逐题内容与视觉证据索引",
        "subject: 数学一",
        "knowledge:",
        "  - 逐题证据覆盖",
        "  - 视觉证据",
        "  - 错因证据分层",
        "source_refs:",
        "  - 错题知识网络/错题卡/",
        "  - 错题知识网络/可视化错题详情/manifest.json",
        "  - 错题知识网络/wiki/synthesis/MATHWIKI-SYNTHESIS-002_语义复核边界回执.json",
        "  - 错题知识网络/wiki/review/MATHWIKI-REVIEW-*_全库逐题语义复核第*批*题.json",
        "status: active",
        f"last_updated: {latest_date}",
        "---",
        "",
        "# 逐题内容与视觉证据索引",
        "",
        "## 读法",
        "",
        "本页逐张列出当前正式卡中的知识点—错因连线，并区分个人错因证据、正文题目/解析覆盖、视觉资产覆盖、历史承接口径与本轮哈希绑定逐题复核状态。表中的“未确认”不等于标签一定错误，只表示当前证据不能把它直接写成用户个人错因。",
        "",
        f"输入状态哈希：`{graph['source_state_sha256']}`。详细图片路径、文件字节数、SHA-256、manifest 记录和完整边表见同目录 JSON。",
        "",
    ]
    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in graph["cards"]:
        by_subject[record["subject"] or "未分类"].append(record)
    for subject in sorted(by_subject):
        lines.extend(
            [
                f"## {subject}",
                "",
                "| 错题 | 章节 | 知识点 ⇄ 错因 | 具体断点 | 证据层 | 当前逐题复核 | 正文 | 视觉 | 待核对 |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
        )
        for record in by_subject[subject]:
            knowledge = "、".join(record["formal_knowledge"]) or "—"
            errors = "、".join(record["edge_error_causes"]) or "—"
            connection = f"{knowledge} ⇄ {errors}"
            breakpoint = plain_markdown_excerpt(record["wrong_point"] or record["missed_action"], 150) or "—"
            formal = "题目 {q}；解析 {a}".format(
                q="有" if record["formal_content"]["has_question_text"] else "缺",
                a="有" if record["formal_content"]["has_analysis_text"] else "缺",
            )
            issues = "、".join(record["issues"]) or "—"
            current_review_code = record["semantic_review"]["current_campaign"].get(
                "current_target_level_review_status", "not_reviewed_in_current_campaign"
            )
            if current_review_code == "not_reviewed_in_current_campaign":
                historical_code = record["semantic_review"].get(
                    "historical_target_level_review_status", "unclassified"
                )
                current_review = HISTORICAL_REVIEW_LABELS.get(
                    historical_code, HISTORICAL_REVIEW_LABELS["unclassified"]
                )
            else:
                current_review = CURRENT_REVIEW_LABELS.get(current_review_code, current_review_code)
            lines.append(
                "| {card} | {chapter} | {connection} | {breakpoint} | {tier} | {historical_review} | {formal} | {visual} | {issues} |".format(
                    card=local_open_link(record["card_id"]),
                    chapter=markdown_escape(record["chapter"]) or "—",
                    connection=markdown_escape(connection),
                    breakpoint=markdown_escape(breakpoint),
                    tier=markdown_escape(record["evidence_tier_label"]),
                    historical_review=markdown_escape(current_review),
                    formal=markdown_escape(formal),
                    visual=markdown_escape(visual_cell(record)),
                    issues=markdown_escape(issues),
                )
            )
        lines.append("")
    first_batch_records = [
        record for record in graph["cards"] if record["semantic_review"].get("first_review_batch") is True
    ]
    lines.extend(
        [
            "## 第一批 30 张逐题语义复核输入",
            "",
            "这批只冻结复核顺序，不授权修改正式卡或 `related`。其中身份裁决对象必须先确认题图、题面与正式 ID 是否一致。",
            "",
            "| 错题 | 入选依据 | 本轮状态 | 当前视觉 | 待核对 |",
            "|---|---|---|---|---|",
        ]
    )
    for record in first_batch_records:
        group_labels = [
            FIRST_REVIEW_BATCH_GROUP_LABELS.get(group, group)
            for group in record["semantic_review"].get("first_review_batch_groups", [])
        ]
        lines.append(
            "| {card} | {groups} | {status} | {visual} | {issues} |".format(
                card=local_open_link(record["card_id"]),
                groups=markdown_escape("、".join(group_labels) or "—"),
                status=markdown_escape(
                    CURRENT_REVIEW_LABELS.get(
                        record["semantic_review"]["current_campaign"].get(
                            "current_target_level_review_status", "not_reviewed_in_current_campaign"
                        ),
                        "—",
                    )
                ),
                visual=markdown_escape(visual_cell(record)),
                issues=markdown_escape("、".join(record["issues"]) or "—"),
            )
        )
    lines.extend(
        [
            "",
            "## 当前优先语义复核队列",
            "",
            "排序只用于补证据：第一批冻结输入、身份疑似错配、视觉登记漂移、题目/解析同时缺证据的卡优先。它不会自动改正式错因或关系。",
            "",
            "| 顺位 | 错题 | 分数 | 证据层 | 视觉状态 | 待核对 |",
            "|---:|---|---:|---|---|---|",
        ]
    )
    queue_candidates = [
        record
        for record in graph["cards"]
        if record["semantic_review"]["current_campaign"].get("current_target_level_review_status")
        != "batch_verified_current_assets"
        or record["semantic_review"]["current_campaign"].get("quality_findings")
    ]
    queue = sorted(
        queue_candidates,
        key=lambda record: (-record["semantic_review_priority"], record["card_id"]),
    )
    for index, record in enumerate(queue[:100], start=1):
        lines.append(
            "| {index} | {card} | {score} | {tier} | {visual} | {issues} |".format(
                index=index,
                card=local_open_link(record["card_id"]),
                score=record["semantic_review_priority"],
                tier=markdown_escape(record["evidence_tier_label"]),
                visual=markdown_escape(record["visual"]["registration_state"]),
                issues=markdown_escape("、".join(record["issues"]) or "—"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def semantic_review_batch_markdown_path(batch: dict[str, Any]) -> Path:
    source_path = PROJECT_ROOT / str(batch.get("_path") or "")
    return source_path.with_suffix(".md")


def render_semantic_review_batch_markdown(batch: dict[str, Any], graph: dict[str, Any]) -> str:
    by_card = {record["card_id"]: record for record in graph["cards"]}
    items = [item for item in batch.get("cards", []) if isinstance(item, dict)]
    records = [by_card[str(item.get("card_id") or "").strip()] for item in items]
    reviewed_unique_assets = {
        digest
        for record in records
        for digest in record["semantic_review"]["current_campaign"].get(
            "reviewed_unique_asset_sha256", []
        )
    }
    physical_asset_paths = sum(
        int(record["semantic_review"]["current_campaign"].get("physical_asset_path_count") or 0)
        for record in records
    )
    verified_count = sum(
        1
        for record in records
        if record["semantic_review"]["current_campaign"].get("current_target_level_review_status")
        == "batch_verified_current_assets"
    )
    quality_card_count = sum(
        1
        for record in records
        if any(
            str(finding.get("resolution_status") or "").strip() not in RESOLVED_FINDING_STATUSES
            for finding in record["semantic_review"]["current_campaign"].get("quality_findings", [])
        )
    )
    wiki_id = str(batch.get("wiki_id") or "MATHWIKI-REVIEW-BATCH").strip()
    title = str(batch.get("title") or "全库逐题语义复核批次").strip()
    guardrails = batch.get("guardrails") if isinstance(batch.get("guardrails"), dict) else {}
    formal_closeout = any(
        bool(guardrails.get(field))
        for field in ("formal_related_write", "formal_card_write", "formal_visual_write")
    )
    if formal_closeout:
        quality_boundary = (
            f"本批有 {quality_card_count} 张出现结构、身份、元数据或来源正文质量问题。"
            "证据充分且无歧义的修正已经正式收口；身份冲突、稳定 ID 合并或证据不足项仍保留为 needs_user，"
            f"详见 `{str(guardrails.get('formal_closeout_ref') or 'formal_closeout_receipt_missing')}`。"
        )
        relation_boundary = "关系裁决中已正式应用的变更以正式收口回执为准；未应用项仍是 SHADOW 建议。"
    else:
        quality_boundary = (
            f"本批有 {quality_card_count} 张出现结构、身份、元数据或来源正文质量问题。"
            "问题只进入派生回执与修复队列；当前 SHADOW 模式没有改正式卡的 `related`、错因字段或视觉详情正文。"
        )
        relation_boundary = "关系裁决是 SHADOW 建议，不授权写回正式 `related`。"
    lines = [
        "---",
        f"wiki_id: {wiki_id}",
        "type: target_level_semantic_review_batch",
        f"title: {title}",
        "subject: 数学一",
        "knowledge:",
        "  - 全库逐题复核",
        "  - 题图解析图核对",
        "  - 知识点错因连线",
        "source_refs:",
        "  - 错题知识网络/错题卡/",
        "  - 错题知识网络/可视化错题详情/",
        "  - 错题知识网络/assets/visual_wrong_questions/",
        f"  - {str(batch.get('_path') or '')}",
        "status: active",
        f"last_updated: {str(batch.get('reviewed_on') or '')}",
        "---",
        "",
        f"# {title}",
        "",
        "## 本批结论",
        "",
        f"本批共逐题核对 {len(items)} 张正式卡，当前哈希仍有效的完整复核为 {verified_count} 张；覆盖 {physical_asset_paths} 个物理图片路径与 {len(reviewed_unique_assets)} 个唯一图片内容。全库当前共 {graph['summary']['formal_card_count']} 张正式卡，本轮活动累计完成 {graph['summary']['semantic_review_campaign_verified_card_count']} 张，剩余 {graph['summary']['semantic_review_campaign_remaining_card_count']} 张。",
        "",
        quality_boundary,
        "",
        "## 证据边界",
        "",
        "- `verified` 表示题面、所问对象、答案、解析路线和当前全部图片内容已经逐一核对，并由正式卡 SHA、详情页 SHA 与图片 SHA-256 绑定。",
        "- 个人错因仍按 `confirmed_personal`、`legacy_unclassified`、`pending_user_confirmation` 和重复占位分别处理；读懂解析不能反推用户为什么做错。",
        "- 同一哈希的重复物理图片只视觉核对一次，但所有物理路径都纳入数量和集合一致性检查。",
        f"- {relation_boundary}",
        "",
        "## 批次总览",
        "",
        "| 错题 | 题目在问什么 | 知识点 | 答案 | 个人错因边界 | 质量发现 |",
        "|---|---|---|---|---|---|",
    ]
    for item, record in zip(items, records):
        campaign = record["semantic_review"]["current_campaign"]
        personal = campaign.get("personal_error", {})
        personal_text = "{status}：{breakpoint}".format(
            status=str(personal.get("evidence_status") or record["evidence_tier_label"]),
            breakpoint=str(personal.get("first_breakpoint") or "未确认具体个人错因"),
        )
        finding_codes = "、".join(
            str(finding.get("code") or "").strip()
            for finding in campaign.get("quality_findings", [])
            if str(finding.get("code") or "").strip()
        ) or "—"
        lines.append(
            "| {card} | {question} | {knowledge} | {answer} | {personal} | {findings} |".format(
                card=local_open_link(record["card_id"]),
                question=markdown_escape(campaign.get("asked_output") or campaign.get("question_summary")),
                knowledge=markdown_escape("、".join(campaign.get("knowledge_nodes", [])) or "—"),
                answer=markdown_escape(campaign.get("answer") or "—"),
                personal=markdown_escape(personal_text),
                findings=markdown_escape(finding_codes),
            )
        )
    lines.extend(["", "## 逐题复核", ""])
    for item, record in zip(items, records):
        campaign = record["semantic_review"]["current_campaign"]
        personal = campaign.get("personal_error", {})
        consistency = campaign.get("consistency", {})
        lines.extend(
            [
                f"### {record['card_id']} {record['title']}",
                "",
                f"- 题目：{campaign.get('question_summary') or '—'}",
                f"- 所问：{campaign.get('asked_output') or '—'}",
                f"- 知识点：{'；'.join(campaign.get('knowledge_nodes', [])) or '—'}",
                f"- 第一动作：{campaign.get('first_action') or '—'}",
                f"- 答案：{campaign.get('answer') or '—'}",
                f"- 个人错因边界：{personal.get('evidence_status') or record['evidence_tier']}；{personal.get('first_breakpoint') or '未确认具体个人错因'}",
                f"- 一致性：题图—解析 {consistency.get('question_solution') or '—'}；正式卡—图片 {consistency.get('formal_visual') or '—'}",
                "- 解析主线：",
            ]
        )
        for step in campaign.get("solution_outline", []):
            lines.append(f"  - {step}")
        findings = campaign.get("quality_findings", [])
        if findings:
            lines.append("- 质量发现：")
            for finding in findings:
                lines.append(
                    f"  - `{str(finding.get('code') or '')}`：{str(finding.get('finding') or '')}；建议：{str(finding.get('recommended_action') or '')}"
                )
        relations = campaign.get("relation_decisions", [])
        if relations:
            lines.append("- 关系裁决：")
            for decision in relations:
                lines.append(
                    f"  - {str(decision.get('target_card_id') or '')}：`{str(decision.get('decision') or '')}`；{str(decision.get('reason') or '')}"
                )
        lines.extend(
            [
                f"- 当前快照：`{campaign.get('snapshot_status')}`；正式卡 `{record['card_sha256']}`；唯一图片 {campaign.get('reviewed_unique_asset_count')} 个；物理路径 {campaign.get('physical_asset_path_count')} 个。",
                "",
            ]
        )
    lines.extend(
        [
            "## 重建与验收",
            "",
            "```bash",
            "python3 错题知识网络/scripts/build_knowledge_error_evidence_graph.py build",
            "python3 错题知识网络/scripts/build_knowledge_error_evidence_graph.py check",
            "python3 -m unittest tests.test_knowledge_error_evidence_graph",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def rendered_outputs(graph: dict[str, Any]) -> dict[Path, str]:
    outputs = {
        GRAPH_JSON_PATH: json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        GRAPH_MD_PATH: render_graph_markdown(graph),
        CARD_INDEX_MD_PATH: render_card_index_markdown(graph),
    }
    for batch in load_semantic_review_batches():
        outputs[semantic_review_batch_markdown_path(batch)] = render_semantic_review_batch_markdown(
            batch, graph
        )
    return outputs


def write_outputs(outputs: dict[Path, str]) -> None:
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def check_outputs(outputs: dict[Path, str]) -> list[str]:
    stale: list[str] = []
    for path, expected in outputs.items():
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            stale.append(project_relpath(path))
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "check"))
    args = parser.parse_args(argv)
    graph = build_graph()
    outputs = rendered_outputs(graph)
    if args.command == "build":
        write_outputs(outputs)
        print(
            json.dumps(
                {
                    "status": "built",
                    "source_state_sha256": graph["source_state_sha256"],
                    "summary": graph["summary"],
                    "outputs": [project_relpath(path) for path in outputs],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    stale = check_outputs(outputs)
    if stale:
        print(json.dumps({"status": "stale", "outputs": stale}, ensure_ascii=False, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "source_state_sha256": graph["source_state_sha256"],
                "outputs": [project_relpath(path) for path in outputs],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
