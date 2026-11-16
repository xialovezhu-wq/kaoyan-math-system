"""Derived projection helpers shared by maintenance and bounded readers.

This module never writes learning facts.  Its tables can be rebuilt from the
native index; query functions use only read-only SQLite connections supplied by
their caller.  Directory scans belong to maintenance, not a teaching query.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

NOOP_GUARD_SCHEMA = 'math-projection-noop-guard-v1'
READY_FILE = 'projection-ready.json'
RUNTIME_FILES = ('math_concept_index.py','math_learning_profiles.py','math_concept_sources.py',
                 'math_concept_review.py','math_formal_observations.py','math_problem_methods.py',
                 'math_exam_context.py','math_exam_profile.py','math_formula_registry.py',
                 'math_memory_lifecycle.py','math_memory_projection.py','wrongnet.py')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS profile_dependencies (
            key TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY(key,path));
        CREATE INDEX IF NOT EXISTS profile_dependencies_path ON profile_dependencies(path);
    """)


def maintenance_guard(root):
    """Capture discovery inputs only after a successful, fully checked build."""
    import math_concept_index as native
    root = Path(root).resolve()
    runtime = Path(__file__).resolve().parent
    cache = root/native.BASE/'个人知识点索引/source_cache'
    state_path = cache/'collection_state.json'
    if not state_path.is_file():
        return None
    state = json.loads(state_path.read_text())
    if not isinstance(state.get('input_stamps'), dict) or not state.get('inventory_sha256'):
        return None
    inputs = {}
    for name, stamp in state['input_stamps'].items():
        path = Path(name)
        if path.is_relative_to(root):
            key = str(path.relative_to(root))
        elif path.parent == runtime and path.name in RUNTIME_FILES:
            key = '@runtime/'+path.name
        else:
            # Never silently omit an input whose namespace is not understood.
            return None
        inputs[key] = stamp
    return {'schema':NOOP_GUARD_SCHEMA, 'inputs':inputs,
            'runtime_stamps':{name:native._stamp(runtime/name) for name in RUNTIME_FILES},
            'sidecar_stamps':{str((cache/name).relative_to(root)):native._stamp(cache/name)
                for name in ('collection_state.json','source_inventory.json','stat_cache.json')}}


def record_ready(root, conn, version):
    """Bind the guard to the committed SQLite file, detecting out-of-band edits."""
    import math_concept_index as native
    root=Path(root).resolve()
    if conn.execute('PRAGMA journal_mode').fetchone()[0].lower() == 'wal':
        # Closing a WAL connection can checkpoint/change the main file after
        # this binding.  Keep the complete path until WAL generation binding
        # is available rather than trusting an untracked WAL mutation.
        return
    target=root/native.INDEX
    path=target.parent/READY_FILE
    if path.is_symlink():
        raise ValueError('projection_ready_symlink_forbidden')
    row=conn.execute("SELECT value FROM meta WHERE key='maintenance_guard'").fetchone()
    guard=json.loads(row[0]) if row else None
    if not guard:
        return
    value={'schema':NOOP_GUARD_SCHEMA,'version':version,'index_stamp':native._stamp(target),
           'guard_sha256':native.digest(guard)}
    data=(_json(value)+'\n').encode()
    if path.is_file() and path.read_bytes()==data:
        return
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.projection-ready-',delete=False) as handle:
        temporary=Path(handle.name)
        handle.write(data); handle.flush(); os.fsync(handle.fileno())
    try:
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def unchanged_receipt(root, conn, previous, affected_ids=None):
    """Fast no-op after complete stamp validation, before loading large payloads.

    Every indexed source is checked, including ctime; every previously watched
    directory is checked, so adding or removing a source changes its parent.
    Source-collector discovery inputs and sidecars are checked separately.
    Nothing is skipped merely because the caller supplied an affected-ID hint.
    """
    import math_concept_index as native
    root=Path(root).resolve(); runtime=Path(__file__).resolve().parent
    if conn.execute('PRAGMA journal_mode').fetchone()[0].lower() == 'wal':
        return None
    if previous.get('implementation') != native.canonical(native.IMPLEMENTATION):
        return None
    try:
        guard=json.loads(previous.get('maintenance_guard','null'))
        receipt=json.loads(previous['receipt'])
        version=json.loads(previous['version'])
        ready_path=root/native.INDEX.parent/READY_FILE
        if ready_path.is_symlink():
            return None
        ready=json.loads(ready_path.read_text())
        if (not guard or guard.get('schema')!=NOOP_GUARD_SCHEMA or ready.get('schema')!=NOOP_GUARD_SCHEMA
                or ready.get('version')!=version or ready.get('guard_sha256')!=native.digest(guard)
                or ready.get('index_stamp')!=native._stamp(root/native.INDEX)):
            return None
        if any(native._stamp(runtime/name)!=stamp for name,stamp in guard['runtime_stamps'].items()):
            return None
        namespace={**json.loads(previous['directories']),**json.loads(previous['store_stamps'])}
        checks={str(root/path):stamp for path,stamp in namespace.items()}
        for key,stamp in guard['inputs'].items():
            path=runtime/key[len('@runtime/'):] if key.startswith('@runtime/') else root/key
            checks[str(path)]=stamp
        checks.update({str(root/path):stamp for path,stamp in guard['sidecar_stamps'].items()})
        source_count=0
        for path,stamp in conn.execute('SELECT path,stamp FROM sources'):
            checks[str(root/path)]=json.loads(stamp);source_count+=1
        if any(native._stamp(Path(path))!=stamp for path,stamp in checks.items()):
            return None
        # A commit or namespace change during validation cannot be returned as
        # the previous generation.  Manual content edits keep the same strict
        # source stamp contract as the complete maintenance path.
        if any(native._stamp(root/path)!=stamp for path,stamp in namespace.items()):
            return None
        if ready['index_stamp']!=native._stamp(root/native.INDEX):
            return None
        deltas={table:{'updated':0,'removed':0,'unchanged':row['updated']+row['unchanged']}
                for table,row in receipt.get('table_deltas',{}).items()}
        return {**receipt,'status':'noop','projection_mode':'noop','full_reason':None,
                'parsed_sources':0,'hashed_sources':0,'stat_reused_sources':source_count,
                'affected_ids_hint':affected_ids or [],'recomputed_concept_keys':[],
                'recomputed_concept_count':0,'retained_concept_count':receipt['concept_count'],
                'table_deltas':deltas,'source_collection':{'mode':'noop','reference_scan':False},
                'noop_guard':{'status':'verified','checked_paths':len(checks),
                              'large_payloads_loaded':False,'source_discovery_preserved':True}}
    except (OSError,ValueError,KeyError,TypeError):
        return None


def update_rows(conn, table, columns, rows, key_columns):
    """Apply a deterministic row delta, preserving every unchanged row."""
    names = ",".join(columns)
    previous = {tuple(row[i] for i in key_columns): tuple(row)
                for row in conn.execute(f"SELECT {names} FROM {table}")}
    current = {tuple(row[i] for i in key_columns): tuple(row) for row in rows}
    if len(current) != len(rows):
        raise ValueError("duplicate_projection_row:" + table)
    removed = sorted(set(previous) - set(current))
    changed = [row for key, row in current.items() if previous.get(key) != row]
    where = " AND ".join(columns[i] + "=?" for i in key_columns)
    if removed:
        conn.executemany(f"DELETE FROM {table} WHERE {where}", removed)
    if changed:
        placeholders = ",".join("?" for _ in columns)
        conn.executemany(f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({placeholders})", changed)
    return {"updated": len(changed), "removed": len(removed),
            "unchanged": len(current) - len(changed)}


def check_query_dependencies(root, conn, concept_keys=(), *, global_stores=True):
    """Check global identities plus only sources used by the requested objects.

    Publication/maintenance still performs a full inventory check.  A teaching
    read does not advertise that the entire vault is current.  The formal card
    directory catches new/deleted identities; selected source parents catch
    additions/removals in the selected evidence scope.  Native commit epochs
    invalidate readers before a failed projection can be used as current.
    """
    import math_concept_index as native
    root = Path(root)
    meta = {k: json.loads(v) for k, v in conn.execute(
        "SELECT key,value FROM meta WHERE key IN ('version','implementation','directories','store_stamps','query_directories')")}
    if not meta.get("version"):
        return {"status": "stale", "reason": "index_not_ready", "changed_sources": [], "exam_changed": []}
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # Old indexes retain their old conservative contract until first maintenance.
    legacy = "profile_dependencies" not in tables or "query_directories" not in meta
    stamps = dict(meta.get("store_stamps", {})) if global_stores else {}
    stamps.update(meta.get("directories", {}) if legacy else meta.get("query_directories", {}))
    keys = sorted(set(concept_keys or ()))
    for key in keys:
        if key.startswith('MATH-CONCEPT-'):
            semantic_path = str(native.BASE/'个人知识点索引/语义概况'/(key+'.json'))
            source = conn.execute('SELECT stamp FROM sources WHERE path=?',(semantic_path,)).fetchone()
            # A newly accepted/replaced profile must invalidate this point even
            # when its derived SQL rows have not yet been refreshed.
            stamps[semantic_path] = json.loads(source[0]) if source else None
        if not legacy:
            for path, stamp in conn.execute(
                    'SELECT s.path,s.stamp FROM profile_dependencies d JOIN sources s ON s.path=d.path WHERE d.key=?',
                    ('__correction__:'+key,)):
                stamps[path] = json.loads(stamp)
        for path, stamp in conn.execute(
                "SELECT DISTINCT s.path,s.stamp FROM records r JOIN membership m ON r.id=m.record_id "
                "JOIN json_each(r.payload,'$.source_refs') j "
                "JOIN sources s ON s.path=json_extract(j.value,'$.path') WHERE m.key=?", (key,)):
            if native._hot_source(path):
                stamps[path] = json.loads(stamp)
        # Personal prose, preferences, methods and exam material have distinct
        # guards in _checked_personal_context / checked_projection.  Do not turn
        # one changed textbook into a whole-personal-context failure here.
    changed = sorted(path for path, stamp in stamps.items() if native._stamp(root / path) != stamp)
    exam_paths = {str(path) for path in native.math_exam_context.FILES}
    exam_changed = [path for path in changed if path in exam_paths]
    changed = [path for path in changed if path not in exam_paths]
    return {"status": "stale" if changed else "ready", "version": meta["version"],
            "changed_sources": changed, "exam_changed": exam_changed,
            "checked_path_count": len(stamps), "scope": "legacy_global" if legacy else "selected_dependencies"}


def query_directories(root):
    import math_concept_index as native
    # Source contents have individual guards.  These roots provide cheap
    # namespace-change signals without thousands of per-query directory stats.
    paths = [native.BASE / "错题卡", native.BASE / "个人知识点索引/正式逐点观测",
             Path("数学一回滚复习系统/知识点复盘/正式会话"),
             native.BASE / "个人知识点索引/记忆维护/transactions"]
    return {str(path): native._stamp(Path(root) / path) for path in paths}


def record_semantic_basis(record):
    """A shared ledger append is not a change to every card's observations.

    Full source hashes stay in records and are checked against the current
    snapshot.  Only semantic invalidation excludes hashes of shared stores;
    the exact selected events/history remain part of the digest.
    """
    import math_concept_index as native
    value = dict(record)
    value.pop("metadata", None)  # material projections are guarded separately
    shared = {str(native.STORES[0]), str(native.STORES[1])}
    value["source_refs"] = [{k: v for k, v in ref.items() if not (k == "sha256" and ref.get("path") in shared)}
                            for ref in record.get("source_refs", [])]
    return value


def effective_point_records(root, records, concept_key):
    """Project corrected point observations without changing indexed raw rows."""
    import copy
    import math_memory_lifecycle as lifecycle
    result = []
    for original in records:
        if original.get('kind') not in {'concept_review', 'formal_concept_observation'}:
            result.append(original)
            continue
        record = copy.deepcopy(original)
        summary = record['summary']
        event = {**summary, 'history': record.get('history', {})}
        effective = lifecycle.apply_observation_corrections(root, [event], concept_key=concept_key)[0]
        record['summary'] = {**summary, **{k:v for k,v in effective.items() if k != 'history'},
                             'wrong_session_count': int('wrong' in effective['outcomes']),
                             'observation_count': len(effective['observations'])}
        result.append(record)
    return result
