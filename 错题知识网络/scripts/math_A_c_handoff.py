#!/usr/bin/env python3
"""Create a C handoff from a genuinely committed A batch, without inventing B."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = Path("/Users/your-user/Documents/Study-Pro-Bridge")
sys.path[:0] = [str(ROOT / "数学一回滚复习系统/scripts"), str(Path(__file__).resolve().parent), str(BRIDGE)]
import quick_intake as qi
import study_personalization_math
import math_enhancement_input
import study_publication
import study_bridge


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def create(args):
    if not re.fullmatch(r"A-BATCH-[A-Za-z0-9_.-]+", args.batch_id):
        raise ValueError("invalid_A_batch_id")
    batch_path = ROOT / "数学一回滚复习系统/A分包" / args.batch_id / "batch-plan.json"
    plan = json.loads(batch_path.read_bytes())
    if plan.get("batch_id") != args.batch_id:
        raise ValueError("A_batch_identity_mismatch")
    package_ids = {p for group in plan["groups"] for p in group["package_ids"]}
    with qi.exclusive_lock(qi.LOCK_PATH):
        state = qi.replay(qi.load_jsonl(qi.EVENTS_PATH))
    captures = {cid: cap for cid, cap in state["captures"].items()
                if (cap.get("conversation_package") or {}).get("package_id") in package_ids}
    if {cap["conversation_package"]["package_id"] for cap in captures.values()} != package_ids:
        raise ValueError("A_batch_capture_coverage_missing")
    if any(cid not in state["closed_by"] for cid in captures):
        raise ValueError("A_batch_not_fully_formalized")
    closeout_ids = sorted({state["closed_by"][cid] for cid in captures},
                         key=lambda key: (state["closeouts"][key].get("recorded_at", ""), key))
    closeouts = [state["closeouts"][key] for key in closeout_ids]
    formal_results = {row["formal_id"]: row for event in closeouts for row in event["formal_results"]}
    formal_ids = sorted(formal_results)
    for fid, row in formal_results.items():
        path, sha = qi.card_path_if_unique(fid)
        if path is None or str(path.relative_to(ROOT)) != row["card_path_after"] or sha != row["card_hash_after"]:
            raise ValueError("A_formal_card_changed_after_closeout:" + fid)
    profile = json.loads(args.profile_receipt.read_bytes())
    if profile.get("status") not in {"accepted", "noop"} or profile.get("event_ids") != closeout_ids:
        raise ValueError("A_profile_receipt_not_accepted_for_exact_closeouts")
    keys = profile.get("concept_keys", [])
    if not keys or len(keys) != len(set(keys)):
        raise ValueError("A_accepted_profile_keys_required")
    profiles = []
    for key in keys:
        path = ROOT / "错题知识网络/个人知识点索引/语义概况" / (key + ".json")
        value = json.loads(path.read_bytes())
        if value.get("status") != "accepted_semantic_update" or value.get("event_ids") != closeout_ids:
            raise ValueError("A_semantic_profile_not_bound_to_batch:" + key)
        profiles.append({k: value[k] for k in ["concept_key", "concept_name", "overview", "short_summary", "progress", "next_check"]})
    local = study_personalization_math.current_identity(ROOT)
    if local.get("status") != "ready":
        raise ValueError("A_handoff_personalization_not_ready")
    current = study_publication.verify_current("math")
    if current.get("status") != "PUBLISHED_CURRENT":
        raise ValueError("A_handoff_publication_not_current:" + json.dumps(current, ensure_ascii=False))
    if current.get("native_calculation_bindings", {}).get("status") != "matched":
        raise ValueError("A_handoff_native_C_bindings_not_current")
    commit = current["source_commit"]
    refs = []
    with tempfile.TemporaryDirectory(prefix="math-A-C-handoff-") as temp:
        snapshot = math_enhancement_input.PublishedSnapshot(BRIDGE, commit, None, None, Path(temp))
        expected = [(f"personalization/math/points/{key}.json", "accepted_personal_context") for key in keys]
        expected += [(row["card_path_after"], "A_formal_card") for row in formal_results.values()]
        for number, (relative, role) in enumerate(expected):
            if relative not in snapshot.known:
                raise ValueError("A_C_source_not_in_current_snapshot:" + relative)
            sha = snapshot.known[relative]["sha256"]
            snapshot.source(relative, sha, number)
            refs.append({"path": relative, "sha256": sha, "source_commit": commit, "role": role})
    target = date.fromisoformat(args.target_date)
    c_run_id = "C-A-" + target.strftime("%Y%m%d") + "-" + args.batch_id.rsplit("-", 1)[-1]
    baseline = date.fromisoformat(plan.get("cutoff_date", plan["through_date"]))
    if target <= baseline:
        raise ValueError("C_target_must_follow_A_cutoff")
    # Data freshness alone does not prove that the native C calculation runs.
    from study_mcp import LibraryStore
    reader = LibraryStore(BRIDGE)
    try:
        eligibility = reader.workflow("C", "math", target.isoformat(), source_commit=commit, limit=1)
    finally:
        reader.close()
    reason = "本次按用户要求由A正式入库结果直接交接C；本次未接收或执行B独立复盘，不补造B学习或审核事实。"
    last_event = closeout_ids[-1]
    binding_by_capture = {}
    for event in closeouts:
        for row in event["capture_results"]:
            if row["capture_event_id"] in captures:
                binding_by_capture[row["capture_event_id"]] = row["formal_id"]
    if set(binding_by_capture) != set(captures):
        raise ValueError("C_capture_formal_mapping_incomplete")
    question_rows = [{"capture_event_id": cid, "package_id": cap["conversation_package"]["package_id"],
        "study_date": cap["study_date"], "formal_id": binding_by_capture[cid],
        "formal_path": formal_results[binding_by_capture[cid]]["card_path_after"],
        "formal_event_id": state["closed_by"][cid]} for cid, cap in sorted(captures.items())]
    formal_readback = {"status": "verified", "event_id": last_event, "event_ids": closeout_ids,
        "capture_event_ids": sorted(captures), "package_ids": sorted(package_ids), "formal_ids": formal_ids,
        "formal_card_count": len(formal_ids), "question_mappings": question_rows}
    profile_receipt = {k: profile[k] for k in ["status", "event_id", "event_ids", "concept_keys", "profile_version"]}
    handoff = {"schema": "math-c-handoff-v1", "project": "C", "subject": "math", "source_project": "A",
        "run_id": c_run_id,
        "source_kind": "A_formal_batch", "source_batch_id": args.batch_id,
        "source_run_ids": [group["run_id"] for group in plan["groups"]],
        "source_session_id": args.session_id, "source_session_role": "formal_processing_task",
        "source_evidence_id": args.batch_id, "formal_event_id": last_event, "formal_event_ids": closeout_ids,
        "target_date": target.isoformat(), "source_commit": commit, "snapshot_id": current.get("snapshot_id", commit),
        "b_review": {"status": "not_performed", "scope": "this_handoff_workflow", "reason": reason},
        "formal_readback": formal_readback, "profile_receipt": profile_receipt,
        "personalization_version": local.get("version"), "profiles": profiles,
        "eligibility_readback": {"source_commit": commit, "target_date": target.isoformat(),
                                "result": eligibility.get("result"), "queue_imported": False},
        "latest_mcp_snapshot": current, "publication_current": current,
        "evidence_manifest": {"path": str(batch_path.relative_to(ROOT)), "sha256": digest(batch_path.read_bytes()),
                              "role": "original_A_input_batch_plan"},
        "constraints": {"questions": "existing_formal_cards_only", "answer_protection": True,
            "generated_B_questions_are_not_formal_cards": True, "do_not_score_source_or_generated_B_questions": True,
            "preserve_original_study_dates": True, "day_0_7_exclusion": True,
            "independent_correct_exclusion": True, "oldest_actual_activity_within_same_goal": True}}
    refs_doc = {"schema": "math-c-handoff-refs-v1", "latest_snapshot": current, "sources": refs}
    instructions = (BRIDGE / "web-projects/C/PROJECT_INSTRUCTIONS.txt").read_text()
    start = (f"# 项目C：{target.isoformat()} 数学次日五题\n\n"
        f"本次C任务run_id：{c_run_id}。返回包manifest使用此run_id，目标日期为{target.isoformat()}。\n\n"
        f"本次依据A正式入库与已更新个性化直接进入C。{reason}\n\n"
        f"已正式处理{len(captures)}条Capture、{len(formal_ids)}道题，更新{len(keys)}个知识点概况。"
        "本包是选题输入，不是已选出的五题，也不是一次B复盘。\n\n"
        "请按下面的现行C指令执行。先核对handoff.json与refs.json，再从最新MCP中选择五道合格真实旧题。"
        "本批刚学过的题只作为诊断锚点，仍受近期活动排除；不凭文件更新时间挑题。"
        "读取或生成失败时保留已完成内容、错误和续接位置。\n\n"
        "本地开始学习前预处理整组题目；逐题复用question-worker讲解和wrong-intake完整Capture。"
        "当场不评分或更新长期调度，保存后继续下一题，晚间再正式入库。\n\n"
        "## 当前项目C指令\n\n" + instructions + "\n\n## 本次个性化检验目标\n\n")
    for row in profiles:
        start += f"### {row['concept_name']}\n\n{row['short_summary']}\n\n下一检查：{row['next_check']}\n\n"
    files = {"START_HERE.md": start.encode(), "handoff.json": canonical(handoff), "refs.json": canonical(refs_doc)}
    raw_zip = io.BytesIO()
    with zipfile.ZipFile(raw_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    raw = raw_zip.getvalue()
    out = args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.read_bytes() != raw:
        raise ValueError("C_handoff_output_conflict")
    if not out.exists():
        out.write_bytes(raw)
    verified = study_bridge.inspect_c_handoff_archive(out)
    return {"status": "ready", "path": str(out.resolve()), "sha256": digest(raw), "bytes": len(raw),
        "source_project": "A", "batch_id": args.batch_id, "formal_event_ids": closeout_ids,
        "capture_count": len(captures), "formal_card_count": len(formal_ids), "concept_count": len(keys),
        "source_commit": commit, "target_date": target.isoformat(), "binding": verified,
        "run_id": c_run_id,
        "new_learning_event_count": 0, "selected_question_count": 0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch-id", required=True)
    p.add_argument("--profile-receipt", type=Path, required=True)
    p.add_argument("--session-id", required=True)
    p.add_argument("--target-date", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(create(args), ensure_ascii=False))


if __name__ == "__main__":
    main()
