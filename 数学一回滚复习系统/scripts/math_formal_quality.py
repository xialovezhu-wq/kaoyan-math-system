"""Quality evidence for new native math freeze/closeout transactions."""

import argparse
from collections import defaultdict
from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import sqlite3
import sys

from math_formal_quality_api import (
    DIMENSIONS, MODEL, Journal, QualityError, canonical, digest, input_hash, read,
    require, sha, vector, write,
)

ROOT = Path(__file__).resolve().parents[2]
ROLLBACK = Path("数学一回滚复习系统")
KNOWLEDGE = Path("错题知识网络")
CONTROL = ROLLBACK / ".formal-quality-v1"
CONFIG = ROLLBACK / "正式质量合同.json"
PRIVATE_SCHEMA = "math-formal-quality-generation-v1"
PUBLIC_SCHEMA = "math-formal-quality-binding-v1"
LOCAL_READBACK = "native_teaching_readback"
TEACHING_READBACK_BYTES = 12000
HOLD = "DEFERRED_FORMAL_QUALITY"
POLICY = "math-safe-projection-v1"
MEMORY_REVIEW = "scoped-learning-memory-v1"
CANDIDATE_POLICY = "source-bound-math-advice-v2"
PROTECTED = {"题目摘要", "标准答案", "卷面解答"}
META_SEMANTIC = {"chapter", "knowledge", "methods", "traps", "wrong_point",
                 "error_causes", "method_gap", "mastery_history", "wrong_history", "status"}
PROFILE_FIELDS = ("overview", "short_summary", "next_check", "progress", "claims",
                  "teaching_preferences", "step_evidence", "solution_connections")
STORED_PROFILE_FIELDS = PROFILE_FIELDS + ("source_refs", "concept_key", "concept_name")
PROTECTED_TEACHING_FIELDS = set(PROFILE_FIELDS) | PROTECTED | {
    "problem_solving", "exam_frequency", "choice_fill_guidance", "exact_question_prior",
    "answer", "standard_answer", "final_answer", "solution", "correct_option",
}
SAFE = re.compile(
    r"(?:https?://|/Users/|/Volumes/|/private/|/attachments/|"
    r"(?<![A-Z0-9])(?:MFI-|MATHPKG-|MATH-ATT-|MATH[123]-|(?:GS|LA|PR)-\d{3})|"
    r"\b[0-9a-f]{24,}\b|(?:20\d\d-\d\d-\d\d)|"
    r"(?:正确选项|答案(?:为|是|[:：])|(?:应|故|只)选\s*[A-DＡ-Ｄ])|"
    r"\.(?:png|jpe?g|pdf)\b|[A-Z]:\\|第\s*\d+\s*页|"
    r"<(?:image|response-annotations)|\bsk-(?:proj-)?[A-Za-z0-9_-]{12,})", re.I)
RUBRIC = {
    "assignment": "候选材料和当前机制是否有具体归属关系，且所涉对象与操作一致？",
    "conditions": "候选材料是否补充或核对了当前机制的必要条件或适用范围？",
    "conflict": "在相同对象和适用范围内，给定片段是否有实质数学冲突？",
    "support": "给定候选材料是否支持当前机制的操作，且无须补造前提？",
    "duplicate": "二者是否只是同一条适用条件与数学作用的重复表述？",
}


def add_native(root):
    for sub in (ROLLBACK, KNOWLEDGE):
        folder = str(Path(root) / sub / "scripts")
        if folder not in sys.path:
            sys.path.insert(0, folder)


def enabled(root):
    path = Path(root) / CONFIG
    if not path.exists():
        return False
    value = read(path)
    require(value.get("schema") == "math-formal-quality-config-v1" and
            isinstance(value.get("legacy_freezes"), list), "quality_config_invalid")
    return value.get("enabled") is True


def control(root, name):
    return Path(root) / CONTROL / name


def active(root):
    path = control(root, "active.json")
    return read(path) if path.is_file() else None


def workspace(root, path, *, create=False):
    path = Path(path).resolve()
    add_native(root)
    if Path(root).resolve() == ROOT:
        import math_workflow_storage as storage
        checked = storage.ensure_cold_output(path)
        require(checked == path and path.is_relative_to(storage.WORK_ROOT.resolve()),
                "quality_workspace_outside_math_t9")
        storage.validate_t9()
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def within(folder, name):
    relative = Path(name)
    require(not relative.is_absolute() and ".." not in relative.parts, "quality_relative_path_required")
    path = folder / relative
    require(path.resolve().is_relative_to(folder.resolve()) and not path.is_symlink(),
            "quality_path_escape")
    return path


def safe(value, maximum=2800):
    require(isinstance(value, str) and 0 < len(value.strip().encode()) <= maximum
            and not SAFE.search(value) and all(ord(c) >= 32 or c == "\n" for c in value),
            "quality_outbound_text_rejected")
    return value.strip()


def identity(root):
    add_native(root)
    import study_personalization_math
    value = study_personalization_math.current_identity(root)
    require(value["status"] == "ready", "quality_native_identity_not_ready")
    return {key: value[key] for key in ("version", "formal_version")}


def baseline(root):
    value = identity(root)
    config = Path(root) / KNOWLEDGE / "个人知识点索引/memory-backends/config.json"
    value["retrieval_config_sha256"] = sha(config.read_bytes()) if config.is_file() else None
    return value


def baseline_matches(root, frozen):
    # Older frozen inputs retain their replica commit as historical metadata.
    return baseline(root) == {key: value for key, value in frozen.items() if key != "source_commit"}


def state(qi):
    return qi.replay(qi.load_jsonl(qi.EVENTS_PATH))


def scope_bindings(qi, freeze_id, *, live):
    replay = state(qi)
    freeze = replay["freezes"].get(freeze_id)
    require(freeze is not None and freeze_id not in replay["aborted_freezes"], "quality_freeze_not_found")
    if live:
        qi.verify_freeze_current(freeze, replay)
    targets = {cid: target["formal_id"] for target in freeze["targets"] for cid in target["capture_event_ids"]}
    sources, turns = {}, {}
    for cid, fid in targets.items():
        event = replay["captures"][cid]
        bundle = qi.effective_source_bundle(event, replay["amendments"][cid])
        require(bundle, "quality_source_required:" + cid)
        manifest, _, _ = qi.validate_source_bundle_manifest(
            bundle["manifest_path"], "quality.source", expected_hash=bundle["manifest_hash"],
            expected_date=freeze["study_date"])
        conversation = manifest["files"].get("conversation") if isinstance(manifest.get("files"), dict) else None
        turns[cid] = {}
        if conversation:
            raw = read(qi.REPO_ROOT / conversation["path"])
            turns[cid] = {turn["sequence"]: turn for turn in raw["turns"]}
        sources[cid] = {"formal_id": fid, "manifest": bundle["manifest_path"],
                        "manifest_sha256": bundle["manifest_hash"], "package_id": manifest["package_id"],
                        "package_sha256": manifest.get("canonical_sha256"),
                        "conversation": conversation,
                        "artifacts": {entry["sha256"]: entry["role"] for entry in manifest.get("artifacts", [])}}
    return freeze, sources, turns


def scope_value(qi, spec):
    require(spec.get("schema") == "math-formal-quality-scope-v1" and spec.get("redacted") is True,
            "quality_reviewed_scope_required")
    freeze, sources, turns = scope_bindings(qi, spec["freeze_id"], live=True)
    units = {}
    used = set()
    for index, row in enumerate(spec["units"], 1):
        require(set(row) == {"capture_id", "mechanism", "objects", "conditions", "goal",
                            "exact_labels", "turns", "attachments"}, "quality_unit_shape")
        cid = row["capture_id"]
        require(cid in sources, "quality_unit_scope")
        used.add(cid)
        fields = [safe(row[name], 900) for name in ("mechanism", "objects", "conditions", "goal")]
        query = "。".join(fields)
        projected = []
        seen = set()
        for item in row["turns"]:
            require(set(item) == {"sequence", "text"}, "quality_turn_projection_shape")
            n = item["sequence"]
            original = turns[cid].get(n)
            require(original and n not in seen and original["role"] in {"user", "assistant"},
                    "quality_unbound_turn_projection")
            fragment = safe(item["text"], 900)
            require(len(fragment) < 32 or fragment not in original["text"], "quality_verbatim_turn")
            seen.add(n)
            projected.append({"sequence": n, "role": original["role"], "text": fragment,
                              "source_text_sha256": sha(original["text"].encode())})
        require(sources[cid]["artifacts"].keys() == row["attachments"].keys() and
                set(row["attachments"].values()) <= {"verified_question", "verified_reference", "archive_only"},
                "quality_attachment_coverage")
        question = {key for key, role in sources[cid]["artifacts"].items() if role == "question_image"}
        require(not question or question <= {key for key, disposition in row["attachments"].items()
                                              if disposition == "verified_question"},
                "quality_question_not_checked")
        require(isinstance(row["exact_labels"], list), "quality_exact_labels")
        units["u-" + str(index)] = {"capture_id": cid, "query": query,
                                     "exact_labels": [safe(s, 360) for s in row["exact_labels"]],
                                     "turns": sorted(projected, key=lambda item: item["sequence"]),
                                     "attachments": row["attachments"]}
    require(used == sources.keys(), "quality_capture_coverage")
    return freeze, sources, units


def _source_file(root, row):
    path = within(root, row["path"])
    require(sha(path.read_bytes()) == row["sha256"], "quality_reference_changed")
    return path


def _vector_key(text, input_identity=None):
    base = [POLICY, MODEL["embeddings"], DIMENSIONS, text]
    return digest(base if input_identity is None else [*base, input_identity])


def _previous(root):
    marker = control(root, "current.json")
    if not marker.is_file():
        return {}
    row = read(marker)
    directory = workspace(root, row["workspace"])
    gen = read(within(directory, "generation.json"))
    require(digest(gen) == row["generation_sha256"], "quality_history_generation_drift")
    return gen.get("objective", {})


def local_candidates(root, frozen, *, query_vectors=None, require_semantic=False):
    import math_memory_retrieval as retrieval
    import math_concept_index as native
    import math_semantic_candidates as semantic
    root = Path(root)
    idx = root / KNOWLEDGE / "个人知识点索引/memory-backends"
    config = read(idx / "config.json")
    discovery = config["backends"]["native"]
    reference = config["reference_semantic"]
    for binding, path_key, sha_key in (
        (discovery, "corpus_path", "corpus_sha256"),
        (reference, "mathematical_reference_path", "mathematical_reference_sha256"),
    ):
        path = Path(binding[path_key])
        require(path.resolve().is_relative_to(idx.resolve()) and sha(path.read_bytes()) == binding[sha_key],
                "quality_catalog_changed")
    catalog = read(reference["mathematical_reference_path"])
    docs = read(discovery["corpus_path"])
    require(catalog["source_version"] == docs["source_version"] == frozen["baseline"]["version"]
            and catalog["content_policy"] == "mathematical_reference_no_learner_evidence",
            "quality_candidate_catalog_stale")
    refs = {doc["concept_key"]: doc for doc in catalog["documents"]}
    global_matches = {}
    if query_vectors:
        try:
            import math_memory_global_vectors
            global_matches = math_memory_global_vectors.formal_candidates(
                root, catalog, query_vectors, model=MODEL["embeddings"], dimensions=DIMENSIONS)
        except (ImportError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
            if require_semantic:
                raise QualityError("quality_semantic_candidates_pending:" + type(exc).__name__) from exc
        if require_semantic:
            require(bool(global_matches) and all(global_matches.get(uid) for uid in query_vectors),
                    "quality_semantic_candidates_pending:index_has_no_verified_vectors")
    previous = _previous(root)
    verified_sources = {}

    def source_ready(row):
        key = (row["path"], row["sha256"])
        if key not in verified_sources:
            try:
                _source_file(root, row)
                verified_sources[key] = True
            except (OSError, QualityError):
                verified_sources[key] = False
        return verified_sources[key]

    pools, rows = {}, {}
    ordered_keys = {}
    for uid, unit in frozen["units"].items():
        exact = [native.concept_key(label) for label in unit["exact_labels"]]
        lexical = retrieval.rank(unit["query"], docs["documents"], limit=6)["ranked"]
        lexical_keys = [row["id"] for row in lexical]
        semantic_keys = global_matches.get(uid, [])
        keys = dict.fromkeys([*exact, *lexical_keys[:2], *semantic_keys, *lexical_keys[2:]])
        ordered_keys[uid] = (exact, semantic_keys, keys)
    prepared = (semantic.formula_inputs(root, (key for _,_,keys in ordered_keys.values() for key in keys))
                if frozen.get("candidate_policy") == CANDIDATE_POLICY else {})
    for uid, (exact, semantic_keys, keys) in ordered_keys.items():
        relevant = {}
        seen_parts = set()
        for key in keys:
            ref = refs.get(key)
            prepared_rows = prepared.get(key, [])
            if not ref and not prepared_rows:
                continue
            accepted = 0
            parts = [*prepared_rows, *[
                {"text": part["text"], "concept_key": key, "stable_id": part["id"],
                 "role": part["kind"], "source_refs": part["source_refs"]}
                for part in (ref or {}).get("fragments", [])
                if part.get("kind") in {"formula", "conclusion", "method", "step"} and part.get("source_refs")]]
            for part in semantic.unique_rows(parts):
                signature = digest([part["role"], semantic.normalized_text(part["text"]),
                                    [(r["path"], r["sha256"], r.get("pdf_page")) for r in part["source_refs"]]])
                if signature in seen_parts:
                    continue
                try:
                    text = safe(part["text"])
                except QualityError:
                    continue
                if not all(source_ready(row) for row in part["source_refs"]):
                    continue
                row_id = "c-" + digest([key, part["stable_id"], part["role"]])[:24]
                if row_id in relevant:
                    continue
                rows[row_id] = {**part, "text": text}
                seen_parts.add(signature)
                relevant[row_id] = ("exact" if key in exact else
                                    "global_vector" if key in semantic_keys else "lexical")
                accepted += 1
                if accepted == 3 or len(relevant) == 12:
                    break
            if len(relevant) == 12:
                break
        for row_id, old in previous.items():
            if len(relevant) >= 12:
                break
            if old["concept_key"] in keys and all(source_ready(row) for row in old["source_refs"]):
                if old.get("role") not in {"formula", "conclusion", "method", "step"}:
                    continue
                safe(old["text"])
                rows[row_id] = {k: old[k] for k in ("text", "concept_key", "stable_id", "role", "source_refs", "input_identity")
                                if k in old}
                relevant.setdefault(row_id, "history")
        pools[uid] = relevant
    return pools, rows, previous


def begin(qi, folder, scope, *, request=None):
    root = qi.REPO_ROOT
    folder = workspace(root, folder, create=True)
    freeze, sources, units = scope_value(qi, scope)
    run = "QMATH-" + digest([freeze["event_id"], sorted(sources)])[:40]
    frozen = {"schema": "math-quality-frozen-v1", "run_id": run, "freeze_id": freeze["event_id"],
              "freeze_sha256": freeze["content_hash"], "study_date": freeze["study_date"],
              "baseline": baseline(root), "sources": sources, "units": units}
    frozen_path = folder / "frozen.json"
    if frozen_path.is_file():
        before = read(frozen_path)
        if "memory_review" in before:
            frozen["memory_review"] = before["memory_review"]
        if "candidate_policy" in before:
            frozen["candidate_policy"] = before["candidate_policy"]
        require(all(before[k] == frozen[k] for k in ("run_id", "freeze_id", "sources", "units")),
                "quality_frozen_scope_changed")
        if before != frozen:
            require(active(root) is None, "quality_rebase_after_write")
            write(folder / "revisions" / ("frozen-" + digest(before) + ".json"), before, immutable=True)
    else:
        frozen["memory_review"] = MEMORY_REVIEW
        frozen["candidate_policy"] = CANDIDATE_POLICY
    write(frozen_path, frozen)
    journal = Journal(folder, run, request=request)
    existing = folder / "candidates.json"
    if existing.is_file():
        old = read(existing)
        if old["frozen_sha256"] == digest(frozen) and old["mode"] == journal.mode:
            return old
        write(folder / "revisions" / ("candidates-" + digest(old) + ".json"), old, immutable=True)
    initial = journal.stage("initial", "embeddings", {k: u["query"] for k, u in units.items()})
    query_vectors = {uid: vector(journal.verify(
        "initial", "embeddings", uid, initial[uid], input_hash("embeddings", unit["query"], None)))
        for uid, unit in units.items()}
    upgraded = frozen.get("candidate_policy") == CANDIDATE_POLICY
    pools, rows, previous = local_candidates(root, frozen, query_vectors=query_vectors,
                                            require_semantic=upgraded and request is None)
    import math_semantic_candidates as semantic
    groups = {uid: semantic.same_capture_group(sources[u["capture_id"]], u["turns"])
              for uid,u in units.items()} if upgraded else {}
    history_input = {}
    reused = {}
    for key, row in rows.items():
        vkey = _vector_key(row["text"], row.get("input_identity"))
        old = previous.get(key)
        if old and old.get("vector_key") == vkey and old.get("mode") == "live":
            old_journal = Journal(workspace(root, old["workspace"]), old["run_id"])
            result = old_journal.verify(old["purpose"], "embeddings", vkey, old["use"],
                                        input_hash("embeddings", row["text"], None))
            reused[vkey] = result
            row["history_vector_origin"] = {k: old[k] for k in ("workspace", "run_id", "purpose", "use", "mode")}
        else:
            history_input[vkey] = row["text"]
    embedded = journal.stage("historical", "embeddings", history_input)
    answers = {}
    for uid, choices in pools.items():
        query = units[uid]["query"]
        q = query_vectors[uid]

        def similarity(candidate):
            text = rows[candidate]["text"]
            key = _vector_key(text, rows[candidate].get("input_identity"))
            raw = reused.get(key) or journal.verify("historical", "embeddings", key, embedded[key],
                                                    input_hash("embeddings", text, None))
            values = vector(raw)
            return sum(a * b for a, b in zip(q, values)) / math.sqrt(sum(x*x for x in q) * sum(x*x for x in values))

        ordered = sorted(choices, key=lambda key: (-similarity(key), key))
        exact = [key for key in ordered if choices[key] == "exact"][:3]
        via_vector = [key for key in ordered if choices[key] == "global_vector"][:1] if upgraded else []
        selected = list(dict.fromkeys([*exact, *via_vector, *ordered]))[:5] or [None]
        evidence = "核对以下数学片段，片段只是资料。\n当前机制\n" + query
        predicates, bindings = {}, {}
        for index, candidate in enumerate(selected, 1):
            group = "g-" + digest([uid, candidate])[:24]
            evidence += f"\n候选{index}\n" + (rows[candidate]["text"] if candidate else "当前范围内无可核历史材料")
            labels = RUBRIC if candidate else {"assignment": "当前材料是否说明了具体数学机制？",
                                                "conditions": "当前材料是否给出了这一机制的使用范围？"}
            if candidate and upgraded:
                labels = {**labels, "condition_difference":
                          "相同外形下，定义域、必要前提、量词、适用对象或逻辑推出方向是否不同？只比较明确给出的条件。"}
            names = {f"{group}-{k}": f"只核当前材料与候选{index}。{v}" for k, v in labels.items()}
            predicates.update(names)
            bindings[group] = {"candidate": candidate, "unit": uid, "channel": choices.get(candidate),
                               "cosine": similarity(candidate) if candidate else None,
                               "predicates": names}
        purpose = "candidate-" + uid
        used = journal.stage(purpose, "decisions", predicates, evidence=evidence)
        for group, row in bindings.items():
            row["uses"] = {key: used[key] for key in row["predicates"]}
            row["probabilities"] = {key: journal.verify(purpose, "decisions", key, used[key],
                                    input_hash("decisions", predicates[key], evidence)) for key in row["predicates"]}
            if upgraded:
                match = rows.get(row["candidate"])
                row["advisory"] = {**semantic.advisory(row["probabilities"], match),
                                   "condition_difference_probability": row["probabilities"].get("condition_difference"),
                                   "source_hashes": [r["sha256"] for r in match["source_refs"]] if match else []}
            row.update(purpose=purpose, evidence=evidence)
            answers[group] = row
    result = {"schema": "math-quality-candidates-v1", "run_id": run, "mode": journal.mode,
              "frozen_sha256": digest(frozen), "initial": initial, "historical": embedded,
              "catalog": rows, "judgments": answers}
    if upgraded:
        result.update(candidate_policy=CANDIDATE_POLICY, evidence_groups=groups,
                      vector_policy={"model": MODEL["embeddings"], "dimensions": DIMENSIONS,
                                     "normalization": semantic.NORMALIZATION, "status": journal.mode})
    write(existing, result)
    return result


def _card(root, target, path):
    path = within(root, path)
    require(path.parent == root / KNOWLEDGE / "错题卡" and
            path.name.startswith(target + "_") and path.suffix == ".md", "quality_card_path_invalid")
    return path


def _card_parts(data):
    import wrongnet
    meta, body = wrongnet.split_front_matter(data.decode())
    require(isinstance(meta, dict) and meta.get("id"), "quality_card_frontmatter_required")
    return meta, body


def _semantic_card(data):
    meta, body = _card_parts(data)
    return digest([dict((k, v) for k, v in meta.items() if k != "lecture_refs"), body])


def _material(folder, name):
    path = within(folder, name)
    return read(path)


def _capture_entries(frozen, source_ids):
    return sorted(uid for uid, row in frozen["units"].items() if row["capture_id"] in source_ids)


def _add_entry(entries, key, role, content, units, *, protected=False):
    if content in (None, "", [], {}):
        return
    require(key not in entries and units, "quality_statement_location_invalid")
    entries[key] = {"sha256": digest(content), "role": role, "units": units,
                    "classification": "protected" if protected else "api"}


def draft_entries(qi, folder, frozen, draft, *, existing_basis=None, prepared_profile=None):
    """Build an exact change inventory. Only projections, never native fields, leave the host."""
    root = qi.REPO_ROOT
    add_native(root)
    import math_concept_index as native
    import math_learning_profiles as profiles
    import wrongnet
    require(draft["schema"] == "math-formal-quality-draft-v1", "quality_draft_schema")
    replay = state(qi)
    freeze = replay["freezes"][frozen["freeze_id"]]
    targets = {row["formal_id"]: row for row in freeze["targets"]}
    observations = _material(folder, draft["observations"])
    priors = _material(folder, draft["priors"])
    outcomes = _material(folder, draft["outcomes"])
    require(set(priors) == targets.keys() and set(outcomes) == frozen["sources"].keys()
            and {r["formal_id"] for r in observations["targets"]} == targets.keys(),
            "quality_draft_coverage")
    entries, files, prospective, concept_units = {}, {}, set(), defaultdict(set)
    before_profiles = {}
    card_rows = {}
    def difference(key, content):
        return existing_basis is None or existing_basis.get(key) != digest(content)

    before = {} if existing_basis is None else dict(existing_basis)

    def check(key, role, content, units, *, protected=False, prior=None):
        if existing_basis is None:
            before[key] = digest(prior)
        if (difference(key, content) if existing_basis is not None else prior != content):
            _add_entry(entries, key, role, content, units, protected=protected)

    for row in draft["cards"]:
        fid, operation = row["formal_id"], row["operation"]
        target = targets[fid]
        require(fid not in card_rows and operation in {"created", "updated", "unchanged"}, "quality_duplicate_card")
        path = _card(root, fid, row["path"])
        after = within(folder, row["draft"]).read_bytes()
        files[row["draft"]] = sha(after)
        meta, body = _card_parts(after)
        require(meta["id"] == fid and (target["card_path_before"] in (None, row["path"])), "quality_card_identity")
        units = _capture_entries(frozen, target["capture_event_ids"])
        old_meta, old_sections = {}, {}
        if existing_basis is None:
            actual = path.read_bytes() if path.is_file() else None
            require((sha(actual) if actual is not None else None) == target["card_hash_before"],
                    "quality_draft_predecessor_drift")
            if actual is not None:
                old_meta, old_body = _card_parts(actual)
                old_sections = _sections(old_body)
            require((operation == "unchanged") == (actual == after) and
                    (operation == "created") == (actual is None), "quality_draft_operation_invalid")
        for label in wrongnet.as_list(meta.get("knowledge")):
            key = native.concept_key(label)
            prospective.add(key)
            concept_units[key].update(units)
        for key in sorted(META_SEMANTIC & meta.keys()):
            check(f"card/{fid}/meta/{key}", "card_metadata", meta[key], units,
                  prior=old_meta.get(key))
        for key, text in _sections(body).items():
            if key == "来源依据":
                continue
            check(f"card/{fid}/section/{key}", "card_text", text, units, protected=key in PROTECTED,
                  prior=old_sections.get(key))
        check(f"teaching/{fid}/prior", "teaching_slice", priors[fid], units)
        card_rows[fid] = {**row, "before": target["card_hash_before"], "sha256": sha(after),
                          "semantic_sha256": _semantic_card(after)}
    require(card_rows.keys() == targets.keys(), "quality_unprepared_card")
    for cid, row in sorted(outcomes.items()):
        require(set(row) == {"outcome", "reason"} and row["reason"].strip(), "quality_outcome_shape")
        check(f"capture/{cid}/disposition", "capture_disposition", row, _capture_entries(frozen, [cid]))
    for target in observations["targets"]:
        fid = target["formal_id"]
        ids = targets[fid]["capture_event_ids"]
        if target["no_observation_reason"]:
            check(f"observation/{fid}/none", "observation_scope", target["no_observation_reason"],
                  _capture_entries(frozen, ids))
        for index, row in enumerate(target["observations"], 1):
            require(row["capture_event_id"] in ids and row["concept_key"] in prospective, "quality_observation_scope")
            check(f"observation/{fid}/{index}", "formal_observation", row,
                  _capture_entries(frozen, [row["capture_event_id"]]))
    for key in ("observations", "priors", "outcomes", "profiles"):
        if draft.get(key):
            files[draft[key]] = sha(within(folder, draft[key]).read_bytes())
    if draft.get("profiles"):
        if prepared_profile is None:
            raw_profiles = _material(folder, draft["profiles"])
            prepared_profile = profiles.prepare_updates(root, raw_profiles, prospective_concepts=prospective)
        for row in prepared_profile["updates"]:
            key = row["concept_key"]
            require(key in concept_units, "quality_profile_outside_draft")
            units = sorted(concept_units[key])
            if existing_basis is None:
                path = root / profiles.SEMANTIC / (key + ".json")
                before_profiles[key] = read(path) if path.is_file() else {}
            old = before_profiles.get(key, {})
            for field in PROFILE_FIELDS:
                value = row.get(field)
                if isinstance(value, list):
                    for i, member in enumerate(value, 1):
                        if existing_basis is None and member in old.get(field, []):
                            before[f"profile/{key}/{field}/{i}"] = digest(member)
                            continue
                        # Ordered connections bind local card/observation evidence.
                        # Their mathematical use is reviewed in the source card and method.
                        check(f"profile/{key}/{field}/{i}", "profile_" + field, member,
                              units, protected=field == "solution_connections")
                else:
                    check(f"profile/{key}/{field}", "profile_" + field, value, units,
                          prior=old.get(field))
    inventory = {"entries": entries, "cards": card_rows, "files": files, "before": before,
                 "profile_sha256": digest(prepared_profile) if prepared_profile is not None else None}
    if "profile_prior_closeout_ids" in draft:
        ids = draft["profile_prior_closeout_ids"]
        require(prepared_profile is not None and isinstance(ids, list) and len(ids) == len(set(ids)),
                "quality_profile_closeout_scope")
        predecessors = {}
        for event_id in ids:
            event = replay["closeouts"].get(event_id)
            require(event and event["study_date"] < frozen["study_date"]
                    and event_id not in replay["invalidated_closeouts"], "quality_profile_predecessor_invalid")
            predecessors[event_id] = event["content_hash"]
        inventory["profile_predecessors"] = predecessors
    return inventory, prepared_profile


def _sections(body):
    sections = {}
    name, start = "正文", 0
    for match in re.finditer(r"(?m)^##\s+([^\n]+)\n", body):
        sections[name] = body[start:match.start()].strip()
        name, start = match[1].strip(), match.end()
    sections[name] = body[start:].strip()
    return sections


def requirements(qi, folder, draft):
    folder = workspace(qi.REPO_ROOT, folder)
    frozen = read(folder / "frozen.json")
    scope_bindings(qi, frozen["freeze_id"], live=True)
    require(baseline_matches(qi.REPO_ROOT, frozen["baseline"]), "quality_baseline_changed_before_prepare")
    inventory, profile = draft_entries(qi, folder, frozen, draft)
    if profile is not None:
        write(folder / "prepared-profiles.json", profile)
    document = {"schema": "math-quality-requirements-v1", "draft": draft,
                "frozen_sha256": digest(frozen), **inventory}
    write(folder / "requirements.json", document)
    return document


def _check_candidates(folder, frozen, candidate, journal):
    require(candidate["run_id"] == frozen["run_id"] and candidate["mode"] == journal.mode
            and candidate["frozen_sha256"] == digest(frozen) and candidate["initial"].keys() == frozen["units"].keys(),
            "quality_candidate_binding")
    for uid, row in frozen["units"].items():
        journal.verify("initial", "embeddings", uid, candidate["initial"][uid],
                       input_hash("embeddings", row["query"], None))
    seen = set()
    upgraded = frozen.get("candidate_policy") == CANDIDATE_POLICY
    if upgraded:
        import math_semantic_candidates as semantic
        require(candidate.get("candidate_policy") == CANDIDATE_POLICY and
                candidate.get("evidence_groups") == {
                    uid: semantic.same_capture_group(frozen["sources"][u["capture_id"]], u["turns"])
                    for uid,u in frozen["units"].items()},
                "quality_candidate_turn_group_changed")
    for row in candidate["judgments"].values():
        seen.add(row["unit"])
        for key, value in row["predicates"].items():
            result = journal.verify(row["purpose"], "decisions", key, row["uses"][key],
                                    input_hash("decisions", value, row["evidence"]))
            require(result == row["probabilities"][key], "quality_decision_value_changed")
        if upgraded:
            match = candidate["catalog"].get(row["candidate"])
            advice = semantic.advisory(row["probabilities"], match)
            require(all(row["advisory"].get(k) == v for k,v in advice.items())
                    and row["advisory"]["source_hashes"] ==
                    ([r["sha256"] for r in match["source_refs"]] if match else []),
                    "quality_candidate_advisory_changed")
    require(seen == frozen["units"].keys(), "quality_candidate_judgments_incomplete")


def verify_candidate_receipts(root, folder, *, formal_id=None):
    """Read the real begin receipt without calling a model or advancing a freeze."""
    import math_semantic_candidates as semantic
    folder = workspace(root, folder)
    frozen, candidate = (read(folder / name) for name in ("frozen.json", "candidates.json"))
    require(candidate["mode"] == "live", "quality_verification_requires_real_receipts")
    journal = Journal(folder, frozen["run_id"])
    _check_candidates(folder, frozen, candidate, journal)
    embeddings = set()
    for row in candidate["catalog"].values():
        text = row["text"]
        key = _vector_key(text, row.get("input_identity"))
        origin = row.get("history_vector_origin")
        if origin:
            require(origin["mode"] == "live", "quality_historical_vector_not_live")
            previous = Journal(workspace(root, origin["workspace"]), origin["run_id"])
            previous.verify(origin["purpose"], "embeddings", key, origin["use"], input_hash("embeddings", text, None))
        else:
            journal.verify("historical", "embeddings", key, candidate["historical"][key],
                           input_hash("embeddings", text, None))
        embeddings.add(key)
    units = {uid for uid,row in frozen["units"].items()
             if formal_id is None or frozen["sources"][row["capture_id"]]["formal_id"] == formal_id}
    require(bool(units), "quality_candidate_exact_formal_id_not_in_scope")
    advisories = []
    for identity, row in candidate["judgments"].items():
        if row["unit"] not in units:
            continue
        part = candidate["catalog"].get(row["candidate"])
        advisories.append({"judgment_id": identity, "origin": row["channel"],
                           "source_hashes": [r["sha256"] for r in part["source_refs"]] if part else [],
                           "reference_id": part["stable_id"] if part else None,
                           "advisory": semantic.advisory(row["probabilities"], part)})
    if formal_id is not None:
        # Historical decisions are evidence of a real provider call, but an
        # outdated formula may no longer be suggested for a current relation.
        fresh = {}
        for part in candidate["catalog"].values():
            key = part["stable_id"]
            try:
                fresh[key] = all(_source_file(Path(root), ref) for ref in part["source_refs"])
            except (OSError, ValueError):
                fresh[key] = False
        advisories = [row for row in advisories if fresh.get(row["reference_id"])]
    return {"status": "VERIFIED_LIVE_RECEIPTS", "run_id": frozen["run_id"],
            "candidate_sha256": digest(candidate), "units": len(units), "verified_historical_vectors": len(embeddings),
            "advisory_count": len(advisories), "source_channels": sorted({r["origin"] for r in advisories if r["origin"]}),
            **({"formal_id": formal_id, "advisories": advisories} if formal_id else {}),
            "candidate_policy": candidate.get("candidate_policy", "existing_semantic_candidates"),
            "learning_write_count": 0}


def _memory_review_role(role):
    return role.startswith("profile_") or role in {"teaching_slice", "formal_observation"}


def _terminal_rubric(frozen, role):
    if frozen.get("memory_review") == MEMORY_REVIEW and _memory_review_role(role):
        if role in {"profile_next_check", "teaching_slice"}:
            return ("这个核对动作或教学切片是否保留定理的对象和必要条件，并接在有证据的正确前缀及首个断点之后？"
                    "未展示的后续作答应保持未知，不能由讲解推出独立掌握。")
        return ("适用对象、题型和必要条件是否与实际材料相符？是否只归因到本人实际展示的操作与第一处断点，"
                "保留已经正确的前缀，并按发生顺序区分提示前独立、提示后修复、复述、自报和未观察？"
                "新的独立证据只能修正同范围旧判断，不能放大到全题或把同标签的其他断点合并。")
    if role in {"card_text", "card_metadata", "teaching_slice", "profile_next_check"}:
        return "此声明是否可作为与本组数学机制相容、保留必要条件或指出适当下一步的内容？"
    return "给定的角色及先后转述是否支持这条有限范围的裁决或记录？"


def terminal_groups(frozen, statements, candidate, uses):
    references = defaultdict(list)
    for key, use in uses.items():
        if use["action"] in {"adopt", "revise", "keep_conditions"}:
            judgment = candidate["judgments"][key]
            match = candidate["catalog"].get(judgment["candidate"])
            if match:
                references[judgment["unit"]].append(safe(match["text"]))
    grouped = defaultdict(dict)
    for key, row in sorted(statements.items()):
        if row["classification"] == "api":
            grouped[tuple(row["units"])][key] = row
    for ids, group in sorted(grouped.items()):
        context = "材料为匿名的数学证据与按顺序核过的角色转述。本人事实只凭实际学员动作。提示和讲解仅作时序证据。"
        for i, uid in enumerate(ids, 1):
            row = frozen["units"][uid]
            context += f"\n材料{i}\n" + row["query"]
            for reference in references.get(uid, []):
                context += "\n已核参考\n" + reference
            for turn in row["turns"]:
                role = "学员" if turn["role"] == "user" else "讲解"
                context += f"\n{role}阶段：{turn['text']}"
        keys = list(group)
        for start in range(0, len(keys), 16):
            subset = keys[start:start+16]
            purpose = "terminal-" + digest([ids, subset])[:24]
            evidence = context
            predicates = {}
            names = {}
            for index, key in enumerate(subset, 1):
                evidence += f"\n声明{index}\n" + group[key]["text"]
                name = "s-" + digest(key)[:28]
                names[key] = name
                role = group[key]["role"]
                rubric = _terminal_rubric(frozen, role)
                predicates[name] = f"只核声明{index}。{rubric}不要求还原隐去的题面、具体数值或原话。"
            yield purpose, evidence, predicates, names


def finalize(qi, folder, reviewed, *, request=None):
    folder = workspace(qi.REPO_ROOT, folder)
    frozen = read(folder / "frozen.json")
    require(baseline_matches(qi.REPO_ROOT, frozen["baseline"]), "quality_baseline_changed_before_finalize")
    req = read(folder / "requirements.json")
    candidate = read(folder / "candidates.json")
    journal = Journal(folder, frozen["run_id"], request=request)
    _check_candidates(folder, frozen, candidate, journal)
    require(reviewed.get("schema") == "math-quality-reviewed-v1" and
            reviewed["requirements_sha256"] == digest(req) and req["frozen_sha256"] == digest(frozen),
            "quality_reviewed_binding")
    require(reviewed["uses"].keys() == candidate["judgments"].keys()
            and reviewed["statements"].keys() == req["entries"].keys(), "quality_reviewed_coverage")
    for key, row in reviewed["uses"].items():
        require(set(row) == {"action", "position", "reason"}
                and row["action"] in {"adopt", "revise", "reject", "keep_conditions"},
                "quality_candidate_unresolved")
        location = req["entries"].get(row["position"])
        judgment = candidate["judgments"][key]
        require(location and judgment["unit"] in location["units"]
                and (row["action"] == "reject" or location["classification"] == "api"),
                "quality_candidate_adoption_position")
        require(isinstance(row["reason"], str) and row["reason"].strip(), "quality_candidate_reason_missing")
    statements = {}
    for key, row in reviewed["statements"].items():
        expected = req["entries"][key]
        require(row["sha256"] == expected["sha256"] and row["classification"] == expected["classification"],
                "quality_statement_drift")
        require(isinstance(row["units"], list) and row["units"] and
                set(row["units"]) <= set(expected["units"]), "quality_statement_source_scope")
        if row["classification"] == "api":
            safe(row["text"])
        else:
            require("text" not in row and row.get("local_verified") is True, "quality_protected_statement")
        if frozen.get("memory_review") == MEMORY_REVIEW and _memory_review_role(expected["role"]):
            # Decisions only receives redacted role summaries. The author
            # must also check the actual assertion and necessary conditions
            # against the full local sources before requesting that decision.
            require(row.get("local_verified") is True, "quality_full_local_memory_review_required:" + key)
        statements[key] = {**row, "role": expected["role"]}
    terminal, unsupported = {}, {}
    for purpose, evidence, predicates, names in terminal_groups(frozen, statements, candidate, reviewed["uses"]):
        used = journal.stage(purpose, "decisions", predicates, evidence=evidence)
        for key, name in names.items():
            probability = journal.verify(purpose, "decisions", name, used[name],
                                         input_hash("decisions", predicates[name], evidence))
            if probability < .65:
                unsupported[key] = probability
            terminal[key] = {"purpose": purpose, "name": name, "use": used[name]}
    if unsupported:
        write(folder / "terminal-needs-review.json",
              {"requirements_sha256": digest(req), "positions": unsupported})
        raise QualityError(f"quality_terminal_needs_revision:{len(unsupported)}")
    require(terminal, "quality_terminal_api_coverage")
    inputs = {_vector_key(statements[key]["text"]): statements[key]["text"] for key in terminal}
    final_vectors = journal.stage("final", "embeddings", inputs)
    for key in terminal:
        vector_key = _vector_key(statements[key]["text"])
        terminal[key].update(vector_key=vector_key, text_sha256=sha(statements[key]["text"].encode()),
                             embedding=final_vectors[vector_key])
    proof = {"schema": "math-quality-proof-v1", "run_id": frozen["run_id"], "freeze_id": frozen["freeze_id"],
             "mode": journal.mode, "frozen_sha256": digest(frozen), "candidate_sha256": digest(candidate),
             "requirements_sha256": digest(req), "uses": reviewed["uses"], "statements": statements,
             "terminal": terminal}
    proof_sha = digest(proof)
    path = folder / ("proof-" + proof_sha + ".json")
    write(path, proof, immutable=True)
    return {"status": "QUALITY_PREPARED", "proof": str(path), "proof_sha256": proof_sha,
            "terminal_api": len(terminal), "protected": len(statements)-len(terminal)}


def verify_proof(qi, proof_path, *, request=None):
    folder = workspace(qi.REPO_ROOT, Path(proof_path).parent)
    proof = read(proof_path)
    require(Path(proof_path) == folder / ("proof-" + digest(proof) + ".json"), "quality_proof_file_mismatch")
    frozen, req, candidates = (read(folder / x) for x in ("frozen.json", "requirements.json", "candidates.json"))
    journal = Journal(folder, frozen["run_id"], request=request)
    require(proof["schema"] == "math-quality-proof-v1" and
            proof["freeze_id"] == frozen["freeze_id"] and proof["run_id"] == frozen["run_id"]
            and proof["mode"] == journal.mode and proof["frozen_sha256"] == digest(frozen)
            and proof["requirements_sha256"] == digest(req) and proof["candidate_sha256"] == digest(candidates),
            "quality_proof_binding")
    _check_candidates(folder, frozen, candidates, journal)
    profile = read(folder / "prepared-profiles.json") if req["profile_sha256"] else None
    projected, _ = draft_entries(qi, folder, frozen, req["draft"],
                                 existing_basis=req["before"], prepared_profile=profile)
    require(projected == {k: req[k] for k in projected}, "quality_prepared_bytes_changed")
    require(proof["statements"].keys() == req["entries"].keys() and proof["uses"].keys() == candidates["judgments"].keys()
            and set(proof["terminal"]) == {k for k, v in req["entries"].items() if v["classification"] == "api"},
            "quality_proof_coverage")
    for purpose, evidence, predicates, names in terminal_groups(frozen, proof["statements"], candidates, proof["uses"]):
        for key, name in names.items():
            proof_row = proof["terminal"][key]
            expected = req["entries"][key]
            row = proof["statements"][key]
            require(row["sha256"] == expected["sha256"] and row["role"] == expected["role"]
                    and set(row["units"]) <= set(expected["units"]), "quality_terminal_scope_changed")
            if frozen.get("memory_review") == MEMORY_REVIEW and _memory_review_role(row["role"]):
                require(row.get("local_verified") is True, "quality_full_local_memory_review_required:" + key)
            text = safe(row["text"])
            vector_key = _vector_key(text)
            require((proof_row["purpose"], proof_row["name"], proof_row["vector_key"], proof_row["text_sha256"])
                    == (purpose, name, vector_key, sha(text.encode())), "quality_terminal_binding")
            probability = journal.verify(purpose, "decisions", name, proof_row["use"],
                                         input_hash("decisions", predicates[name], evidence))
            require(probability >= .65, "quality_terminal_support_insufficient")
            journal.verify("final", "embeddings", vector_key, proof_row["embedding"], input_hash("embeddings", text, None))
    return folder, proof, frozen, req


def _owned(root, marker=None):
    marker = marker or active(root)
    require(marker is not None, "quality_no_active_writer")
    folder = workspace(root, marker["workspace"])
    path = folder / ("proof-" + marker["proof_sha256"] + ".json")
    require(digest(read(path)) == marker["proof_sha256"], "quality_active_proof_drift")
    return marker, folder, read(folder / "requirements.json")


def _card_hash(path):
    return sha(path.read_bytes()) if path.is_file() else None


def apply_cards(qi, proof_path, *, request=None):
    root = qi.REPO_ROOT
    folder, proof, frozen, req = verify_proof(qi, Path(proof_path).resolve(), request=request)
    require(request is None or root != ROOT, "quality_fixture_proof_in_production")
    proof_sha = digest(proof)
    owner = {"schema": "math-quality-active-v1", "run_id": proof["run_id"], "freeze_id": proof["freeze_id"],
             "workspace": str(folder), "proof_sha256": proof_sha, "status": "WRITING"}
    with qi.exclusive_lock(qi.FORMAL_LOCK_PATH), qi.exclusive_lock(qi.LOCK_PATH):
        replay = state(qi)
        freeze = replay["freezes"][frozen["freeze_id"]]
        require(freeze["content_hash"] == frozen["freeze_sha256"], "quality_freeze_drift")
        prior = active(root)
        if prior is None:
            require(baseline_matches(root, frozen["baseline"]), "quality_baseline_changed_before_first_write")
            qi.verify_freeze_current(freeze, replay)
            require(not qi.freeze_formal_state_changed(freeze), "quality_formal_predecessor_drift")
        else:
            require(prior == owner, "quality_other_writer_or_already_committed")
            qi.verify_freeze_current(freeze, replay)
        receipt_path = folder / "card-apply.json"
        receipt = read(receipt_path) if receipt_path.is_file() else {}
        for fid, row in req["cards"].items():
            target = _card(root, fid, row["path"])
            existing, current = qi.card_path_if_unique(fid)
            require(existing is None or existing == target, "quality_formal_id_collision")
            require(current == row["before"] or (fid in receipt and current == row["sha256"])
                    or (fid in receipt and receipt[fid]["status"] == "verified"
                        and current and _semantic_card(target.read_bytes()) == row["semantic_sha256"]),
                    "quality_unexpected_live_card:" + fid)
        if prior is None:
            write(control(root, "active.json"), owner)
        import math_learning_state
        for fid, row in req["cards"].items():
            target = _card(root, fid, row["path"])
            if receipt.get(fid, {}).get("status") == "verified":
                continue
            receipt[fid] = {"status": "intent", "before": row["before"], "sha256": row["sha256"]}
            write(receipt_path, receipt)
            if _card_hash(target) != row["sha256"]:
                raw = within(folder, row["draft"]).read_bytes()
                require(sha(raw) == row["sha256"], "quality_card_draft_changed")
                math_learning_state.atomic_write(root, target, raw)
            require(_card_hash(target) == row["sha256"], "quality_card_apply_readback")
            receipt[fid]["status"] = "verified"
            write(receipt_path, receipt)
    return {"status": "CARD_APPLIED", "proof_sha256": proof_sha, "cards": receipt}


def require_target(root, formal_id, *, outcome=None):
    """Enforce ownership for the native display/rollback steps of this batch."""
    marker = active(root)
    if marker is None:
        return
    marker, folder, req = _owned(root, marker)
    row = req["cards"].get(formal_id)
    if row is None:
        return
    require(marker["status"] == "WRITING", "quality_native_write_already_committed")
    receipt = read(folder / "card-apply.json")
    require(receipt.get(formal_id, {}).get("status") == "verified"
            and _semantic_card(_card(Path(root), formal_id, row["path"]).read_bytes()) == row["semantic_sha256"],
            "quality_target_without_applied_proof")
    if outcome is not None:
        frozen = read(folder / "frozen.json")
        outcomes = _material(folder, req["draft"]["outcomes"])
        require(any(outcomes[cid]["outcome"] in outcome for cid, binding in frozen["sources"].items()
                    if binding["formal_id"] == formal_id), "quality_outcome_does_not_authorize_rollback")


def verify_method_continuity(root, formal_id, card, previous_fingerprint, current_fingerprint, fingerprint):
    """Bind a semantic recurrence to both native fingerprints without rewriting the card."""
    marker = active(root)
    if marker is None or previous_fingerprint == current_fingerprint:
        return False
    _, folder, req = _owned(root, marker)
    witness_path = folder / "method-continuity" / (formal_id + ".json")
    if not witness_path.is_file():
        return False
    import quick_intake as qi
    require_target(root, formal_id, outcome={"recurrence_recorded"})
    _, proof, frozen, req = verify_proof(qi, folder / ("proof-" + marker["proof_sha256"] + ".json"))
    row = req["cards"][formal_id]
    before = within(folder, "formal-before/" + card.name).read_bytes()
    old_meta, _ = _card_parts(before)
    new_meta, _ = _card_parts(card.read_bytes())
    witness = read(witness_path)
    history = f"card/{formal_id}/meta/wrong_history"
    method = f"card/{formal_id}/meta/method_gap"
    expected = {"formal_id": formal_id, "proof_sha256": marker["proof_sha256"],
                "old_card_sha256": row["before"], "new_card_semantic_sha256": row["semantic_sha256"],
                "previous_fingerprint": previous_fingerprint, "current_fingerprint": current_fingerprint}
    require(witness.get("schema") == "math-quality-method-continuity-v1"
            and all(witness.get(key) == value for key, value in expected.items())
            and witness.get("reason", "").strip() and sha(before) == row["before"]
            and previous_fingerprint and current_fingerprint and fingerprint(old_meta) == previous_fingerprint
            and fingerprint(new_meta) == current_fingerprint
            and history in proof["terminal"] and method in proof["terminal"]
            and witness.get("capture_id") in frozen["sources"]
            and frozen["sources"][witness["capture_id"]]["formal_id"] == formal_id,
            "quality_recurrence_continuity_unverified")
    return True


def canonical_prepared_prior(prior):
    """Expand authored unresolved text without changing its prepared evidence.

    The quality draft predates the typed teaching-context atom contract. Keep
    its bytes and proof immutable; only its unresolved strings inherit the
    already prepared first-break Capture when materializing/comparing context.
    All other fields and already typed atoms remain exact.
    """
    unresolved = prior.get("unresolved", [])
    require(isinstance(unresolved, list), "quality_prior_unresolved_array_required")
    if not any(isinstance(item, str) for item in unresolved):
        return prior
    source = prior.get("first_break", {}).get("source_capture_id")
    require(isinstance(source, str) and source,
            "quality_prior_shorthand_requires_prepared_capture")
    return {**prior, "unresolved": [
        {"text": item, "evidence_origin": "unresolved", "source_capture_id": source}
        if isinstance(item, str) else item for item in unresolved
    ]}


def require_close(qi, raw, *, legacy_receipt=None):
    root = qi.REPO_ROOT
    marker = active(root)
    if marker is None:
        if not enabled(root):
            return
        if raw["freeze_id"] in read(root / CONFIG)["legacy_freezes"]:
            return
        if legacy_receipt:
            validate_legacy_return(qi, raw["freeze_id"], legacy_receipt)
            return
        raise QualityError("quality_close_requires_applied_proof")
    marker, folder, req = _owned(root, marker)
    require(marker["status"] == "WRITING" and raw["freeze_id"] == marker["freeze_id"],
            "quality_close_not_owned")
    rows = {x["formal_id"]: x for x in raw["formal_results"]}
    require(rows.keys() == req["cards"].keys(), "quality_close_card_coverage")
    for fid, row in req["cards"].items():
        require_target(root, fid)
        final = rows[fid]
        require(final["operation"] == row["operation"] and final["card_path_after"] == row["path"]
                and final["card_hash_after"] == _card_hash(root / row["path"]), "quality_close_result_drift")
    outcomes = _material(folder, req["draft"]["outcomes"])
    require({x["capture_event_id"]: x["outcome"] for x in raw["capture_results"]}
            == {k: v["outcome"] for k, v in outcomes.items()}, "quality_close_outcome_drift")
    require(raw.get("concept_observations") == _material(folder, req["draft"]["observations"]),
            "quality_close_observation_drift")
    priors = _material(folder, req["draft"]["priors"])
    for teaching in raw["batch_receipts"]["teaching_contexts"]:
        target = within(root, teaching["context_path"])
        require(read(target)["prior"] == canonical_prepared_prior(priors[teaching["formal_id"]]),
                "quality_close_prior_drift")


def validate_legacy_return(qi, freeze_id, receipt_paths):
    accepted = {}
    for receipt_path in receipt_paths:
        path = Path(receipt_path).resolve()
        workspace(qi.REPO_ROOT, path.parent)
        receipt = read(path)
        require(path.name == "receipt.json" and path.parent.parent.name == "A增强输入"
                and path.parent.name == receipt.get("run_id")
                and receipt.get("schema_version") == "math-enhancement-prepared-input-v1"
                and receipt.get("subject") == "math" and receipt.get("project") == "A"
                and receipt.get("status") == "prepared" and not receipt.get("gaps")
                and receipt.get("artifact_storage") == "t9_workspace_v1",
                "quality_legacy_return_not_verified")
        files = {Path(row["path"]).name: row for row in receipt["staged_files"]
                 if Path(row["path"]).parent.name == path.parent.name}
        for name in ("advice.json", "manifest.json"):
            entry = within(path.parent, name)
            require(name in files and sha(entry.read_bytes()) == files[name]["sha256"],
                    "quality_legacy_staged_input_changed")
        manifest = read(path.parent / "manifest.json")
        require(all(manifest[k] == receipt[k] for k in ("run_id", "source_commit", "input_packages")),
                "quality_legacy_stage_binding_mismatch")
        for row in receipt["input_packages"]:
            key, version = row["package_id"], row["version"]
            require(accepted.get(key, version) == version, "quality_legacy_package_conflict")
            accepted[key] = version
    _, sources, _ = scope_bindings(qi, freeze_id, live=True)
    require(all(accepted.get(row["package_id"]) == row["package_sha256"] for row in sources.values()),
            "quality_legacy_scope_mismatch")


def require_profile(root, payload, events):
    marker = active(root)
    if marker is None:
        return
    selected = [row for row in events if row.get("freeze_id") == marker["freeze_id"]]
    if not selected:
        return
    _, _, req = _owned(root, marker)
    other = {r["event_id"]: r["content_hash"] for r in events if r not in selected}
    require(len(selected) == 1 and other == req.get("profile_predecessors", {})
            and req["profile_sha256"] == digest(payload),
            "quality_profiles_not_bound_to_prepared_payload")
    return True


def _verify_profile_accept(qi, folder, req, events):
    if not req["profile_sha256"]:
        return {}
    add_native(qi.REPO_ROOT)
    import math_learning_profiles as profiles
    payload = read(folder / "prepared-profiles.json")
    require(digest(payload) == req["profile_sha256"], "quality_prepared_profile_drift")
    result = {}
    for row in payload["updates"]:
        key = row["concept_key"]
        actual = read(qi.REPO_ROOT / profiles.SEMANTIC / (key + ".json"))
        require(actual.get("status") == "accepted_semantic_update" and
                set(actual.get("event_ids", [])) == set(events) and
                all(actual.get(k) == row.get(k) for k in STORED_PROFILE_FIELDS),
                "quality_profile_acceptance_missing:" + key)
        require(actual["content_sha256"] == profiles.digest({k: v for k, v in actual.items()
                                                             if k != "content_sha256"}),
                "quality_profile_hash_drift")
        result[key] = actual
    return result


def _contains_protected_teaching_data(value):
    if isinstance(value, dict):
        return any((key in PROTECTED_TEACHING_FIELDS and item not in (None, "", [], {}))
                   or _contains_protected_teaching_data(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_protected_teaching_data(v) for v in value)
    return False


def verify_native_profiles(root, profiles, versions):
    """Read fine-point summaries and verify that parent references stay withheld."""
    import math_teaching_context as teaching

    checked, references = {}, {}
    for key, profile in sorted(profiles.items()):
        views = {}
        reference_only = None
        for view in ("protected", "after_attempt", "direct"):
            output = teaching.resolve_teaching_concepts(
                root, [key], view, TEACHING_READBACK_BYTES, teaching_turn=True)
            rows = output.get("records", [])
            scope = key + ":" + view
            require(output.get("view") == view
                    and output.get("source_version") == versions["version"]
                    and re.fullmatch(r"[0-9a-f]{64}", output.get("version") or "")
                    and len(rows) == 1 and rows[0].get("concept_key") == key,
                    "quality_native_profile_readback:" + scope)
            is_reference = output.get("status") == "source_based"
            require(reference_only is None or is_reference == reference_only,
                    "quality_native_profile_scope_changed:" + scope)
            reference_only = is_reference
            if is_reference:
                points = (output.get("teaching_inputs") or {}).get("points", {})
                allowed_reference_points = {key: {"binding": "reference_only", "profile_status": None}}
                require(rows[0] == {
                    "concept_key": key, "concept_name": profile["concept_name"],
                    "object_role": "topic_reference", "reference_only": True,
                    "fine_point": False, "personal_evidence_eligible": False,
                    "personal_history_status": "not_applicable_to_parent_reference",
                } and output.get("resolution") == {
                    "status": "reference_only", "fine_point": False,
                    "current_point_confirmed": False,
                } and not _contains_protected_teaching_data(output)
                        and (points == {} or (view != "protected" and points == allowed_reference_points)),
                        "quality_native_reference_protection:" + scope)
            else:
                require(output.get("status") == "available"
                        and rows[0].get("status") == "semantic_current",
                        "quality_native_profile_readback:" + scope)
            if not is_reference and view == "protected":
                require(rows[0].keys() <= {"concept_key", "concept_name", "status"}
                        and not _contains_protected_teaching_data(output)
                        and not (output.get("teaching_inputs") or {}).get("points"),
                        "quality_native_profile_protection:" + scope)
            elif not is_reference:
                require(all(rows[0].get(field) == profile[field] for field in ("short_summary", "next_check")),
                        "quality_native_profile_content:" + scope)
            views[view] = {"version": output["version"], "sha256": digest(output)}
        target = references if reference_only else checked
        target[key] = {"accepted_profile_sha256": profile["content_sha256"], "views": views}
    return {"source_version": versions["version"], "formal_version": versions["formal_version"],
            "profiles": checked, **({"reference_only_profiles": references} if references else {})}


def _record_completion(root, result):
    write(control(root, "current.json"), result)
    control(root, "active.json").unlink()


def _recover_completed(root, folder):
    """Finish activating a sealed receipt under the native formal lock."""
    result = read(folder / "complete.json")
    marker = active(root)
    if marker and Path(marker["workspace"]) == folder:
        require(result.get("status") == "VERIFIED_CURRENT"
                and marker["proof_sha256"] == result["proof_sha256"]
                and digest(read(folder / "generation.json")) == result["generation_sha256"],
                "quality_completion_receipt_drift")
        _record_completion(root, result)
    return result


def reconcile(qi, folder):
    root = qi.REPO_ROOT
    folder = workspace(root, folder)
    complete = folder / "complete.json"
    if complete.is_file():
        with qi.exclusive_lock(qi.FORMAL_LOCK_PATH):
            return _recover_completed(root, folder)
    marker, owner_folder, req = _owned(root)
    require(folder == owner_folder, "quality_reconcile_other_workspace")
    path = folder / ("proof-" + marker["proof_sha256"] + ".json")
    _, proof, frozen, req = verify_proof(qi, path)
    replay = state(qi)
    closeout_ids = {replay["closed_by"].get(cid) for cid in frozen["sources"]}
    require(None not in closeout_ids and len(closeout_ids) == 1, "quality_native_closeout_pending")
    closeout = replay["closeouts"][next(iter(closeout_ids))]
    require(closeout["freeze_id"] == frozen["freeze_id"], "quality_closeout_mismatch")
    health = qi.build_backlog_plan(qi.load_jsonl(qi.EVENTS_PATH), frozen["study_date"],
                                  exact_capture_ids=list(frozen["sources"]))
    require(not health["plan"]["global_gate"]["residual"], "quality_archive_or_locator_pending")
    profile_events = closeout_ids | set(req.get("profile_predecessors", {}))
    profiles = _verify_profile_accept(qi, folder, req, profile_events)
    for card in closeout["formal_results"]:
        row = req["cards"][card["formal_id"]]
        current = _card(root, card["formal_id"], row["path"]).read_bytes()
        require(sha(current) == card["card_hash_after"] and _semantic_card(current) == row["semantic_sha256"],
                "quality_actual_card_drift")
    import math_teaching_context as teaching
    teaching_readback = {}
    committed_teaching = {row["formal_id"]: row for row in closeout["batch_receipts"]["teaching_contexts"]}
    for result in closeout["formal_results"]:
        fid = result["formal_id"]
        checked = teaching.verify_context(root, fid)
        committed = committed_teaching[fid]
        if checked.get("reason_code") == "learning_state_changed":
            # Closing and archiving change the live learner-state stamp. Rebind
            # only the original committed context; a later pointer is another operation.
            context = within(root, committed["context_path"])
            pointer = within(root, committed["pointer_path"])
            require(sha(context.read_bytes()) == committed["context_sha256"]
                    and read(pointer)["context_sha256"] == committed["context_sha256"],
                    "quality_teaching_successor_scope_changed:" + fid)
            teaching.materialize_context(root, read(context))
            checked = teaching.verify_context(root, fid)
        require(checked["status"] == "valid" and checked["context_sha256"] == committed["context_sha256"],
                "quality_native_teaching_readback_failed:" + fid)
        teaching_readback[fid] = {key: checked[key] for key in ("context_sha256", "pointer_sha256")}
    versions = identity(root)
    native_readback = verify_native_profiles(root, profiles, versions)
    candidates = read(folder / "candidates.json")
    objective = dict(_previous(root))
    for key, row in candidates["catalog"].items():
        vkey = _vector_key(row["text"], row.get("input_identity"))
        origin = row.get("history_vector_origin") or {
            "workspace": str(folder), "run_id": proof["run_id"], "purpose": "historical",
            "use": candidates["historical"][vkey], "mode": "live",
        }
        objective[key] = {**row, **origin, "vector_key": vkey}
    import math_concept_index as native
    for position, row in proof["statements"].items():
        if not row.get("objective"):
            continue
        match = re.fullmatch(r"card/([^/]+)/section/可迁移结论", position)
        if match is None or position not in proof["terminal"]:
            continue
        fid = match[1]
        card = req["cards"][fid]
        meta, _ = _card_parts((root / card["path"]).read_bytes())
        close = next(x for x in closeout["formal_results"] if x["formal_id"] == fid)
        vec = proof["terminal"][position]
        for label in meta.get("knowledge", []):
            concept = native.concept_key(label)
            key = "h-" + digest([concept, fid, position])[:24]
            objective[key] = {"text": row["text"], "concept_key": concept, "stable_id": position,
                              "role": "conclusion", "source_refs": [{"path": card["path"], "sha256": close["card_hash_after"]}],
                              "workspace": str(folder), "run_id": proof["run_id"], "mode": "live",
                              "purpose": "final", "use": vec["embedding"], "vector_key": vec["vector_key"]}
    evidence = {"schema": PRIVATE_SCHEMA, "run_id": proof["run_id"], "proof_sha256": digest(proof),
                **versions, "closeout_ids": sorted(closeout_ids), "closeout_sha256": closeout["content_hash"],
                "cards": {x["formal_id"]: x["card_hash_after"] for x in closeout["formal_results"]},
                "profiles": {key: row["content_sha256"] for key, row in profiles.items()},
                "profile_prepared_sha256": req["profile_sha256"],
                "profile_closeout_ids": sorted(profile_events),
                "teaching_readback": teaching_readback,
                "local_teaching_readback": native_readback,
                "objective": objective, "candidate_uses": proof["uses"],
                "method_continuity": {
                    p.stem: sha(p.read_bytes()) for p in sorted((folder / "method-continuity").glob("*.json"))
                    if p.stem in req["cards"]
                },
                "statements": {k: {"role": v["role"], "sha256": v["sha256"], "units": v["units"],
                                   "classification": v["classification"], **proof["terminal"].get(k, {})}
                               for k, v in proof["statements"].items()},
                "coverage": {"target_count": len(proof["statements"]), "verified": len(proof["terminal"]),
                             "protected": len(proof["statements"]) - len(proof["terminal"]),
                             "missing": [], "legacy_source_gaps": []}}
    sha256 = digest(evidence)
    result = {key: value for key, value in marker.items() if key not in ("publication_event_id", "source_commit")}
    result.update(status="VERIFIED_CURRENT", native_event_id=closeout["event_id"],
                  generation_sha256=sha256, verification_basis=LOCAL_READBACK,
                  local_teaching_readback=native_readback, **versions)
    with qi.exclusive_lock(qi.FORMAL_LOCK_PATH):
        if complete.is_file():
            return _recover_completed(root, folder)
        require(active(root) == marker and identity(root) == versions
                and _verify_profile_accept(qi, folder, req, profile_events) == profiles,
                "quality_final_identity_drift")
        write(folder / "generations" / (sha256 + ".json"), evidence, immutable=True)
        write(folder / "generation.json", evidence)
        write(complete, result, immutable=True)
        _record_completion(root, result)
    return result


def publication_binding(root, event=None):
    require(active(root) is None, HOLD)
    path = control(root, "current.json")
    if not path.is_file():
        return None
    current = read(path)
    if current.get("verification_basis") != LOCAL_READBACK:
        return None
    versions = identity(root)
    if any(current.get(key) != value for key, value in versions.items()):
        return None
    directory = workspace(root, current["workspace"])
    generation = read(directory / "generation.json")
    require(digest(generation) == current["generation_sha256"]
            and all(generation.get(key) == value for key, value in versions.items())
            and generation.get("local_teaching_readback") == current.get("local_teaching_readback"),
            "quality_publication_generation_drift")
    return {"schema": PUBLIC_SCHEMA, "generation_sha256": current["generation_sha256"]}


def binding_is_expected(root, event, manifest):
    binding = manifest.get("formal_quality")
    require(active(root) is None, HOLD)
    if binding is not None:
        path = control(root, "current.json")
        require(path.is_file(), "quality_publication_receipt_missing")
        current = read(path)
        if current.get("verification_basis") == LOCAL_READBACK:
            require(binding == publication_binding(root, event), "quality_publication_binding_mismatch")
            require(all(manifest.get(key) == current[key] for key in ("version", "formal_version")),
                    "quality_publication_version_mismatch")
        else:
            require(current["publication_event_id"] == event
                    and current["generation_sha256"] == binding["generation_sha256"],
                    "quality_publication_receipt_mismatch")
    return binding


@contextmanager
def publication_window(root, event):
    if not enabled(root) and active(root) is None:
        yield None
        return
    add_native(root)
    import quick_intake as qi
    with qi.exclusive_lock(Path(root) / ROLLBACK / ".正式层写入.lock"):
        yield publication_binding(root, event)


def status(root, folder):
    folder = workspace(root, folder)
    marker = active(root)
    if (folder / "complete.json").is_file():
        result = read(folder / "complete.json")
        return {**result, "status": "LOCAL_COMPLETION_PENDING"} if marker and Path(marker["workspace"]) == folder else result
    if marker and Path(marker["workspace"]) == folder:
        if marker["status"] == "READY_TO_PUBLISH":
            return {**marker, "status": "FORMAL_COMMITTED_LOCAL_READBACK_PENDING"}
        import quick_intake as qi
        freeze = state(qi)["freezes"][marker["freeze_id"]]
        closed = set(freeze["capture_event_ids"]) <= state(qi)["closed_by"].keys()
        return {**marker, "status": "FORMAL_COMMITTED_INDEX_PENDING" if closed else "NATIVE_WRITE_PENDING"}
    if list(folder.glob("proof-*.json")):
        return {"status": "QUALITY_PREPARED"}
    return {"status": "QUALITY_PENDING"}


def main():
    import quick_intake as qi
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name, arg in (("begin", "scope"), ("requirements", "draft"), ("finalize", "reviewed"),
                      ("reconcile", None), ("status", None), ("verify-candidates", None)):
        cmd = commands.add_parser(name)
        cmd.add_argument("--workspace", type=Path, required=True)
        if arg:
            cmd.add_argument("--" + arg, type=Path, required=True)
        if name == "reconcile":
            cmd.add_argument("--publication-verify", type=Path, help=argparse.SUPPRESS)
        if name == "verify-candidates":
            cmd.add_argument("--formal-id", help="Read verified recommendations scoped to one formal problem")
    args = parser.parse_args()
    try:
        if args.command == "begin":
            value = begin(qi, args.workspace, read(args.scope))
            value = {"status": "CANDIDATES_READY", "run_id": value["run_id"],
                     "judgments": len(value["judgments"]), "units": len(value["initial"]),
                     "candidate_policy": value.get("candidate_policy", "existing_semantic_candidates")}
        elif args.command == "requirements":
            value = requirements(qi, args.workspace, read(args.draft))
            value = {"status": "REQUIREMENTS_READY", "requirements_sha256": digest(value),
                     "locations": len(value["entries"])}
        elif args.command == "finalize":
            value = finalize(qi, args.workspace, read(args.reviewed))
        elif args.command == "reconcile":
            value = reconcile(qi, args.workspace)
        elif args.command == "verify-candidates":
            value = verify_candidate_receipts(qi.REPO_ROOT, args.workspace, formal_id=args.formal_id)
        else:
            value = status(qi.REPO_ROOT, args.workspace)
    except (QualityError, OSError, KeyError, ValueError) as exc:
        print(json.dumps({"status": "QUALITY_PENDING", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
