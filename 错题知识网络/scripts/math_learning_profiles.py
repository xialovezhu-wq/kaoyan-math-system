#!/usr/bin/env python3
"""Precomputed learning pages and compact teaching reads; no model calls.

Formal sources remain authoritative. Learning updates require real committed
events; semantic maintenance binds an unchanged prepared evidence snapshot.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import closing
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from urllib.parse import quote

BASE = Path('错题知识网络/个人知识点索引')
SEMANTIC = BASE / '语义概况'
PAGES = BASE / '学习路径'
SCHEMA = 'math-learning-profile-update-v1'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def evidence_basis(record):
    return digest({k:record.get(k) for k in ('kind','formal_id','summary','history','text')})


def record_event(record):
    return record.get('summary',{}).get('event_id') or record.get('metadata',{}).get('closeout_id')


def write_changed(path, value):
    data = value if isinstance(value, bytes) else value.encode() if isinstance(value, str) else (canonical(value)+'\n').encode()
    if path.is_file() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.profile-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def safe_source(root, ref):
    if not isinstance(ref, dict) or not isinstance(ref.get('path'), str):
        raise ValueError('profile_source_reference_required')
    path = root / ref['path']
    if Path(ref['path']).is_absolute() or '..' in Path(ref['path']).parts or path.is_symlink():
        raise ValueError('profile_source_outside_repository')
    path = path.resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('profile_source_outside_repository')
    if hashlib.sha256(path.read_bytes()).hexdigest() != ref.get('sha256'):
        raise ValueError('profile_source_changed:'+ref['path'])
    return {**ref, 'path': ref['path'], 'sha256': ref['sha256']}


def _semantic_revision_archive(root, path, old, row):
    """Validate a revision without writing, so callers can validate a whole batch."""
    previous = old.get('content_sha256')
    reason = row.get('revision_reason')
    if (not isinstance(previous, str) or not re.fullmatch(r'[0-9a-f]{64}', previous)
            or row.get('supersedes_content_sha256') != previous
            or not isinstance(reason, str) or not reason.strip()):
        raise ValueError('same_event_profile_conflict:'+row['concept_key'])
    if digest({k:v for k,v in old.items() if k != 'content_sha256'}) != previous:
        raise ValueError('profile_revision_predecessor_invalid:'+row['concept_key'])
    archived = root/SEMANTIC/'历史版本'/row['concept_key']/(previous+'.json')
    raw = path.read_bytes()
    if json.loads(raw) != old:
        raise ValueError('profile_revision_predecessor_changed:'+row['concept_key'])
    if archived.exists() and archived.read_bytes() != raw:
        raise ValueError('profile_revision_archive_conflict:'+row['concept_key'])
    return archived, raw


def preserve_semantic_revision(root, path, old, row):
    """Require an exact predecessor and preserve its original bytes."""
    archived, raw = _semantic_revision_archive(root, path, old, row)
    write_changed(archived, raw)


def _profile_derived_path(path):
    return any(path == str(base) or path.startswith(str(base)+'/') for base in (SEMANTIC, PAGES))


def _maintenance_basis(conn, meta):
    """Snapshot index evidence, excluding only this module's own projections."""
    records = [(rid, json.loads(body)) for rid, body in conn.execute('SELECT id,payload FROM records ORDER BY id')]
    return {
        '_basis_evidence_version': digest([records, list(conn.execute('SELECT key,record_id FROM membership ORDER BY key,record_id'))]),
        '_basis_sources': {path: {'stamp': json.loads(stamp), 'sha256': sha}
                           for path, stamp, sha in conn.execute('SELECT path,stamp,sha256 FROM sources')
                           if not _profile_derived_path(path)},
        '_basis_store_stamps': meta.get('store_stamps', {}),
        '_basis_directories': {p: s for p, s in meta.get('directories', {}).items() if not _profile_derived_path(p)},
    }


def prepare_updates(repo_root, payload):
    root = Path(repo_root).resolve()
    if not isinstance(payload, dict) or payload.get('schema') != SCHEMA or not isinstance(payload.get('updates'), list) or not payload['updates']:
        raise ValueError('profile_update_schema_required')
    import math_concept_index as native
    with closing(sqlite3.connect((root/native.INDEX).as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('BEGIN')
        meta = {k: json.loads(v) for k,v in conn.execute('SELECT key,value FROM meta')}
        if payload.get('basis_version') and payload['basis_version'] != meta['version']:
            raise ValueError('profile_basis_version_changed')
        known = {k for k, in conn.execute('SELECT key FROM concepts')}
        maintenance_basis = _maintenance_basis(conn, meta)
        basis={}
        review_ids={}
        for row in payload['updates']:
            if not isinstance(row,dict):
                raise ValueError('profile_update_object_required')
            key=row.get('concept_key')
            values={rid:json.loads(body) for rid,body in conn.execute(
                'SELECT r.id,r.payload FROM records r JOIN membership m ON r.id=m.record_id WHERE m.key=?',(key,))}
            basis[key]={rid:evidence_basis(value) for rid,value in values.items()}
            review_ids[key]={rid:sorted(str(item.get('event',{}).get('event_id')) for item in value.get('history',{}).get('review_events',[]) if item.get('event',{}).get('event_id'))
                             for rid,value in values.items() if value.get('kind')=='personal_card'}
    seen, updates = set(), []
    for row in payload['updates']:
        key = row.get('concept_key')
        if key not in known or key in seen:
            raise ValueError('unknown_or_duplicate_profile_concept:'+str(key))
        seen.add(key)
        for field in ('overview', 'short_summary', 'next_check'):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError('profile_text_required:'+field)
        if not isinstance(row.get('progress'), list) or any(not isinstance(x,str) for x in row['progress']):
            raise ValueError('profile_progress_must_be_text_array')
        if len(row['short_summary'].encode()) > 2000:
            raise ValueError('short_summary_exceeds_2000_bytes')
        if not row.get('source_refs'):
            raise ValueError('profile_evidence_required')
        refs = [safe_source(root, ref) for ref in row['source_refs']]
        updates.append({**row, 'source_refs':refs})
    cited_sources = {ref['path']: {'sha256': ref['sha256'], 'stamp': native._stamp(root/ref['path'])}
                     for row in updates for ref in row['source_refs']}
    return {**payload, **maintenance_basis, '_basis_cited_sources': cited_sources,
            'basis_version':meta['version'], '_basis_records':basis,
            '_basis_review_event_ids':review_ids, 'updates':updates}


def accept_maintenance(repo_root, payload, maintenance_reason=None):
    """Save semantics only; never create or reuse a learning-event identity.

    All rows and archives are checked before the first write. Atomic per-file
    replacement and content-derived identity make interrupted batches resumable.
    A refreshed global version is accepted only for an entirely identical retry
    whose complete evidence snapshot still matches.
    """
    root = Path(repo_root).resolve()
    (root/BASE).mkdir(parents=True, exist_ok=True)
    with (root/BASE/'profile-update.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _accept_maintenance(root, payload, maintenance_reason)


def _accept_maintenance(root, payload, maintenance_reason):
    if not isinstance(payload, dict):
        raise ValueError('profile_update_schema_required')
    if payload.get('_deferred_batch_merge'):
        raise ValueError('topic_shard_profile_requires_consolidation_before_acceptance')
    reason = maintenance_reason if maintenance_reason is not None else payload.get('maintenance_reason')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('profile_maintenance_reason_required')
    required = ('basis_version', '_basis_records', '_basis_review_event_ids',
                '_basis_evidence_version', '_basis_sources', '_basis_store_stamps', '_basis_directories',
                '_basis_cited_sources')
    if any(field not in payload for field in required) or not payload['basis_version']:
        raise ValueError('profile_maintenance_must_be_prepared')
    prepared = prepare_updates(root, {**payload, 'basis_version': None})
    keys = {row['concept_key'] for row in prepared['updates']}
    for field in ('_basis_records', '_basis_review_event_ids'):
        if not isinstance(payload[field], dict) or set(payload[field]) != keys:
            raise ValueError('profile_maintenance_exact_basis_required:'+field)
        if payload[field] != prepared[field]:
            raise ValueError('profile_point_changed_since_preparation:'+field)
    for field in required[3:]:
        if payload[field] != prepared[field]:
            raise ValueError('profile_maintenance_evidence_changed:'+field)
    import math_concept_index as native
    # Do not trust a matching SQLite version: files may have changed without a
    # refresh. Hash every frozen source and check stamps on both sides of reads.
    for path, expected in {**prepared['_basis_cited_sources'], **prepared['_basis_sources']}.items():
        if native._stamp(root/path) != expected['stamp']:
            raise ValueError('profile_source_stamp_changed:'+path)
        safe_source(root, {'path': path, 'sha256': expected['sha256']})
        if native._stamp(root/path) != expected['stamp']:
            raise ValueError('profile_source_stamp_changed:'+path)
    for field in ('_basis_store_stamps', '_basis_directories'):
        for path, stamp in prepared[field].items():
            if native._stamp(root/path) != stamp:
                raise ValueError('profile_source_stamp_changed:'+path)
    maintenance_id = 'MATH-PROFILE-MAINT-'+digest({'prepared': payload, 'maintenance_reason': reason})
    reserved = {'schema', 'status', 'event_id', 'event_ids', 'maintenance_id', 'maintenance_reason',
                'basis_version', 'through_event_ids', 'card_evidence_versions',
                'evidence_record_versions', 'evidence_review_event_ids', 'content_sha256'}
    plans = []
    with closing(sqlite3.connect((root/native.INDEX).as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('BEGIN')
        current_version = json.loads(conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
        if current_version != prepared['basis_version']:
            raise ValueError('profile_basis_version_changed')
        for row in prepared['updates']:
            key = row['concept_key']
            if reserved.intersection(row):
                raise ValueError('profile_maintenance_reserved_fields:'+key)
            values = [json.loads(body) for body, in conn.execute(
                'SELECT r.payload FROM records r JOIN membership m ON r.id=m.record_id WHERE m.key=?', (key,))]
            stored = {**row, 'schema': SCHEMA, 'status': 'accepted_semantic_maintenance',
                      'maintenance_id': maintenance_id, 'maintenance_reason': reason,
                      'basis_version': payload['basis_version'],
                      'through_event_ids': sorted({str(record_event(v)) for v in values if record_event(v)}),
                      'card_evidence_versions': {v['record_id']: evidence_basis(v) for v in values if v.get('kind') == 'personal_card'},
                      'evidence_record_versions': prepared['_basis_records'][key],
                      'evidence_review_event_ids': prepared['_basis_review_event_ids'][key]}
            stored['content_sha256'] = digest(stored)
            path = root/SEMANTIC/(key+'.json')
            old = json.loads(path.read_text()) if path.exists() else None
            archive = None
            unchanged = old == stored
            if old is not None and not unchanged:
                archive = _semantic_revision_archive(root, path, old, row)
            elif old is None and row.get('supersedes_content_sha256'):
                raise ValueError('profile_revision_predecessor_missing:'+key)
            plans.append((path, stored, archive, unchanged))
    noop = all(plan[3] for plan in plans)
    if prepared['basis_version'] != payload['basis_version'] and not noop:
        raise ValueError('profile_basis_version_changed')
    # No validation below this boundary. A failed replacement can be retried
    # against the same prepared bytes; already-installed rows become no-ops.
    for path, stored, archive, unchanged in plans:
        if archive:
            write_changed(*archive)
    for path, stored, archive, unchanged in plans:
        if not unchanged:
            write_changed(path, stored)
    return {'status': 'noop' if noop else 'accepted', 'maintenance_id': maintenance_id,
            'concept_keys': [row['concept_key'] for row in prepared['updates']],
            'profile_version': digest(prepared['updates']), 'refresh_required': True}


def finish_maintenance(repo_root, result, refresh_only=False):
    """Refresh projections and independently publish; never run event closeout."""
    root = Path(repo_root).resolve()
    import math_concept_index as native
    refreshed = native.build_index(root)
    result = {**result, 'refresh': {k: refreshed[k] for k in ('status', 'version', 'concept_count', 'record_count')},
              'refresh_required': False}
    if not refresh_only:
        sys.path.insert(0, str(root/'数学一回滚复习系统/scripts'))
        import math_postcommit
        result['publication'] = math_postcommit.request_publication(
            subject='math', event_id=result['maintenance_id'], repo_root=root)
    return result


def accept_updates(repo_root, payload, event_id):
    root=Path(repo_root).resolve()
    (root/BASE).mkdir(parents=True,exist_ok=True)
    with (root/BASE/'profile-update.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _accept_updates(root,payload,event_id)


def _accept_updates(repo_root, payload, event_id):
    if payload.get('_deferred_batch_merge'):
        raise ValueError('topic_shard_profile_requires_consolidation_before_acceptance')
    root = Path(repo_root).resolve()
    sys.path.insert(0, str(root/'数学一回滚复习系统/scripts'))
    import math_postcommit
    event_ids=[event_id] if isinstance(event_id,str) else list(event_id)
    if not event_ids or any(not isinstance(x,str) or not x for x in event_ids) or len(event_ids)!=len(set(event_ids)):
        raise ValueError('unique_formal_event_ids_required')
    events=[math_postcommit.find_committed_event(root,x) for x in event_ids]
    if any(e.get('event_type') not in ('concept_review','closeout') for e in events):
        raise ValueError('profiles_require_real_formal_commit')
    if len(events)>1 and any(e['event_type']!='closeout' for e in events):
        raise ValueError('multiple_events_only_for_one_A_closeout_batch')
    events.sort(key=lambda e:(e.get('recorded_at',''),e['event_id']))
    event_ids=[e['event_id'] for e in events]
    event=events[-1]
    event_id=event['event_id']
    # Preparation is before the writer. Recheck cited bytes after that commit;
    # its own index refresh may legitimately have advanced the global version.
    prepared = prepare_updates(root, {**payload, 'basis_version':None})
    if event['event_type']=='concept_review':
        allowed=set(event['concept_keys'])
    else:
        import math_concept_index as native
        expected_cards={r['formal_id']:r for e in events for r in e.get('formal_results',[])}
        ids=set(expected_cards)
        with closing(sqlite3.connect((root/native.INDEX).as_uri()+'?mode=ro',uri=True)) as conn:
            for fid,expected in expected_cards.items():
                indexed=conn.execute('SELECT stamp,sha256 FROM sources WHERE path=?',(expected['card_path_after'],)).fetchone()
                if not indexed or indexed[1]!=expected['card_hash_after'] or native._stamp(root/expected['card_path_after'])!=json.loads(indexed[0]):
                    raise ValueError('refresh_final_cards_before_profile_acceptance:'+fid)
            allowed={k for fid in ids for k, in conn.execute('SELECT key FROM membership WHERE record_id=?',(fid,))}
    if not {row['concept_key'] for row in prepared['updates']} <= allowed:
        raise ValueError('profile_concepts_not_in_committed_event')
    keys=[]
    import math_concept_index as native
    with closing(sqlite3.connect((root/native.INDEX).as_uri()+'?mode=ro',uri=True)) as conn:
        through={}
        card_versions={}
        for row in prepared['updates']:
            values=[json.loads(p) for p, in conn.execute('SELECT r.payload FROM records r JOIN membership m ON r.id=m.record_id WHERE m.key=?',(row['concept_key'],))]
            previous=payload.get('_basis_records',{}).get(row['concept_key'])
            if previous is None:
                raise ValueError('profile_update_must_be_prepared_before_commit')
            own_ids={r.get('formal_id') for e in events for r in e.get('formal_results',[])}
            for value in values:
                rid=value['record_id']
                own=record_event(value) in event_ids or value.get('formal_id') in own_ids
                if not own and previous.get(rid)!=evidence_basis(value):
                    raise ValueError('profile_point_changed_since_preparation:'+row['concept_key'])
                previous_reviews=payload.get('_basis_review_event_ids',{}).get(row['concept_key'],{}).get(rid)
                if previous_reviews is not None:
                    current_reviews=sorted(str(item.get('event',{}).get('event_id')) for item in value.get('history',{}).get('review_events',[]) if item.get('event',{}).get('event_id'))
                    if current_reviews!=previous_reviews:
                        raise ValueError('new_actual_review_since_profile_preparation:'+rid)
            through[row['concept_key']]=sorted(set(event_ids)|{str(record_event(v)) for v in values if record_event(v)})
            card_versions[row['concept_key']]={v['record_id']:evidence_basis(v) for v in values if v.get('kind')=='personal_card'}
    for row in prepared['updates']:
        stored = {**row, 'schema':SCHEMA, 'event_id':event_id,
                  'event_ids':event_ids, 'card_evidence_versions':card_versions[row['concept_key']],
                  'basis_version':payload.get('basis_version'), 'status':'accepted_semantic_update',
                  'through_event_ids':through[row['concept_key']]}
        stored['content_sha256']=digest(stored)
        path=root/SEMANTIC/(row['concept_key']+'.json')
        if path.exists():
            old=json.loads(path.read_text())
            if old.get('event_id')==event_id and all(old.get(k)==v for k,v in row.items()):
                keys.append(row['concept_key'])
                continue
            if old.get('event_id')==event_id and old.get('content_sha256')!=stored['content_sha256']:
                preserve_semantic_revision(root, path, old, row)
        write_changed(path,stored)
        keys.append(row['concept_key'])
    return {'status':'accepted','event_id':event_id,'concept_keys':keys,
            'event_ids':event_ids,
            'profile_version':digest(prepared['updates']), 'refresh_required':True}


def _text(value):
    return value if isinstance(value,str) else canonical(value)


def _date(value):
    match=re.search(r'20\d\d-\d\d-\d\d', _text(value))
    return match.group(0) if match else None


def _link(root, formal_id, card_path):
    detail=root/'错题知识网络/可视化错题详情'
    # Cold construction only: resolve navigation once, never during teaching.
    matches=list(detail.glob('*/'+formal_id+'_*.md'))
    path=str(matches[0].relative_to(root)) if len(matches)==1 else card_path
    return {'formal_id':formal_id, 'path':path,
            'wikilink':'[['+path.removesuffix('.md')+'|'+formal_id+']]',
            'obsidian_url':'obsidian://open?vault=kaoyan-math&file='+quote(path,safe='')}


def enrich_index(root, concepts, records, sources, membership, read_source):
    """Run only in the existing cold index transaction, before version hashing."""
    members={}
    for key,rid in membership:
        members.setdefault(key,[]).append(rid)
    links={}
    for rid,record in records.items():
        if record.get('kind')=='personal_card':
            refs=[r['path'] for r in record['source_refs'] if '/错题卡/' in r['path']]
            if refs:
                links[rid]=_link(root,rid,refs[0])
    page_index=['# 数学知识点学习路径','',
                '原始学习证据保留完整；未有 GPT-6 审核成稿的页面明确标记为证据整理，不推断独立掌握。','']
    hot_rows=[]
    for key,concept in concepts.items():
        rows=[records[rid] for rid in members.get(key,[])]
        reference_anchors=sorted([r['metadata']['reference_anchor'] for r in rows
            if r.get('metadata',{}).get('reference_anchor',{}).get('concept_key')==key],key=lambda a:a['path'])
        timeline=[]
        for record in rows:
            kind=record.get('kind')
            if kind=='personal_card':
                hist=record.get('history',{})
                for field in ('wrong_history','mastery_history'):
                    values=hist.get(field,[])
                    values=values if isinstance(values,list) else [values]
                    for pos,value in enumerate(values):
                        if not value:
                            continue
                        timeline.append({'date':_date(value),'question':record['formal_id'],
                            'scope':'相关题记录，未据此推断该知识点同错', 'kind':field,
                            'text':_text(value),'source_refs':record['source_refs'][:1],
                            'position':pos})
                for item in hist.get('review_events',[]):
                    event=item.get('event',{})
                    timeline.append({'date':_date(event),'question':record['formal_id'],
                        'scope':item.get('attribution','真实题级复习'), 'kind':'review_event',
                        'text':_text(event),'source_refs':record['source_refs'], 'position':item.get('ordinal')})
            elif kind in ('formal_concept_observation','concept_review'):
                summary=record.get('summary',{})
                for pos,item in enumerate(summary.get('observations',[])):
                    # These observations, unlike a card association, bind the point.
                    text=item.get('error_detail') or item.get('correction_text') or item.get('outcome','')
                    timeline.append({'date':summary.get('study_date'),
                        'question':record.get('formal_id') or item.get('question_ref'),
                        'scope':'正式逐知识点观察','kind':item.get('outcome','unresolved'),
                        'text':_text(text),'source_refs':record['source_refs'], 'position':pos})
        timeline.sort(key=lambda x:(x['date'] is None,x['date'] or '',str(x['question']),str(x['position']),x['kind'],x['scope'],digest(x)))
        dated=[x for x in timeline if x['date']]
        explicit=[x for x in timeline if x['scope']=='正式逐知识点观察']
        linked=[links[x] for x in concept['formal_ids'] if x in links]
        overview=f'关联 {len(linked)} 道正式题；整理 {len(timeline)} 条已记录历史，其中 {len(explicit)} 条明确绑定本知识点。'
        if dated:
            overview+=f" 记录时间 {dated[0]['date']} 至 {dated[-1]['date']}。"
        semantic=None
        semantic_stale_reason=None
        semantic_path=root/SEMANTIC/(key+'.json')
        if semantic_path.is_file():
            read_source(semantic_path,'external')
            candidate=json.loads(semantic_path.read_text())
            try:
                for ref in candidate.get('source_refs',[]):
                    safe_source(root,ref)
                current_events={record_event(r) for r in rows if record_event(r)}
                if not current_events <= set(candidate.get('through_event_ids',[])):
                    raise ValueError('new_observations_require_profile_update')
                current_cards={r['record_id']:evidence_basis(r) for r in rows if r.get('kind')=='personal_card'}
                if candidate.get('card_evidence_versions')!=current_cards:
                    raise ValueError('new_card_or_review_requires_profile_update')
                if (candidate.get('status') == 'accepted_semantic_maintenance'
                        and candidate.get('evidence_record_versions') != {r['record_id']: evidence_basis(r) for r in rows}):
                    raise ValueError('changed_evidence_requires_profile_update')
                semantic=candidate
            except (ValueError,OSError) as exc:
                semantic_stale_reason=str(exc)
        if semantic:
            overview=semantic['overview']
        dated_explicit=[x for x in explicit if x['date']]
        latest=([(dated_explicit or explicit)[-1]] if explicit else [])
        latest_history=(dated or timeline)[-1] if timeline else None
        if latest_history and (not latest or digest(latest[-1])!=digest(latest_history)):
            latest.append(latest_history)
        short=semantic['short_summary'] if semantic else (('原语义概况尚未覆盖最新记录；以下为当前事实整理。\n' if semantic_stale_reason else '')+overview)
        if not semantic:
            snippets=[]
            for item in reversed(latest):
                # Keep complete evidence atoms; no suffix cutting or inference.
                excerpt=item['text']
                if len(excerpt.encode())>950:
                    sentences=re.split(r'(?<=[。！？])',excerpt)
                    excerpt=''
                    for sentence in sentences:
                        if len((excerpt+sentence).encode())>800:break
                        excerpt+=sentence
                    excerpt=(excerpt+'（原记录较长，此处仅引完整首句，全文见学习路径。）') if excerpt else ''
                if excerpt:
                    snippets.append(f"{item['date'] or '日期未记录'} {item['question'] or ''} [{item['scope']}]：{excerpt}")
            short+='\n'+'\n'.join(snippets)
        page=PAGES/(key+'.md')
        lines=['# '+concept['label']+'｜学习路径','', '> [!summary] 学习概况',
               '> '+overview.replace('\n','\n> '),'',
               '概况状态：'+('GPT-6 正式审核成稿' if semantic else '原语义成稿已过期；当前采用最新证据整理' if semantic_stale_reason else '完整证据整理；尚无跨事件语义进步裁决')+'。','',
               '## 进步与待验证','']
        progress=semantic.get('progress',[]) if semantic else []
        lines += ['- '+x for x in progress] or ['尚未有经审核的跨事件进步对照；提示后完成与独立完成分别依据原始记录判断。']
        next_check=semantic.get('next_check') if semantic else '依据当前真实作答核对相关具体操作；无记录不能推断掌握或错误。'
        lines += ['',next_check,'','## 涉及题目','']+[x['wikilink'] for x in linked]
        if reference_anchors:
            lines += ['','## 通用知识锚点资料','', '这些资料说明知识范围与条件，不代表本人已经学过或掌握。','']
            lines += ['- [['+a['path'].removesuffix('.md')+'|'+concept['label']+'：知识范围、公式与来源]]' for a in reference_anchors]
        lines += ['','## 完整已记录时间路径','']
        for item in timeline:
            ref=item['source_refs'][0] if item['source_refs'] else None
            q=links.get(item['question'],{}).get('wikilink',str(item['question'] or '知识点复盘'))
            lines += ['### '+str(item['date'] or '时间未记录')+' · '+q,
                      item['scope']+' / '+item['kind'],'',item['text'],'']
            if ref:
                lines += ['来源：[['+ref['path'].removesuffix('.md')+']]；原始位置 '+str(item['position'])+'。','']
        if not timeline:
            lines += ['暂无可归入本点的个人学习历史；仅有相关资料或标签，不推断个人表现。']
        archived=[r for r in rows if r.get('kind') in ('accepted_conversation_excerpt','accepted_capture_reference')]
        if archived:
            lines += ['','## 已正式接纳来源中的原始摘录','',
                      '以下保留来源证据，未另行判为本知识点错误，也不重复增加学习次数。','']
            for record in sorted(archived,key=lambda r:r['record_id']):
                lines += ['### '+record['record_id'],'',record.get('text','') or '完整证据由下列来源定位。','']
                for ref in record.get('source_refs',[]):
                    lines += ['来源：`'+ref['path']+'`；SHA-256 `'+ref['sha256']+'`。','']
        write_changed(root/page,'\n'.join(lines)+'\n')
        page_source=read_source(root/page,'external')
        profile={'concept_key':key,'concept_name':concept['label'], 'overview':overview,
            'short_summary':short,'progress':progress,'next_check':next_check,
            'status':'semantic_current' if semantic else 'semantic_stale' if semantic_stale_reason else 'evidence_digest_only',
            'timeline_count':len(timeline),'explicit_observation_count':len(explicit),
            'first_date':dated[0]['date'] if dated else None,'latest_date':dated[-1]['date'] if dated else None,
            'page':str(page),'obsidian_url':'obsidian://open?vault=kaoyan-math&file='+quote(str(page),safe=''),
            'representative_questions':[links[x['question']] for x in reversed(latest) if x['question'] in links],
            'source_refs':[{'path':str(page),'sha256':page_source['sha256']}],
            'scope':'all_saved_matching_evidence;card_association_is_not_point_error'}
        concept['learning_profile']=profile
        if reference_anchors:
            concept['reference_anchors']=reference_anchors
        for view in ('protected','after_attempt','direct'):
            value={k:profile[k] for k in ('concept_key','concept_name','short_summary','progress','next_check','status','first_date','latest_date','page')}
            value['questions']=[{'formal_id':x['formal_id'],'obsidian_url':x['obsidian_url']} for x in profile['representative_questions'][:1]]
            value['progress']=value['progress'][:2]
            if reference_anchors:
                value['reference_pages']=[a['path'] for a in reference_anchors]
            if view=='protected':
                value={k:profile[k] for k in (
                'concept_key','concept_name','status','timeline_count','explicit_observation_count','first_date','latest_date')}
            hot_rows.append((key,view,canonical(value)))
        page_index.append('- [['+str(page).removesuffix('.md')+'|'+concept['label']+']]')
    write_changed(root/PAGES/'index.md','\n'.join(page_index)+'\n')
    return hot_rows


def resolve(repo_root, concepts, view='protected', max_bytes=4500, known_version=None, formal_id=None, source_id=None):
    import math_concept_index as native
    root=Path(repo_root).resolve()
    with closing(sqlite3.connect((root/native.INDEX).as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('BEGIN')
        meta={k:json.loads(v) for k,v in conn.execute("SELECT key,value FROM meta WHERE key IN ('version','store_stamps','directories','alias_problems','scope_notes','require_scope_check')")}
        changed=[p for p,s in {**meta.get('store_stamps',{}),**meta.get('directories',{})}.items() if native._stamp(root/p)!=s]
        if changed:
            return {'status':'stale','reason':'formal_sources_changed','records':[]}
        identity=None
        if source_id:
            found=list(conn.execute('SELECT DISTINCT formal_id,card_path FROM source_identities WHERE source_id=?',(source_id,)))
            if len(found)>1:
                return {'status':'ambiguous_identity','records':[]}
            if formal_id and (not found or found[0][0]!=formal_id):
                return {'status':'identity_conflict','formal_id':formal_id,'source_question_id':source_id,'records':[]}
            identity={'kind':'formal_card','formal_id':found[0][0],'card_path':found[0][1]} if found else {'kind':'new_source','source_question_id':source_id}
            formal_id=found[0][0] if found else None
        if formal_id:
            row=conn.execute('SELECT payload FROM records WHERE id=?',(formal_id,)).fetchone()
            if not row:
                return {'status':'unknown_formal_id','formal_id':formal_id,'records':[]}
            record=json.loads(row[0])
            if not concepts:
                concepts=record.get('labels',[])[:3]
            card=next((r['path'] for r in record['source_refs'] if '/错题卡/' in r['path']),None)
            identity={'kind':'formal_card','formal_id':formal_id,'card_path':card}
            detail=sorted((root/'错题知识网络/assets/visual_wrong_questions'/formal_id).glob('question_*'))
            identity['question_images']=[str(p.relative_to(root)) for p in detail if p.is_file()]
        keys=[];unknown=[];ambiguous=[];suggestions={}
        bad={native.normalize(x['alias']) for x in meta.get('alias_problems',[])}
        for q in concepts:
            if native.normalize(q) in bad:
                ambiguous.append(q);continue
            found=[k for k, in conn.execute('SELECT l.key FROM lookup l JOIN concepts c ON c.key=l.key WHERE l.name=? ORDER BY (c.normalized=?) DESC,c.label,l.key',(native.normalize(q),native.normalize(q)))]
            if not found:unknown.append(q)
            keys.extend(k for k in found if k not in keys)
        if unknown:
            labels=dict(conn.execute('SELECT label,key FROM concepts ORDER BY label'))
            for q in unknown[:3]:
                contained=[label for label in labels if native.normalize(q) and native.normalize(q) in native.normalize(label)]
                names=contained[:3] or difflib.get_close_matches(q,labels,n=3,cutoff=0.5)
                suggestions[q]=[{'concept_name':name,'concept_key':labels[name]} for name in names]
        query_version=digest(['chat-links-v1',meta['version'],keys,view,identity,concepts,max_bytes])
        base={'status':'available','version':query_version,'source_version':meta['version'], 'identity':identity,
              'unknown':unknown,'ambiguous':ambiguous,'view':view,'records':[]}
        if suggestions:base['suggestions']=suggestions
        if known_version==query_version:
            return {**base,'status':'unchanged'}
        scope=meta.get('scope_notes',{})
        base['scope_notes']={q:scope[q] for q in concepts if q in scope}
        total=0
        for key in keys:
            row=conn.execute('SELECT payload FROM teaching_profiles WHERE key=? AND view=?',(key,view)).fetchone()
            if not row:continue
            total+=1
            value=json.loads(row[0])
            for question in value.get('questions', []):
                formal = question.get('formal_id', '')
                if re.fullmatch(r'(?:GS|LA|PR)-\d+', formal) and question.get('obsidian_url'):
                    question['chat_link'] = f'{formal}（[在 Obsidian 打开](http://127.0.0.1:8765/open/{formal})）'
            base['records'].append(value)
            if len(canonical(base).encode())>max_bytes:
                base['records'].pop();break
        base.update(total=len(keys),returned=len(base['records']),truncated=len(base['records'])<len(keys))
        if not base['records']:
            base['status']='budget_too_small' if total else 'unknown_concept' if not keys else 'index_missing'
        return base


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[2])
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('refresh')
    prep=sub.add_parser('prepare');prep.add_argument('--input',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    accept=sub.add_parser('accept');accept.add_argument('--input',type=Path,required=True);accept.add_argument('--event-id',required=True,action='append',help='Repeat for all real closeouts of the same A batch')
    maintenance=sub.add_parser('accept-maintenance',help='Rewrite summaries against unchanged prepared evidence; no learning event')
    maintenance.add_argument('--input',type=Path,required=True)
    maintenance.add_argument('--maintenance-reason',required=True)
    maintenance.add_argument('--refresh-only',action='store_true',help='Save and refresh local projections without requesting publication')
    args=parser.parse_args()
    if args.command=='refresh':
        import math_concept_index
        result=math_concept_index.build_index(args.repo)
        result={k:result[k] for k in ('status','version','concept_count','record_count')}
    elif args.command=='prepare':
        result=prepare_updates(args.repo,json.loads(args.input.read_text()))
        write_changed(args.output,result);result={'status':'prepared','output':str(args.output),'concept_count':len(result['updates'])}
    elif args.command=='accept-maintenance':
        result=accept_maintenance(args.repo,json.loads(args.input.read_text()),args.maintenance_reason)
        result=finish_maintenance(args.repo,result,refresh_only=args.refresh_only)
    else:
        result=accept_updates(args.repo,json.loads(args.input.read_text()),args.event_id)
        import math_postcommit
        result['postcommit']=math_postcommit.run_after_commit(args.repo,result['event_id'])
    print(canonical(result))


if __name__=='__main__':
    main()
