#!/usr/bin/env python3
"""Derived, source-addressed cross-card concept index. Never writes formal data.

Stable keys identify labels, while content hashes identify evidence versions.
Membership means card association, never proof of a shared personal error.
The resolver reads SQLite plus source/directory stamps, not the card library.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import importlib
import json
import re
import sqlite3
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import wrongnet
import math_exam_context

SCHEMA = "math-concept-index-v1"
ATOMIC_OBSERVATION_IMPLEMENTATION = 16
IMPLEMENTATION = ATOMIC_OBSERVATION_IMPLEMENTATION
BASE = Path("错题知识网络")
INDEX = BASE / "个人知识点索引/index.sqlite3"
ALIASES = BASE / "schema/math_concept_aliases.json"
FORMAL = re.compile(r"^(?:GS|LA|PR)-\d+$")
STORES = [Path("数学一回滚复习系统/复习单元.json"),
          Path("数学一回滚复习系统/复习记录.jsonl"),
          Path("数学一回滚复习系统/快速入库事件.jsonl"), ALIASES,
          BASE / "生成/wrong_questions.json", BASE / "个人知识点索引/formal_commit_epoch.json"]
HOT_STORES = [STORES[0], STORES[1], ALIASES, STORES[5], *math_exam_context.FILES]
BUILD_ONLY_PATHS = ("数学一回滚复习系统/快速入库事件.jsonl", "数学一回滚复习系统/快速入库来源",
                    "数学一回滚复习系统/原始会话归档回执.jsonl",
                    "数学一回滚复习系统/原始会话归档意图", "数学一回滚复习系统/历史证据归档指针")
FORBIDDEN = re.compile(r"answer|solution|question|题干|题目|答案|解析|正确选项|最终结果", re.I)
PERSONAL_FIELDS = ("wrong_point", "wrong_history", "mastery_history")


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text))).casefold()


def concept_key(label: str) -> str:
    return "MATH-CONCEPT-" + hashlib.sha256(normalize(label).encode()).hexdigest()[:24]


def _items(value: Any) -> list:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def _stamp(path: Path) -> list[int] | None:
    try:
        stat = path.stat()
        return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino]
    except FileNotFoundError:
        return None


def _hot_source(path: str) -> bool:
    return not any(path == prefix or path.startswith(prefix+"/") for prefix in BUILD_ONLY_PATHS)


def _safe(value: Any) -> Any:
    """Drop answer/question fields recursively, retaining original evidence text."""
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items() if k == "user_answer_text" or not FORBIDDEN.search(k)}
    if isinstance(value, list):
        return [_safe(v) for v in value]
    return value


def _json_rows(text: str, suffix: str) -> list[dict]:
    if not text.strip():
        return []
    if suffix == ".jsonl":
        values = [json.loads(line) for line in text.split("\n") if line.strip()]
    else:
        value = json.loads(text)
        values = value if isinstance(value, list) else value.get("units", value.get("cards", []))
    return [v for v in values if isinstance(v, dict)]


def _directories(root: Path, extra: tuple = ()) -> dict[str, Any]:
    # Directory mtimes detect additions/removals without reading any card body.
    paths = [BASE / "错题卡", BASE / "wiki/concepts", BASE / "wiki/topics/knowledge_clusters",
             BASE / "方法论库", BASE / "知识树", BASE / "学习记录",
             BASE / "个人知识点索引/正式逐点观测", BASE / "个人知识点索引/语义概况",
             BASE / "个人知识点索引/做题方法",
             BASE / "个人知识点索引/记忆维护/transactions",
             Path("数学一回滚复习系统/知识点复盘/正式会话")] + [Path(p) for p in extra]
    result = {}
    for rel in paths:
        path = root / rel
        result[str(rel)] = _stamp(path)
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_dir():
                    result[str(child.relative_to(root))] = _stamp(child)
    return result


def _evidence_date(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("date", value.get("recorded_at", value.get("timestamp", "")))
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", str(value))
    if match:
        try:
            return date(*(int(x) for x in match.groups())).isoformat()
        except ValueError:
            pass
    return None


def _history_ends(values: list) -> tuple[Any, Any, dict]:
    dated = [(day, position, value) for position, value in enumerate(values) if (day := _evidence_date(value))]
    dated.sort(key=lambda item: (item[0], item[1]))
    return (dated[0][2] if dated else None, dated[-1][2] if dated else None,
            {"first_date": dated[0][0] if dated else "时间未记录",
             "latest_date": dated[-1][0] if dated else "时间未记录",
             "undated_count": len(values)-len(dated),
             "undated_source": "original_history_preserved_in_direct_view",
             "ordering": "explicit_original_date_then_original_position"})


def _event_summary(event: dict | None) -> dict | None:
    if event is None:
        return None
    raw = event["event"]
    fields = ("event_id", "date", "score", "attempt_type", "advances_long_term", "delivered_card_id", "hint_dependency", "independent_correct")
    result = {key: raw[key] for key in fields if key in raw}
    outcome = raw.get("review_outcome", {})
    if isinstance(outcome, dict):
        result["review_outcome"] = {key: outcome[key] for key in ("user_answer_text", "correction_text", "hint_dependency", "independent_correct") if key in outcome}
    return {"source_line": event["ordinal"]+1, "attribution": event["attribution"], **result}


def _db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript("""
      CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS sources (path TEXT PRIMARY KEY, stamp TEXT, sha256 TEXT, payload TEXT);
      CREATE TABLE IF NOT EXISTS concepts (key TEXT PRIMARY KEY, label TEXT, normalized TEXT, payload TEXT);
      CREATE TABLE IF NOT EXISTS lookup (name TEXT, key TEXT, PRIMARY KEY(name,key));
      CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, formal_id TEXT, payload TEXT);
      CREATE INDEX IF NOT EXISTS records_formal_id ON records(formal_id);
      CREATE TABLE IF NOT EXISTS membership (key TEXT, record_id TEXT, PRIMARY KEY(key,record_id));
      CREATE INDEX IF NOT EXISTS membership_key ON membership(key);
      CREATE INDEX IF NOT EXISTS membership_record_key ON membership(record_id,key);
      CREATE TABLE IF NOT EXISTS source_identities (source_id TEXT, formal_id TEXT, card_path TEXT, PRIMARY KEY(source_id,formal_id));
      CREATE TABLE IF NOT EXISTS teaching_profiles (key TEXT, view TEXT, payload TEXT, PRIMARY KEY(key,view));
      CREATE TABLE IF NOT EXISTS formula_projection_refs (
        generation TEXT, key TEXT, view TEXT, card_id TEXT, ordinal INTEGER,
        PRIMARY KEY(generation,key,view,ordinal)
      );
    """)
    import math_memory_projection
    math_memory_projection.ensure_tables(connection)
    return connection


def build_index(repo_root: str | Path, affected_ids: list[str] | None = None, *, force_full: bool = False) -> dict:
    """Atomically refresh complete coverage, reusing unchanged parsed sources.

    affected_ids is an optimization hint only, never a coverage restriction.
    First-seen or changed sources are fully hashed. A previously verified source
    with unchanged size/mtime/ctime/inode reuses its hash and parsed payload.
    """
    root = Path(repo_root).resolve()
    target = root / INDEX
    target.parent.mkdir(parents=True, exist_ok=True)
    with (target.parent / "build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        conn = _db(target)
        try:
            result = _build(root, conn, affected_ids, force_full=force_full)
            import math_memory_projection
            math_memory_projection.record_ready(root, conn, result['version'])
            return result
        finally:
            conn.close()


def _build(root: Path, conn: sqlite3.Connection, affected_ids: list[str] | None, *, force_full: bool = False) -> dict:
    import math_memory_projection as projection
    previous = dict(conn.execute("SELECT key,value FROM meta"))
    if not force_full:
        unchanged = projection.unchanged_receipt(root, conn, previous, affected_ids)
        if unchanged is not None:
            return unchanged
    cached = {row[0]: row[1:] for row in conn.execute("SELECT path,stamp,sha256,payload FROM sources")}
    compatible = previous.get("implementation") == canonical(IMPLEMENTATION)
    previous_concepts = {key: json.loads(payload) for key, payload in conn.execute("SELECT key,payload FROM concepts")} if compatible else {}
    previous_records = {key: json.loads(payload) for key, payload in conn.execute("SELECT id,payload FROM records")} if compatible else {}
    previous_hot = list(conn.execute("SELECT key,view,payload FROM teaching_profiles")) if compatible else []
    previous_dependencies = {}
    if compatible:
        for key, path in conn.execute("SELECT key,path FROM profile_dependencies"):
            previous_dependencies.setdefault(key, set()).add(path)
    sources: dict[str, dict] = {}
    parsed_count = 0
    hashed_count = 0
    reused_count = 0
    exam_stamps = {str(p): _stamp(root / p) for p in math_exam_context.FILES}

    def read(path: Path, kind: str) -> dict:
        nonlocal parsed_count, hashed_count, reused_count
        rel = str(path.relative_to(root))
        before = _stamp(path)
        in_flight = sources.get(rel)
        if in_flight and in_flight['stamp'] != before:
            raise RuntimeError('source_changed_during_build: '+rel)
        if (in_flight and in_flight['stamp'] == before
                and (kind == 'external' or in_flight['payload'].get('kind') == kind)):
            # A later method/source guard needs the verified bytes/hash, not a
            # weaker parser that destroys the card identity cached above.
            reused_count += 1
            return in_flight
        old = cached.get(rel)
        compatible = previous.get("implementation") == canonical(IMPLEMENTATION)
        old_payload = json.loads(old[2]) if old else None
        role_compatible = old_payload is not None and (kind == 'external' or old_payload.get('kind') == kind)
        if old and compatible and role_compatible and json.loads(old[0]) == before:
            # Only hashes already proven by a complete prior read may take this
            # path. ctime also invalidates same-size writes with restored mtime.
            sha = old[1]
            payload = old_payload
            reused_count += 1
        else:
            raw = path.read_bytes()
            hashed_count += 1
            if before != _stamp(path):
                raise RuntimeError("source_changed_during_build: " + rel)
            sha = hashlib.sha256(raw).hexdigest()
            if old and compatible and role_compatible and old[1] == sha:
                payload = old_payload
                source = {"path": rel, "stamp": before, "sha256": sha, "payload": payload}
                sources[rel] = source
                return source
            text = "" if kind == "external" else raw.decode("utf-8")
            if kind == "card":
                meta, body = wrongnet.split_front_matter(text)
                # Parse the complete body; only allowlisted personal sections persist.
                sections = []
                for match in re.finditer(r"(?m)^#{1,6}\s+([^\n]+)\n([\s\S]*?)(?=^#{1,6}\s|\Z)", body):
                    heading, content = match.group(1).strip(), match.group(2).strip()
                    if re.search(r"错因|错误|复发|复习记录|掌握记录|我的作答|学习记录", heading) and not FORBIDDEN.search(heading):
                        sections.append({"heading": heading, "text": content})
                payload = {"kind": kind, "id": str(meta.get("id", "")),
                           "source_identity": {k:meta.get(k) for k in ('source','source_question_id','question_id','source_id')},
                           "labels": _items(meta.get("knowledge")),
                           "evidence_origin": {"formal": meta.get("evidence_origin"),
                                               "method_gap": meta.get("method_gap", {}).get("evidence_origin") if isinstance(meta.get("method_gap"), dict) else None,
                                               "semantic_review": meta.get("semantic_review_trace", {}).get("evidence_origin") if isinstance(meta.get("semantic_review_trace"), dict) else None},
                           "personal": {k: meta[k] for k in PERSONAL_FIELDS if k in meta},
                           "exclusion_context": {k: _safe(meta[k]) for k in ("status", "semantic_review_trace", "identity_status", "quality_hold", "content_hold") if k in meta},
                           "sections": sections}
            elif kind == "material":
                meta, body = wrongnet.split_front_matter(text)
                payload = {"kind": kind, "labels": _items(meta.get("knowledge")),
                           "wiki_id": meta.get("wiki_id"), "title": meta.get("title", path.stem),
                           "text": body, "source_kind": "general_learning_material"}
                if meta.get('anchor_registration') == 'formal_reference_anchor':
                    payload['metadata'] = {'reference_anchor': {
                        'concept_key':meta.get('concept_key'), 'path':rel,
                        'module_ref':meta.get('module_ref'), 'source_scope':meta.get('source_scope'),
                        'source_origin':'user_supplied_derived_reference', 'personal_observation':False}}
            elif kind == "store":
                if path.name == "快速入库事件.jsonl":
                    # Capture acceptance is owned by the explicit source adapter.
                    text = ""
                elif path.name == "wrong_questions.json":
                    text = canonical([{"id": row.get("id", row.get("meta", {}).get("id"))} for row in _json_rows(text, ".json")])
                elif path == root / ALIASES:
                    config = json.loads(text)
                    clean = _safe(config)
                    # Declared lookup names are configuration, not answer-bearing
                    # evidence fields: e.g. 解析式 is a legitimate math phrase.
                    clean["aliases"] = config.get("aliases", {})
                    text = canonical(clean)
                elif path.suffix == ".jsonl":
                    text = "\n".join(canonical(_safe(row)) for row in _json_rows(text, ".jsonl"))
                else:
                    text = canonical(_safe(json.loads(text)))
                payload = {"kind": kind, "text": text}
            elif kind == "external":
                # External source text is supplied by its typed adapter; never cache
                # arbitrary archived conversation or answer-bearing raw bytes.
                payload = {"kind": kind}
            else:
                payload = {"kind": kind, "text": text}
            parsed_count += 1
        source = {"path": rel, "stamp": before, "sha256": sha, "payload": payload}
        # One source can be used in several roles.  Keep the richest canonical
        # typed parse in SQLite while returning the requested parse to callers.
        priority = {'external':0, 'material':1, 'store':2, 'card':3}
        if not in_flight or priority.get(payload.get('kind'), 0) >= priority.get(in_flight['payload'].get('kind'), 0):
            sources[rel] = source
        return source

    import math_formal_observations
    formal_observation_sources = math_formal_observations.prepare_sources(root)
    try:
        extension = importlib.import_module("math_concept_sources")
    except ModuleNotFoundError as error:
        if error.name != "math_concept_sources":
            raise
        extension = None
    extra_watch = tuple(p for p in getattr(extension, "SOURCE_WATCH_PATHS", ()) if _hot_source(str(p)))
    directories = _directories(root, extra_watch)
    cards: dict[str, dict] = {}
    ignored = []
    for path in sorted((root / BASE / "错题卡").rglob("*.md")):
        source = read(path, "card")
        fid = source["payload"]["id"]
        if not FORMAL.fullmatch(fid):
            ignored.append(source["path"])
            continue
        if fid in cards:
            raise ValueError("duplicate_formal_id: " + fid)
        cards[fid] = source
    store_text = {}
    for rel in STORES:
        if (root / rel).is_file():
            store_text[str(rel)] = read(root / rel, "store")["payload"]["text"]
    alias_data = json.loads(store_text.get(str(ALIASES), "{}"))
    aliases = alias_data.get("aliases", {})
    overlays = alias_data.get("card_concepts", {})
    concepts: dict[str, dict] = {}
    names: dict[str, set[str]] = {}
    records: dict[str, dict] = {}
    membership: set[tuple[str, str]] = set()

    def register(label: str) -> str:
        label = unicodedata.normalize("NFKC", str(label)).strip()
        key = concept_key(label)
        concepts.setdefault(key, {"key": key, "label": label, "source_refs": [], "wiki_ids": [], "wiki_paths": []})
        names.setdefault(normalize(label), set()).add(key)
        names.setdefault(normalize(key), set()).add(key)
        return key

    def link(record: dict, labels: list[str]) -> None:
        rid = record["record_id"]
        records[rid] = record
        for label in labels:
            if str(label).strip():
                membership.add((register(str(label)), rid))

    units_rel = str(STORES[0])
    reviews_rel = str(STORES[1])
    units = _json_rows(store_text.get(units_rel, ""), ".json")
    reviews = _json_rows(store_text.get(reviews_rel, ""), ".jsonl")
    units_by_id = {str(unit.get("复习单元ID", unit.get("unit_id", ""))): unit for unit in units}
    reviews_by_card: dict[str, list] = {}
    related_unit_events: dict[str, list] = {}
    for index, event in enumerate(reviews):
        # Match math_learning_state.read_stores: actual delivery takes priority
        # over scheduler anchor. Method units are related evidence only.
        fid = event.get("delivered_card_id")
        attribution = "actual_delivery" if fid else "associated_wrong_card"
        if not fid:
            unit = units_by_id.get(str(event.get("unit_id", "")), {})
            fid = unit.get("关联错题ID", event.get("formal_id", ""))
            if unit.get("类型") not in (None, "", "错题"):
                attribution = "related_unit_only"
        fid = str(fid or "")
        if fid in cards:
            target = related_unit_events if attribution == "related_unit_only" else reviews_by_card
            target.setdefault(fid, []).append({"ordinal": index, "attribution": attribution, "event": _safe(event)})
    unit_by_card: dict[str, list] = {}
    for unit in units:
        fid = str(unit.get("关联错题ID", unit.get("formal_id", "")))
        if fid in cards:
            unit_by_card.setdefault(fid, []).append(_safe(unit))

    for fid, source in cards.items():
        payload = source["payload"]
        labels = list(dict.fromkeys([str(x) for x in payload["labels"] + _items(overlays.get(fid)) if str(x).strip()]))
        source_ref = {"path": source["path"], "sha256": source["sha256"]}
        events = reviews_by_card.get(fid, [])
        old_record = previous_records.get(fid)
        old_history = old_record.get('history', {}) if old_record else {}
        if (not force_full and old_record and old_record.get('labels') == labels
                and source_ref in old_record.get('source_refs', [])
                and old_history.get('review_events', []) == events
                and old_history.get('review_units', []) == unit_by_card.get(fid, [])
                and old_history.get('related_unit_events', []) == related_unit_events.get(fid, [])):
            retained = copy.deepcopy(old_record)
            retained['source_refs'] = [{**ref, 'sha256':sources[ref['path']]['sha256']}
                if ref['path'] in (units_rel,reviews_rel) and ref['path'] in sources else ref
                for ref in retained['source_refs']]
            link(retained, labels)
            continue
        chronological = sorted([event for event in events if _evidence_date(event["event"])],
                               key=lambda event: (_evidence_date(event["event"]), event["ordinal"]))
        personal = payload["personal"]
        wrong = _items(personal.get("wrong_history"))
        mastery = _items(personal.get("mastery_history"))
        first_wrong, latest_wrong, wrong_dates = _history_ends(wrong)
        _, latest_mastery, mastery_dates = _history_ends(mastery)
        summary = {"wrong_point": personal.get("wrong_point"),
                   "first_wrong": first_wrong, "latest_wrong": latest_wrong,
                   "wrong_history_dates": wrong_dates, "mastery_history_dates": mastery_dates,
                   "latest_mastery_history": latest_mastery,
                   "latest_review_event": _event_summary(chronological[-1] if chronological else None),
                   "review_event_undated_count": len(events)-len(chronological)}
        for field in ("correction_text", "hint_dependency"):
            for event in reversed(chronological):
                outcome = event["event"].get("review_outcome", {})
                value = outcome.get(field) if isinstance(outcome, dict) else None
                value = value or event["event"].get(field)
                if value:
                    summary["latest_"+field] = {"date": _evidence_date(event["event"]), "source_line": event["ordinal"]+1, "value": value}
                    break
        # Exact duplicate strings may share a pointer; never semantically merge
        # two different statements, dates, negations, or evidence origins.
        duplicates = {}
        seen_statements = {}
        for field, value in list(summary.items()):
            if isinstance(value, str) and value:
                if value in seen_statements:
                    duplicates[field] = seen_statements[value]
                    del summary[field]
                else:
                    seen_statements[value] = field
        if duplicates:
            summary["exact_duplicate_fields"] = duplicates
        origins = payload.get("evidence_origin", {})
        actual_review = any(event["attribution"] == "actual_delivery" for event in events)
        explicit_personal = any(origin in {"user_observed", "user_confirmed"} for origin in origins.values() if isinstance(origin, str))
        dates = [_evidence_date(value) for value in wrong+mastery+[personal.get("wrong_point", "")]]
        dates += [_evidence_date(event["event"]) for event in events]
        latest_learning_date = max((value for value in dates if value), default=None)
        record = {"record_id": fid, "formal_id": fid, "kind": "personal_card",
                  "source_refs": [source_ref], "labels": labels,
                  "association": "card_associated", "not_proof_of_same_error": True,
                  "summary": summary,
                  "evidence_origin": origins,
                  "retrieval_priority": {"explicit_personal_or_actual_delivery": explicit_personal or actual_review,
                                         "latest_explicit_learning_date": latest_learning_date,
                                         "not_a_mastery_judgment": True},
                  "evidence_counts": {"wrong_history": len(wrong), "mastery_history": len(mastery),
                                      "review_events": len(events), "review_units": len(unit_by_card.get(fid, []))},
                  "history": {**personal, "personal_sections": payload["sections"],
                              "review_events": events, "review_units": unit_by_card.get(fid, []),
                              "related_unit_events": related_unit_events.get(fid, [])},
                  "mastery_inference": "none"}
        for rel in (units_rel, reviews_rel):
            if rel in sources:
                record["source_refs"].append({"path": rel, "sha256": sources[rel]["sha256"]})
        link(record, labels)

    material_sources = []
    for folder in ("wiki/concepts", "wiki/topics/knowledge_clusters", "方法论库", "知识树", "学习记录"):
        for path in sorted((root / BASE / folder).rglob("*.md")):
            source = read(path, "material")
            material_sources.append({"path": source["path"], "sha256": source["sha256"], **source["payload"]})
    source_collection = {'mode':'unavailable'}
    if extension is not None:
        if getattr(extension, 'SUPPORTS_INCREMENTAL', False):
            external_items = extension.collect_sources(root, changed_formal_ids=affected_ids if compatible else None, stats=source_collection)
        else:
            external_items = extension.collect_sources(root)
        for item in external_items:
            path = root / item["path"]
            if path.is_file() and item["path"] not in sources:
                read(path, "external")
            if path.is_file() and sources[item["path"]]["sha256"] != item["sha256"]:
                raise RuntimeError("external_source_hash_mismatch: " + item["path"])
            material_sources.append(item)
    seen_materials = set()
    for material in material_sources:
        # A source may deliberately emit separate capture refs; path-only sources dedupe.
        identity = str(material.get("record_id", material["path"]))
        if material.get("source_kind", "general_learning_material") == "general_learning_material" and material.get("source_refs"):
            identity = material["source_refs"][0]["path"]
        if identity in seen_materials:
            continue
        seen_materials.add(identity)
        labels = list(_items(material.get("labels")))
        for fid in _items(material.get("formal_ids")):
            if fid in records:
                labels.extend(records[fid]["labels"])
        labels = list(dict.fromkeys(labels))
        refs = [{"path": material["path"], "sha256": material["sha256"]}]
        for ref in material.get("source_refs", []):
            path = root / ref["path"]
            if path.is_file() and ref["path"] not in sources:
                read(path, "external")
            if ref["path"] in sources and sources[ref["path"]]["sha256"] != ref["sha256"]:
                raise RuntimeError("external_source_hash_mismatch: " + ref["path"])
            refs.append(ref)
        wiki_id = material.get("wiki_id")
        if wiki_id:
            # A Wiki concept is itself addressable, and maps to its explicit labels.
            for label in labels or [material.get("title", wiki_id)]:
                key = register(label)
                names.setdefault(normalize(wiki_id), set()).add(key)
                concepts[key]["wiki_ids"].append(wiki_id)
                concepts[key]['wiki_paths'].append(material['path'])
        if not labels and material.get("title"):
            labels = [material["title"]]
        record = {"record_id": "source:" + digest(identity)[:24], "formal_id": None,
                  "kind": material.get("source_kind", "general_learning_material"),
                  "source_refs": refs,
                  "labels": labels, "text": material.get("text", ""),
                  "metadata": _safe(material.get("metadata", {})),
                  "association": "learning_material_not_personal_error",
                  "not_proof_of_same_error": True}
        link(record, labels)

    # Independent review sessions attach to existing concept keys, never to
    # card review histories. Error mechanisms remain observation fields.
    import math_concept_review
    for record in math_concept_review.collect_records(root, read):
        if concept_key(record["labels"][0]) != record["concept_key"]:
            raise ValueError("concept_review_binding_mismatch")
        link(record, record["labels"])

    formal_recorded = {event['event_id']: event.get('closed_at') or event.get('recorded_at')
                       for _, event, _ in formal_observation_sources}
    for record in math_formal_observations.collect_records(root, read, formal_observation_sources):
        recorded = formal_recorded.get(record['summary']['event_id'])
        if recorded:
            record['summary']['recorded_at'] = recorded
        link(record, record["labels"])

    import math_memory_lifecycle
    maintenance_by_key = {}
    for transaction in math_memory_lifecycle.transactions(root):
        path = math_memory_lifecycle.TRANSACTIONS / (math_memory_lifecycle.digest(transaction['request_id'])+'.json')
        source = read(root/path, 'external')
        for correction in transaction['corrections']:
            refs = maintenance_by_key.setdefault(correction['concept_key'], {})
            refs[str(path)] = source['sha256']
            for ref in correction.get('source_refs', []):
                evidence = read(root/ref['path'], 'external')
                if evidence['sha256'] != ref['sha256']:
                    raise RuntimeError('memory_correction_source_changed:'+ref['path'])
                refs[ref['path']] = evidence['sha256']

    alias_problems = []
    for alias, raw in aliases.items():
        targets = raw.get("canonical_labels", []) if isinstance(raw, dict) else _items(raw)
        resolved = set()
        unknown = []
        for label in targets:
            keys = names.get(normalize(label), set())
            if keys:
                resolved.update(keys)
            else:
                unknown.append(label)
        exact = names.get(normalize(alias), set())
        if unknown or (exact and not exact.issubset(resolved)):
            alias_problems.append({"alias": alias, "unknown_targets": unknown,
                                   "reason": "unknown_target" if unknown else "conflicting_exact_label"})
            continue
        names.setdefault(normalize(alias), set()).update(resolved)

    members_by_key = {}
    for key, rid in membership:
        members_by_key.setdefault(key, []).append(rid)
    # Each record's canonical evidence bytes are independent of its many
    # memberships.  Encode once, then hash the same canonical list framing.
    record_basis_bytes = {rid: canonical(projection.record_semantic_basis(record)).encode()
                          for rid, record in records.items()}
    for key, concept in concepts.items():
        linked = sorted(members_by_key.get(key, ()))
        concept["formal_ids"] = sorted({records[rid]["formal_id"] for rid in linked if records[rid]["formal_id"]})
        import math_memory_projection as projection
        content_hash = hashlib.sha256(b'[[')
        for position, rid in enumerate(linked):
            if position:
                content_hash.update(b',')
            content_hash.update(record_basis_bytes[rid])
        content_hash.update(b'],')
        content_hash.update(canonical(maintenance_by_key.get(key, {})).encode())
        content_hash.update(b']')
        concept['content_sha256'] = content_hash.hexdigest()
        concept["wiki_ids"] = sorted(set(concept["wiki_ids"]))
        concept['wiki_paths'] = sorted(set(concept['wiki_paths']))
        reviews = projection.effective_point_records(root,
            [records[rid] for rid in linked if records[rid].get("kind") == "concept_review"], key)
        concept["review_markers"] = {
            "session_count": len(reviews),
            "wrong_session_count": sum(row["summary"]["wrong_session_count"] for row in reviews),
            "observation_count": sum(row["summary"]["observation_count"] for row in reviews),
            "latest_study_date": max((row["summary"]["study_date"] for row in reviews), default=None),
            "count_scope": "new_concept_review_sessions_only_not_card_history"}
        concept["review_page"] = str(math_concept_review.PAGES / (key + ".md"))
    del record_basis_bytes
    import math_learning_profiles
    # Semantic compilation is scoped even when maintenance verifies the source
    # inventory.  Global catalog/alias changes legitimately invalidate all
    # concepts; ordinary card/profile changes do not regenerate unrelated pages.
    changed_sources = {path for path, source in sources.items()
                       if path not in cached or cached[path][1] != source['sha256']}
    deleted_sources = {path for path in cached if not (root/path).is_file()}
    import math_problem_methods
    registry_paths = previous_dependencies.get('__registry__', set())
    registry_changed = (force_full or not compatible or bool((changed_sources | deleted_sources) & registry_paths)
                        or any(path not in cached or _stamp(root/path) != json.loads(cached[path][0])
                               for path in registry_paths)
                        or any((root/path).is_file() and str(path) not in cached for path in
                               (math_problem_methods.CATALOG, math_problem_methods.BINDINGS, *math_exam_context.FILES))
                        or any(str(path) in changed_sources for path in
                               (ALIASES, math_problem_methods.CATALOG, math_problem_methods.BINDINGS)))
    selected = set(concepts) if registry_changed else {
        key for key, value in concepts.items()
        if key not in previous_concepts
        or value['content_sha256'] != previous_concepts[key].get('content_sha256')
        or value.get('wiki_ids') != previous_concepts[key].get('wiki_ids')
        or any(_stamp(root/path) != json.loads(cached[path][0])
               for path in previous_dependencies.get(key, ()) if path in cached)
        or (root/math_learning_profiles.SEMANTIC/(key+'.json')).is_file()
           and str(math_learning_profiles.SEMANTIC/(key+'.json')) not in cached}
    dependencies = {key: set(paths) for key, paths in previous_dependencies.items()
                    if key in concepts and key not in selected}
    # Unchanged point projections retain their exact verified sources.  Reusing
    # a source with drift is forbidden; it would have selected the point above.
    for key in set(concepts)-selected:
        for field in ('learning_profile', 'reference_anchors'):
            if field in previous_concepts[key]:
                concepts[key][field] = previous_concepts[key][field]
        for path in previous_dependencies.get(key, ()):
            if path not in sources:
                if path not in cached:
                    raise RuntimeError('source_changed_during_build:'+path)
                old = cached[path]
                old_stamp = json.loads(old[0])
                current_stamp = _stamp(root/path)
                if current_stamp != old_stamp:
                    # A generated page can receive macOS metadata after the
                    # dependency-selection pass. Keep its prior proof here;
                    # the existing final guard below must rehash its bytes.
                    generated_page = path.startswith(str(math_learning_profiles.PAGES) + '/')
                    metadata_only = (generated_page and current_stamp is not None and old_stamp is not None
                        and [current_stamp[i] for i in (0, 1, 3)] == [old_stamp[i] for i in (0, 1, 3)])
                    if not metadata_only:
                        raise RuntimeError('source_changed_during_build:'+path)
                sources[path] = {'path':path,'stamp':old_stamp,'sha256':old[1],'payload':json.loads(old[2])}
    # Reuse textbook attachments for card records when the catalog is unchanged.
    if not registry_changed:
        for rid, record in records.items():
            old_method = previous_records.get(rid, {}).get('metadata', {}).get('problem_solving')
            if old_method is not None:
                record.setdefault('metadata', {})['problem_solving'] = old_method
    generated_hot = math_learning_profiles.enrich_index(root, concepts, records, sources, membership, read,
        only_keys=selected, refresh_registry=registry_changed, dependency_sets=dependencies)
    for key, refs in maintenance_by_key.items():
        if key in concepts:
            dependencies.setdefault(key, set()).update(refs)
            dependencies.setdefault('__correction__:'+key, set()).update(refs)
    hot_profiles = ([row for row in previous_hot if row[0] not in selected
                     and (row[0] in concepts or not registry_changed and not row[0].startswith('MATH-CONCEPT-'))] + generated_hot)
    source_identities = set()
    for fid, source in cards.items():
        identity = source['payload'].get('source_identity', {})
        ids = {str(identity[k]) for k in ('source_question_id','question_id','source_id') if identity.get(k) not in (None,'')}
        text = str(identity.get('source') or '')
        ids.update(re.findall(r'(?<![A-Za-z0-9])[0-9]{5,}(?![A-Za-z0-9])', text))
        ids.update(re.findall(r'(?i)(?<![A-Za-z0-9])ID\s*[:：]\s*([A-Za-z0-9_-]+)', text))
        source_identities.update((identity,fid,source['path']) for identity in ids)
    observed = sorted(cards)
    generated = _json_rows(store_text.get(str(STORES[4]), ""), ".json")
    generated_ids = sorted({str(row.get("id", row.get("meta", {}).get("id", ""))) for row in generated
                            if FORMAL.fullmatch(str(row.get("id", row.get("meta", {}).get("id", ""))))})
    expected = observed  # Full canonical directory enumeration is authoritative.
    coverage = {"expected_count": len(expected), "observed_count": len(observed),
                "authority": "complete_formal_card_directory_enumeration_and_frontmatter_ids",
                "expected_ids": expected, "observed_ids": observed,
                "missing_ids": sorted(set(expected)-set(observed)),
                "unexpected_ids": sorted(set(observed)-set(expected)),
                "generated_index_missing_ids": sorted(set(observed)-set(generated_ids)) if generated else [],
                "generated_index_unexpected_ids": sorted(set(generated_ids)-set(observed)),
                "without_concepts": sorted(fid for fid in cards if not records[fid]["labels"]),
                "indexed_formal_count": sum(bool(records[fid]["labels"]) for fid in cards),
                "excluded": [{"formal_id": fid, "reason": "no_formal_concept_label_no_inference",
                              "source_context": cards[fid]["payload"].get("exclusion_context", {})}
                             for fid in sorted(cards) if not records[fid]["labels"]],
                "ignored_files": ignored}
    source_hashes = {p: s["sha256"] for p, s in sorted(sources.items())}
    version = digest({"schema": SCHEMA, "implementation": IMPLEMENTATION, "sources": source_hashes, "records": records,
                      "names": {k: sorted(v) for k, v in names.items()}, "teaching_profiles":sorted(hot_profiles)})
    stamps = {str(rel): _stamp(root / rel) for rel in HOT_STORES}
    # macOS may attach metadata to a freshly generated learning page after its
    # atomic write. Only these build-owned outputs may accept a ctime-only
    # transition, and only after reading and hashing the exact bytes again.
    # Formal inputs retain the strict stamp gate (including ctime).
    profile_prefix = str(math_learning_profiles.PAGES) + "/"
    for path, source in sources.items():
        if not path.startswith(profile_prefix):
            continue
        current = _stamp(root / path)
        before = source["stamp"]
        if current == before:
            continue
        if (current is not None and before is not None
                and [current[i] for i in (0, 1, 3)] == [before[i] for i in (0, 1, 3)]
                and hashlib.sha256((root / path).read_bytes()).hexdigest() == source["sha256"]
                and _stamp(root / path) == current):
            source["stamp"] = current
    # Reject a changing snapshot rather than committing a mixture of source versions.
    if (directories != _directories(root, extra_watch)
            or any(_stamp(root / p) != s["stamp"] for p, s in sources.items())
            or any(_stamp(root / p) != stamp for p, stamp in exam_stamps.items())):
        raise RuntimeError("source_changed_during_build")
    receipt = {"schema": SCHEMA, "status": "noop" if previous.get("version") == canonical(version) else "ready",
               "version": version, "index_path": str(INDEX), "coverage": coverage,
               "concept_count": len(concepts), "record_count": len(records),
               "source_hashes": source_hashes, "alias_problems": alias_problems,
               "parsed_sources": parsed_count, "hashed_sources": hashed_count,
               "stat_reused_sources": reused_count, "affected_ids_hint": affected_ids or [],
               "projection_mode": "full" if registry_changed else "incremental",
               "source_collection": source_collection,
               "recomputed_concept_keys": sorted(selected),
               "recomputed_concept_count": len(selected),
               "retained_concept_count": len(concepts)-len(selected),
               "full_reason": "explicit_full_repair" if force_full else "initial_or_implementation_change" if not compatible else
                              "shared_registry_or_alias_change" if registry_changed else None}
    with conn:
        metadata = {"schema": SCHEMA, "implementation": IMPLEMENTATION, "version": version, "receipt": receipt,
                           "directories": directories, "store_stamps": stamps,
                           "query_directories": projection.query_directories(root),
                           "maintenance_guard": projection.maintenance_guard(root),
                           "coverage": {k: v for k, v in coverage.items() if k not in {"expected_ids", "observed_ids", "excluded"}},
                           "alias_problems": alias_problems,
                           "scope_notes": alias_data.get("scope_notes", {}),
                           "require_scope_check": alias_data.get("require_scope_check", [])}
        deltas = {}
        for table, columns, rows, primary in (
            ('sources', ('path','stamp','sha256','payload'), [(p,canonical(s['stamp']),s['sha256'],canonical(s['payload'])) for p,s in sources.items()], (0,)),
            ('concepts', ('key','label','normalized','payload'), [(k,c['label'],normalize(c['label']),canonical(c)) for k,c in concepts.items()], (0,)),
            ('lookup', ('name','key'), [(name,key) for name,keys in names.items() for key in keys], (0,1)),
            ('records', ('id','formal_id','payload'), [(rid,r['formal_id'],canonical(r)) for rid,r in records.items()], (0,)),
            ('membership', ('key','record_id'), sorted(membership), (0,1)),
            ('source_identities', ('source_id','formal_id','card_path'), sorted(source_identities), (0,1)),
            ('teaching_profiles', ('key','view','payload'), hot_profiles, (0,1)),
            ('profile_dependencies', ('key','path'), [(key,p) for key,paths in dependencies.items() for p in paths], (0,1))):
            deltas[table] = projection.update_rows(conn, table, columns, rows, primary)
        receipt['table_deltas'] = deltas
        if previous.get('version') == canonical(version) and 'receipt' in previous:
            metadata['receipt'] = json.loads(previous['receipt'])
        projection.update_rows(conn, 'meta', ('key','value'), [(k,canonical(v)) for k,v in metadata.items()], (0,))
    return receipt


def is_personal_record(record: dict) -> bool:
    return record.get("formal_id") is not None or record.get("kind") == "concept_review"


def point_history(repo_root: str | Path, concept_keys: list[str] | None = None, *,
                  valid_at: str | None = None, known_at: str | None = None) -> dict:
    """Read explicit point events from one current snapshot, never infer card errors.

    This maintenance/selection API includes complete saved evidence and is not
    an answer-safe learner surface. Callers must keep it in their evidence bundle.
    """
    from contextlib import closing
    import study_personalization_math as snapshot
    root = Path(repo_root).resolve()
    identity = snapshot.current_identity(root)
    if identity.get("status") != "ready":
        return {"status": identity.get("status", "unavailable"), "reason": identity.get("reason"), "points": []}
    with closing(sqlite3.connect((root / INDEX).as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("BEGIN")
        meta = {k: json.loads(v) for k, v in conn.execute("SELECT key,value FROM meta")}
        if meta.get("version") != identity["version"]:
            return {"status": "stale", "reason": "snapshot_changed", "points": []}
        catalog = {key: json.loads(payload) for key, payload in conn.execute("SELECT key,payload FROM concepts")}
        selected = set(catalog) if concept_keys is None else set(concept_keys)
        unknown = sorted(selected - set(catalog))
        if unknown:
            return {"status": "unknown_concept", "unknown": unknown, "points": []}
        points = []
        checked_sources = set()
        for key in sorted(selected):
            concept = catalog[key]
            events = []
            for (payload,) in conn.execute("SELECT r.payload FROM records r JOIN membership m ON r.id=m.record_id WHERE m.key=? ORDER BY r.id", (key,)):
                record = json.loads(payload)
                if record.get("kind") not in {"concept_review", "formal_concept_observation"}:
                    continue
                for ref in record["source_refs"]:
                    if ref["path"] in checked_sources:
                        continue
                    source = conn.execute("SELECT stamp,sha256 FROM sources WHERE path=?", (ref["path"],)).fetchone()
                    if not source or source[1] != ref["sha256"] or _stamp(root / ref["path"]) != json.loads(source[0]):
                        return {"status": "stale", "reason": "point_source_changed", "changed_source": ref["path"], "points": []}
                    checked_sources.add(ref["path"])
                summary = record["summary"]
                rows = summary["observations"]
                events.append({"event_id": summary["event_id"], "event_type": "formal_intake" if record["kind"] == "formal_concept_observation" else "concept_review",
                               "study_date": summary["study_date"], "episode_id": summary.get("episode_id", summary["event_id"]),
                               "recorded_at": summary.get('recorded_at'),
                               "outcomes": [row["outcome"] for row in rows], "error_details": [row["error_detail"] for row in rows if row["error_detail"]],
                               "source_refs": record["source_refs"], "related_formal_ids": summary["related_formal_ids"],
                               "observations": rows, "history": record["history"], "source_ordinal": summary.get("source_ordinal", 0)})
            import math_memory_lifecycle
            events = math_memory_lifecycle.apply_observation_corrections(root, events,
                valid_at=valid_at, known_at=known_at, concept_key=key)
            history_gaps = [{'event_id': row.get('event_id'), 'reason': row.get('memory_status','event_time_unknown')}
                            for row in events if row.get('memory_status') == 'known_time_unknown' or not row.get('study_date')]
            events = [row for row in events if row.get('memory_status') != 'known_time_unknown' and row.get('study_date')]
            events.sort(key=lambda row: (row["study_date"], row["source_ordinal"], row["event_id"]))
            known_wrong_count = len({row['episode_id'] for row in events if 'wrong' in row['outcomes']})
            point = {"concept_key": key, "label": concept["label"], "formal_ids": concept["formal_ids"], "events": events,
                     "latest_event": events[-1] if events else None,
                     "wrong_episode_count": None if history_gaps else known_wrong_count,
                     "known_wrong_episode_count": known_wrong_count,
                     "history_gaps": history_gaps, "history_complete": not history_gaps,
                     "memory_version": math_memory_lifecycle.version(root, [key]),
                     "valid_at": valid_at, "known_at": known_at}
            point["point_source_version"] = digest(point)
            points.append(point)
    return {"status": "ready", "version": identity["version"], "points": points,
            "count_scope": "explicit_point_events_only_legacy_card_history_is_not_point_error"}


def _view(record: dict, view: str, resolved: list[dict]) -> dict:
    result = {k: v for k, v in record.items() if k not in {"summary", "history", "text", "metadata", "labels"}}
    if view == "protected":
        # A filename such as "...轮换对称截面法.md" is itself a method hint.
        result["source_refs"] = [{"source_key": "source:"+digest(ref["path"])[:24], "sha256": ref["sha256"]}
                                 for ref in record["source_refs"]]
    if view != "protected":
        if "summary" in record:
            result["summary"] = record["summary"]
        if "metadata" in record and view == "direct":
            result["metadata"] = record["metadata"]
        text = canonical(record.get("summary", {}))
        result["directly_named_keys"] = [c["key"] for c in resolved if normalize(c["label"]) in normalize(text)]
        if view == "direct":
            result.update({k: record[k] for k in ("history", "text") if k in record})
    return result


def _bound(result: dict, max_bytes: int) -> dict:
    result["returned_bytes"] = 0
    for _ in range(5):
        size = len(canonical(result).encode())
        if size == result["returned_bytes"]:
            break
        result["returned_bytes"] = size
    if result["returned_bytes"] > max_bytes:
        fallback = {"status": "budget_too_small", "required_min_bytes": result["returned_bytes"]}
        if len(canonical(fallback).encode()) > max_bytes:
            raise ValueError("max_bytes too small for error envelope")
        # A long source path can make even the empty page exceed its budget.
        # Preserve explicit pagination state whenever that small envelope fits.
        empty_page = {**fallback, "returned": 0, "next_cursor": None}
        if len(canonical(empty_page).encode()) <= max_bytes:
            return empty_page
        return fallback
    return result


def resolve_concepts(repo_root: str | Path, concepts: list[str], view: str = "protected",
                     max_bytes: int = 12000, offset: int = 0, material_limit: int | None = None,
                     record_projection=None) -> dict:
    """Resolve exact keys/labels/declared aliases with stable, lossless row pagination.

    Serialize with canonical() to honor the byte contract. A too-large individual
    record is never cut or skipped: required_min_bytes asks for an explicit larger
    evidence slice. Offsets belong to the returned version and query.
    """
    if view not in {"protected", "after_attempt", "direct"}:
        raise ValueError("invalid view")
    if not isinstance(offset, int) or offset < 0 or max_bytes < 64:
        raise ValueError("invalid offset or max_bytes")
    if material_limit is not None and (type(material_limit) is not int or material_limit < 1):
        raise ValueError("material_limit must be positive or None")
    root = Path(repo_root).resolve()
    if not (root / INDEX).is_file():
        return _bound({"schema": SCHEMA, "status": "index_missing", "records": []}, max_bytes)
    conn = sqlite3.connect((root / INDEX).as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("BEGIN")
        meta = {k: json.loads(v) for k, v in conn.execute("SELECT key,value FROM meta WHERE key IN ('schema','version','directories','store_stamps','coverage','alias_problems','scope_notes','require_scope_check')")}
        if not {"schema", "version", "directories", "store_stamps", "coverage", "alias_problems"}.issubset(meta):
            return _bound({"status": "stale", "reason": "index_not_ready_or_schema_outdated", "records": []}, max_bytes)
        import math_memory_projection
        freshness = math_memory_projection.check_query_dependencies(root, conn)
        changed = freshness['changed_sources']
        exam_changed = freshness['exam_changed']
        if changed:
            return _bound({"schema": SCHEMA, "status": "stale", "version": meta["version"],
                           "changed_sources": changed, "records": []}, max_bytes)
        scope_notes = {normalize(k): v for k, v in meta.get("scope_notes", {}).items()}
        scope_checks = {normalize(k) for k in meta.get("require_scope_check", [])}
        query_scope = [{"query": q, "note": scope_notes[normalize(q)],
                        "require_scope_check": normalize(q) in scope_checks}
                       for q in concepts if normalize(q) in scope_notes]
        keys = set()
        unknown = []
        ambiguous = []
        bad_aliases = {normalize(p["alias"]): p for p in meta["alias_problems"]}
        for query in concepts:
            if normalize(query) in bad_aliases:
                ambiguous.append({"query": query, **bad_aliases[normalize(query)]})
                continue
            found = {row[0] for row in conn.execute("SELECT key FROM lookup WHERE name=?", (normalize(query),))}
            if not found:
                unknown.append(query)
            keys.update(found)
        freshness = math_memory_projection.check_query_dependencies(root, conn, keys)
        if freshness['changed_sources']:
            return _bound({'schema': SCHEMA, 'status': 'stale', 'version': meta['version'],
                           'changed_sources': freshness['changed_sources'], 'records': []}, max_bytes)
        exam_changed = sorted(set(exam_changed + freshness['exam_changed']))
        resolved = []
        all_ids = set()
        rows = {}
        for key in sorted(keys):
            concept = json.loads(conn.execute("SELECT payload FROM concepts WHERE key=?", (key,)).fetchone()[0])
            if exam_changed and view != 'protected' and concept.get('learning_profile'):
                profile = concept['learning_profile']
                profile['exam_context'] = math_exam_context.stale(profile.get('exam_context'))
                if 'exam_frequency' in profile:
                    profile['exam_frequency'] = math_exam_context.announcement(profile['exam_context'],view=view)
            all_ids.update(concept["formal_ids"])
            resolved.append({k: v for k, v in concept.items() if k not in {"formal_ids", "source_refs"} and (view != 'protected' or k not in {'learning_profile','reference_anchors'})} | {"formal_count": len(concept["formal_ids"])})
            for rid, payload in conn.execute("SELECT r.id,r.payload FROM records r JOIN membership m ON r.id=m.record_id WHERE m.key=?", (key,)):
                rows[rid] = json.loads(payload)
        # Check only selected evidence paths, never rescan all formal-card contents.
        for path in {ref["path"] for record in rows.values() for ref in record["source_refs"]}:
            if not _hot_source(path):
                continue
            source = conn.execute("SELECT stamp FROM sources WHERE path=?", (path,)).fetchone()
            if source and _stamp(root/path) != json.loads(source[0]):
                changed.append(path)
        if changed:
            return _bound({"schema": SCHEMA, "status": "stale", "version": meta["version"],
                           "changed_sources": changed, "records": []}, max_bytes)
        def ranking(rid):
            record = rows[rid]
            priority = record.get("retrieval_priority", {})
            day = priority.get("latest_explicit_learning_date")
            return (not is_personal_record(record),
                    -int(bool(priority.get("explicit_personal_or_actual_delivery"))),
                    -int(day.replace("-", "")) if day else 0, rid)
        ordered = []
        for rid in sorted(rows, key=ranking):
            projected = _view(rows[rid], view, resolved)
            ordered.append(record_projection(projected, rows[rid], view) if record_projection is not None else projected)
        coverage = meta["coverage"]
        query_version = digest([meta['version'], {p: _stamp(root/p) for p in exam_changed}]) if exam_changed else meta['version']
        result = {"schema": SCHEMA, "status": "ambiguous_concept" if ambiguous else "unknown_concept" if not keys else "available",
                  "version": query_version, "view": view, "resolved": resolved,
                  "unknown": unknown, "ambiguous": ambiguous, "query_scope_notes": query_scope,
                  "coverage": {"expected_count": coverage["expected_count"], "observed_count": coverage["observed_count"],
                               "missing_ids": coverage["missing_ids"], "matched_formal_count": len(all_ids),
                               "matched_formal_ids_sha256": digest(sorted(all_ids))},
                  "evidence_policy": "card_association_is_not_proof_of_same_error; current_attempt_is_authoritative; no_mastery_inference",
                  "order": "explicit_personal_or_actual_delivery_then_recent_explicit_date_then_id;materials_last",
                  "total": len(ordered), "personal_record_count": sum(is_personal_record(r) for r in ordered),
                  "material_record_count": sum(not is_personal_record(r) for r in ordered),
                  "material_limit": material_limit, "returned": 0, "offset": offset,
                  "truncated": offset < len(ordered), "next_cursor": None, "records": [],
                  "max_bytes": max_bytes, "byte_encoding": "utf-8/canonical-json"}
        accumulated_bytes = len(canonical(result).encode())
        material_count = 0
        for record in ordered[offset:]:
            if not is_personal_record(record):
                if material_limit is not None and material_count >= material_limit:
                    break
                material_count += 1
            result["records"].append(record)
            accumulated_bytes += len(canonical(record).encode()) + 1
            result["returned"] = len(result["records"])
            next_offset = offset + result["returned"]
            result["truncated"] = next_offset < len(ordered)
            result["next_cursor"] = {"offset": next_offset, "version": query_version, "query_sha256": digest([sorted(keys), view, material_limit])} if result["truncated"] else None
            # Only serialize the complete envelope near the byte limit. Exporting
            # all rows must not repeatedly serialize the ever-growing full table.
            candidate = _bound(dict(result), max_bytes) if accumulated_bytes + 512 > max_bytes else {"status": "available"}
            if candidate.get("status") == "budget_too_small":
                result["records"].pop()
                if not result["records"]:
                    result["required_min_bytes"] = candidate["required_min_bytes"]
                break
        result["returned"] = len(result["records"])
        next_offset = offset + result["returned"]
        result["truncated"] = next_offset < len(ordered)
        result["next_cursor"] = {"offset": next_offset, "version": query_version, "query_sha256": digest([sorted(keys), view, material_limit])} if result["truncated"] and result["returned"] else None
        if result["truncated"] and not result["returned"]:
            result["status"] = "budget_too_small"
        return _bound(result, max_bytes)
    finally:
        conn.close()


def export_index(repo_root: str | Path, concepts: list[str], output: str | Path,
                 view: str = "protected", format: str = "json") -> dict:
    if not concepts:
        target = Path(repo_root).resolve() / INDEX
        if not target.is_file():
            return {"status": "index_missing"}
        with sqlite3.connect(target.as_uri()+"?mode=ro", uri=True) as conn:
            concepts = [row[0] for row in conn.execute("SELECT key FROM concepts ORDER BY key")]
    result = resolve_concepts(repo_root, concepts, view=view, max_bytes=1024*1024*1024)
    if result["status"] != "available":
        return result
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if format == "json":
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    elif format == "md":
        lines = ["# 个人知识点学习索引", "", "版本："+result["version"], "", "知识点归属不证明个人错因相同。", "",
                 "| 记录 | 来源类别 | 原文精简记录 |", "| --- | --- | --- |"]
        for record in result["records"]:
            text = canonical(record.get("summary", {})) if view != "protected" else "答案保护视图隐藏个人经历"
            lines.append("| "+" | ".join(str(value).replace("|", "\\|").replace("\n", "<br>") for value in [record["record_id"], record["kind"], text])+" |")
        path.write_text("\n".join(lines)+"\n", encoding="utf-8")
    else:
        raise ValueError("invalid format")
    return {"status": "exported", "path": str(path), "version": result["version"], "view": view, "records": result["returned"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--affected-id", action="append")
    build.add_argument('--full', action='store_true', help='Explicit full semantic projection for initialization or repair')
    for command in ("resolve", "export"):
        p = sub.add_parser(command)
        p.add_argument("concepts", nargs="+" if command == "resolve" else "*")
        p.add_argument("--view", choices=["protected", "after_attempt", "direct"], default="protected")
        if command == "resolve":
            p.add_argument("--max-bytes", type=int, default=12000)
            p.add_argument("--offset", type=int, default=0)
        else:
            p.add_argument("--output", type=Path, required=True)
            p.add_argument("--format", choices=["json", "md"], default="json")
    args = parser.parse_args()
    if args.command == "build":
        result = build_index(args.repo_root, args.affected_id, force_full=args.full)
    elif args.command == "resolve":
        result = resolve_concepts(args.repo_root, args.concepts, args.view, args.max_bytes, args.offset)
    else:
        result = export_index(args.repo_root, args.concepts, args.output, args.view, args.format)
    print(canonical(result))


if __name__ == "__main__":
    main()
