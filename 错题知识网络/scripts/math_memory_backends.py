"""Bounded local candidate retrieval; never an authority for learning evidence.

The adapters only index an explicitly exported, answer-safe discovery corpus.
Native readers authenticate and hydrate the returned stable identities.  Runtime
installation/indexing is an explicit maintenance operation, never a query side
effect.  No adapter falls back to a hosted model.
"""
from __future__ import annotations

import argparse
import atexit
from contextlib import closing
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import select
import signal
import sqlite3
import socket
import subprocess
import sys
import time
from typing import Any

CONFIG = Path("错题知识网络/个人知识点索引/memory-backends/config.json")
SCHEMA = "math-memory-backends-v1"
CORPUS_SCHEMA = "math-memory-corpus-v1"
ENGINES = {"native", "qmd", "basic-memory", "graphiti"}
KEY = re.compile(r"MATH-CONCEPT-[0-9a-f]{24}\Z")
MAX_CORPUS_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
_RUNNER = None
_RUNNER_KEY = None


class BackendError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_corpus(path: Path, expected_hash: str | None = None) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CORPUS_BYTES:
        raise BackendError("discovery_corpus_unavailable")
    data = path.read_bytes()
    if expected_hash and hashlib.sha256(data).hexdigest() != expected_hash:
        raise BackendError("discovery_corpus_changed")
    value = json.loads(data)
    if value.get("schema") != CORPUS_SCHEMA or not isinstance(value.get("source_version"), str):
        raise BackendError("discovery_corpus_schema_invalid")
    if value.get("content_policy") != "safe_discovery_metadata_only":
        raise BackendError("answer_safe_corpus_required")
    docs = value.get("documents")
    if not isinstance(docs, list):
        raise BackendError("discovery_documents_required")
    ids: set[str] = set()
    for doc in docs:
        if not isinstance(doc, dict) or not KEY.fullmatch(str(doc.get("concept_key", ""))):
            raise BackendError("discovery_concept_identity_invalid")
        identity = doc.get("id", doc["concept_key"])
        if not isinstance(identity, str) or identity in ids or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", identity):
            raise BackendError("discovery_document_identity_invalid")
        ids.add(identity)
        doc["id"] = identity
        for field in ("title", "text"):
            if not isinstance(doc.get(field, ""), str) or len(doc.get(field, "")) > 24000:
                raise BackendError("discovery_metadata_invalid")
        if not isinstance(doc.get("aliases", []), list) or any(not isinstance(x, str) for x in doc.get("aliases", [])):
            raise BackendError("discovery_aliases_invalid")
        if not isinstance(doc.get("source_refs", []), list):
            raise BackendError("discovery_sources_invalid")
        for ref in doc.get("source_refs", []):
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not re.fullmatch(r"[0-9a-f]{64}", ref.get("sha256", "")):
                raise BackendError("discovery_source_binding_invalid")
    return value


def _read_config(root: Path, config_path: Path | None = None) -> dict:
    path = config_path or root / CONFIG
    if not path.is_file():
        raise BackendError("backend_not_configured")
    if path.is_symlink() or path.stat().st_size > 65536:
        raise BackendError("backend_config_invalid")
    value = json.loads(path.read_text())
    if value.get("schema") != SCHEMA or not isinstance(value.get("backends", {}), dict):
        raise BackendError("backend_config_invalid")
    from math_runtime_paths import rebase_backend_paths
    return rebase_backend_paths(value, root)


def native_version(root: Path) -> str:
    index = root / '错题知识网络/个人知识点索引/index.sqlite3'
    if not index.is_file():
        raise BackendError('native_index_unavailable')
    with closing(sqlite3.connect(index.as_uri() + '?mode=ro', uri=True)) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()
    if not row:
        raise BackendError('native_version_unavailable')
    version = json.loads(row[0])
    if not isinstance(version, str):
        raise BackendError('native_version_invalid')
    return version


def _offline_environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not (
        "API_KEY" in k or k.endswith("_TOKEN") or k.startswith(("OPENAI_", "ANTHROPIC_", "GEMINI_", "BASIC_MEMORY_"))
    )}
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", DO_NOT_TRACK="1",
               ANONYMIZED_TELEMETRY="false", GRAPHITI_TELEMETRY_ENABLED="false",
               BASIC_MEMORY_CLOUD_MODE="false", BASIC_MEMORY_LOCAL_MODE="true",
               BASIC_MEMORY_FORCE_LOCAL='true', BASIC_MEMORY_FORCE_CLOUD='false',
               BASIC_MEMORY_SEMANTIC_EMBEDDING_PROVIDER='fastembed')
    return env


def run_process(command: list[str], payload: dict, timeout: float, *, env: dict | None = None) -> dict:
    """Bound one process group, including grandchildren, with a wall deadline."""
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env or _offline_environment(), start_new_session=True)
    try:
        stdout, stderr = proc.communicate(canonical(payload), timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.communicate(timeout=0.25)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
        raise BackendError("backend_timeout") from None
    if len(stdout) > MAX_OUTPUT_BYTES:
        raise BackendError("backend_output_budget_exceeded")
    if proc.returncode:
        # Package diagnostics can contain indexed snippets; never copy them to
        # the tutor surface.  Maintenance records the separate runtime error.
        raise BackendError("backend_process_failed")
    try:
        value = json.loads(stdout)
    except (ValueError, UnicodeError):
        raise BackendError("backend_output_invalid") from None
    if not isinstance(value, dict):
        raise BackendError("backend_output_invalid")
    if value.get("error"):
        error = BackendError(str(value["error"])[:120])
        error.diagnostic = stderr.decode(errors='replace')[-8000:]
        raise error
    return value


def close_runtimes(*, force=False):
    global _RUNNER, _RUNNER_KEY
    proc, _RUNNER, _RUNNER_KEY = _RUNNER, None, None
    if proc is None:
        return
    if force:
        try:
            os.killpg(proc.pid,signal.SIGTERM)
            proc.wait(timeout=0.1)
        except (OSError,subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid,signal.SIGKILL)
                proc.wait(timeout=0.1)
            except (OSError,subprocess.TimeoutExpired):pass
        return
    try:
        proc.stdin.close()
        proc.wait(timeout=0.5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired):
                pass


atexit.register(close_runtimes)


def runtime_query(engine: dict, backend: str, query: str, allowed_ids: list[str], limit: int,
                  timeout: float = 8.0, **extra) -> dict:
    """Reuse one local model process; callers own explicit cold/warm reporting."""
    if engine.get('content_policy') in {'mathematical_reference_no_learner_evidence',
                                      'accepted_point_annotations_and_math_references'}:
        from math_memory_reference_catalog import require_reference_view
        require_reference_view(extra.get('view'))
    global _RUNNER, _RUNNER_KEY
    # A new accepted source generation must refresh the queried rows without
    # needlessly unloading an unchanged model. Replaced DB/config/model files
    # still force a fresh runtime.
    stable={k:engine.get(k) for k in ('python','node','qmd_module','database','config_dir','project',
                                    'documents','model','model_cache','local_model_path')}
    if engine.get('database') and Path(engine['database']).exists():
        stat=Path(engine['database']).stat();stable['database_inode']=[stat.st_dev,stat.st_ino]
    if engine.get('config_dir'):
        path=Path(engine['config_dir'])/'config.json'
        stable['config_hash']=sha(path) if path.is_file() else None
    key = hashlib.sha256(canonical([backend, stable])).hexdigest()
    reused = _RUNNER is not None and _RUNNER.poll() is None and _RUNNER_KEY == key
    if not reused:
        close_runtimes()
        env = _offline_environment()
        if backend == 'qmd':
            command = [engine['node'], str(Path(__file__).with_name('math_memory_qmd_runner.mjs'))]
            env['XDG_CACHE_HOME'] = engine['model_cache']
        else:
            command = [engine['python'], str(Path(__file__).with_name('math_memory_backend_runner.py')), '--serve-jsonl']
        _RUNNER = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env, start_new_session=True, bufsize=0)
        _RUNNER_KEY = key
    payload = {'action': 'query', 'backend': backend, 'engine': engine, 'query': query,
               'allowed_ids': allowed_ids, 'limit': limit, **extra}
    deadline = time.monotonic() + timeout
    try:
        _RUNNER.stdin.write(canonical(payload))
        _RUNNER.stdin.flush()
        buffer = b''
        while time.monotonic() < deadline:
            ready, _, _ = select.select([_RUNNER.stdout], [], [], max(0, deadline-time.monotonic()))
            if not ready:
                break
            chunk = os.read(_RUNNER.stdout.fileno(), 65536)
            if not chunk:
                raise BackendError('backend_process_failed')
            buffer += chunk
            if len(buffer) > MAX_OUTPUT_BYTES:
                raise BackendError('backend_output_budget_exceeded')
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                marker = b'MATH_BACKEND_RESULT\t'
                if marker not in line:
                    continue
                value = json.loads(line.split(marker,1)[1])
                if value.get('error'):
                    raise BackendError(str(value['error'])[:120])
                value['runtime_reused'] = reused
                return value
        raise BackendError('backend_timeout')
    except (OSError, ValueError):
        close_runtimes(force=True)
        raise


def _socket_request(path: str, payload: dict, timeout: float) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(path)
        client.sendall(canonical(payload))
        chunks = b''
        while b'\n' not in chunks:
            chunk = client.recv(65536)
            if not chunk: raise BackendError('backend_service_disconnected')
            chunks += chunk
            if len(chunks) > MAX_OUTPUT_BYTES: raise BackendError('backend_output_budget_exceeded')
    return json.loads(chunks.split(b'\n',1)[0])


def ensure_service(root: Path, config_path: Path, socket_path: Path, deadline: float) -> bool:
    """Start/reuse only this configured local cache process, never reindex."""
    if len(str(socket_path).encode()) >= 100 or socket_path.parent.is_symlink():
        raise BackendError('backend_socket_path_invalid')
    socket_path.parent.mkdir(parents=True,exist_ok=True)
    lock_path=socket_path.with_suffix('.launch.lock')
    pid_path=socket_path.with_suffix('.pid.json')
    with lock_path.open('a') as lock:
        os.chmod(lock_path,0o600)
        fcntl.flock(lock,fcntl.LOCK_EX)
        alive=False
        if pid_path.is_file():
            try:
                saved=json.loads(pid_path.read_text())
                if saved.get('config_path')==str(config_path.resolve()):
                    os.kill(saved['pid'],0);alive=True
            except (OSError,ValueError,KeyError,TypeError): pass
        if not alive:
            if socket_path.exists():
                if not socket_path.is_socket():raise BackendError('backend_socket_type_invalid')
                socket_path.unlink()
            process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--repo',str(root),
                '--config',str(config_path),'serve','--socket',str(socket_path)],stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=_offline_environment(),start_new_session=True)
            pid_path.write_bytes(canonical({'pid':process.pid,'config_path':str(config_path.resolve())}))
            os.chmod(pid_path,0o600)
    while time.monotonic()<deadline:
        if socket_path.is_socket():return True
        time.sleep(min(0.05,max(0,deadline-time.monotonic())))
    return False


def _native(query: str, docs: list[dict], limit: int) -> list[dict]:
    # Compatibility helper. Selection, including deliberate abstention, is
    # owned by the precision ranker rather than a score>0 top-k filler.
    from math_memory_retrieval import rank
    selection = rank(query, docs, limit=limit)
    return selection['ranked'] if selection['status'] == 'matched' else []


def candidate_query(repo_root, query, *, concept_keys=None, formal_id=None,
                    view="protected", limit=5, timeout=8.0, backend=None,
                    config_path=None, expected_source_version=None, reference_allowed=True,
                    structured_math=False, _in_service=False) -> dict:
    started = time.monotonic()
    if backend == 'basic_memory':
        backend = 'basic-memory'
    active_config_path=Path(config_path or os.environ.get('MATH_MEMORY_BACKEND_CONFIG') or Path(repo_root)/CONFIG)
    result = {"status": "degraded", "backend": backend or "disabled", "candidates": [],
              "degraded": None, "formal_write_count": 0, "api_requests": 0,
              "answer_safe_metadata_only": True}
    try:
        if view not in {"protected", "after_attempt", "direct"} or not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise BackendError("backend_query_invalid")
        if type(limit) is not int or not 1 <= limit <= 12 or not 0 < timeout <= 8:
            raise BackendError("backend_query_budget_invalid")
        if type(reference_allowed) is not bool or type(structured_math) is not bool:
            raise BackendError('reference_permission_invalid')
        keys = set(concept_keys or [])
        if any(not isinstance(k, str) or not KEY.fullmatch(k) for k in keys):
            raise BackendError("backend_scope_invalid")
        config = _read_config(Path(repo_root), active_config_path)
        selected = backend or config.get("selected", "disabled")
        result["backend"] = selected
        if selected not in ENGINES:
            raise BackendError("backend_disabled")
        engine = config.get("backends", {}).get(selected)
        if not isinstance(engine, dict) or engine.get("status") != "ready":
            raise BackendError("backend_not_ready")
        corpus_path = Path(engine["corpus_path"])
        corpus = read_corpus(corpus_path, engine.get("corpus_sha256"))
        if engine.get("source_version") != corpus["source_version"]:
            raise BackendError("backend_source_version_mismatch")
        current_version = native_version(Path(repo_root))
        if current_version != corpus['source_version'] or (
                expected_source_version is not None and current_version != expected_source_version):
            raise BackendError('backend_source_stale')
        reference_engine=(config.get('reference_semantic') or {}).get('engine')
        semantic_eligible=bool(selected=='native' and isinstance(reference_engine,dict)
            and reference_engine.get('status')=='ready' and view in {'after_attempt','direct'}
            and (config.get('reference_semantic') or {}).get('automatic_selection_enabled',True)
            and reference_allowed and structured_math and not keys and not formal_id)
        if semantic_eligible:
            from math_memory_retrieval import analyze_query
            semantic_eligible=not re.search(r'原话|逐字|学习记录|作答记录|我的历史|本人历史|说过|写过|首答|那句|那条',query) and not analyze_query(query)['formal_ids']
        if config.get('service_socket') and (selected != 'native' or semantic_eligible) and not _in_service:
            payload={'query': query, 'concept_keys': list(keys), 'formal_id': formal_id, 'view': view, 'limit': limit,
                     'timeout': timeout, 'backend': backend, 'expected_source_version': expected_source_version,
                     'reference_allowed':reference_allowed,'structured_math':structured_math}
            try:
                value = _socket_request(config['service_socket'],payload,timeout+0.25)
                value['service_reused'] = True
                return value
            except (OSError, BackendError):
                if not ensure_service(Path(repo_root),active_config_path,
                                      Path(config['service_socket']),started+timeout):
                    raise BackendError('backend_service_starting')
                remaining=max(0.01,timeout-(time.monotonic()-started))
                payload['timeout']=remaining
                value=_socket_request(config['service_socket'],payload,remaining+0.1)
                value.update(service_reused=False,elapsed_ms=round((time.monotonic()-started)*1000,3))
                return value
        docs = [d for d in corpus["documents"] if (not keys or d["concept_key"] in keys)
                and (not formal_id or formal_id in d.get("formal_ids", []))]
        by_id = {d["id"]: d for d in docs}
        selection = None
        if not docs:
            raw = []
            selection = {'status': 'no_match', 'ranked': [], 'reason': 'no_document_in_scope'}
        elif selected == "native":
            from math_memory_retrieval import rank
            selection = rank(query, docs, limit=limit)
            exact=bool(selection.get('ranked') and selection['ranked'][0].get('match_kind') in
                       {'exact_identity','exact_title','exact_declared_alias'})
            if semantic_eligible and not exact:
                from math_memory_semantic import resolve as semantic_resolve
                try:
                    selection,diagnostic=semantic_resolve(repo_root,query,docs,reference_engine,
                        view=view,native_selection=selection,
                        timeout=max(.01,timeout-(time.monotonic()-started)),discovery=corpus)
                    result['semantic_reference']=diagnostic
                except (OSError,ValueError,KeyError,sqlite3.Error) as exc:
                    result['semantic_reference']={'status':'unavailable','reason':str(exc)[:120],
                        'fallback':'native_declared_metadata','model_result_not_used':True}
            raw = selection['ranked'] if selection['status'] == 'matched' else []
        else:
            response = runtime_query(engine, selected, query, list(by_id), limit,
                                     max(0.01, timeout - (time.monotonic() - started)))
            raw = response.get('candidates', [])
            result['runtime_reused'] = response['runtime_reused']
        if not isinstance(raw, list):
            raise BackendError("backend_candidates_invalid")
        if selection is None:
            # External similarity is also only discovery, never an automatic
            # license to attach a learner's unrelated history.
            from math_memory_retrieval import rank
            pool = [by_id[r['id']] for r in raw if isinstance(r, dict) and r.get('id') in by_id]
            selection = rank(query, pool, limit=limit)
            raw = selection['ranked'] if selection['status'] == 'matched' else []
        result['selection_status'] = selection['status']
        result['selection_reason'] = selection.get('reason') or selection.get('reasons')
        result['query_constraints'] = selection.get('constraints', {})
        import math_memory_retrieval
        result['retrieval_version'] = hashlib.sha256(canonical([
            selection.get('schema'), corpus.get('retrieval_revision'),
            sha(Path(math_memory_retrieval.__file__)),
            {k:v for k,v in (result.get('semantic_reference') or {}).items() if k!='runtime_reused'},
            reference_engine.get('reference_version') if semantic_eligible else None])).hexdigest()
        result['disambiguation_candidates'] = []
        if selection['status'] == 'ambiguous':
            for item in selection['ranked'][:2]:
                if item.get('id') in by_id:
                    doc = by_id[item['id']]
                    result['disambiguation_candidates'].append({'concept_key': doc['concept_key'],
                        'concept_name': doc['title'], 'requires_discrimination': True})
        seen = set()
        for row in raw:
            if not isinstance(row, dict) or row.get("id") not in by_id or row["id"] in seen:
                continue
            doc = by_id[row["id"]]
            seen.add(row["id"])
            # Hydrate from the authenticated export, never from backend prose.
            references = doc.get("source_refs", [])
            if view == 'protected':
                references = [{'source_key': 'source:' + hashlib.sha256(r['path'].encode()).hexdigest()[:24],
                               'sha256': r['sha256']} for r in references]
            result["candidates"].append({"concept_key": doc["concept_key"], "record_id": doc["id"],
                "source_refs": references, "source_version": corpus["source_version"],
                "match_basis": row.get('match_kind', selected + '_scoped_match'),
                "match_reasons": row.get('reasons', []), "requires_scope_check": True,
                "reference_only": bool(row.get('reference_only', False)),
                "fine_point": row.get('fine_point', True),
                "personal_evidence_eligible": row.get('personal_evidence_eligible', True),
                "record_scope_required": bool(row.get('record_scope_required', False)),
                "selection_status": selection['status']})
            if len(result["candidates"]) >= limit:
                break
        if native_version(Path(repo_root)) != current_version:
            raise BackendError('native_version_changed_during_query')
        result.update(status="ready", degraded=None, source_version=corpus["source_version"])
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        result["candidates"] = []
        result["degraded"] = str(exc)[:120] if isinstance(exc, BackendError) else type(exc).__name__
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
    return result


def prepare_backend(corpus_path: Path, workspace: Path, runtime_root: Path, backend: str, *,
                    reference_repo_root: Path | None = None,
                    point_context_repo_root: Path | None = None) -> dict:
    """Explicit maintenance only. Caller verifies/registers the T9 workspace."""
    if backend not in ENGINES or workspace.is_symlink():
        raise BackendError('backend_prepare_invalid')
    if reference_repo_root is not None and point_context_repo_root is not None:
        raise BackendError('mixed_private_corpus_contracts')
    if point_context_repo_root is not None:
        if backend != 'qmd':
            raise BackendError('point_context_backend_not_supported')
        from math_memory_point_context import load_point_context
        corpus=load_point_context(point_context_repo_root,corpus_path,view='direct')
    elif reference_repo_root is None:
        corpus = read_corpus(corpus_path)
    else:
        if backend != 'qmd':
            raise BackendError('reference_backend_not_supported')
        from math_memory_reference_catalog import load_references
        corpus=load_references(reference_repo_root,corpus_path,view='direct')
    workspace.mkdir(parents=True, exist_ok=True)
    documents = workspace / backend / 'discovery'
    documents.mkdir(parents=True, exist_ok=True)
    manifest_path=workspace/backend/'export-manifest.json'
    previous=json.loads(manifest_path.read_text()) if manifest_path.is_file() else {'ids':[]}
    current_ids={d['id'] for d in corpus['documents']}
    for identity in set(previous.get('ids',[]))-current_ids:
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',identity):
            raise BackendError('generated_identity_invalid')
        retired=workspace/backend/'retired'/hashlib.sha256(corpus['source_version'].encode()).hexdigest()[:16]
        source=documents/(identity+'.md')
        if source.is_file() and not source.is_symlink():
            retired.mkdir(parents=True,exist_ok=True)
            source.rename(retired/source.name)
    import yaml
    for doc in corpus['documents']:
        metadata = {'title': doc['title'], 'type': 'memory-concept', 'identity': doc['id'],
                    'concept_key': doc['concept_key'],
                    'permalink': 'math-discovery/'+doc['id'].lower(),
                    'qmd': {'metadata': {'identity': doc['id']}}}
        lines = ['---', yaml.safe_dump(metadata, allow_unicode=True, sort_keys=True).rstrip(), '---',
                 '', '# '+doc['title'], '', doc.get('text', ''), '', '## Aliases',
                 *('- '+alias for alias in doc.get('aliases', []))]
        relations = [r for r in corpus.get('relations', []) if r.get('source') == doc['id']]
        if relations:
            lines.extend(['', '## Relations'])
            lines.extend('- '+str(r['type'])+' [['+str(r['target'])+']]' for r in relations)
        target = documents/(doc['id']+'.md')
        content = '\n'.join(lines)+'\n'
        if not target.is_file() or target.read_text() != content:
            target.write_text(content)
    manifest_path.write_bytes(canonical({'ids':sorted(current_ids),'source_version':corpus['source_version']}))
    engine = {'status': 'preparing', 'version': None, 'corpus_path': str(corpus_path.resolve()),
              'corpus_sha256': sha(corpus_path), 'source_version': corpus['source_version'],
              'documents': str(documents.resolve()), 'python': str(runtime_root/'python/bin/python')}
    engine['content_policy']=corpus['content_policy']
    if reference_repo_root is not None or point_context_repo_root is not None:
        engine['reference_version']=corpus['version']
    if backend == 'native':
        engine.update(status='ready', version='native-v1', model=None)
        return engine
    if backend == 'qmd':
        import shutil
        module = runtime_root/'qmd/node_modules/@tobilu/qmd'
        engine.update(version=json.loads((module/'package.json').read_text())['version'],
                      node=shutil.which('node'), qmd_module=str(module/'dist/index.js'),
                      database=str(workspace/backend/'index.sqlite'), model_cache=str(runtime_root/'models'),
                      model='hf:Qwen/Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf')
    elif backend == 'basic-memory':
        config_dir = workspace/backend/'config'
        config_dir.mkdir(exist_ok=True)
        model_cache = runtime_root/'models/fastembed'
        config = {'projects': {'math-discovery': {'path': str(documents), 'mode': 'local'}},
                  'default_project': 'math-discovery', 'log_level': 'ERROR',
                  'logfire_enabled': False, 'logfire_send_to_logfire': False,
                  'semantic_embedding_provider': 'fastembed',
                  'semantic_embedding_model': 'intfloat/multilingual-e5-large',
                  'semantic_embedding_dimensions': 1024,
                  'semantic_embedding_document_prefix': 'passage: ',
                  'semantic_embedding_query_prefix': 'query: ',
                  'semantic_embedding_cache_dir': str(model_cache),
                  'semantic_embedding_threads': 4, 'semantic_embedding_parallel': 1,
                  'semantic_embedding_batch_size': 2, 'semantic_embedding_request_concurrency': 1,
                  'ensure_frontmatter_on_sync': False, 'format_on_save': False,
                  'skip_initialization_sync': False}
        (config_dir/'config.json').write_bytes(canonical(config))
        engine.update(config_dir=str(config_dir), model=config['semantic_embedding_model'], version='1.0.0')
    else:
        engine.update(database=str(workspace/backend/'graph.rdb'), version='0.31.2',
                      model='intfloat/multilingual-e5-large', model_cache=str(runtime_root/'models/fastembed'))
    # Installation/indexing may download public model artifacts. API credentials
    # remain excluded, and each runner fixes an explicit local provider.
    env = _offline_environment()
    env.pop('HF_HUB_OFFLINE', None)
    env.pop('TRANSFORMERS_OFFLINE', None)
    env['NODE_USE_ENV_PROXY'] = '1'
    try:
        result = run_process([engine['python'], str(Path(__file__).with_name('math_memory_backend_runner.py'))],
                             {'action': 'prepare', 'backend': backend, 'engine': engine}, 3600, env=env)
    except BackendError as exc:
        (workspace/backend/'prepare-error.log').write_text(getattr(exc, 'diagnostic', str(exc)))
        raise
    if result.get('status') != 'ready':
        raise BackendError('backend_prepare_not_ready')
    if backend == 'qmd':
        files = list((Path(engine['model_cache'])/'qmd/models').glob('*Qwen3-Embedding-0.6B-Q8_0.gguf'))
        if len(files) != 1:
            raise BackendError('qmd_local_model_not_verified')
        engine['local_model_path'] = str(files[0])
    engine['status'] = 'ready'
    engine['preparation'] = result
    return engine


def export_discovery(root: Path, destination: Path, version: str) -> dict:
    """Export names/declared aliases only, in the same read transaction."""
    index = root/'错题知识网络/个人知识点索引/index.sqlite3'
    with closing(sqlite3.connect(index.as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('BEGIN')
        actual = json.loads(conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
        if actual != version: raise BackendError('native_version_changed')
        aliases: dict[str, list[str]] = {}
        for name, key in conn.execute('SELECT name,key FROM lookup ORDER BY key,name'):
            if (isinstance(name, str) and len(name) <= 100 and re.search('[\u3400-\u9fff]',name)
                    and not re.search(r'[=\\\n\r]',name)):
                aliases.setdefault(key, []).append(name)
        docs=[]
        for key,label,body in conn.execute('SELECT key,label,payload FROM concepts ORDER BY key'):
            names=sorted(set([label,*aliases.get(key,[])]))
            docs.append({'id':key,'concept_key':key,'title':label,'aliases':names,
                'text':'数学知识点：'+label+'\n已登记名称：'+'；'.join(names),'source_refs':[],
                'formal_ids':json.loads(body).get('formal_ids',[])})
    import math_memory_catalog as catalog
    docs, excluded = catalog.build_descriptors(root, docs)
    value = {'schema': CORPUS_SCHEMA, 'content_policy': 'safe_discovery_metadata_only',
             'source_version': version, 'documents': docs, 'relations': [],
             'retrieval_revision': catalog.source_revision(root),
             'excluded_catalog_entries': excluded,
             'exclusion_policy': 'discovery_only_canonical_records_retained'}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.tmp')
    temporary.write_bytes(canonical(value))
    os.replace(temporary, destination)
    return value


def refresh_selected(repo_root, *, version, changed_concept_keys=None) -> dict:
    """Explicit postcommit continuation; failures never invalidate facts."""
    root = Path(repo_root)
    try:
        config = _read_config(root)
    except BackendError as exc:
        return {'status': 'disabled', 'reason': str(exc)}
    selected = config.get('selected', 'disabled')
    if selected not in ENGINES:
        return {'status': 'disabled', 'backend': selected}
    previous = config.get('backends', {}).get(selected, {})
    semantic_config=config.get('reference_semantic') or {}
    semantic_enabled=bool(selected=='native' and semantic_config.get('mode')=='point_context')
    import math_memory_catalog as catalog
    retrieval_revision = catalog.source_revision(root)
    if previous.get('source_version') == version and previous.get('status') == 'ready':
        try:
            cached=read_corpus(Path(previous['corpus_path']),previous.get('corpus_sha256'))
            if (cached['source_version']==version
                    and cached.get('retrieval_revision') == retrieval_revision):
                if semantic_enabled:
                    private=semantic_config.get('engine') or {}
                    if private.get('status')!='ready' or sha(Path(private['corpus_path']))!=private.get('corpus_sha256'):
                        raise ValueError('point_context_refresh_required')
                    from math_memory_point_context import load_point_context
                    load_point_context(root,private['corpus_path'],view='direct',discovery=cached)
                return {'status': 'noop', 'backend': selected, 'source_version': version}
        except (OSError,ValueError,KeyError,TypeError):
            pass  # Resume only the missing/corrupt derived catalog below.
    try:
        runtime_root = Path(config['runtime_root']) if selected != 'native' or semantic_enabled else None
        workspace = root/CONFIG.parent/'indexes'
        corpus_path = workspace/'discovery-corpus.json'
        exported = export_discovery(root, corpus_path, version)
        if selected == 'native':
            engine={'status':'ready','version':'native-precision-v1','model':None,'corpus_path':str(corpus_path),
                    'corpus_sha256':sha(corpus_path),'source_version':version,
                    'retrieval_revision':retrieval_revision}
        else:
            engine = prepare_backend(corpus_path, workspace, runtime_root, selected)
        private_engine=None
        if semantic_enabled:
            from math_memory_reference_catalog import export_references
            from math_memory_point_context import export_point_context
            reference_path=workspace/'reference-corpus.json'
            point_path=workspace/'point-context-corpus.json'
            reference=export_references(root,exported,reference_path)
            export_point_context(root,exported,reference,point_path)
            private_engine=prepare_backend(point_path,workspace/'semantic',runtime_root,'qmd',
                                           point_context_repo_root=root)
        if native_version(root) != version: raise BackendError('native_version_changed')
        latest = _read_config(root)
        if latest.get('selected') != selected: raise BackendError('selected_backend_changed')
        latest['backends'][selected] = engine
        if private_engine is not None:
            latest['reference_semantic']={**semantic_config,'engine':private_engine,
                'mathematical_reference_path':str(reference_path),
                'mathematical_reference_sha256':sha(reference_path)}
        temporary = (root/CONFIG).with_suffix('.tmp')
        temporary.write_bytes(canonical(latest))
        os.replace(temporary, root/CONFIG)
        return {'status': 'ready', 'backend': selected, 'source_version': version,
                'changed_concept_count': len(changed_concept_keys or []),
                'discovery_count':len(exported['documents']),
                'excluded_count':len(exported.get('excluded_catalog_entries', [])),
                'point_context_status':'ready' if private_engine else 'not_enabled'}
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        return {'status': 'pending', 'backend': selected, 'source_version': version,
                'reason': str(exc)[:160] if isinstance(exc, BackendError) else type(exc).__name__}


def prepare_authorized_backend(projection_path: Path, corpus_path: Path, workspace: Path,
                               runtime_root: Path, backend: str) -> dict:
    """Explicit trial for allowed learned evidence; never a default corpus."""
    if backend not in {'basic-memory','graphiti'}:
        raise BackendError('authorized_backend_invalid')
    projection=json.loads(projection_path.read_text())
    if projection.get('default_search_allowed') is not False:
        raise BackendError('explicit_evidence_scope_required')
    documents=projection['documents']
    ids={d['id'] for d in documents}
    if len(ids)!=len(documents) or any(r['source'] not in ids or r['target'] not in ids for r in projection['relations']):
        raise BackendError('authorized_projection_identity_invalid')
    scope=sorted({d['concept_key'] for d in documents if d.get('concept_key')})
    if not scope or any(not KEY.fullmatch(k) for k in scope):
        raise BackendError('authorized_projection_scope_invalid')
    target=workspace/backend/'authorized'
    target.mkdir(parents=True,exist_ok=True)
    engine={'status':'preparing','version':'1.0.0' if backend=='basic-memory' else '0.31.2',
        'python':str(runtime_root/'python/bin/python'),'source_version':projection['source_version'],
        'corpus_path':str(corpus_path),'authorized_projection':str(projection_path),
        'authorized_projection_sha256':sha(projection_path),'allowed_concept_keys':scope,
        'default_search_allowed':False,'project':'math-authorized',
        'model':'intfloat/multilingual-e5-large','model_cache':str(runtime_root/'models/fastembed')}
    if backend=='basic-memory':
        import yaml
        filenames={d['id']:'MATH-EVIDENCE-'+hashlib.sha256(d['id'].encode()).hexdigest()[:24] for d in documents}
        for doc in documents:
            name=filenames[doc['id']]
            meta={'title':doc.get('title',doc['id']),'type':doc.get('kind','evidence'),
                  'identity':doc['id'],'concept_key':doc.get('concept_key',''),
                  'known_at':doc.get('known_at'),'permalink':'math-authorized/'+name.lower()}
            body=['---',yaml.safe_dump(meta,allow_unicode=True).rstrip(),'---','',
                  '# '+doc.get('title',doc['id']),'','## Source data','',
                  '```json',json.dumps({'role_preserving_content':doc.get('body',doc.get('text',''))},ensure_ascii=False),'```']
            if doc.get('valid_from') and doc.get('kind')=='formal_concept_observation':
                body+=['','## Observations','', '- [learning-event] @occurred:'+str(doc['valid_from'])+' '+doc['id']]
            linked=[r for r in projection['relations'] if r['source']==doc['id']]
            if linked:
                body+=['','## Relations','']+['- '+r['type']+' [['+filenames[r['target']]+']]' for r in linked]
            (target/(name+'.md')).write_text('\n'.join(body)+'\n')
        config_dir=workspace/backend/'authorized-config';config_dir.mkdir(exist_ok=True)
        config={'projects':{'math-authorized':{'path':str(target),'mode':'local'}},'default_project':'math-authorized',
                'log_level':'ERROR','logfire_enabled':False,'semantic_embedding_provider':'fastembed',
                'semantic_embedding_model':engine['model'],'semantic_embedding_dimensions':1024,
                'semantic_embedding_document_prefix':'passage: ','semantic_embedding_query_prefix':'query: ',
                'semantic_embedding_cache_dir':engine['model_cache'],'semantic_embedding_threads':4,
                'semantic_embedding_parallel':1,'semantic_embedding_request_concurrency':1,
                'format_on_save':False,'ensure_frontmatter_on_sync':False}
        (config_dir/'config.json').write_bytes(canonical(config))
        engine.update(config_dir=str(config_dir),documents=str(target),document_paths=filenames)
    else:
        engine.update(database=str(workspace/backend/'authorized.rdb'),
                      group_id='math-authorized-'+hashlib.sha256(projection['source_version'].encode()).hexdigest()[:16])
    env=_offline_environment()
    result=run_process([engine['python'],str(Path(__file__).with_name('math_memory_backend_runner.py'))],
        {'action':'prepare','backend':backend,'engine':engine},1200,env=env)
    if result.get('status')!='ready':raise BackendError('authorized_prepare_not_ready')
    engine.update(status='ready',preparation=result)
    return engine


def authorized_context_query(engine: dict, backend: str, *, concept_keys: list[str],
                             identifier=None, query=None, valid_at=None, known_at=None,
                             timeout=8.0, view='protected') -> dict:
    if view not in {'after_attempt','direct'}:
        raise BackendError('evidence_view_not_authorized')
    if engine.get('default_search_allowed') is not False or not concept_keys:
        raise BackendError('explicit_evidence_scope_required')
    if not set(concept_keys)<=set(engine['allowed_concept_keys']):
        raise BackendError('evidence_scope_exceeded')
    path=Path(engine['authorized_projection'])
    if sha(path)!=engine['authorized_projection_sha256']:
        raise BackendError('authorized_projection_changed')
    projection=json.loads(path.read_text())
    allowed=[d['id'] for d in projection['documents'] if d.get('concept_key') in concept_keys]
    if backend=='basic-memory':
        if identifier:
            # BM context has no source-row filter. Only allow a project-wide
            # explicitly authorized scope; reject a narrower request.
            if set(concept_keys)!=set(engine['allowed_concept_keys']):
                raise BackendError('basic_memory_context_scope_filter_unavailable')
            if identifier not in engine['document_paths']:
                raise BackendError('evidence_identifier_unknown')
            return runtime_query(engine,backend,'',allowed,50,timeout,action='context',
                                 identifier=engine['document_paths'][identifier]+'.md')
        if known_at:
            raise BackendError('basic_memory_known_at_requires_native_view')
        return runtime_query(engine,backend,query or '',allowed,50,timeout,valid_at=valid_at,
                             items=['observation'],mode='text',return_scoped_result=True)
    if backend=='graphiti':
        return runtime_query(engine,backend,'',concept_keys,50,timeout,action='context',
                             valid_at=valid_at,known_at=known_at)
    raise BackendError('authorized_backend_invalid')


def serve_socket(root: Path, config_path: Path, socket_path: Path, idle_seconds=300):
    """Task-owned Unix socket, mode 0600; no TCP or login service."""
    def stop(signum,frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,stop)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        raise BackendError('backend_socket_already_exists')
    config = _read_config(root, config_path)
    selected = config.get('selected')
    engine = config.get('backends', {}).get(selected, {})
    corpus = read_corpus(Path(engine['corpus_path']), engine.get('corpus_sha256'))
    docs = corpus['documents']
    if selected != 'native' and docs:
        runtime_query(engine, selected, docs[0]['title'], [d['id'] for d in docs], 1, 120)
    last = time.monotonic()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        server.listen(4)
        server.settimeout(min(10,idle_seconds))
        try:
            while time.monotonic()-last < idle_seconds:
                try: client, _ = server.accept()
                except socket.timeout: continue
                with client:
                    client.settimeout(9)
                    body = b''
                    try:
                        while b'\n' not in body:
                            chunk = client.recv(16384)
                            if not chunk: break
                            body += chunk
                            if len(body)>65536: raise BackendError('backend_request_too_large')
                        request = json.loads(body)
                        allowed = {'query','concept_keys','formal_id','view','limit','timeout','backend','expected_source_version','reference_allowed','structured_math'}
                        if not isinstance(request,dict) or set(request)-allowed:
                            raise BackendError('backend_service_request_invalid')
                        value = candidate_query(root, config_path=config_path, _in_service=True, **request)
                        client.sendall(canonical(value))
                    except (OSError,ValueError,TypeError):
                        try: client.sendall(canonical({'status':'degraded','candidates':[], 'degraded':'backend_service_request_failed'}))
                        except OSError: pass
                last=time.monotonic()
        finally:
            socket_path.unlink(missing_ok=True)
            close_runtimes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--corpus', type=Path, required=True)
    prepare.add_argument('--workspace', type=Path, required=True)
    prepare.add_argument('--runtime-root', type=Path, required=True)
    prepare.add_argument('--backend', choices=sorted(ENGINES), required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('--socket', type=Path, required=True)
    serve.add_argument('--idle-seconds', type=int, default=300)
    query = sub.add_parser("query")
    query.add_argument("--query", required=True)
    query.add_argument("--backend", choices=sorted(ENGINES))
    query.add_argument("--concept", action="append")
    query.add_argument("--formal-id")
    query.add_argument("--view", default="protected", choices=["protected", "after_attempt", "direct"])
    args = parser.parse_args()
    if args.command == 'serve':
        serve_socket(args.repo,args.config or args.repo/CONFIG,args.socket,args.idle_seconds)
        return 0
    elif args.command == 'prepare':
        value = prepare_backend(args.corpus, args.workspace, args.runtime_root, args.backend)
    elif args.command == "status":
        try:
            value = _read_config(args.repo, args.config)
            value = {"status": "configured", "selected": value.get("selected", "disabled"),
                     "backends": {k: {f: row.get(f) for f in ("status", "version", "model", "source_version")} for k, row in value["backends"].items()}}
        except (ValueError, OSError) as exc:
            value = {"status": "unavailable", "reason": str(exc)}
    else:
        value = candidate_query(args.repo, args.query, concept_keys=args.concept, formal_id=args.formal_id,
                                view=args.view, backend=args.backend, config_path=args.config)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
