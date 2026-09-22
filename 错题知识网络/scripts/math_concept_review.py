"""Atomic, concept-anchored review sessions; never writes cards or Captures."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
from zoneinfo import ZoneInfo

SCHEMA = "concept-review-session-v1"
BASE = Path("数学一回滚复习系统/知识点复盘")
SESSIONS = BASE / "正式会话"
PAGES = Path("错题知识网络/个人知识点索引/知识点复盘")
PREFIX = "CONCEPT-REVIEW-"
CONCEPT_RE = re.compile(r"^MATH-CONCEPT-[0-9a-f]{24}$")
OUTCOMES = {"wrong", "independent_correct", "corrected_after_hint", "unresolved"}


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def event_id(session_id):
    return PREFIX + digest(["math", session_id])[:32]


def safe_path(root, path):
    root = Path(root).resolve()
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    if not path.is_relative_to(root):
        raise ValueError("concept_review_path_outside_repository")
    current = root
    for part in path.relative_to(root).parts:
        if part in {".", ".."}:
            raise ValueError("concept_review_unsafe_path")
        current /= part
        if current.is_symlink():
            raise ValueError("concept_review_symlink_forbidden")
    return path


def _text(value, name, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError("invalid_" + name)
    return value


def _timestamp(value, name):
    try:
        parsed = datetime.fromisoformat(_text(value, name).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("invalid_" + name) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(name + "_requires_timezone")
    return parsed


def _catalog(root):
    import math_concept_index as native
    import study_personalization_math as snapshot
    if snapshot.current_identity(root)["status"] != "ready":
        raise ValueError("concept_review_requires_current_index_run_refresh")
    with closing(sqlite3.connect((root / native.INDEX).as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("BEGIN")
        return {key: json.loads(payload) for key, payload in conn.execute("SELECT key,payload FROM concepts")}


def validate_session(root, payload):
    """Validate every observation before creating any authoritative file."""
    root = Path(root).resolve()
    required = {"schema", "subject", "session_id", "study_date", "started_at", "ended_at", "conversation", "artifacts", "observations"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("invalid_concept_review_session_fields")
    if payload["schema"] != SCHEMA or payload["subject"] != "math":
        raise ValueError("invalid_concept_review_subject_or_schema")
    session_id = _text(payload["session_id"], "session_id")
    if len(session_id) > 128 or session_id != session_id.strip() or any(ord(c) < 32 for c in session_id):
        raise ValueError("invalid_session_id")
    started = _timestamp(payload["started_at"], "started_at")
    ended = _timestamp(payload["ended_at"], "ended_at")
    try:
        day = date.fromisoformat(payload["study_date"])
    except (TypeError, ValueError):
        raise ValueError("invalid_study_date") from None
    if day.isoformat() != payload["study_date"] or started.astimezone(ZoneInfo("Asia/Shanghai")).date() != day:
        raise ValueError("study_date_must_match_session_start_shanghai")
    if ended < started:
        raise ValueError("session_end_before_start")
    turns = payload["conversation"]
    if not isinstance(turns, list) or not turns:
        raise ValueError("complete_conversation_required")
    for turn in turns:
        if not isinstance(turn, dict) or set(turn) != {"role", "text"} or turn["role"] not in {"user", "assistant"}:
            raise ValueError("invalid_conversation_turn")
        _text(turn["text"], "conversation_text")
    observations = payload["observations"]
    if not isinstance(observations, list) or not observations:
        raise ValueError("observations_required")
    catalog = _catalog(root)
    seen = set()
    concepts = {}
    for row in observations:
        fields = {"observation_id", "concept_key", "question_ref", "outcome", "error_detail", "user_turn_indices", "hint_turn_indices", "related_formal_ids"}
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("invalid_observation_fields")
        identity = _text(row["observation_id"], "observation_id")
        if identity in seen:
            raise ValueError("duplicate_observation_id")
        seen.add(identity)
        key = row["concept_key"]
        if not isinstance(key, str) or not CONCEPT_RE.fullmatch(key) or key not in catalog:
            raise ValueError("unknown_exact_concept_key")
        _text(row["question_ref"], "question_ref")
        if row["outcome"] not in OUTCOMES:
            raise ValueError("invalid_observation_outcome")
        _text(row["error_detail"], "error_detail", empty=row["outcome"] != "wrong")
        for field, role in (("user_turn_indices", "user"), ("hint_turn_indices", "assistant")):
            indices = row[field]
            if not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < len(turns) for i in indices):
                raise ValueError("invalid_" + field)
            if len(indices) != len(set(indices)) or any(turns[i]["role"] != role for i in indices):
                raise ValueError("invalid_evidence_role_or_duplicate_index")
        if not row["user_turn_indices"]:
            raise ValueError("user_evidence_required")
        hints = row["hint_turn_indices"]
        if row["outcome"] == "independent_correct" and hints:
            raise ValueError("independent_correct_cannot_have_hint_evidence")
        if row["outcome"] == "corrected_after_hint" and (not hints or min(hints) >= max(row["user_turn_indices"])):
            raise ValueError("corrected_after_hint_requires_prior_hint")
        related = row["related_formal_ids"]
        if not isinstance(related, list) or any(not isinstance(fid, str) or fid not in catalog[key]["formal_ids"] for fid in related):
            raise ValueError("related_formal_id_not_linked_to_concept")
        if len(related) != len(set(related)):
            raise ValueError("duplicate_related_formal_id")
        concepts[key] = {"key": key, "label": catalog[key]["label"], "wiki_ids": catalog[key].get("wiki_ids", [])}
    artifacts = payload["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("invalid_artifacts")
    prepared = []
    for number, item in enumerate(artifacts):
        if isinstance(item, str):
            item = {"path": item}
        if not isinstance(item, dict) or "path" not in item or set(item) - {"path", "sha256", "role", "name"}:
            raise ValueError("invalid_artifact")
        source = Path(_text(item["path"], "artifact_path")).expanduser()
        if not source.is_absolute():
            source = root / source
        if source.is_symlink() or not source.is_file():
            raise ValueError("artifact_not_regular_file")
        raw = source.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if "sha256" in item and item["sha256"] != sha:
            raise ValueError("artifact_hash_mismatch")
        metadata = {k: _text(item[k], "artifact_" + k) for k in ("role", "name") if k in item}
        prepared.append({**metadata, "source_path": item["path"], "path": f"artifacts/{number:04d}-{sha}{source.suffix[:16]}",
                         "sha256": sha, "size": len(raw), "_bytes": raw})
    # Validate selected native evidence freshness as well as catalog identity.
    import math_concept_index as native
    for key in concepts:
        if native.resolve_concepts(root, [key], view="protected")["status"] != "available":
            raise ValueError("concept_review_requires_current_selected_evidence")
    normalized = {**payload, "artifacts": [{k: v for k, v in item.items() if k != "_bytes"} for item in prepared]}
    elapsed = (ended - started).total_seconds()
    core = {"payload": normalized, "concept_bindings": concepts,
            "event_id": event_id(session_id), "event_type": "concept_review", "budget_seconds": 1800,
            "duration_seconds": elapsed, "over_budget": elapsed > 1800,
            "attribution": "concept_session_only_not_formal_card_attempts"}
    return {**core, "content_sha256": digest(core)}, prepared


def load_session(root, path):
    """Verify the entire immutable commit, including all copied attachments."""
    root = Path(root).resolve()
    path = safe_path(root, path)
    value = json.loads(path.read_bytes())
    core = {k: v for k, v in value.items() if k != "content_sha256"}
    if value.get("content_sha256") != digest(core):
        raise ValueError("concept_review_session_hash_mismatch")
    if path.parent.name != value["event_id"] or value["event_id"] != event_id(value["payload"]["session_id"]):
        raise ValueError("concept_review_session_identity_mismatch")
    for item in value["payload"]["artifacts"]:
        artifact = safe_path(root, path.parent / item["path"])
        if not artifact.is_relative_to(path.parent):
            raise ValueError("concept_review_artifact_outside_session")
        raw = artifact.read_bytes()
        if len(raw) != item["size"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("concept_review_artifact_hash_mismatch")
    return value


def committed_event(root, identity):
    root = Path(root).resolve()
    if not re.fullmatch(re.escape(PREFIX) + r"[0-9a-f]{32}", identity):
        raise ValueError("invalid_concept_review_event_id")
    path = Path(root) / SESSIONS / identity / "session.json"
    if not path.is_file():
        raise ValueError("postcommit_event_not_unique")
    session = load_session(root, path)
    return {"event_id": identity, "event_type": "concept_review", "concept_keys": sorted(session["concept_bindings"]),
            "content_sha256": session["content_sha256"], "session_path": str(path.relative_to(root))}


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _retry_value(root, payload):
    """An exact replay can recover from the sealed artifact if originals moved."""
    if not isinstance(payload, dict) or not isinstance(payload.get("session_id"), str):
        return None
    path = safe_path(root, root / SESSIONS / event_id(payload["session_id"]) / "session.json")
    if not path.is_file():
        return None
    previous = load_session(root, path)
    expected = previous["payload"]
    if {k: v for k, v in payload.items() if k != "artifacts"} != {k: v for k, v in expected.items() if k != "artifacts"}:
        raise ValueError("concept_review_session_conflict")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(expected["artifacts"]):
        raise ValueError("concept_review_session_conflict")
    for item, saved in zip(artifacts, expected["artifacts"]):
        item = {"path": item} if isinstance(item, str) else item
        if not isinstance(item, dict) or set(item) - {"path", "sha256", "role", "name"}:
            raise ValueError("concept_review_session_conflict")
        if item.get("path") != saved["source_path"] or any(item.get(k) != saved.get(k) for k in ("role", "name")):
            raise ValueError("concept_review_session_conflict")
        if item.get("sha256", saved["sha256"]) != saved["sha256"]:
            raise ValueError("concept_review_session_conflict")
        source = Path(item["path"]).expanduser()
        source = source if source.is_absolute() else root / source
        if source.exists() and (not source.is_file() or source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != saved["sha256"]):
            raise ValueError("concept_review_session_conflict")
    return previous


def commit_session(repo_root, payload, *, refresh_only=False, postcommit=True):
    root = Path(repo_root).resolve()
    previous = _retry_value(root, payload)
    value, artifacts = (previous, []) if previous else validate_session(root, payload)
    directory = safe_path(root, root / SESSIONS)
    base = safe_path(root, root / BASE)
    base.mkdir(parents=True, exist_ok=True)
    identity = value["event_id"]
    target = directory / identity
    status = "recorded"
    with safe_path(root, base / "commit.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        directory.mkdir(parents=True, exist_ok=True)
        if target.exists():
            previous = load_session(root, target / "session.json")
            if previous["content_sha256"] != value["content_sha256"]:
                raise ValueError("concept_review_session_conflict")
            status = "noop"
        else:
            # Stage outside the watched authoritative directory. Rename is the
            # single commit point; abandoned staging directories are not events.
            staging = Path(tempfile.mkdtemp(prefix=".session-", dir=base))
            try:
                for item in artifacts:
                    path = staging / item["path"]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as handle:
                        handle.write(item["_bytes"])
                        handle.flush()
                        os.fsync(handle.fileno())
                with (staging / "session.json").open("xb") as handle:
                    handle.write(canonical(value))
                    handle.flush()
                    os.fsync(handle.fileno())
                if (staging / "artifacts").exists():
                    _fsync_dir(staging / "artifacts")
                _fsync_dir(staging)
                os.rename(staging, target)
                _fsync_dir(directory)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
    # Failures after this point are recovery-only, never a replay of learning.
    load_session(root, target / "session.json")
    result = {"status": status, "committed": True, "event_id": identity, "session_path": str((target / "session.json").relative_to(root)),
              "content_sha256": value["content_sha256"], "concept_count": len(value["concept_bindings"]),
              "observation_count": len(payload["observations"]), "formal_card_write_count": 0, "capture_write_count": 0}
    if postcommit:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "数学一回滚复习系统/scripts"))
        try:
            import math_postcommit
            result["postcommit"] = math_postcommit.run_after_commit(root, identity, refresh_only=refresh_only)
        except Exception as exc:
            result["postcommit"] = {"status": "local_refresh_pending", "reason": str(exc), "recover_event_id": identity}
        finally:
            sys.path.pop(0)
    return result


def collect_records(root, read):
    """Feed verified source-addressed personal records into the native index."""
    root = Path(root).resolve()
    directory = safe_path(root, root / SESSIONS)
    for path in sorted(directory.glob("*/session.json")):
        session = load_session(root, path)
        source = read(path, "external")
        refs = [{"path": source["path"], "sha256": source["sha256"]}]
        payload = session["payload"]
        for item in payload["artifacts"]:
            artifact = read(path.parent / item["path"], "external")
            refs.append({"path": artifact["path"], "sha256": artifact["sha256"]})
        for key, binding in sorted(session["concept_bindings"].items()):
            observations = [row for row in payload["observations"] if row["concept_key"] == key]
            yield {"record_id": session["event_id"] + ":" + key, "formal_id": None,
                   "kind": "concept_review", "concept_key": key, "labels": [binding["label"]],
                   "source_refs": refs, "association": "explicit_concept_review",
                   "not_proof_of_same_error": True,
                   "retrieval_priority": {"explicit_personal_or_actual_delivery": True,
                                          "latest_explicit_learning_date": payload["study_date"]},
                   "summary": {"session_id": payload["session_id"], "event_id": session["event_id"],
                               "study_date": payload["study_date"], "wrong_session_count": int(any(row["outcome"] == "wrong" for row in observations)),
                               "observation_count": len(observations), "observations": observations,
                               "related_formal_ids": sorted({fid for row in observations for fid in row["related_formal_ids"]}),
                               "attribution": session["attribution"]},
                   "history": {"conversation": payload["conversation"], "artifacts": payload["artifacts"],
                               "started_at": payload["started_at"], "ended_at": payload["ended_at"]}}


def refresh_pages(repo_root):
    """Rebuild readable concept pages from one verified native snapshot."""
    import math_concept_index as native
    import study_personalization_math as snapshot
    root = Path(repo_root).resolve()
    identity = snapshot.current_identity(root)
    if identity["status"] != "ready":
        raise ValueError("concept_review_pages_require_current_index")
    with closing(sqlite3.connect((root / native.INDEX).as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("BEGIN")
        concepts = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM concepts ORDER BY label,key")]
        records = {rid: json.loads(payload) for rid, payload in conn.execute("SELECT id,payload FROM records")}
        membership = list(conn.execute("SELECT key,record_id FROM membership ORDER BY key,record_id"))
    output = safe_path(root, root / PAGES)
    output.mkdir(parents=True, exist_ok=True)
    lines = ["# 数学知识点复盘", "", "知识点是唯一锚点。关联题仅提供来源，不表示本次复做过这些题。", "",
             "新复盘标记来自正式完整会话；旧题历史不回填为新复发。", "", f"快照版本：`{identity['version']}`", ""]
    count = 0
    wiki_paths = {}
    for path in (root / "错题知识网络/wiki").rglob("*.md"):
        wiki_paths.setdefault(path.stem.partition("_")[0], []).append(path)
    for concept in concepts:
        key = concept["key"]
        reviews = [records[rid] for member, rid in membership if member == key and records[rid].get("kind") == "concept_review"]
        reviews.sort(key=lambda row: (row["summary"]["study_date"], row["record_id"]))
        wrong_sessions = sum(row["summary"]["wrong_session_count"] for row in reviews)
        count += len(reviews)
        body = [f"# {concept['label']}", "", f"知识点键：`{key}`", "", "## 关联正式题", "",
                "这里只表示知识点关联，不推断关联题本轮作答、错因或掌握度。", ""]
        for fid in concept["formal_ids"]:
            refs = records[fid]["source_refs"]
            card_path = next((ref["path"] for ref in refs if ref["path"].startswith("错题知识网络/错题卡/")), None)
            relative = os.path.relpath(root / card_path, output) if card_path else None
            body.append(f"- [{fid}]({relative})" if relative else f"- {fid}")
        for wiki_id in concept.get("wiki_ids", []):
            paths = wiki_paths.get(wiki_id, [])
            for path in paths:
                body.append(f"- [既有知识点页 {wiki_id}]({os.path.relpath(path, output)})")
        if not concept["formal_ids"]:
            body.append("暂无关联正式题。")
        body += ["", "## 正式复盘标记", "", f"会话数：{len(reviews)}；出现明确错误的会话数：{wrong_sessions}。同会话同知识点最多计一次，全部观测保留。", ""]
        for review in reviews:
            summary = review["summary"]
            body += [f"### {summary['study_date']} · {summary['session_id']}", ""]
            for row in summary["observations"]:
                body += [f"- {row['question_ref']} · {row['outcome']} · 用户原话索引 {row['user_turn_indices']} · 提示索引 {row['hint_turn_indices']}",
                         "  " + (row["error_detail"] or "本次未记录错误细节。")]
            relative = os.path.relpath(root / review["source_refs"][0]["path"], output)
            body += ["", f"[完整会话与证据]({relative})", ""]
        if not reviews:
            body.append("暂无正式知识点复盘事件。")
        snapshot._write(output / (key + ".md"), ("\n".join(body) + "\n").encode())
        lines.append(f"- [{concept['label']}]({key}.md) · 关联题 {len(concept['formal_ids'])} · 复盘 {len(reviews)} · 错误会话 {wrong_sessions}")
    snapshot._write(output / "index.md", ("\n".join(lines) + "\n").encode())
    return {"status": "refreshed", "index_path": str(PAGES / "index.md"), "concept_count": len(concepts),
            "concept_session_count": count, "version": identity["version"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    commands = parser.add_subparsers(dest="command", required=True)
    commit = commands.add_parser("commit")
    commit.add_argument("--input", type=Path, required=True)
    commit.add_argument("--refresh-only", action="store_true")
    commands.add_parser("refresh")
    recover = commands.add_parser("recover")
    recover.add_argument("--event-id", required=True)
    recover.add_argument("--refresh-only", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    if args.command == "commit":
        result = commit_session(root, json.loads(args.input.read_text()), refresh_only=args.refresh_only)
    elif args.command == "refresh":
        import math_concept_index as native
        result = {"index": native.build_index(root), "pages": refresh_pages(root), "formal_event_write_count": 0}
        result["index"] = {k: result["index"][k] for k in ("status", "version", "concept_count", "record_count")}
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "数学一回滚复习系统/scripts"))
        import math_postcommit
        result = math_postcommit.run_after_commit(root, args.event_id, refresh_only=args.refresh_only)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
