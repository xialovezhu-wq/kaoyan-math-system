#!/usr/bin/env python3
"""Recover local projections after a real commit, with opt-in replica publication."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
WRONGNET_SCRIPTS = ROOT / "错题知识网络/scripts"
if str(WRONGNET_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(WRONGNET_SCRIPTS))
import math_learning_state
import math_concept_index
import study_personalization_math
import math_runtime_paths

PRODUCTION_ROOT = ROOT
PUBLICATION_SCRIPT = math_runtime_paths.bridge_root(ROOT) / "study_publication.py"
RECEIPTS = Path("数学一回滚复习系统/正式提交后续")
COMPONENTS = ("local_refresh", "concept_index", "formula_projection", "concept_pages",
              "personal_record_scopes", "user_utterances", "retrieval_backend", "pending_memory",
              "global_vectors", "study_recipes")
SUCCESS = {"ready", "noop", "refreshed", "published"}
HEX = re.compile(r"[0-9a-f]{64}")
OPAQUE = re.compile(r"(?:MFI-CLOSE|SCORE|CONCEPT-REVIEW|MATH-PROFILE-MAINT|MATH-DERIVED|MATH-ENGINEERING)-[0-9a-f]{16,64}")
ERROR_CODES = {"ValueError", "RuntimeError", "OSError", "ImportError", "KeyError", "OperationalError",
               "publication_entry_unavailable", "local_personalization_unavailable",
               "formal_quality_generation_pending", "formula_asset_write_failed", "backend_config_invalid"}


def receipt_path(root, identity):
    return Path(root) / RECEIPTS / (hashlib.sha256(identity.encode()).hexdigest() + ".json")


def read_handoff(root, identity):
    path = receipt_path(root, identity)
    if path.is_symlink() or not path.is_file():
        return None
    data = json.loads(path.read_bytes())
    if (data.get("event_id") or data.get("maintenance_id")) != identity:
        raise ValueError("maintenance_receipt_identity_changed")
    return data


def native_generation(root):
    try:
        from contextlib import closing
        with closing(sqlite3.connect((Path(root) / math_concept_index.INDEX).resolve().as_uri()+"?mode=ro", uri=True)) as conn:
            return json.loads(conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def retrieval_required(root):
    import math_memory_backends as backends
    try:
        return backends._read_config(Path(root)).get("selected", "disabled") != "disabled"
    except backends.BackendError as exc:
        # An invalid installed configuration is unresolved, not an opt-out.
        return str(exc) != "backend_not_configured"
    except (OSError, ValueError, TypeError):
        return True


def _component_state(value):
    status = str(value.get("status", "unknown")).lower()
    if status in SUCCESS:
        return "published" if status == "published" else "ready"
    if status in {"disabled", "not_applicable", "isolated_no_publication"}:
        return "not_applicable"
    if status in {"not_requested", "stale", "failed", "unavailable", "unknown", "pending"}:
        return status
    return "pending" if status in {"started", "preparing", "prepared", "queued", "in_progress", "committed_quality_pending"} else "unknown"


def _safe_id(value):
    return value if isinstance(value, str) and OPAQUE.fullmatch(value) else None


def _safe_generation(value):
    return value if isinstance(value, str) and HEX.fullmatch(value) else None


def summarize_handoff(record, current_generation=None, *, publishing_snapshot=False):
    """Project an existing native receipt into bounded phase and recovery facts."""
    kind = record.get("handoff_kind")
    if kind not in {"postcommit", "semantic_maintenance", "engineering"}:
        kind = "unknown"
    identity = _safe_id(record.get("event_id") or record.get("maintenance_id"))
    generation = _safe_generation(record.get("native_generation"))
    required = [name for name in COMPONENTS if name in record.get("required_components", ())]
    optional = [name for name in COMPONENTS if name in record.get("optional_components", ()) and name not in required]
    stages = {}
    for name in COMPONENTS:
        value = record.get(name) or (record.get("refresh") if name == "concept_index" else {}) or {}
        status = _component_state(value) if value else ("unknown" if kind == "unknown" or name in required + optional
                                                         else "not_applicable")
        expected = _safe_generation(value.get("native_generation"))
        if status == "ready":
            if not expected or not current_generation:
                status = "unknown"
            elif expected != current_generation:
                status = "stale"
        stages[name] = row = {"status": status}
        if expected:
            row["native_generation"] = expected
        if own := _safe_generation(value.get("version")):
            row["component_version"] = own
        if status not in {"ready", "not_applicable", "not_requested"} and value.get("reason"):
            reason = value["reason"]
            row["error_code"] = reason if isinstance(reason, str) and reason in ERROR_CODES else "native_component_error"
    publication = record.get("publication", {})
    publish_status = _component_state(publication)
    publish_id = _safe_id(record.get("publication_event_id"))
    # The replica captures the pre-publication handoff. Its own published
    # identity and independent readback belong to the outer publication receipt.
    if publishing_snapshot:
        publish_status = "pending"
    unfinished = [name for name in required if stages[name]["status"] not in {"ready", "not_applicable"}]
    followup = {"postcommit": "resume_postcommit", "semantic_maintenance": "resume_maintenance"}.get(kind)
    actions = ([{"action": followup, "event_id": identity, "components": unfinished}]
               if unfinished and followup else [])
    if publish_status in {"pending", "failed", "stale", "unavailable"}:
        actions.append({"action": "resume_publication", "event_id": publish_id or identity})
    publish_row = {"status": publish_status, "event_id": publish_id}
    if publish_status not in {"published", "not_requested"} and publication.get("reason") and not publishing_snapshot:
        reason = publication["reason"]
        publish_row["error_code"] = reason if isinstance(reason, str) and reason in ERROR_CODES else "native_publication_pending"
    transaction = "accepted" if kind == "semantic_maintenance" else "not_applicable"
    return {"schema": "math-maintenance-summary-v1", "event_id": identity, "kind": kind,
            "semantic_transaction": {"status": transaction},
            "native_generation": generation, "formal": {"status": "committed" if kind == "postcommit" else
                "not_applicable" if kind in {"semantic_maintenance", "engineering"} else "unknown"},
            "components": stages, "required_components": required, "optional_components": optional,
            "previous_incomplete_phase_receipts": len(record.get("prior_phase_failures", [])),
            "required_status": "pending" if unfinished else "ready" if required else "unknown",
            "publication": publish_row, "recovery": {"formal_writer_replay": False, "actions": actions},
            "independent_readback": {"status": "not_requested" if publish_status == "not_requested" else "pending"}}


def save_handoff(root, record, previous=None):
    """Store phase readback beside the owning receipt, separate from study facts."""
    failures = list((previous or {}).get("prior_phase_failures", []))
    if previous:
        actual = {key: value for key in (*COMPONENTS, "publication")
                  if isinstance((value := previous.get(key)), dict) and _component_state(value) in
                  {"pending", "failed", "unavailable", "stale"}}
        if actual:
            attempt = {"native_generation": previous.get("native_generation"), "phases": actual}
            if attempt not in failures:
                failures.append(attempt)
    if failures:
        record["prior_phase_failures"] = failures
    record["maintenance_summary"] = summarize_handoff(record, native_generation(root))
    identity = record.get("event_id") or record["maintenance_id"]
    path = receipt_path(root, identity)
    math_learning_state.atomic_write(root, path, math_learning_state.canonical(record))
    return path


def bind_handoff(root, record, generation):
    record["native_generation"] = generation
    if not generation or native_generation(root) != generation:
        return
    for name in COMPONENTS:
        value = record.get(name)
        if name == "concept_index" and not value:
            value = record.get("refresh")
        if not value or _component_state(value) != "ready":
            continue
        actual = value.get("native_version") or value.get("source_version")
        if name in ("concept_index", "concept_pages"):
            actual = value.get("version")
        if name == "formula_projection":
            try:
                import math_formula_cards
                actual = ((math_formula_cards.pointer(root) or {}).get("native_bindings") or {}).get("bound_profile_version")
            except (OSError, ValueError):
                continue
        if actual is not None or name != "formula_projection":
            value["native_generation"] = actual or generation


def find_committed_event(root: Path, event_id: str) -> dict[str, Any]:
    import math_concept_review
    if event_id.startswith(math_concept_review.PREFIX):
        return math_concept_review.committed_event(root, event_id)
    path = root / ("数学一回滚复习系统/复习记录.jsonl" if event_id.startswith("SCORE-") else "数学一回滚复习系统/快速入库事件.jsonl")
    matches = [row for row in (json.loads(line) for line in path.read_text().split("\n") if line.strip()) if row.get("event_id") == event_id]
    if len(matches) != 1:
        raise ValueError("postcommit_event_not_unique")
    event = matches[0]
    if not event_id.startswith("SCORE-") and event.get("event_type") != "closeout":
        raise ValueError("postcommit_requires_score_or_formal_closeout")
    return event


def affected_ids(root: Path, event: dict[str, Any]) -> list[str]:
    if event.get("event_type") == "concept_review":
        # Related cards are reference material, not attempts to score/refresh.
        return []
    if event.get("event_type") == "closeout":
        identities = [row.get("formal_id") for row in event.get("formal_results", [])]
    else:
        identity = event.get("delivered_card_id")
        units_path = root / "数学一回滚复习系统/复习单元.json"
        units = json.loads(units_path.read_text()) if units_path.exists() else []
        matches = [u.get("关联错题ID") for u in units if u.get("复习单元ID") == event.get("unit_id")]
        anchor = matches[0] if len(matches) == 1 else None
        # A transfer can update the anchor's schedule and the delivered card's
        # actual history. Refresh both without attributing that attempt twice.
        identities = [identity or anchor, anchor]
    return sorted({str(identity) for identity in identities if math_learning_state.FORMAL_RE.fullmatch(str(identity or ""))})


def request_publication(*, subject: str, event_id: str, repo_root: Path) -> dict[str, Any]:
    # Existing test suites patch their data roots. They must never reach the
    # user's production publisher merely because the source module is real.
    if repo_root.resolve() != PRODUCTION_ROOT.resolve():
        return {"status": "ISOLATED_NO_PUBLICATION", "reason": "nonproduction_repository"}
    if not PUBLICATION_SCRIPT.is_file():
        return {"status": "PENDING", "reason": "publication_entry_unavailable"}
    name = "_math_shared_study_publication"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, PUBLICATION_SCRIPT)
        if spec is None or spec.loader is None:
            return {"status": "PENDING", "reason": "publication_entry_unavailable"}
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        previous_path = list(sys.path)
        try:
            sys.path.insert(0, str(PUBLICATION_SCRIPT.parent))
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
        finally:
            sys.path[:] = previous_path
    # This module's owning checkout passed the production guard above. Keep the
    # publisher and its worker bound to it even if the checkout was renamed.
    if hasattr(module, "SUBJECTS") and subject == "math":
        module.SUBJECTS["math"]["root"] = PRODUCTION_ROOT.resolve()
    return module.request_publication(subject=subject, event_id=event_id, repo_root=repo_root)


def refresh_formal_epoch(root: Path) -> None:
    """Pending captures must not invalidate teaching; committed closeouts must.

    Fingerprint the current complete committed set, so retrying an older event
    cannot move the marker back to an older state.
    """
    ledger = root / "数学一回滚复习系统/快速入库事件.jsonl"
    committed = [row for row in (json.loads(line) for line in ledger.read_text().split("\n") if line.strip())
                 if row.get("event_type") == "closeout"]
    encoded = math_learning_state.canonical(committed)
    data = math_learning_state.canonical({"schema_version": "math-formal-concept-epoch-v1",
                                         "closeout_count": len(committed),
                                         "closeouts_sha256": hashlib.sha256(encoded).hexdigest()})
    path = root / "错题知识网络/个人知识点索引/formal_commit_epoch.json"
    if not path.exists() or path.read_bytes() != data:
        math_learning_state.atomic_write(root, path, data)


def resume_formula_only(root: Path, event_id: str | None = None) -> dict[str, Any]:
    import math_formula_cards
    previous = None
    if event_id:
        find_committed_event(root, event_id)
        path = receipt_path(root, event_id)
        if path.is_file():
            previous = path.read_bytes()
    result = math_formula_cards.refresh(root)
    if previous is not None:
        record = json.loads(previous)
        prior = json.loads(previous)
        if record.get("event_id") != event_id:
            raise ValueError("formula_postcommit_receipt_identity_changed")
        record["formula_projection"] = result
        if result["status"] == "READY" and record.get("status") == "formula_projection_pending":
            publication = record.get("publication", {}).get("status")
            record["status"] = ("completed_local" if publication == "NOT_REQUESTED"
                                else "completed" if publication == "PUBLISHED" else "local_updated_cloud_pending")
        if path.read_bytes() != previous:
            raise ValueError("formula_postcommit_receipt_changed_retry_readback")
        if record.get("handoff_kind") == "postcommit" and result.get("status") == "READY":
            pointer = math_formula_cards.pointer(root) or {}
            record["formula_projection"]["native_generation"] = (pointer.get("native_bindings") or {}).get("bound_profile_version")
        save_handoff(root, record, prior)
        result = {**result, "postcommit_receipt_path": path.relative_to(root).as_posix(),
                  "maintenance_summary": record["maintenance_summary"]}
    return {**result, "formal_replay_allowed": False}


def run_after_commit(
    repo_root: Path | str,
    event_id: str,
    *,
    requester: Callable[..., dict[str, Any]] | None = None,
    refresh_only: bool = False,
    publish: bool = False,
    refresh_global_vectors: bool = False,
    refresh_all_profiles: bool = False,
) -> dict[str, Any]:
    """Call outside the subject writer/score locks, including on a score noop.

    Only an explicit publication request uses the separate publisher.
    """
    if refresh_only and publish:
        raise ValueError("postcommit_refresh_only_conflicts_with_publication")
    root = Path(repo_root).resolve()
    event = find_committed_event(root, event_id)
    if refresh_global_vectors and event.get("event_type") != "closeout":
        raise ValueError("global_vector_refresh_requires_formal_closeout")
    identities = affected_ids(root, event)
    closeout = event.get("event_type") == "closeout"
    required = ["local_refresh", "concept_index", "concept_pages", "personal_record_scopes", "user_utterances"]
    optional = []
    if event.get("event_type") in {"closeout", "concept_review"}:
        required.append("formula_projection")
    (required if closeout else optional).append("pending_memory")
    (required if retrieval_required(root) else optional).append("retrieval_backend")
    if refresh_global_vectors:
        required.append("global_vectors")
    record: dict[str, Any] = {"schema_version": "math-postcommit-v1", "event_id": event_id, "formal_ids": identities,
                              "handoff_kind": "postcommit", "required_components": required, "optional_components": optional}
    path = receipt_path(root, event_id)
    try:
        previous = json.loads(path.read_bytes()) if path.is_file() else None
    except (OSError, ValueError):
        previous = None
    if previous and previous.get("event_id") != event_id:
        raise ValueError("postcommit_receipt_identity_changed")
    record["publication"] = {"status": "NOT_REQUESTED",
                             "reason": "explicit_refresh_only" if refresh_only else "explicit_publication_required"}
    try:
        local = math_learning_state.refresh_states(root, identities)
        record["local_refresh"] = local
        if event.get("event_type") == "closeout":
            refresh_formal_epoch(root)
        concept_index = math_concept_index.build_index(
            root, affected_ids=identities, force_full=refresh_all_profiles)
        if concept_index.get("status") not in {"ready", "noop"}:
            raise ValueError("concept_index_not_ready")
        record["concept_index"] = {key: concept_index.get(key) for key in
                                   ("status", "version", "index_path", "concept_count", "record_count",
                                    "projection_mode", "recomputed_concept_count", "retained_concept_count", "full_reason", "table_deltas")}
        if event.get("event_type") in {"closeout", "concept_review"}:
            try:
                import math_formula_cards
                record["formula_projection"] = math_formula_cards.refresh(root)
            except (ImportError, OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error,
                    subprocess.SubprocessError) as exc:
                record["formula_projection"] = {"status": "PENDING", "reason": str(exc),
                                                "formal_replay_allowed": False}
        import math_concept_review
        record["concept_pages"] = math_concept_review.refresh_pages(
            root, concept_keys=concept_index.get('recomputed_concept_keys'))
        try:
            import math_memory_record_scopes
            record['personal_record_scopes'] = math_memory_record_scopes.refresh(root, concept_index['version'])
        except (ImportError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
            record['personal_record_scopes'] = {'status':'pending','reason':type(exc).__name__,
                                               'formal_replay_allowed':False}
        try:
            import math_memory_utterances
            record['user_utterances'] = math_memory_utterances.refresh(root, concept_index['version'])
        except (ImportError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
            record['user_utterances'] = {'status':'pending','reason':type(exc).__name__,
                                        'formal_replay_allowed':False}
        try:
            import math_memory_backends
            record['retrieval_backend'] = math_memory_backends.refresh_selected(root,
                version=concept_index['version'],
                changed_concept_keys=concept_index.get('recomputed_concept_keys'))
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            record['retrieval_backend'] = {'status':'pending','reason':str(exc),'formal_replay_allowed':False}
        if refresh_global_vectors:
            try:
                import math_memory_global_vectors
                record["global_vectors"] = math_memory_global_vectors.refresh(
                    root, event_id=event_id, version=concept_index["version"])
            except (ImportError, OSError, ValueError, RuntimeError, KeyError, sqlite3.Error) as exc:
                record["global_vectors"] = {"status": "pending", "reason": str(exc),
                                            "source_version": concept_index["version"],
                                            "formal_replay_allowed": False}
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        if "local_refresh" not in record:
            record["local_refresh"] = {"status": "failed", "reason": str(exc)}
        phase = "concept_pages" if "concept_index" in record else "concept_index"
        record[phase] = {"status": "failed", "reason": str(exc)}
        if publish:
            record["publication"] = {"status": "PENDING", "reason": "local_personalization_unavailable"}
        if refresh_global_vectors:
            record["global_vectors"] = {"status": "pending", "reason": "local_personalization_unavailable"}
    # Pending evidence has a separate freshness contract.  Its recovery cannot
    # replay or invalidate the already committed score/formal transaction.
    try:
        import math_memory_pending
        record['pending_memory'] = math_memory_pending.refresh_pending(root)
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        record['pending_memory'] = {'status':'pending','reason':str(exc),'formal_replay_allowed':False}
    local_ready = (record["local_refresh"]["status"] == "refreshed"
                   and record["concept_index"]["status"] in {"ready", "noop"}
                   and record.get("concept_pages", {}).get("status") != "failed")
    generation = record["concept_index"].get("version")
    old_vectors = (previous or {}).get("global_vectors")
    if not refresh_global_vectors and old_vectors and old_vectors.get("source_version") == generation:
        record["global_vectors"] = dict(old_vectors)
        optional.append("global_vectors")
    bind_handoff(root, record, generation)
    if publish and local_ready:
        try:
            identity = study_personalization_math.current_identity(root)
            if identity["status"] != "ready":
                raise ValueError("personalization_identity_not_ready")
            record["personalization"] = identity
            import math_formal_quality as quality
            if quality.active(root):
                published = {"status": quality.HOLD, "reason": "formal_quality_generation_pending"}
            else:
                publication_event_id = "MATH-DERIVED-" + math_concept_index.digest(
                    [event_id, identity["version"], identity["formal_version"], local.get("versions", {})])
                record["publication_event_id"] = publication_event_id
                record["publication"] = {"status": "PENDING"}
                record["status"] = "local_updated_cloud_pending"
                save_handoff(root, record, previous)
                published = (requester or request_publication)(
                    subject="math", event_id=publication_event_id, repo_root=root)
            if not isinstance(published, dict) or not isinstance(published.get("status"), str):
                raise ValueError("invalid_publication_result")
            record["publication"] = published
        except Exception as exc:
            record["publication"] = {"status": "PENDING", "reason": type(exc).__name__}
    status = record["publication"]["status"]
    if not local_ready:
        record["status"] = "local_refresh_pending"
    elif record.get("formula_projection", {}).get("status") == "PENDING":
        record["status"] = "formula_projection_pending"
    elif not publish:
        record["status"] = "completed_local"
    else:
        record["status"] = "completed" if status == "PUBLISHED" else "local_updated_cloud_pending"
    save_handoff(root, record, previous)
    return {**record, "postcommit_receipt_path": path.relative_to(root).as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--event-id")
    parser.add_argument("--formula-only", action="store_true",
                        help="Resume the formula/diagram projection without rewriting committed learning")
    publication = parser.add_mutually_exclusive_group()
    publication.add_argument("--refresh-only", action="store_true", help="Compatible spelling for the default local refresh")
    publication.add_argument("--publish", action="store_true", help="Request a replica only for an authorized shared or external handoff")
    parser.add_argument("--refresh-global-vectors", action="store_true",
                        help="Refresh the whole semantic catalog after final profile and archive readback")
    parser.add_argument("--refresh-all-profiles", action="store_true",
                        help="Recompute the full personal profile projection from current evidence")
    args = parser.parse_args()
    if not args.formula_only and not args.event_id:
        parser.error("--event-id is required unless --formula-only is selected")
    try:
        if args.formula_only:
            if args.publish or args.refresh_global_vectors or args.refresh_all_profiles:
                parser.error("--formula-only only resumes the local formula projection")
            value = resume_formula_only(Path(args.repo).resolve(), args.event_id)
        else:
            value = run_after_commit(args.repo, args.event_id, refresh_only=args.refresh_only, publish=args.publish,
                                     refresh_global_vectors=args.refresh_global_vectors,
                                     refresh_all_profiles=args.refresh_all_profiles)
    except (OSError, ValueError, KeyError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "unavailable", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(value, ensure_ascii=False))
    if args.formula_only:
        return 0 if value["status"] in {"READY", "NOT_APPLICABLE"} else 1
    local_ready = (value["local_refresh"]["status"] == "refreshed" and value["concept_index"]["status"] in {"ready", "noop"}
                   and value.get("concept_pages", {}).get("status") != "failed")
    vectors_ready = not args.refresh_global_vectors or value["global_vectors"]["status"] in {"ready", "noop"}
    formula_ready = value.get("formula_projection", {}).get("status") != "PENDING"
    return 0 if local_ready and vectors_ready and formula_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
