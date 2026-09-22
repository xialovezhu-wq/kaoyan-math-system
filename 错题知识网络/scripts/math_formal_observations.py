"""Point-specific formal judgments bound to an existing freeze and closeout.

No Capture/session writer. A successful closeout is the only commit point.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA = "math-formal-concept-observations-v1"
OUTCOMES = {"wrong", "unresolved", "corrected_after_hint", "independent_correct"}
LEDGER = Path("数学一回滚复习系统/快速入库事件.jsonl")
PROJECTIONS = Path("错题知识网络/个人知识点索引/正式逐点观测")


def normalize(value, freeze, state, formal_by_id, verified, qi):
    import math_concept_index as native
    import wrongnet
    if not isinstance(value, dict) or set(value) != {"schema", "targets"} or value["schema"] != SCHEMA:
        raise ValueError("invalid_formal_concept_observations")
    targets = value["targets"]
    if not isinstance(targets, list):
        raise ValueError("formal_observation_targets_required")
    seen, normalized = set(), []
    for target in targets:
        if not isinstance(target, dict) or set(target) != {"formal_id", "observations", "no_observation_reason"}:
            raise ValueError("invalid_formal_observation_target")
        fid = target["formal_id"]
        if fid not in formal_by_id or fid in seen:
            raise ValueError("formal_observation_target_mismatch")
        seen.add(fid)
        card, _ = qi.card_path_if_unique(fid)
        meta, _ = wrongnet.split_front_matter(card.read_text())
        labels = native._items(meta.get("knowledge"))
        bindings = qi.teaching_context_capture_bindings(freeze, fid)
        captures = {row["capture_event_id"] for row in bindings}
        observations = target["observations"]
        reason = target["no_observation_reason"]
        if not isinstance(observations, list) or not isinstance(reason, str) or (bool(observations) == bool(reason.strip())):
            raise ValueError("explicit_observations_or_no_observation_reason_required")
        rows, packages = [], {}
        for row in observations:
            fields = {"concept_key", "concept_label", "capture_event_id", "outcome", "error_detail", "user_evidence", "hint_evidence"}
            if not isinstance(row, dict) or set(row) != fields:
                raise ValueError("invalid_formal_observation_fields")
            key, label = row["concept_key"], row["concept_label"]
            if label not in labels or native.concept_key(label) != key:
                raise ValueError("formal_observation_requires_exact_card_concept")
            cid = row["capture_event_id"]
            if cid not in captures:
                raise ValueError("formal_observation_capture_not_frozen_for_target")
            if row["outcome"] not in OUTCOMES or not isinstance(row["error_detail"], str):
                raise ValueError("invalid_formal_observation_outcome")
            if row["outcome"] in {"wrong", "unresolved"} and not row["error_detail"].strip():
                raise ValueError("formal_observation_error_detail_required")
            if cid not in packages:
                capture = state["captures"][cid]
                bundle = qi.effective_source_bundle(capture, state["amendments"].get(cid, []))
                if not bundle:
                    raise ValueError("formal_observation_requires_complete_frozen_package")
                document, manifest, children = qi.validate_source_bundle_manifest(
                    bundle["manifest_path"], "formal_concept_observations.source",
                    expected_hash=bundle["manifest_hash"], expected_date=freeze["study_date"])
                if "conversation" not in document.get("files", {}):
                    raise ValueError("formal_observation_requires_complete_frozen_package")
                conversation_path = qi.resolve_repo_artifact(document["files"]["conversation"]["path"], "observation.conversation")
                conversation = json.loads(conversation_path.read_text())
                refs = []
                for path in [manifest, *children]:
                    rel = str(path.relative_to(qi.REPO_ROOT.resolve()))
                    sha = qi.file_sha256(path)
                    verified[rel] = sha
                    refs.append({"path": rel, "sha256": sha})
                packages[cid] = {"package_id": document["package_id"], "source_refs": refs,
                                 "conversation": conversation["turns"]}
            package = packages[cid]
            turns = package["conversation"]
            for field, role in (("user_evidence", "user"), ("hint_evidence", "assistant")):
                evidence = row[field]
                if not isinstance(evidence, list) or (field == "user_evidence" and not evidence):
                    raise ValueError("formal_observation_user_evidence_required")
                for quote in evidence:
                    if not isinstance(quote, dict) or set(quote) != {"sequence", "quote"}:
                        raise ValueError("invalid_formal_observation_quote")
                    number = quote["sequence"]
                    if type(number) is not int or not 1 <= number <= len(turns):
                        raise ValueError("formal_observation_turn_out_of_range")
                    turn = turns[number - 1]
                    if turn["role"] != role or not isinstance(quote["quote"], str) or not quote["quote"].strip() or quote["quote"] not in turn["text"]:
                        raise ValueError("formal_observation_quote_or_role_mismatch")
            hints = row["hint_evidence"]
            if row["outcome"] == "independent_correct" and hints:
                raise ValueError("formal_observation_independent_cannot_have_hint")
            if row["outcome"] == "corrected_after_hint" and (not hints or min(x["sequence"] for x in hints) >= max(x["sequence"] for x in row["user_evidence"])):
                raise ValueError("formal_observation_correction_requires_prior_hint")
            rows.append(row)
        normalized.append({**target, "observations": rows, "capture_bindings": bindings, "packages": packages,
                           "study_date": freeze["study_date"],
                           "episode_id": "FORMAL-EPISODE-" + native.digest([freeze["study_date"], fid])[:24]})
    if seen != set(formal_by_id):
        raise ValueError("formal_observations_must_cover_all_targets")
    return {"schema": SCHEMA, "targets": normalized,
            "count_scope": "one_original_study_date_formal_target_concept_not_each_capture_or_quote"}


def prepare_sources(root):
    """Recover stable per-closeout derived bytes before index directory stamps.

    Their authority remains the ledger. Unrelated pending captures cannot change
    a previously accepted point source hash. No new learning event is written.
    """
    import math_concept_index as native
    import study_personalization_math as snapshot
    root = Path(root)
    path = root / LEDGER
    if not path.exists():
        return []
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    invalid = {row.get("closeout_id") for row in events if row.get("event_type") == "closeout_invalidation"}
    prepared = []
    seen = set()
    for ordinal, event in enumerate(events):
        if event.get("event_type") != "closeout" or event.get("event_id") in invalid:
            continue
        envelope = event.get("concept_observations")
        if not envelope:
            continue
        if envelope.get("schema") != SCHEMA:
            raise ValueError("unknown_committed_formal_observation_schema")
        identity = event["event_id"]
        if identity in seen:
            continue
        seen.add(identity)
        if not event.get("content_hash"):
            raise ValueError("formal_observation_closeout_hash_required")
        if event.get("content_hash"):
            # Same canonical encoding as quick_intake.with_content_hash.
            body = {k: v for k, v in event.items() if k != "content_hash"}
            import hashlib
            encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            if hashlib.sha256(encoded).hexdigest() != event["content_hash"]:
                raise ValueError("formal_observation_closeout_hash_mismatch")
        if not re.fullmatch(r"MFI-CLOSE-[a-f0-9]{24}", identity):
            raise ValueError("invalid_formal_observation_closeout_identity")
        target = root / PROJECTIONS / (identity + ".json")
        import math_concept_review
        math_concept_review.safe_path(root, target)
        saved = {"schema": SCHEMA, "closeout_id": identity, "closeout_content_hash": event.get("content_hash"),
                 "freeze_id": event["freeze_id"], "ledger_path": str(LEDGER), "concept_observations": envelope}
        snapshot._write(target, (native.canonical(saved) + "\n").encode())
        prepared.append((ordinal, event, target))
    return prepared


def collect_records(root, read, prepared):
    """Reconstruct only explicit committed judgments; legacy rows stay legacy."""
    import math_concept_index as native
    for ordinal, event, path in prepared:
        identity = event["event_id"]
        envelope = event["concept_observations"]
        source = read(path, "external")
        for target in envelope["targets"]:
            keys = sorted({row["concept_key"] for row in target["observations"]})
            for key in keys:
                rows = [row for row in target["observations"] if row["concept_key"] == key]
                label = rows[0]["concept_label"]
                if native.concept_key(label) != key:
                    raise ValueError("formal_observation_concept_binding_mismatch")
                yield {"record_id": identity + ":" + target["formal_id"] + ":" + key,
                       "formal_id": target["formal_id"], "kind": "formal_concept_observation", "concept_key": key,
                       "labels": [label], "source_refs": [{"path": source["path"], "sha256": source["sha256"]}],
                       "association": "explicit_formal_concept_judgment", "not_proof_of_same_error": True,
                       "retrieval_priority": {"explicit_personal_or_actual_delivery": True, "latest_explicit_learning_date": target["study_date"]},
                       "summary": {"event_id": identity, "episode_id": target["episode_id"], "study_date": target["study_date"],
                                   "observations": rows, "related_formal_ids": [target["formal_id"]], "source_ordinal": ordinal,
                                   "attribution": "explicit_formal_intake_not_concept_review"},
                       "history": {"freeze_id": event["freeze_id"], "capture_bindings": target["capture_bindings"],
                                   "packages": target["packages"], "count_scope": envelope["count_scope"]}}
