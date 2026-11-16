"""Derived exact scope for archived captures without rewriting their bytes.

Accepted raw excerpts remain unadjudicated references. This metadata projection
adds identity and dates from the original Capture and its exact closeout, never
from note names, filesystem time, or conceptual similarity.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

SCHEMA = 'math-personal-record-scope-v1'
INDEX = Path('错题知识网络/个人知识点索引/index.sqlite3')
OUTPUT = Path('错题知识网络/个人知识点索引/记录定位/index.json')
LEDGER = Path('数学一回滚复习系统/快速入库事件.jsonl')
KINDS = {'accepted_conversation_excerpt', 'accepted_capture_reference'}


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('record_scope_symlink_forbidden')
    data = canonical(value)
    if path.is_file() and path.read_bytes() == data:
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.record-scope-', delete=False) as out:
        temporary = Path(out.name); out.write(data); out.flush(); os.fsync(out.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load(root, version):
    path = Path(root)/OUTPUT
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 8*1024*1024:
        raise ValueError('record_scope_unavailable')
    value = json.loads(path.read_bytes())
    checksum = value.pop('content_sha256', None)
    if value.get('schema') != SCHEMA or digest(value) != checksum:
        raise ValueError('record_scope_corrupt')
    if value.get('native_version') != version:
        raise ValueError('record_scope_stale')
    if value.get('builder_sha256') != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('record_scope_implementation_changed')
    return value


def refresh(repo_root, version):
    root = Path(repo_root).resolve()
    try:
        old = _load(root, version)
        return {'status':'noop', 'version':old['version'], 'records':len(old['records'])}
    except (OSError, ValueError, KeyError):
        pass
    captures, accepted = {}, {}
    ledger = root/LEDGER
    raw = ledger.read_bytes() if ledger.is_file() else b''
    for line in raw.decode('utf-8').split('\n'):
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get('event_type') == 'capture':
            captures[event['event_id']] = {k:event.get(k) for k in
                ('event_id','study_date','recorded_at','content_hash')}
        elif event.get('event_type') == 'closeout':
            for result in event.get('capture_results', []):
                cid = result.get('capture_event_id')
                if cid:
                    accepted[(cid,event['event_id'])] = {
                        'formal_id':result.get('formal_id'), 'outcome':result.get('outcome'),
                        'accepted_at':event.get('closed_at'), 'closeout_id':event['event_id']}
    rows, missing = [], []
    with closing(sqlite3.connect((root/INDEX).as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('BEGIN')
        actual = json.loads(conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
        if actual != version:
            raise ValueError('record_scope_generation_changed')
        memberships = {}
        for key,rid in conn.execute('SELECT key,record_id FROM membership'):
            memberships.setdefault(rid,[]).append(key)
        for rid,body in conn.execute("SELECT id,payload FROM records WHERE json_extract(payload,'$.kind') IN ('accepted_conversation_excerpt','accepted_capture_reference')"):
            record = json.loads(body); meta = record.get('metadata', {}); bindings = []
            for cid in meta.get('capture_ids', []):
                closeout_id = meta.get('closeout_id')
                matches = [(k,v) for k,v in accepted.items() if k[0] == cid and (not closeout_id or k[1] == closeout_id)]
                capture = captures.get(cid)
                if len(matches) != 1 or not capture:
                    missing.append({'record_id':rid,'capture_id':cid,'reason':'capture_closeout_binding_not_unique'})
                    continue
                _, decision = matches[0]
                if not decision.get('formal_id'):
                    continue
                bindings.append({'capture_id':cid, **decision,
                    'study_date':capture.get('study_date'), 'recorded_at':capture.get('recorded_at'),
                    'capture_content_hash':capture.get('content_hash')})
            if bindings:
                rows.append({'record_id':rid, 'kind':record['kind'],
                    'record_sha256':hashlib.sha256(body.encode()).hexdigest(),
                    'concept_keys':sorted(set(memberships.get(rid,[]))), 'bindings':bindings,
                    'evidence_role':'raw_unadjudicated_reference', 'not_a_new_learning_event':True})
    semantic = {'schema':SCHEMA, 'native_version':version,'records':rows,'missing':missing,
                'builder_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'authority':str(LEDGER), 'ledger_sha256_at_build':hashlib.sha256(raw).hexdigest(),
                'recorded_at_semantics':'original_capture_recorded_at',
                'accepted_at_semantics':'exact_closeout_closed_at'}
    semantic['version'] = digest(semantic)
    semantic['content_sha256'] = digest(semantic)
    _atomic(root/OUTPUT,semantic)
    return {'status':'ready','version':semantic['version'],'records':len(rows),
            'missing_bindings':len(missing),'native_version':version,'formal_write_count':0}


def lookup(repo_root, expected_version, *, concept_keys=(), formal_ids=(), dates=(), limit=64):
    """Read metadata only. Caller must short-circuit protected before this call."""
    if not concept_keys and not formal_ids:
        return {'status':'scope_required','records':[]}
    if not 1 <= limit <= 256:
        raise ValueError('record_scope_limit_invalid')
    try:
        value = _load(repo_root,expected_version)
    except (OSError, ValueError, KeyError) as error:
        return {'status':'unavailable','records':[], 'reason':str(error),
                'does_not_prove_no_learning':True}
    from math_memory_evidence import _matches_date
    selected = []
    for row in value['records']:
        if concept_keys and not set(row['concept_keys']).intersection(concept_keys):
            continue
        bindings = [b for b in row['bindings'] if (not formal_ids or b['formal_id'] in formal_ids)
                    and _matches_date(b.get('study_date'),dates)]
        if bindings:
            selected.append({**row,'bindings':bindings})
    return {'status':'available', 'records':selected[:limit], 'total':len(selected),
            'omitted':max(0,len(selected)-limit), 'version':value['version'],
            'native_version':expected_version, 'scope':'accepted_capture_metadata_only'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[2])
    args=parser.parse_args()
    from math_memory_backends import native_version
    print(json.dumps(refresh(args.repo,native_version(args.repo)),ensure_ascii=False))
