"""Register verified B/C sources and record actual learner outcomes.

Registration is not learning. All scores/corrections use the existing math
review ledger; delayed schedule advancement still belongs to the scorer.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable
from zipfile import ZipFile

import math_postcommit
import math_learning_state as state

SOURCE_SCHEMA = "math-review-source-v1"
SOURCE_SCHEMA_V2 = "math-review-source-v2"
OUTCOME_SCHEMA = "math-review-outcome-v1"
REPOSITORY = "YOUR_GITHUB_ACCOUNT/kaoyan-math"
BRIDGE_INBOX = Path("/Users/your-user/Documents/Study-Pro-Bridge/inbox")
BRIDGE_OUTBOX = Path("/Users/your-user/Documents/Study-Pro-Bridge/outbox")
RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ReviewError(ValueError):
    pass


def file_hash(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def shared_publisher():
    name = "_math_review_shared_publisher"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, math_postcommit.PUBLICATION_SCRIPT)
        if spec is None or spec.loader is None:
            raise ReviewError("publication_verifier_unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        # The shared publisher imports its sibling modules. Loading by file
        # location alone does not add that directory to Python's module path.
        publisher_dir = str(Path(math_postcommit.PUBLICATION_SCRIPT).resolve().parent)
        if publisher_dir not in sys.path:
            sys.path.insert(0, publisher_dir)
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


def default_verifier(root: Path, commit: str) -> dict[str, Any]:
    if root.resolve() != math_postcommit.PRODUCTION_ROOT.resolve():
        raise ReviewError("isolated_repository_requires_injected_verifier")
    return shared_publisher().verify_published("math", commit)


def read_source(root: Path, run_id: str) -> dict[str, Any]:
    if not RUN_RE.fullmatch(run_id):
        raise ReviewError("invalid_run_id")
    path = state.safe_file(root, root / "数学一回滚复习系统/复盘来源" / run_id / "source.json")
    record = json.loads(path.read_text())
    if not isinstance(record, dict):
        raise ReviewError("registered_source_must_be_object")
    content = {k: v for k, v in record.items() if k != "source_record_sha256"}
    if record.get("source_record_sha256") != state.digest(content):
        raise ReviewError("registered_source_hash_mismatch")
    if record.get("subject") != "math" or record.get("run_id") != run_id:
        raise ReviewError("registered_source_identity_mismatch")
    return record


def input_file(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ReviewError("review_file_must_be_absolute")
    path = Path(value)
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".json", ".jsonl", ".md", ".txt", ".pdf"} or path.name.startswith("."):
        raise ReviewError("unsupported_review_document_type")
    # macOS /var and /tmp are normal aliases; other supplied symlinks are not
    # accepted as artifact identities, even when their target happens to exist.
    for component in (path, *path.parents):
        if component.is_symlink() and str(component) not in {"/var", "/tmp"}:
            raise ReviewError("review_document_symlink_forbidden")
    path = path.resolve(strict=True)
    allowed = next((base.resolve() for base in (root, BRIDGE_INBOX) if path.is_relative_to(base.resolve())), None)
    if allowed is None:
        raise ReviewError("review_file_outside_subject_or_bridge_inbox")
    return state.safe_file(allowed, path)


def normalized_source_request(root: Path, document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Path]]:
    if document.get("schema_version") not in {SOURCE_SCHEMA, SOURCE_SCHEMA_V2} or document.get("subject") != "math":
        raise ReviewError("invalid_math_review_source")
    if document.get("project") not in {"B", "C"}:
        raise ReviewError("invalid_review_project")
    if document.get("repository") != REPOSITORY or document.get("branch") != "main":
        raise ReviewError("wrong_repository_or_branch")
    run_id = str(document.get("run_id") or "")
    if not RUN_RE.fullmatch(run_id):
        raise ReviewError("invalid_run_id")
    commit = str(document.get("source_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ReviewError("invalid_source_commit")
    target_date = date.fromisoformat(str(document.get("target_date"))).isoformat()
    questions = document.get("questions")
    if not isinstance(questions, list) or not questions or (document["project"] == "C" and len(questions) != 5):
        raise ReviewError("C_requires_exactly_five_real_questions" if document["project"] == "C" else "questions_missing")
    rows, files, identities = [], {}, set()
    for question in questions:
        if not isinstance(question, dict):
            raise ReviewError("question_must_be_object")
        identity = str(question.get("formal_id") or "")
        if not state.FORMAL_RE.fullmatch(identity) or identity in identities:
            raise ReviewError("invalid_or_duplicate_formal_id")
        identities.add(identity)
        row = {"formal_id": identity}
        for key in ("formal_card_sha256", "state_source_version"):
            if not HASH_RE.fullmatch(str(question.get(key) or "")):
                raise ReviewError("missing_or_invalid_" + key)
            row[key] = question[key]
        for role in ("question", "solution"):
            path = input_file(root, question.get(role + "_path"))
            digest = file_hash(path)
            relative = "files/" + digest + path.suffix.lower()
            row[role + "_file"] = relative
            row[role + "_sha256"] = digest
            files[relative] = path
        if document.get("schema_version") == SOURCE_SCHEMA_V2 and document["project"] == "C":
            anchor_id = str(question.get("anchor_id") or "")
            if not (state.FORMAL_RE.fullmatch(anchor_id) or re.fullmatch(r"MATH-CONCEPT-[0-9a-f]{24}", anchor_id)):
                raise ReviewError("C_v2_anchor_id_required")
            row["anchor_id"] = anchor_id
        row["public_value_reason"] = str(question.get("public_value_reason") or "")
        # Original rationale is retained privately. No unverified reason or
        # question image is automatically exposed during registration.
        row["question_surface_status"] = "question_surface_pending"
        row["selection_mode"] = "external_project_" + document["project"].lower()
        rows.append(row)
    basis = {}
    if document.get("schema_version") == SOURCE_SCHEMA_V2 and document["project"] == "C":
        supplied = document.get("selection_basis")
        if not isinstance(supplied, dict) or supplied.get("schema_version") != "warmup-candidate-bundle-v2" or not HASH_RE.fullmatch(str(supplied.get("candidate_bundle_sha256", ""))):
            raise ReviewError("C_v2_selection_basis_required")
        versions = supplied.get("concept_evidence_versions")
        if not isinstance(versions, list):
            raise ReviewError("C_v2_concept_evidence_versions_required")
        seen = set()
        for entry in versions:
            if not isinstance(entry, dict) or not re.fullmatch(r"MATH-CONCEPT-[0-9a-f]{24}", str(entry.get("concept_key", ""))) or entry["concept_key"] in seen or not HASH_RE.fullmatch(str(entry.get("point_source_version", ""))) or not isinstance(entry.get("source_refs"), list) or not entry["source_refs"]:
                raise ReviewError("C_v2_invalid_concept_evidence_version")
            seen.add(entry["concept_key"])
            for ref in entry["source_refs"]:
                if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not HASH_RE.fullmatch(str(ref.get("sha256", ""))):
                    raise ReviewError("C_v2_invalid_concept_source_ref")
        basis = {"selection_basis": supplied}
    return ({"schema_version": document["schema_version"], "subject": "math", "project": document["project"],
             "repository": REPOSITORY, "branch": "main", "run_id": run_id, "source_commit": commit,
             "target_date": target_date, "questions": rows, **basis}, files)


def validate_c_selection_basis(request: dict, bundle: dict, published_files: dict, *, check_published: bool = True) -> dict:
    """Validate only point versions that informed this selection, not unrelated points."""
    import warmup_v5
    points = {row["concept_key"]: row for row in bundle.get("concept_evidence", [])}
    selected = {row["formal_id"] for row in request["questions"]}
    relevant = {key for key, point in points.items() if selected.intersection(point.get("formal_ids", []))}
    basis = request.get("selection_basis")
    if not basis:
        if relevant:
            raise ReviewError("C_concept_evidence_newer_refresh_required:" + ",".join(sorted(relevant)))
        return {"concept_evidence_checked": True, "concept_keys": []}
    versions = {row["concept_key"]: row for row in basis["concept_evidence_versions"]}
    if not relevant.issubset(versions):
        raise ReviewError("C_concept_evidence_missing_refresh_required:" + ",".join(sorted(relevant - versions.keys())))
    anchors = warmup_v5.anchor_rows(bundle)
    for question in request["questions"]:
        anchor_id = question["anchor_id"]
        if anchor_id not in anchors or anchor_id == question["formal_id"]:
            raise ReviewError("C_anchor_not_due_or_not_transfer:" + anchor_id)
        if anchors[anchor_id].get("anchor_kind") == "concept_review" and anchor_id not in versions:
            raise ReviewError("C_selected_concept_evidence_missing:" + anchor_id)
    for key, entry in versions.items():
        point = points.get(key)
        if point is None or point["point_source_version"] != entry["point_source_version"]:
            raise ReviewError("C_concept_source_changed_refresh_required:" + key)
        refs = {ref["path"]: ref["sha256"] for event in point["events"] for ref in event["source_refs"]}
        provided = {ref["path"]: ref["sha256"] for ref in entry["source_refs"]}
        if refs != provided:
            raise ReviewError("C_concept_sources_incomplete:" + key)
        for path, sha in refs.items():
            if check_published and published_files.get(path, {}).get("sha256") != sha:
                raise ReviewError("C_concept_source_not_in_published_snapshot:" + path)
    return {"concept_evidence_checked": True, "concept_keys": sorted(versions),
            "selection_candidate_bundle_sha256": basis["candidate_bundle_sha256"]}


def import_source(root: Path, document: dict[str, Any], scheduler: Any, *, verifier: Callable[[str], dict[str, Any]] | None = None) -> dict[str, Any]:
    root = root.resolve()
    request, input_files = normalized_source_request(root, document)
    request_hash = state.digest(request)
    directory = root / "数学一回滚复习系统/复盘来源" / request["run_id"]
    if (directory / "source.json").exists():
        existing = read_source(root, request["run_id"])
        if existing.get("request_sha256") != request_hash:
            raise ReviewError("run_id_already_bound_to_different_source")
        return source_result(root, existing, "noop")
    proof = verifier(request["source_commit"]) if verifier else default_verifier(root, request["source_commit"])
    if (proof.get("verified") is not True or proof.get("status") != "PUBLISHED" or proof.get("subject") != "math"
            or proof.get("repository") != REPOSITORY or proof.get("branch") != "main"
            or proof.get("source_commit") != request["source_commit"]):
        raise ReviewError("source_commit_not_verified_for_math")
    manifest_path = Path(proof.get("resolved_manifest_path") or proof.get("manifest_path") or "")
    manifest = json.loads(manifest_path.read_text())
    files = {row["path"]: row for row in manifest.get("files", [])}
    for question in request["questions"]:
        identity = question["formal_id"]
        current = state.load_state(root, identity)
        card_entry = files.get(current["formal_card_path"], {})
        state_entry = files.get(f"错题知识网络/教学投影/{identity}/learning-state.json", {})
        if card_entry.get("sha256") != question["formal_card_sha256"]:
            raise ReviewError("formal_card_hash_not_in_published_snapshot:" + identity)
        if state_entry.get("state_source_version") != question["state_source_version"]:
            raise ReviewError("learning_state_version_not_in_published_snapshot:" + identity)
        if current["formal_card_sha256"] != question["formal_card_sha256"] or current["source_version"] != question["state_source_version"]:
            raise ReviewError("related_local_state_changed_since_source:" + identity)
        if request["project"] == "C":
            for role, names in (("question", {"question", "question_image"}), ("solution", {"solution", "solution_image", "explanation_image"})):
                allowed = [entry for entry in files.values() if identity in entry.get("formal_ids", [])
                           and (entry.get("role") in names or Path(entry["path"]).name.startswith((role + "_", "explanation_" if role == "solution" else "question_")))]
                # Some genuine old cards have a saved textual answer but no
                # separate solution image. Their exact verified formal-card
                # bytes are a private solution source, never a public question.
                if role == "solution" and question["solution_sha256"] == question["formal_card_sha256"]:
                    allowed.append(card_entry)
                if not any(entry.get("sha256") == question[role + "_sha256"] for entry in allowed):
                    raise ReviewError("C_surface_not_bound_to_published_original:" + identity + ":" + role)
        question["unit_id"] = (current.get("scheduling") or {}).get("复习单元ID")
    eligibility = None
    if request["project"] == "C":
        import warmup_v5
        bundle, _ = warmup_v5.build_candidate_bundle(current_date=date.fromisoformat(request["target_date"]), count=5, legacy=vars(scheduler))
        concept_proof = validate_c_selection_basis(request, bundle, files)
        eligible = {row["formal_id"]: row for row in bundle["eligible_candidates"]}
        for row in request["questions"]:
            if row["formal_id"] not in eligible or eligible[row["formal_id"]]["sha256"] != row["formal_card_sha256"]:
                raise ReviewError("C_question_ineligible_under_local_rules:" + row["formal_id"])
        if len({row["question_sha256"] for row in request["questions"]}) != 5:
            raise ReviewError("C_duplicate_question_surface")
        eligibility = {**concept_proof, "candidate_bundle_sha256": bundle["candidate_bundle_sha256"], "local_eligibility_checked": True,
                       "python_semantic_selection_performed": False, "native_reader_execution_claimed": False}
    queue_id = "WQ-" + state.digest({"source": request_hash, "kind": "external_project_c"})[:24] if request["project"] == "C" else None
    for row in request["questions"]:
        row["queue_item_id"] = "QI-" + state.digest({"run_id": request["run_id"], "formal_id": row["formal_id"]})[:20] if queue_id else None
    record = {**request, "request_sha256": request_hash, "queue_id": queue_id, "local_eligibility": eligibility,
              "publication_verification": {key: proof.get(key) for key in ("receipt_path", "manifest_sha256", "verified_at", "source_commit")},
              "registration_state": "SOURCE_REGISTERED_NOT_STUDIED", "learning_events_written": 0}
    record["source_record_sha256"] = state.digest(record)
    with scheduler.exclusive_file_lock(root / "数学一回滚复习系统/.复盘来源.lock"):
        if (directory / "source.json").exists():
            raise ReviewError("concurrent_source_registration_retry_same_request")
        for relative, source in input_files.items():
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != Path(relative).stem:
                raise ReviewError("input_file_changed_before_registration")
            state.atomic_write(root, directory / relative, data)
        state.atomic_write(root, directory / "source.json", state.canonical(record))
    return source_result(root, record, "recorded")


def source_result(root: Path, record: dict[str, Any], status: str) -> dict[str, Any]:
    return {"status": status, "subject": "math", "project": record["project"], "run_id": record["run_id"],
            "source_commit": record["source_commit"], "target_date": record["target_date"], "queue_id": record["queue_id"],
            "source_path": str(root / "数学一回滚复习系统/复盘来源" / record["run_id"] / "source.json"),
            "registration_state": "SOURCE_REGISTERED_NOT_STUDIED", "learning_events_written": 0,
            "questions": [{key: row[key] for key in ("formal_id", "queue_item_id", "question_surface_status", "selection_mode")} for row in record["questions"]]}


def show_source(root: Path, run_id: str, scheduler: Any, current_date: date) -> dict[str, Any]:
    """Expose C original questions, with one existing-ledger delivery event."""
    root = root.resolve()
    source = read_source(root, run_id)
    if source["project"] == "B":
        return {"status": "B_DOCUMENT_REQUIRES_LOCAL_QUESTION_SELECTION", "run_id": run_id,
                "source_path": str(root / "数学一回滚复习系统/复盘来源" / run_id / "source.json"),
                "reason": "B文档含个人依据与对照分析；本地先按文档确定当前题干，不将整行或rubric当题面。",
                "learning_events_written": 0, "delivery_events_written": 0}
    if current_date.isoformat() != source["target_date"]:
        raise ReviewError("C_display_target_date_mismatch")
    directory = root / "数学一回滚复习系统/复盘来源" / run_id
    public_path = directory / "questions.md"
    lines = ["数学学习前原题", "", f"日期：{source['target_date']}", "",
             f"来源：Project C；run {run_id}；已验证版本 {source['source_commit']}", ""]
    public_questions = []
    for index, row in enumerate(source["questions"], 1):
        path = state.safe_file(root, directory / row["question_file"])
        if file_hash(path) != row["question_sha256"]:
            raise ReviewError("registered_question_file_hash_mismatch:" + row["formal_id"])
        # A question's exact original bytes may be an image, PDF or text. The
        # solution file and private semantic rationale never enter this view.
        label = f"第 {index} 题 · {row['formal_id']} · 已核对的正式原题"
        lines.extend([label, ""])
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
            lines.extend([f"![{row['formal_id']} 题面](<{path}>)", ""])
        else:
            lines.extend([f"[打开原题](<{path}>)", ""])
        public_questions.append({"formal_id": row["formal_id"], "queue_item_id": row["queue_item_id"],
                                 "question_path": str(path), "question_sha256": row["question_sha256"]})
    text = "\n".join(lines)
    log = scheduler.WARMUP_LOG_PATH
    with scheduler.exclusive_file_lock(log.with_name(f".{log.name}.lock")):
        matches = [row for row in scheduler.load_warmup_logs() if row.get("queue_id") == source["queue_id"]]
        if len(matches) > 1 or (matches and matches[0].get("registered_source_sha256") != source["source_record_sha256"]):
            raise ReviewError("C_delivery_identity_conflict")
        if not matches:
            for row in source["questions"]:
                validate_current_basis(root, row)
            import warmup_v5
            bundle, _ = warmup_v5.build_candidate_bundle(current_date=current_date, count=5, legacy=vars(scheduler))
            validate_c_selection_basis(source, bundle, {}, check_published=False)
            eligible = {row["formal_id"]: row["sha256"] for row in bundle["eligible_candidates"]}
            if any(eligible.get(row["formal_id"]) != row["formal_card_sha256"] for row in source["questions"]):
                raise ReviewError("C_question_no_longer_eligible_at_actual_display")
            event = {"schema_version": "math-external-C-delivery-v1", "queue_id": source["queue_id"],
                     "date": source["target_date"], "mode": "external_project_c", "run_id": run_id,
                     "source_commit": source["source_commit"], "registered_source_sha256": source["source_record_sha256"],
                     "requested_count": 5, "learning_events_written": 0,
                     "selected": [{"id": row["formal_id"], "delivered_card_id": row["formal_id"],
                                   "queue_item_id": row["queue_item_id"], "unit_id": row["unit_id"],
                                   "selection_mode": "external_project_c", "card_source_version": row["formal_card_sha256"]}
                                  for row in source["questions"]]}
            state.atomic_write(root, public_path, text.encode())
            scheduler.append_jsonl_entry(log, event)
        elif not public_path.exists() or public_path.read_text() != text:
            raise ReviewError("C_existing_display_artifact_missing_or_changed")
    return {"status": "noop" if matches else "DISPLAY_READY", "run_id": run_id, "queue_id": source["queue_id"],
            "source_commit": source["source_commit"], "display_path": str(public_path), "questions": public_questions,
            "delivery_events_written": 0 if matches else 1, "learning_events_written": 0}


def normalize_outcome(root: Path, value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if value.get("schema_version") != OUTCOME_SCHEMA or value.get("subject") != "math":
        raise ReviewError("invalid_math_review_outcome")
    source = read_source(root, str(value.get("run_id") or ""))
    for key in ("project", "source_commit"):
        if value.get(key) != source[key]:
            raise ReviewError("outcome_source_identity_mismatch:" + key)
    matches = [row for row in source["questions"] if row["formal_id"] == value.get("formal_id")]
    if len(matches) != 1:
        raise ReviewError("question_not_in_registered_source")
    question = matches[0]
    for key in ("formal_card_sha256", "state_source_version"):
        if value.get(key) != question[key]:
            raise ReviewError("outcome_basis_mismatch:" + key)
    if source["project"] == "C" and (value.get("queue_id") != source["queue_id"] or value.get("queue_item_id") != question["queue_item_id"]):
        raise ReviewError("outcome_queue_identity_mismatch")
    day = date.fromisoformat(str(value.get("date"))).isoformat()
    if source["project"] == "C" and day != source["target_date"]:
        raise ReviewError("C_outcome_target_date_mismatch")
    score = value.get("score")
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 5:
        raise ReviewError("score_must_be_0_to_5")
    answer = value.get("user_answer_text")
    if not isinstance(answer, str) or not answer.strip():
        raise ReviewError("actual_user_answer_required")
    if value.get("evidence_origin") not in {"user_observed", "user_confirmed"}:
        raise ReviewError("actual_user_evidence_origin_required")
    hints = value.get("hint_dependency")
    if hints not in {"none", "l1", "l2", "l3", "l4", "l5", "direct_explanation", "mixed", "unknown"}:
        raise ReviewError("invalid_hint_dependency")
    independent = value.get("independent_correct")
    if not isinstance(independent, bool) or (independent and hints != "none") or (score >= 4 and independent is not True):
        raise ReviewError("score_and_independence_evidence_disagree")
    attempt = str(value.get("attempt_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", attempt):
        raise ReviewError("invalid_attempt_id")
    payload = {key: value[key] for key in ("subject", "project", "run_id", "source_commit", "formal_id", "formal_card_sha256", "state_source_version", "score", "user_answer_text", "hint_dependency", "independent_correct", "evidence_origin")}
    payload.update({"schema_version": OUTCOME_SCHEMA, "date": day, "attempt_id": attempt,
                    "correction_text": str(value.get("correction_text") or ""), "queue_id": source["queue_id"],
                    "queue_item_id": question["queue_item_id"], "registered_source_sha256": source["source_record_sha256"]})
    return payload, source, question


def validate_current_basis(root: Path, payload: dict[str, Any]) -> None:
    current = state.load_state(root, payload["formal_id"])
    if current["formal_card_sha256"] != payload["formal_card_sha256"] or current["source_version"] != payload["state_source_version"]:
        raise ReviewError("related_local_state_changed_before_outcome")


def capture_required(**identity: Any) -> dict[str, Any]:
    return {
        "status": "capture_required",
        "reason": "morning_review_uses_fast_capture_until_formal_intake",
        "next_action": "Use capture_current_math.py with the current question's complete conversation and queue/item; no score event is required. Stop after recorded/noop and continue the next prepared question.",
        "identity": {key: value for key, value in identity.items() if value is not None},
        "formal_write_count": 0, "score_write_count": 0,
        "new_learning_events": 0, "postcommit_started": False,
    }


def record_outcome(root: Path, value: dict[str, Any], scheduler: Any, *, formal_intake: bool = False) -> dict[str, Any]:
    if value.get("project") == "C" and not formal_intake:
        return capture_required(**{key: value.get(key) for key in ("run_id", "queue_id", "queue_item_id", "formal_id")})
    root = root.resolve()
    payload, source, question = normalize_outcome(root, value)
    payload_hash = state.digest(payload)
    canonical_attempt = "review:" + state.digest({"project": source["project"], "run_id": source["run_id"], "formal_id": payload["formal_id"], "attempt_id": payload["attempt_id"]})[:40]
    unit_id = question.get("unit_id")
    _, event_id = scheduler.score_attempt_identity(unit_id or payload["formal_id"], date.fromisoformat(payload["date"]), canonical_attempt)
    logs = scheduler.load_review_logs()
    existing = [event for event in logs if event.get("event_id") == event_id]
    if existing:
        if len(existing) != 1 or existing[0].get("review_outcome_sha256") != payload_hash:
            raise ReviewError("review_attempt_conflicts_with_saved_evidence")
        post = math_postcommit.run_after_commit(root, event_id)
        return {"status": "noop", "event_id": event_id, "postcommit": post, "new_learning_events": 0}
    if source["project"] == "C":
        deliveries = [row for row in scheduler.load_warmup_logs() if row.get("queue_id") == source["queue_id"]]
        if len(deliveries) != 1 or deliveries[0].get("registered_source_sha256") != source["source_record_sha256"]:
            raise ReviewError("C_requires_registered_original_question_delivery_before_scoring")
    units = scheduler.load_units()
    unit = next((item for item in units if item.get("复习单元ID") == unit_id), None)
    markers = [event for event in (unit or {}).get("评分事件历史", []) if event.get("event_id") == event_id]
    if markers and (len(markers) != 1 or markers[0].get("review_outcome_sha256") != payload_hash):
        raise ReviewError("review_attempt_conflicts_with_saved_unit_marker")
    recovering_score = bool(markers)
    if not recovering_score:
        validate_current_basis(root, payload)
    day = date.fromisoformat(payload["date"])
    due = scheduler.safe_parse_date(unit.get("下次复习日期")) if unit else None
    recurrence = scheduler.safe_parse_date(unit.get("最近复发日期")) if unit else None
    may_advance = bool(unit and due and day >= due and (recurrence is None or day > recurrence))
    if may_advance or recovering_score:
        args = argparse.Namespace(unit_id=unit_id, score=payload["score"], date=payload["date"], attempt_id=canonical_attempt,
                                  dry_run=False, review_outcome=payload, review_outcome_sha256=payload_hash,
                                  review_source_context=payload)
        # The existing scorer owns delay eligibility, state transitions,
        # idempotency and unit/log recovery. Its internal call releases locks.
        scheduler._cmd_score(args)
    else:
        with scheduler.exclusive_file_lock(scheduler.LOG_PATH.with_name(".延迟复习评分.lock")):
            existing = [event for event in scheduler.load_review_logs() if event.get("event_id") == event_id]
            if existing:
                if len(existing) != 1 or existing[0].get("review_outcome_sha256") != payload_hash:
                    raise ReviewError("review_attempt_conflicts_with_saved_evidence")
            else:
                validate_current_basis(root, payload)
                event = {"event_id": event_id, "attempt_id": canonical_attempt, "date": payload["date"], "unit_id": unit_id,
                         "delivered_card_id": payload["formal_id"], "score": payload["score"], "attempt_type": "review_document_check",
                         "advances_long_term": False, "coverage_resolves_active_gap": False, "long_term_success_increment": 0,
                         "review_outcome": payload, "review_outcome_sha256": payload_hash}
                scheduler.append_log(event)
    saved = [event for event in scheduler.load_review_logs() if event.get("event_id") == event_id]
    if len(saved) != 1 or saved[0].get("review_outcome_sha256") != payload_hash:
        raise ReviewError("review_outcome_readback_failed")
    post = math_postcommit.run_after_commit(root, event_id)
    return {"status": "recorded", "event_id": event_id, "run_id": source["run_id"], "source_commit": source["source_commit"],
            "advances_long_term": saved[0].get("advances_long_term", False), "new_learning_events": 1, "postcommit": post}


def advice_binding(root: Path, run_record_path: str, quick: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Bind the current Bridge run and actual advice bytes, not its mutable stage."""
    path = Path(run_record_path).resolve(strict=True)
    allowed = BRIDGE_OUTBOX.resolve() if root == math_postcommit.PRODUCTION_ROOT.resolve() else root
    state.safe_file(allowed, path)
    run = json.loads(path.read_text())
    if run.get("schema_version") != 1 or run.get("project") != "A" or run.get("subject") != "math":
        raise ReviewError("not_a_current_math_A_run")
    run_id = str(run.get("run_id") or "")
    if not RUN_RE.fullmatch(run_id):
        raise ReviewError("invalid_A_run_id")
    validation = run.get("validation") if isinstance(run.get("validation"), dict) else {}
    commit = run.get("source_commit")
    if (not re.fullmatch(r"[0-9a-f]{40}", str(commit or "")) or validation.get("source_commit") != commit
            or validation.get("subject_decision_required") is not True
            or validation.get("learning_events_written") != 0 or run.get("web_read_status") != "verified"):
        raise ReviewError("A_run_validation_incomplete")
    verified_at = str(validation.get("verified_at") or "")
    instant = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ReviewError("A_validation_time_requires_timezone")
    output = Path(run.get("output_dir") or "").resolve(strict=True)
    output_root = BRIDGE_INBOX.resolve() if root == math_postcommit.PRODUCTION_ROOT.resolve() else root
    archive = state.safe_file(output_root, output.parent / "download.zip")
    archive_hash = file_hash(archive)
    if archive_hash != run.get("download_sha256") or archive_hash != validation.get("download_sha256"):
        raise ReviewError("A_advice_zip_hash_mismatch")
    web = run.get("web_evidence") if isinstance(run.get("web_evidence"), dict) else {}
    web_path = Path(str(web.get("path") or "")).resolve(strict=True)
    if root == math_postcommit.PRODUCTION_ROOT.resolve():
        web_root = Path("/Users/your-user/Documents/Study-Pro-Bridge")
    else:
        web_root = root
    state.safe_file(web_root, web_path)
    if file_hash(web_path) != web.get("sha256"):
        raise ReviewError("A_web_evidence_hash_mismatch")
    with ZipFile(archive) as bundle:
        info = bundle.getinfo("advice.json")
        if info.file_size > 16 * 1024 * 1024:
            raise ReviewError("A_advice_json_exceeds_bounded_input")
        advice_raw = bundle.read(info)
    extracted = state.safe_file(output_root, output / "advice.json")
    if extracted.read_bytes() != advice_raw:
        raise ReviewError("A_extracted_advice_differs_from_download")
    advice = json.loads(advice_raw)
    items = advice.get("items") if isinstance(advice, dict) else None
    expected = {(str(row.get("package_id")), str(row.get("question_id"))) for row in run.get("input_questions", [])}
    actual = [(str(row.get("package_id")), str(row.get("question_id"))) for row in items] if isinstance(items, list) and all(isinstance(row, dict) for row in items) else []
    if not expected or len(actual) != len(set(actual)) or set(actual) != expected:
        raise ReviewError("A_advice_does_not_cover_exact_input_questions")
    package_rows = []
    for package in run.get("input_packages", []):
        package_id = str(package.get("package_id") or "")
        if not re.fullmatch(r"MATHPKG-[0-9a-f]+", package_id):
            raise ReviewError("A_requires_native_complete_package_identity")
        days = {str(row.get("study_date")) for row in run["input_questions"] if row.get("package_id") == package_id}
        if len(days) != 1:
            raise ReviewError("A_package_study_date_ambiguous")
        day = date.fromisoformat(next(iter(days))).isoformat()
        relative = f"数学一回滚复习系统/快速入库来源/{day}/{package_id}/manifest.json"
        native, manifest_path, _ = quick.validate_source_bundle_manifest(relative, "A.original_package")
        if native.get("canonical_sha256") != package.get("version") or native.get("package_id") != package_id:
            raise ReviewError("A_original_package_version_mismatch")
        package_rows.append({"package_id": package_id, "package_version": native["canonical_sha256"],
                             "manifest_path": relative, "manifest_sha256": file_hash(manifest_path),
                             "quick_zip_sha256": package.get("zip_sha256")})
    if {row["package_id"] for row in package_rows} != {pair[0] for pair in expected}:
        raise ReviewError("A_package_set_mismatch")
    binding = {"project": "A", "subject": "math", "run_id": run_id, "source_commit": commit,
               "run_record_path": str(path), "advice_zip_path": str(archive), "advice_zip_sha256": archive_hash,
               "advice_json_sha256": hashlib.sha256(advice_raw).hexdigest(), "validation_verified_at": verified_at,
               "web_evidence_sha256": web["sha256"], "packages": package_rows}
    return binding, items


def record_advice_decision(root: Path, payload: dict[str, Any], quick: Any) -> dict[str, Any]:
    root = root.resolve()
    with quick.exclusive_lock(root / "数学一回滚复习系统/.A建议裁决.lock"):
        result = _record_advice_decision(root, payload, quick)
    # Rejections and observed no-change decisions are durable adjudication,
    # without manufacturing a Capture, score or mastery event.
    try:
        publication = math_postcommit.request_publication(subject="math", event_id=result["publication_event_id"], repo_root=root)
    except Exception as exc:
        publication = {"status": "PENDING", "reason": type(exc).__name__}
    return {**result, "publication": publication}


def _record_advice_decision(root: Path, payload: dict[str, Any], quick: Any) -> dict[str, Any]:
    root = root.resolve()
    if payload.get("schema_version") != "math-web-advice-decision-v1":
        raise ReviewError("invalid_A_decision_schema")
    binding, items = advice_binding(root, str(payload.get("run_record_path") or ""), quick)
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not all(isinstance(row, dict) for row in decisions):
        raise ReviewError("A_decisions_must_be_array")
    expected = {(row["package_id"], row["question_id"]) for row in items}
    pairs = [(row.get("package_id"), row.get("question_id")) for row in decisions]
    if len(pairs) != len(set(pairs)) or set(pairs) != expected:
        raise ReviewError("A_decisions_require_every_exact_advice_pair")
    request_hash = state.digest({"binding": binding, "decisions": decisions})
    path = root / "数学一回滚复习系统/A建议裁决" / (binding["run_id"] + ".json")
    if path.exists():
        saved = verify_advice_decision(root, binding["run_id"], quick)
        if saved["request_sha256"] != request_hash:
            raise ReviewError("A_run_already_has_a_different_decision")
        return {**saved, "status": "noop", "decision_receipt_path": str(path)}
    ledger = quick.replay(quick.load_jsonl(quick.EVENTS_PATH))
    closed_after = datetime.fromisoformat(binding["validation_verified_at"].replace("Z", "+00:00"))
    package_by_id = {row["package_id"]: row for row in binding["packages"]}
    normalized = []
    publication_events = set()
    for decision in decisions:
        outcome = decision.get("outcome")
        reason = decision.get("local_reason")
        changed = decision.get("requires_formal_change")
        if outcome not in {"accepted", "modified", "rejected", "no_change"} or not isinstance(reason, str) or not reason.strip() or not isinstance(changed, bool):
            raise ReviewError("A_decision_requires_outcome_reason_and_explicit_effect")
        if changed and outcome not in {"accepted", "modified"}:
            raise ReviewError("rejected_or_no_change_cannot_claim_formal_write")
        row = {"package_id": decision["package_id"], "question_id": decision["question_id"],
               "outcome": outcome, "local_reason": reason, "requires_formal_change": changed}
        formal_id = decision.get("formal_id")
        if changed:
            closeout_id = decision.get("writer_closeout_id")
            closeout = ledger["closeouts"].get(closeout_id)
            if closeout is None or closeout_id in ledger.get("invalidated_closeouts", set()):
                raise ReviewError("A_change_requires_real_writer_closeout")
            closed_at = datetime.fromisoformat(str(closeout.get("closed_at") or "").replace("Z", "+00:00"))
            if closed_at.tzinfo is None or closed_at < closed_after:
                raise ReviewError("old_closeout_does_not_prove_this_A_advice_was_applied")
            native = quick.verify_formal_package(package_by_id[decision["package_id"]]["manifest_path"])
            if closeout_id not in native["closeout_ids"]:
                raise ReviewError("A_writer_not_bound_to_original_package")
            results = [item for item in closeout.get("formal_results", []) if item.get("formal_id") == formal_id]
            if len(results) != 1 or results[0].get("operation") == "unchanged":
                raise ReviewError("A_change_missing_unique_changed_formal_result")
            result = results[0]
            card = state.find_card(root, str(formal_id))
            if file_hash(card) != result.get("card_hash_after"):
                raise ReviewError("A_writer_after_hash_not_current")
            row.update({"formal_id": formal_id, "writer_closeout_id": closeout_id,
                        "writer_result": deepcopy(result)})
            publication_events.add(closeout_id)
        elif outcome in {"accepted", "modified", "no_change"}:
            card = state.find_card(root, str(formal_id or ""))
            observed = decision.get("observed_card_sha256")
            if observed != file_hash(card):
                raise ReviewError("A_no_change_requires_current_card_observation")
            row.update({"formal_id": formal_id, "observed_card_sha256": observed})
        normalized.append(row)
    record = {"schema_version": "math-web-advice-decision-receipt-v1", **binding, "request_sha256": request_hash,
              "decisions": normalized, "publication_event_ids": sorted(publication_events),
              "publication_event_id": "MATH-A-DECISION-" + request_hash[:32],
              "status": "LOCAL_DECISION_COMPLETE", "learning_events_written": 0, "formal_writes_by_this_command": 0}
    record["record_sha256"] = state.digest(record)
    if path.exists():
        raise ReviewError("concurrent_A_decision_retry_same_request")
    state.atomic_write(root, path, state.canonical(record))
    return {**record, "decision_receipt_path": str(path)}


def verify_advice_decision(root: Path, run_id: str, quick: Any) -> dict[str, Any]:
    if not RUN_RE.fullmatch(run_id):
        raise ReviewError("invalid_A_run_id")
    path = state.safe_file(root, root / "数学一回滚复习系统/A建议裁决" / (run_id + ".json"))
    saved = json.loads(path.read_text())
    if saved.get("record_sha256") != state.digest({k: v for k, v in saved.items() if k != "record_sha256"}):
        raise ReviewError("A_decision_record_hash_mismatch")
    binding, _items = advice_binding(root, saved["run_record_path"], quick)
    if any(saved.get(key) != value for key, value in binding.items()):
        raise ReviewError("A_current_run_or_advice_differs_from_saved_decision")
    ledger = quick.replay(quick.load_jsonl(quick.EVENTS_PATH))
    for decision in saved["decisions"]:
        identity = decision.get("writer_closeout_id")
        if identity and (identity not in ledger["closeouts"] or identity in ledger.get("invalidated_closeouts", set())):
            raise ReviewError("A_bound_writer_result_no_longer_trusted")
    return {**saved, "decision_receipt_path": str(path), "verified": True}
