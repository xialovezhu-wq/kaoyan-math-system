"""Discover mathematical scopes before loading a learner's personal profile.

Candidates are inspectable source references, not successful personal matches.
The current tutoring model chooses the scope; the reader checks identity,
generation, view and the choice's bounded discovery receipt.
"""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
import sqlite3

import math_memory_backends as backends
import math_memory_retrieval as retrieval

SCHEMA='math-scope-discovery-v1'


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


def _ticket(value):
    raw=_canonical(value)
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')+'.'+hashlib.sha256(raw).hexdigest()


def _unticket(token):
    body,checksum=token.rsplit('.',1)
    raw=base64.urlsafe_b64decode(body+'='*((-len(body))%4))
    if hashlib.sha256(raw).hexdigest()!=checksum:
        raise ValueError('invalid_math_selection_receipt')
    value=json.loads(raw)
    if value.get('schema')!=SCHEMA:
        raise ValueError('invalid_math_selection_receipt')
    return value


def _sources(root,config_path):
    config=backends._read_config(root,Path(config_path) if config_path else None)
    engine=config['backends']['native']
    public=backends.read_corpus(Path(engine['corpus_path']),engine['corpus_sha256'])
    if public['source_version']!=backends.native_version(root):
        raise ValueError('discovery_source_stale')
    return config,public,engine


def _surface(query,docs):
    text=retrieval._lexical_text(query)
    grams={text[i:i+2] for i in range(max(0,len(text)-1))}
    ranked=[]
    for doc in docs:
        names=[doc['title'],*doc.get('aliases',[]),*doc.get('search_descriptions',[])]
        exact=any(text==retrieval._lexical_text(name) for name in [doc['title'],*doc.get('aliases',[])])
        score=max((len(grams & {value[i:i+2] for i in range(max(0,len(value)-1))})/
                   max(1,len(grams | {value[i:i+2] for i in range(max(0,len(value)-1))}))
                  for value in map(retrieval._lexical_text,names)),default=0)
        if score or exact:ranked.append({'id':doc['id'],'weight':100 if exact else score})
    return sorted(ranked,key=lambda r:(-r['weight'],r['id']))


def _expanded_order(root, query, reference, docs, ordered, limit, diagnostics):
    # Keep the old strongest candidates. Reserve the last two slots to recover
    # mathematically related points that wording and the local model both missed.
    if not ordered or limit < 4:
        return ordered
    from math_memory_global_vectors import INDEX, neighbor_candidates
    if not (root / INDEX).is_file():
        return ordered
    from math_memory_semantic import query_readiness, scope_rejection
    intent = query_readiness(query, docs.values())
    if not intent['ready']:
        return ordered
    try:
        seeds = [key for key in ordered[:5] if not scope_rejection(docs[key], query, intent['intent'])]
        candidates = neighbor_candidates(root, reference, seeds)
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        diagnostics.append({'component':'global_vector_neighbors','status':'unavailable','reason':type(exc).__name__})
        return ordered
    tail_start = limit - 2
    extra = [key for key in candidates if key in docs and key not in ordered[:limit]
             and not scope_rejection(docs[key], query, intent['intent'])][:2]
    if extra:
        diagnostics.append({'component':'global_vector_neighbors','status':'used','added':len(extra)})
        return [*ordered[:tail_start], *extra, *ordered[tail_start:]]
    return ordered


def discover(repo_root,query,*,view='after_attempt',config_path=None,limit=8,max_bytes=24000):
    if view=='protected':
        return {'schema':SCHEMA,'status':'protected','records':[],'candidates':[],
                'personal_profile_loaded':False,'private_annotations_read':False}
    if view not in {'after_attempt','direct'} or not isinstance(query,str) or not query.strip() or len(query)>1000:
        raise ValueError('invalid_math_discovery_request')
    if not 1<=limit<=12 or not 64<=max_bytes<=64000:
        raise ValueError('invalid_math_discovery_budget')
    if max_bytes<2000:
        return {'status':'budget_too_small','records':[],'required_min_bytes':2000}
    root=Path(repo_root).resolve();config,public,engine=_sources(root,config_path)
    docs=[d for d in public['documents'] if retrieval.is_discovery_eligible(d)];by_id={d['id']:d for d in docs}
    surface=_surface(query,docs);native=retrieval.rank(query,docs,limit=2)
    rankings=[[r['id'] for r in native['ranked']],[r['id'] for r in surface[:24]]]
    exact=[r['id'] for r in surface if r['weight']==100]
    diagnostics=[];private=(config.get('reference_semantic') or {}).get('engine')
    if not exact and isinstance(private,dict) and private.get('status')=='ready':
        try:
            from math_memory_point_context import load_point_context
            if backends.sha(Path(private['corpus_path']))!=private['corpus_sha256']:
                raise ValueError('point_context_hash_changed')
            load_point_context(root,private['corpus_path'],view=view,discovery=public)
            # The locator never returns annotation text, outcomes or source
            # quotations to the mathematical scope-selection stage.
            response=backends.runtime_query(private,'qmd',query,list(by_id),16,view=view,timeout=8)
            rankings.append([r['id'] for r in response.get('candidates',[]) if r.get('id') in by_id])
        except (OSError,ValueError,KeyError) as exc:
            diagnostics.append({'component':'semantic_candidates','status':'unavailable','reason':str(exc)[:120]})
    scores={}
    for ranking in rankings:
        for rank,identity in enumerate(ranking):scores[identity]=scores.get(identity,0)+1/(20+rank+1)
    ordered=exact if exact else sorted(scores,key=lambda k:(-scores[k],k))
    math_docs={};math_version=None
    reference_path=(config.get('reference_semantic') or {}).get('mathematical_reference_path')
    if reference_path:
        try:
            from math_memory_reference_catalog import load_references
            reference=load_references(root,reference_path,view=view,discovery=public)
            math_docs={d['id']:d for d in reference['documents']};math_version=reference['version']
            if not exact:
                ordered = _expanded_order(root, query, reference, by_id, ordered, limit, diagnostics)
        except (OSError,ValueError,KeyError) as exc:
            diagnostics.append({'component':'mathematical_scope_material','status':'unavailable','reason':str(exc)[:120]})
    candidates=[]
    for key in ordered[:limit]:
        doc=by_id[key];fragments=math_docs.get(key,{}).get('fragments',[])
        candidates.append({'concept_key':key,'concept_name':doc['title'],
            'catalogue_kind':doc.get('knowledge_type'),'primary_operations':doc.get('retrieval_signature',{}).get('primary_operations',[]),
            'mathematical_scope_references':[{'id':f['id'],'title':f['title'],
                'conditions':f.get('conditions',[]),'source_refs':f['source_refs']} for f in fragments[:2]],
            'not_personal_evidence':True,'not_applicability_confirmation':True})
    receipt={'schema':SCHEMA,'query_sha256':hashlib.sha256(query.encode()).hexdigest(),
             'view':view,'source_version':public['source_version'],'catalogue_sha256':engine['corpus_sha256'],
             'math_reference_version':math_version,'candidate_keys':[r['concept_key'] for r in candidates]}
    result={'schema':SCHEMA,'status':'needs_math_scope_selection' if candidates else 'no_candidate',
            'records':[],'candidates':candidates,'source_version':public['source_version'],
            'selection_receipt':_ticket(receipt),'personal_profile_loaded':False,
            'selection_owner':'current_assistant_checks_object_goal_and_conditions',
            'candidate_count_is_not_success':True,'diagnostics':diagnostics,'learning_write_count':0}
    while len(_canonical(result))>max_bytes and len(candidates)>1:
        candidates.pop();receipt['candidate_keys']=[r['concept_key'] for r in candidates]
        result['selection_receipt']=_ticket(receipt);result['more_candidates_omitted']=True
    if len(_canonical(result))>max_bytes:
        result.update(status='budget_too_small',required_min_bytes=len(_canonical(result)),candidates=[],selection_receipt=None)
    return result


def validate_selection(repo_root,query,key,receipt,*,view,config_path=None):
    value=_unticket(receipt);root=Path(repo_root).resolve()
    config,public,engine=_sources(root,config_path)
    if value['view']!=view or value['query_sha256']!=hashlib.sha256(query.encode()).hexdigest():
        raise ValueError('math_selection_question_or_view_changed')
    if value['source_version']!=public['source_version'] or value['catalogue_sha256']!=engine['corpus_sha256']:
        raise ValueError('math_selection_source_changed')
    if key is not None and (key not in value['candidate_keys'] or key not in {d['id'] for d in public['documents']}):
        raise ValueError('math_selection_outside_inspected_candidates')
    if value.get('math_reference_version'):
        from math_memory_reference_catalog import load_references
        path=(config.get('reference_semantic') or {}).get('mathematical_reference_path')
        if not path or load_references(root,path,view=view,discovery=public)['version']!=value['math_reference_version']:
            raise ValueError('math_selection_reference_changed')
    return value
