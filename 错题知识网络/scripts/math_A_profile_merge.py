"""Bind an A profile consolidation to the original plan, staged returns and closeouts."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

import math_enhancement_input as stage
import math_workflow_storage as storage

PLAN = Path("数学一回滚复习系统/A分包")
LEDGER = Path("数学一回滚复习系统/快速入库事件.jsonl")
STRUCTURED = ("claims", "step_evidence", "teaching_preferences", "solution_connections")


def _read(root, path):
    path = Path(path)
    if root == storage.REPO:
        path = storage.ensure_cold_output(path)
    path = stage.require_file(path).resolve()
    # Hash and decode the same bytes even if an input is replaced concurrently.
    with path.open("rb") as stream:
        data = stream.read(stage.MAX_JSON_BYTES + 1)
    if len(data) > stage.MAX_JSON_BYTES:
        stage.fail("contribution_file_too_large", str(path))
    value = json.loads(data)
    if not isinstance(value, dict):
        stage.fail("profile_contribution_object_required", str(path))
    return path, value, hashlib.sha256(data).hexdigest()


def _inventory(root, batch_id, receipt_paths):
    if not isinstance(batch_id, str) or not stage.ID_RE.fullmatch(batch_id):
        stage.fail("invalid_topic_batch_binding")
    _, plan, plan_sha = _read(root, root / PLAN / batch_id / "batch-plan.json")
    if (plan.get("schema"), plan.get("batch_id")) != ("math-A-topic-batch-plan-v1", batch_id):
        stage.fail("invalid_profile_merge_plan")
    groups = {group["shard_id"]: group for group in plan["groups"]}
    packages = [p["package_id"] for group in groups.values() for p in group["input_packages"]]
    if (not groups or len(groups) != len(plan["groups"]) or not packages
            or any(not group["input_packages"] for group in groups.values())
            or len(set(packages)) != len(packages)):
        stage.fail("invalid_profile_merge_group_scope")
    receipts, points, gaps = {}, defaultdict(dict), {}
    for receipt_path in receipt_paths:
        path, receipt, receipt_sha = _read(root, receipt_path)
        binding = receipt.get("batch_binding") or {}
        shard = binding.get("shard_id")
        group = groups.get(shard)
        if (not group or shard in receipts or path.name != "receipt.json" or path.parent.name != group["run_id"] or
                receipt.get("schema_version") != stage.STAGE_SCHEMA or
                (receipt.get("subject"), receipt.get("project")) != ("math", "A") or
                receipt.get("profile_merge_required") is not True or
                binding.get("batch_id") != batch_id or binding.get("plan_sha256") != plan_sha or
                receipt.get("source_commit") != plan["source_commit"] or
                receipt.get("run_id") != group["run_id"] or
                receipt.get("input_packages") != group["input_packages"]):
            stage.fail("profile_contribution_receipt_scope_or_duplicate", shard)
        receipts[shard] = {"path": str(path), "sha256": receipt_sha}
        # Even a mapping-required return has locally bound contributions.
        # Keep its identity as a gap until the exact native prepared file exists.
        if receipt.get("status") != "prepared":
            gaps[shard] = receipt.get("status") or "receipt_not_prepared"
            continue
        profile_path, prepared, profile_sha = _read(root, path.parent / "prepared_profiles.json")
        file_root = path.parent.parent if receipt.get("artifact_storage") == "t9_workspace_v1" else root
        if (not any(row["sha256"] == profile_sha and (file_root / row["path"]).resolve() == profile_path
                    for row in receipt["staged_files"])
                or prepared.get("schema") != stage.PROFILE_SCHEMA
                or prepared.get("_deferred_batch_merge") != binding
                or receipt.get("prepared_profile_count") != len(prepared["updates"])):
            stage.fail("profile_contribution_prepared_bytes_changed", shard)
        for row in prepared["updates"]:
            key = row["concept_key"]
            if shard in points[key]:
                stage.fail("profile_contribution_duplicate_concept", [shard, key])
            points[key][shard] = row
    return plan_sha, groups, receipts, points, gaps


def _closeouts(root, groups):
    # Use the subject's replay contract so invalidated closeouts and a
    # different version of the same package cannot back the consolidation.
    sys.path.insert(0, str(storage.REPO / "数学一回滚复习系统/scripts"))
    try:
        import quick_intake as qi
    finally:
        sys.path.pop(0)
    state = qi.replay(qi.load_jsonl(root / LEDGER))
    packages = {p["package_id"]: p["version"] for group in groups.values() for p in group["input_packages"]}
    captures = defaultdict(set)
    for capture, row in state["captures"].items():
        package = row.get("conversation_package") or {}
        pid = package.get("package_id")
        if pid in packages and package.get("package_sha256") == packages[pid]:
            captures[pid].add(capture)
    selected = set().union(*captures.values())
    missing = sorted(pid for pid in packages if not captures[pid] or
                     not captures[pid] <= state["closed_by"].keys())
    event_ids = {state["closed_by"][cid] for cid in selected if cid in state["closed_by"]}
    extraneous = sorted(event_id for event_id in event_ids
                        if set(state["closeouts"][event_id]["capture_event_ids"]) - selected)
    return sorted(event_ids), missing, extraneous


def inspect(root, batch_id, receipt_paths):
    plan_sha, groups, receipts, points, gaps = _inventory(root, batch_id, receipt_paths)
    closeouts, pending, outside = _closeouts(root, groups)
    missing_shards = sorted(groups.keys() - receipts.keys())
    return {"status": "contributions_incomplete" if missing_shards or gaps else "contributions_ready",
            "binding": {"batch_id": batch_id, "plan_sha256": plan_sha, "receipts": receipts},
            "concept_shards": {key: sorted(rows) for key, rows in sorted(points.items())},
            "missing_shards": missing_shards, "unprepared_shards": gaps, "event_ids": closeouts,
            "packages_without_closeout": pending, "closeouts_outside_batch_scope": outside}


def validate(root, payload, *, event_ids=None):
    """Validate the existing author's merged rows. Never accept a shard as a writer."""
    binding = payload.get("batch_contributions")
    if binding is None:
        return {}
    from math_learning_profiles import digest
    if not isinstance(binding, dict) or set(binding) != {"batch_id", "plan_sha256", "receipts"}:
        stage.fail("invalid_profile_contribution_binding")
    receipts = binding["receipts"]
    if not isinstance(receipts, dict) or not all(isinstance(row, dict) and set(row) == {"path", "sha256"}
                                                 for row in receipts.values()):
        stage.fail("invalid_profile_contribution_receipt_refs")
    plan_sha, groups, actual, points, gaps = _inventory(
        root, binding["batch_id"], [row["path"] for row in receipts.values()])
    if plan_sha != binding["plan_sha256"] or actual != receipts:
        stage.fail("profile_contribution_binding_changed")
    if groups.keys() != actual.keys() or gaps:
        stage.fail("profile_contributions_incomplete", sorted((groups.keys() - actual.keys()) | gaps.keys()))
    rows = {row["concept_key"]: row for row in payload["updates"]}
    if not points.keys() <= rows.keys():
        stage.fail("profile_contribution_concepts_missing", sorted(points.keys() - rows.keys()))
    provenance = {}
    for key, contributions in points.items():
        row = rows[key]
        reviews = row.get("contribution_reviews") or {}
        if (not isinstance(reviews, dict) or set(reviews) != contributions.keys() or
                any(not isinstance(note, str) or not note.strip() for note in reviews.values())):
            stage.fail("profile_contribution_review_required", key)
        refs = {(r["path"], r["sha256"]) for r in row["source_refs"]}
        for shard, source in contributions.items():
            required = {(r["path"], r["sha256"]) for r in source["source_refs"]}
            if not required <= refs:
                stage.fail("profile_contribution_source_missing", [key, shard])
            # A changed or omitted structured assertion must be named and
            # reconciled explicitly. The original staged row remains pinned.
            removed = {field for field in STRUCTURED if any(
                value not in row.get(field, []) for value in source.get(field, []))}
            if removed and not all(field in reviews[shard] for field in removed):
                stage.fail("profile_contribution_structured_conflict", [key, shard, sorted(removed)])
        provenance[key] = {"batch_id": binding["batch_id"], "plan_sha256": plan_sha,
                           "shards": {shard: {"receipt_sha256": actual[shard]["sha256"],
                                              "contribution_sha256": digest(source)}
                                      for shard, source in sorted(contributions.items())}}
    if event_ids is not None:
        expected, pending, outside = _closeouts(root, groups)
        if pending or outside or set(expected) != set(event_ids):
            stage.fail("profile_contribution_closeout_union_required",
                       {"expected": expected, "pending_packages": pending, "outside_scope": outside})
    return provenance
