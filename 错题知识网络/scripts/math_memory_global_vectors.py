"""OpenAI vectors for the complete math discovery catalog and offline neighbors."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import math_memory_backends as backends

INDEX = backends.CONFIG.parent / "indexes" / "global-vectors.sqlite3"
SCHEMA = "math-global-vectors-v1"
NEIGHBORS = 12
ROOT = Path(__file__).resolve().parents[2]


def _read_index(root):
    return closing(sqlite3.connect((Path(root) / INDEX).as_uri() + "?mode=ro", uri=True))


def _meta(db):
    row = db.execute("SELECT manifest FROM generation").fetchone()
    manifest = json.loads(row[0]) if row else {}
    if manifest.get("schema") != SCHEMA:
        raise ValueError("global_vector_schema_changed")
    return manifest


def _math_content(reference):
    # Ignore new learner observations and archive relocations if the verified
    # mathematical corpus, including the discoverable identities, is unchanged.
    return hashlib.sha256(backends.canonical(
        sorted((row["id"], row["text"]) for row in reference["documents"])
    )).hexdigest()


def _bound_meta(db, reference):
    meta = _meta(db)
    if (meta["reference_version"] != reference["version"]
            and meta["math_content_sha256"] != _math_content(reference)):
        raise ValueError("global_vector_catalog_changed")
    return meta


def neighbor_candidates(root, reference, seeds, *, limit=6):
    """Query by stable identities locally. The caller must validate the view and corpus."""
    if not seeds:
        return []
    with _read_index(root) as db:
        _bound_meta(db, reference)
        scores = {}
        for index, key in enumerate(seeds[:5]):
            for candidate, score in db.execute(
                "SELECT target, similarity FROM neighbors WHERE source=? ORDER BY rank", (key,)
            ):
                if candidate not in seeds:
                    value = score / (1 + index * 0.20)
                    scores[candidate] = max(scores.get(candidate, -1), value)
    return sorted(scores, key=lambda key: (-scores[key], key))[:limit]


def formal_candidates(root, reference, query_vectors, *, model, dimensions, limit=5):
    """Search the same embedding space during formal intake using its existing query vectors."""
    import numpy as np

    with _read_index(root) as db:
        meta = _bound_meta(db, reference)
        if (meta["model"], meta["dimensions"]) != (model, dimensions):
            raise ValueError("global_vector_model_changed")
        rows = db.execute(
            "SELECT m.concept_key, v.vector FROM members m JOIN vectors v USING (input_hash)"
            " WHERE m.fine=1 ORDER BY m.concept_key"
        ).fetchall()
    if not rows or not query_vectors:
        return {}
    keys, blobs = zip(*rows)
    matrix = _unit_rows(np.vstack([np.frombuffer(blob, dtype="<f4") for blob in blobs]))
    if matrix.shape[1] != dimensions:
        raise ValueError("global_vector_dimensions_changed")
    queries = _unit_rows(np.asarray(list(query_vectors.values()), dtype="float32"))
    ranks = np.argsort(-(queries @ matrix.T), axis=1, kind="stable")[:, :limit]
    return {uid: [keys[i] for i in rank] for uid, rank in zip(query_vectors, ranks)}


def _unit_rows(matrix):
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1)
    if not np.all(np.isfinite(norms) & (norms > 0)):
        raise ValueError("global_vector_invalid_norm")
    return matrix / norms[:, None]


def _outbound_rows(reference, safety_check, hash_input):
    members, inputs = {}, {}
    withheld = 0
    for row in reference["documents"]:
        title = safety_check(row["title"], maximum=7000)
        items = ["数学知识点：" + title]
        for text in ("登记名称：" + "；".join(row["aliases"]),
                     *(f["text"] for f in row["fragments"])):
            try:
                checked = safety_check(text, maximum=7000)
            except ValueError:
                withheld += 1
                continue
            if len("\n\n".join([*items, checked]).encode()) <= 7000:
                items.append(checked)
            else:
                withheld += 1
        text = "\n\n".join(items)
        key = hash_input("embeddings", text, None)
        members[row["id"]] = key
        inputs[key] = text
    return members, inputs, withheld


def _cache(root, inputs, api):
    cached = {}
    try:
        with _read_index(root) as db:
            meta = _meta(db)
            if (meta["model"], meta["dimensions"]) != (api.MODEL["embeddings"], api.DIMENSIONS):
                return {}
            for key, raw, raw_sha, origin in db.execute(
                    "SELECT input_hash, vector, sha, request_id FROM vectors"):
                if (key in inputs and len(raw) == 4 * api.DIMENSIONS and api.sha(raw) == raw_sha
                        and api.valid_id(origin)):
                    cached[key] = (raw, raw_sha, origin)
    except (OSError, ValueError, KeyError, sqlite3.Error):
        pass  # Rebuild this derived cache using matching provider receipts if available.
    return cached


def _native_coverage(root, version, included, excluded):
    import math_concept_index as native

    with closing(sqlite3.connect((root / native.INDEX).as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        actual = json.loads(db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
        keys = {key for key, in db.execute("SELECT key FROM concepts")}
        if actual != version or included & excluded or included | excluded != keys:
            raise ValueError("global_vector_native_coverage_changed")
        return dict(db.execute(
            "SELECT COALESCE(json_extract(p.payload, '$.status'), 'missing'), COUNT(*)"
            " FROM concepts c LEFT JOIN teaching_profiles p ON c.key=p.key AND p.view='after_attempt'"
            " GROUP BY 1"
        ))


def _install(path, members, fine, vectors, manifest, check_current):
    from tempfile import TemporaryDirectory
    import numpy as np

    keys = sorted(members)
    matrix = _unit_rows(np.vstack([np.frombuffer(vectors[members[key]][0], dtype="<f4") for key in keys]))
    fine_indices = np.asarray([i for i, key in enumerate(keys) if key in fine], dtype=int)
    if not len(fine_indices):
        raise ValueError("global_vector_no_fine_points")
    fine_matrix = matrix[fine_indices].T.copy()
    with TemporaryDirectory(dir=path.parent, prefix=".global-vectors-") as tmp:
        staged = Path(tmp) / path.name
        with closing(sqlite3.connect(staged)) as db, db:
            db.executescript("""
                CREATE TABLE generation(manifest TEXT NOT NULL);
                CREATE TABLE vectors(input_hash TEXT PRIMARY KEY, vector BLOB, sha TEXT, request_id TEXT);
                CREATE TABLE members(concept_key TEXT PRIMARY KEY, input_hash TEXT, fine INTEGER);
                CREATE TABLE neighbors(source TEXT, rank INTEGER, target TEXT, similarity REAL,
                                       PRIMARY KEY (source, rank));
            """)
            db.execute("INSERT INTO generation VALUES (?)", (json.dumps(manifest, sort_keys=True),))
            db.executemany("INSERT INTO vectors VALUES (?, ?, ?, ?)", ((key, *value) for key, value in vectors.items()))
            db.executemany("INSERT INTO members VALUES (?, ?, ?)",
                           [(key, members[key], key in fine) for key in keys])
            for start in range(0, len(keys), 128):
                similarities = matrix[start:start + 128] @ fine_matrix
                ordered = np.argsort(-similarities, axis=1, kind="stable")[:, :NEIGHBORS + 1]
                rows = []
                for offset, indexes in enumerate(ordered):
                    key = keys[start + offset]
                    targets = [i for i in indexes if keys[fine_indices[i]] != key][:NEIGHBORS]
                    rows.extend((key, rank, keys[fine_indices[i]], float(similarities[offset, i]))
                                for rank, i in enumerate(targets, 1))
                db.executemany("INSERT INTO neighbors VALUES (?, ?, ?, ?)", rows)
            if (db.execute("SELECT COUNT(DISTINCT source) FROM neighbors").fetchone()[0] != len(keys)
                    or db.execute("SELECT COUNT(*) FROM members JOIN vectors USING (input_hash)").fetchone()[0]
                    != len(keys)):
                raise ValueError("global_vector_coverage_missing")
        os.chmod(staged, 0o600)
        check_current()
        os.replace(staged, path)


def refresh(root, *, event_id, version):
    """Refresh after accepted profiles and archive locators. Never writes learning facts."""
    import fcntl
    # Fail before contacting the provider if this runtime cannot build the matrix.
    import numpy  # noqa: F401
    import math_formal_quality as quality
    import math_formal_quality_api as api
    import math_memory_reference_catalog as references
    import math_workflow_storage as storage

    root = Path(root).resolve()
    if root != ROOT:
        raise ValueError("global_vector_live_checkout_required")
    target = root / INDEX
    target.parent.mkdir(parents=True, exist_ok=True)
    with (target.parent / "global-vectors.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = backends._read_config(root)
        discovery = config["backends"]["native"]
        binding = config["reference_semantic"]
        public = backends.read_corpus(Path(discovery["corpus_path"]), discovery["corpus_sha256"])
        ref_path = Path(binding["mathematical_reference_path"])
        if backends.sha(ref_path) != binding["mathematical_reference_sha256"]:
            raise ValueError("global_vector_reference_changed")
        reference = references.load_references(root, ref_path, view="direct", discovery=public)
        if public["source_version"] != version or reference["source_version"] != version:
            raise ValueError("global_vector_source_changed")
        keys = {row["id"] for row in public["documents"]}
        excluded = {row["concept_key"] for row in public.get("excluded_catalog_entries", [])}
        fine = {row["id"] for row in public["documents"] if row.get("knowledge_type") != "parent"}
        if {row["id"] for row in reference["documents"]} != keys or not keys:
            raise ValueError("global_vector_reference_universe_mismatch")
        statuses = _native_coverage(root, version, keys, excluded)

        def check_current():
            latest = backends._read_config(root)
            if (backends.native_version(root) != version
                    or latest["backends"]["native"]["corpus_sha256"] != discovery["corpus_sha256"]
                    or latest["reference_semantic"]["mathematical_reference_sha256"]
                    != binding["mathematical_reference_sha256"]):
                raise ValueError("global_vector_source_changed")

        try:
            with _read_index(root) as db:
                old = _meta(db)
                if (old["source_version"], old["reference_version"], old["event_id"],
                    old["model"], old["dimensions"]) == (version, reference["version"], event_id,
                                                          api.MODEL["embeddings"], api.DIMENSIONS):
                    found = {row[0] for row in db.execute(
                        "SELECT concept_key FROM members JOIN vectors USING (input_hash)"
                        " WHERE length(vector)=?", (4 * api.DIMENSIONS,)
                    )}
                    neighbors = {key for key, in db.execute("SELECT DISTINCT source FROM neighbors")}
                    if (found == keys and neighbors == keys and old["profile_statuses"] == statuses
                            and old["excluded_concepts"] == len(excluded)):
                        check_current()
                        return {**old, "status": "noop", "api_documents_this_call": 0}
        except (OSError, ValueError, KeyError, sqlite3.Error):
            pass

        members, inputs, withheld = _outbound_rows(reference, quality.safe, api.input_hash)
        vectors = _cache(root, inputs, api)
        missing = {key: inputs[key] for key in inputs.keys() - vectors.keys()}
        registration = None
        api_batches = 0
        new_documents = 0
        prompt_tokens = 0
        if missing:
            # Archive metadata or a retry of the closeout can change the local
            # generation without changing any provider input.
            run = "MATH-GLOBAL-" + api.digest([SCHEMA, sorted(missing)])[:40]
            folder = storage.ensure_workspace(storage.WORK_ROOT / "数学全库向量" / run)
            journal = api.Journal(folder, run, seconds=900)
            request_folder = journal.folder / "math-catalog"
            previous_requests = {path.stem for path in request_folder.glob("qmath-*.json")}
            uses = journal.stage("math-catalog", "embeddings", dict(sorted(missing.items())))
            request_ids = set()
            for key, use in uses.items():
                raw = bytes.fromhex(journal.verify("math-catalog", "embeddings", key, use, key))
                request_ids.add(use["request"])
                new_documents += int(use["request"] not in previous_requests)
                vectors[key] = (raw, api.sha(raw), use["request"])
            for request_id in request_ids:
                row = api.read(request_folder / (request_id + ".json"))
                prompt_tokens += row["usage"].get("prompt_tokens", 0)
            api_batches = len(request_ids)
            proof_path = folder / "registration.json"
            if proof_path.is_file():
                registration = api.read(proof_path)
            else:
                proof = storage.register_cold_artifact(
                    journal.folder, purpose="数学全库向量 OpenAI 请求和向量溯源回执")
                registration = proof["receipt_path"]
                api.write(proof_path, registration, immutable=True)

        manifest = {"schema": SCHEMA, "event_id": event_id, "source_version": version,
                    "reference_version": reference["version"], "math_content_sha256": _math_content(reference),
                    "model": api.MODEL["embeddings"], "dimensions": api.DIMENSIONS,
                    "source_concepts": len(keys | excluded),
                    "indexed_concepts": len(keys), "fine_concepts": len(fine),
                    "excluded_concepts": len(excluded),
                    "neighbor_sources": len(keys), "input_vectors": len(inputs),
                    "api_documents": len(missing), "api_documents_this_call": new_documents,
                    "reused_vectors": len(inputs) - new_documents,
                    "verified_api_batches": api_batches, "prompt_tokens": prompt_tokens,
                    "withheld_fragments": withheld, "profile_statuses": statuses,
                    "t9_request_registration": registration}
        _install(target, members, fine, vectors, manifest, check_current)
        with _read_index(root) as db:
            if _bound_meta(db, reference) != manifest:
                raise ValueError("global_vector_readback_failed")
        return {**manifest, "status": "ready"}
