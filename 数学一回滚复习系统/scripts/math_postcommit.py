#!/usr/bin/env python3
"""Recover local projections and request one publication after a real commit."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
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

PRODUCTION_ROOT = Path("/Users/your-user/Documents/kaoyan-math")
PUBLICATION_SCRIPT = Path("/Users/your-user/Documents/Study-Pro-Bridge/study_publication.py")


def find_committed_event(root: Path, event_id: str) -> dict[str, Any]:
    import math_concept_review
    if event_id.startswith(math_concept_review.PREFIX):
        return math_concept_review.committed_event(root, event_id)
    path = root / ("数学一回滚复习系统/复习记录.jsonl" if event_id.startswith("SCORE-") else "数学一回滚复习系统/快速入库事件.jsonl")
    matches = [row for row in (json.loads(line) for line in path.read_text().splitlines() if line.strip()) if row.get("event_id") == event_id]
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
    return module.request_publication(subject=subject, event_id=event_id, repo_root=repo_root)


def refresh_formal_epoch(root: Path) -> None:
    """Pending captures must not invalidate teaching; committed closeouts must.

    Fingerprint the current complete committed set, so retrying an older event
    cannot move the marker back to an older state.
    """
    ledger = root / "数学一回滚复习系统/快速入库事件.jsonl"
    committed = [row for row in (json.loads(line) for line in ledger.read_text().splitlines() if line.strip())
                 if row.get("event_type") == "closeout"]
    encoded = math_learning_state.canonical(committed)
    data = math_learning_state.canonical({"schema_version": "math-formal-concept-epoch-v1",
                                         "closeout_count": len(committed),
                                         "closeouts_sha256": hashlib.sha256(encoded).hexdigest()})
    path = root / "错题知识网络/个人知识点索引/formal_commit_epoch.json"
    if not path.exists() or path.read_bytes() != data:
        math_learning_state.atomic_write(root, path, data)


def run_after_commit(
    repo_root: Path | str,
    event_id: str,
    *,
    requester: Callable[..., dict[str, Any]] | None = None,
    refresh_only: bool = False,
) -> dict[str, Any]:
    """Call outside the subject writer/score locks, including on a score noop.

    The publication helper atomically marks pending and starts at most one
    deterministic child. It does not wait for network or run a model.
    """
    root = Path(repo_root).resolve()
    event = find_committed_event(root, event_id)
    identities = affected_ids(root, event)
    record: dict[str, Any] = {"schema_version": "math-postcommit-v1", "event_id": event_id, "formal_ids": identities}
    try:
        local = math_learning_state.refresh_states(root, identities)
        record["local_refresh"] = local
        if event.get("event_type") == "closeout":
            refresh_formal_epoch(root)
        concept_index = math_concept_index.build_index(root, affected_ids=identities)
        if concept_index.get("status") not in {"ready", "noop"}:
            raise ValueError("concept_index_not_ready")
        import math_concept_review
        record["concept_pages"] = math_concept_review.refresh_pages(root)
        # Keep the full inventory in the index, not in every score receipt.
        record["concept_index"] = {key: concept_index.get(key) for key in
                                   ("status", "version", "index_path", "concept_count", "record_count")}
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        if "local_refresh" not in record:
            record["local_refresh"] = {"status": "failed", "reason": str(exc)}
        record["concept_index"] = {"status": "failed", "reason": str(exc)}
        record["publication"] = {"status": "PENDING", "reason": "local_personalization_unavailable"}
    else:
        if refresh_only:
            record["publication"] = {"status": "NOT_REQUESTED", "reason": "explicit_refresh_only"}
        else:
            try:
                identity = study_personalization_math.current_identity(root)
                if identity["status"] != "ready":
                    raise ValueError("personalization_identity_not_ready")
                # Business identity stays immutable. A later archive/index version
                # gets a successor publication instead of a suppressed old request.
                publication_event_id = "MATH-DERIVED-" + math_concept_index.digest(
                    [event_id, identity["version"], identity["formal_version"], local.get("versions", {})])
                record["publication_event_id"] = publication_event_id
                record["personalization"] = identity
                published = (requester or request_publication)(subject="math", event_id=publication_event_id, repo_root=root)
                if not isinstance(published, dict) or not isinstance(published.get("status"), str):
                    raise ValueError("invalid_publication_result")
                record["publication"] = published
            except Exception as exc:
                # The durable score/closeout is already committed. Never turn
                # a network/startup failure into a replay of that fact.
                record["publication"] = {"status": "PENDING", "reason": type(exc).__name__}
    status = record["publication"]["status"]
    local_ready = (record["local_refresh"]["status"] == "refreshed"
                   and record["concept_index"]["status"] in {"ready", "noop"})
    record["status"] = "completed" if status == "PUBLISHED" else "local_updated_cloud_pending" if local_ready else "local_refresh_pending"
    name = hashlib.sha256(event_id.encode()).hexdigest() + ".json"
    path = root / "数学一回滚复习系统/正式提交后续" / name
    math_learning_state.atomic_write(root, path, math_learning_state.canonical(record))
    return {**record, "postcommit_receipt_path": path.relative_to(root).as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--refresh-only", action="store_true")
    args = parser.parse_args()
    try:
        value = run_after_commit(args.repo, args.event_id, refresh_only=args.refresh_only)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "unavailable", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(value, ensure_ascii=False))
    return 0 if value["local_refresh"]["status"] == "refreshed" and value["concept_index"]["status"] in {"ready", "noop"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
