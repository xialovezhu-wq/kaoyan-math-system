"""Local mathematical reference retrieval, separate from personal evidence.

The model orders source-backed mathematical topics. It never adjudicates a
learner's statement, establishes applicability, or writes a learning event.
"""
from __future__ import annotations

import re
from pathlib import Path

import math_memory_retrieval as lexical

REVISION='math-reference-semantic-selection-v1'
_TECHNICAL=('无偏','偏差','期望','方差','协方差','独立','同分布','正态','零相关',
    '均值','密度','分布函数','条件概率','幂级数','展开式','系数','次幂','收敛',
    '特征值','特征向量','行满秩','列满秩','满行秩','满列秩','余子式','伴随',
    '线性组合','非零行','阶梯形','零空间','解空间','正定','半正定','矩阵幂',
    '圆心','圆盘','半径','曲面','曲线','切线','切平面','计数','排列','组合数',
    '极坐标','坐标','积分区域','被积函数','微分方程','导数','偏导数',
    '无穷小','泰勒','相乘','相减','同次数','定限','换序','换元','依概率','依分布')
_SOFTWARE=re.compile(r'快捷键|按钮|菜单|安装|卸载|登录|账号|照片|视频剪辑|电影|电视剧|'
    r'photoshop|浏览器|网页样式|css|html|word文档|pdf阅读器|软件界面',re.I)
_FORMULA=re.compile(r'(?<![A-Za-z])(?:sin|cos|tan|ln|exp|cov)\b|[∫∑Σ√λμσθ∞]|'
    r'[A-Za-z][A-Za-z0-9(){}^*+\-]*\s*(?:=|≤|≥|→)',re.I)


def query_readiness(query,docs):
    """Require a mathematical target, without demanding its canonical name."""
    intent=lexical.analyze_query(query)
    positive=intent['positive'];original=lexical.normalize(query)
    if _SOFTWARE.search(original):
        return {'ready':False,'status':'no_match','reason':'non_mathematical_action','intent':intent}
    terms=set(_TECHNICAL)
    for doc in docs:
        sig=doc.get('retrieval_signature') or {}
        for field in ('objects','operations','conditions'):
            terms.update(t for t in sig.get(field,[]) if isinstance(t,str) and len(t)>=2)
    terms={lexical.normalize(t) for t in terms if t not in lexical._GENERIC or t=='独立'}
    hits=lexical._longest_terms(positive,terms)
    formula=bool(_FORMULA.search(intent['positive_text']))
    named=any(len(name)>=4 and name not in lexical._BROAD and lexical._contains(positive,name)
              for doc in docs for name in lexical._names(doc))
    specific=bool(len(hits)>=2 or formula and hits or named or
                  any(len(term)>=3 for term in hits) and
                  re.search(r'条件|区别|前提|定义|怎么|怎样|为何|为什么|能否|求|算|变换|消去|消因子',positive))
    return {'ready':specific,'status':'ambiguous','reason':None if specific else 'mathematical_target_not_specific',
            'math_terms':hits,'formula_present':formula,'intent':intent}


def scope_rejection(doc,query,constraints):
    if lexical.exclusion_reason(doc):
        return 'ineligible_catalog_entry'
    if doc.get('knowledge_type')=='parent' or (doc.get('retrieval_signature') or {}).get('broad'):
        return 'parent_not_specific_operation'
    positive=constraints['positive']
    if lexical.special_scope_reason(doc,positive):
        return lexical.special_scope_reason(doc,positive)
    title=lexical.normalize(doc['title']);sig=doc.get('retrieval_signature') or {}
    if lexical._dimension_conflict(title,positive):
        return 'explicit_dimension_conflict'
    # Joint normality is a meaningful distinguishing scope; a query may ask
    # about its limits, but a bare correlation question does not supply it.
    if re.search(r'二维正态|二元正态|联合正态',title) and not re.search(
            r'二维正态|二元正态|联合正态',positive):
        return 'joint_normal_topic_not_stated'
    names=lexical._names(doc)
    for rejected in constraints.get('excluded',[]):
        for term in rejected.get('terms',[]):
            if len(term)<3:
                continue
            if any(term==name or term in name for name in names):
                components=lexical._title_components(doc['title'])
                if not any(term not in part and lexical._contains(positive,part) for part in components):
                    return 'explicitly_excluded_topic'
    return None


def select(query,docs,ranked,*,native_selection=None):
    """Use relevance order only after explicit scope checks, never score truth."""
    readiness=query_readiness(query,docs)
    base={'schema':REVISION,'ranked':[],'constraints':readiness['intent'],
          'reference_only':False,'personal_evidence_eligible':False,
          'score_semantics':'source_relevance_order_not_truth_or_mastery',
          'math_terms':readiness.get('math_terms',[]),'not_personal_record_verification':True}
    if not readiness['ready']:
        return {**base,'status':readiness['status'],'reason':readiness['reason']}
    lookup={doc['id']:doc for doc in docs};accepted=[];rejected=[]
    for position,item in enumerate(ranked):
        doc=lookup.get(item.get('id'))
        if doc is None:
            continue
        reason=scope_rejection(doc,query,readiness['intent'])
        if reason:
            rejected.append({'id':doc['id'],'reason':reason});continue
        accepted.append({'id':doc['id'],'concept_key':doc['concept_key'],
            'match_kind':'local_mathematical_reference_relevance',
            'reasons':['source_bound_mathematical_reference','explicit_scope_checked'],
            'semantic_rank':position+1,'reference_only':False,'fine_point':True,
            'personal_evidence_eligible':True,'requires_scope_check':True,
            'not_proof_of_current_error':True,'applicability_confirmed':False})
    if not accepted:
        return {**base,'status':'no_match','reason':'no_semantic_candidate_within_requested_scope',
                'rejected_semantic_candidates':rejected}
    return {**base,'status':'matched','ranked':accepted[:1],
            'personal_evidence_eligible':True,'reason':'local_reference_topic_selected',
            'rejected_semantic_candidates':rejected}


def preferred_declared_selection(native,docs):
    """Prefer explicit object/operation evidence over an embedding neighbour.

    Weak lookup descriptions cannot establish this priority. All remaining
    choices continue to semantic discovery; this is not a rejection threshold.
    """
    if not native or native.get('status')!='matched' or not native.get('ranked'):
        return False
    row=native['ranked'][0];doc=next((d for d in docs if d['id']==row['id']),{})
    kind=row.get('match_kind');sig=doc.get('retrieval_signature') or {}
    if kind in {'exact_identity','exact_title','exact_declared_alias'}:
        return True
    if row.get('named_condition_support'):
        return True
    if kind in {'specific_name_in_request','specific_compound_subtopic','object_and_operation'}:
        return bool(row.get('primary_operation_matches') and row.get('coverage',0)>=.75)
    if kind=='distinctive_catalog_phrases':
        trusted=[lexical._lexical_text(s) for s in sig.get('trusted_phrases',[])]
        terms=[term for term in row.get('catalog_phrase_evidence',[])
               if any(term in phrase for phrase in trusted)]
        operation=bool(row.get('primary_operation_matches') or
            re.search(r'定理|定律|不等式|法则|准则',doc.get('title','')) and row.get('operation_matches'))
        return operation and len(terms)>=2 and sum(map(len,terms))>=6
    return False


def prefer_unique_recorded_method_point(selected,docs,contexts,query):
    """Resolve a method-name reference to its unique recorded fine point.

    This uses the same authenticated method identity, not chapter similarity;
    multiple recorded branches remain separate and are never picked by recency.
    """
    if selected.get('status')!='matched' or not selected.get('ranked'):
        return selected
    public={d['id']:d for d in docs};row=selected['ranked'][0];doc=public[row['id']]
    if contexts.get(row['id'],{}).get('content_role')!='mathematical_reference':
        return selected
    methods=doc.get('descriptor_method_ids') or []
    if len(methods)!=1 or doc['title'] not in doc.get('method_identity_names',[]):
        return selected
    matches=[other for other in docs if other.get('descriptor_method_ids')==methods
        and contexts.get(other['id'],{}).get('content_role')=='accepted_point_annotation'
        and not scope_rejection(other,query,selected['constraints'])]
    if len(matches)!=1:
        return selected
    target=matches[0]
    return {**selected,'ranked':[{**row,'id':target['id'],'concept_key':target['concept_key'],
        'match_kind':'unique_recorded_point_for_same_declared_method',
        'reasons':[*row.get('reasons',[]),'same_verified_method_identity_unique_recorded_point']}],
        'method_reference_identity':doc['id'],'not_current_mastery':True}


def resolve(repo_root,query,docs,engine,*,view,native_selection=None,timeout=8.0,discovery=None):
    from math_memory_reference_catalog import require_reference_view,load_references
    require_reference_view(view)  # Before any reference path is opened.
    if preferred_declared_selection(native_selection,docs):
        return native_selection,{'model_used':False,'route':'declared_object_operation_or_named_condition'}
    if (native_selection and native_selection.get('status')=='ambiguous'
            and not native_selection.get('ranked') and
            native_selection.get('rejected_counts',{}).get('operation_pair_requires_object_or_identity')):
        return native_selection,{'model_used':False,'route':'missing_mathematical_object'}
    readiness=query_readiness(query,docs)
    if not readiness['ready']:
        return select(query,docs,[],native_selection=native_selection),{'model_used':False}
    import math_memory_backends as backend
    path=Path(engine['corpus_path'])
    if backend.sha(path)!=engine['corpus_sha256']:
        raise ValueError('reference_corpus_changed')
    annotation_policy=engine.get('content_policy')=='accepted_point_annotations_and_math_references'
    if annotation_policy:
        from math_memory_point_context import load_point_context
        reference=load_point_context(repo_root,path,view=view,discovery=discovery)
    else:
        reference=load_references(repo_root,path,view=view,discovery=discovery)
    by_id={d['id']:d for d in reference['documents']}
    if set(by_id)!={d['id'] for d in docs}:
        raise ValueError('reference_scope_filter_unavailable')
    response=backend.runtime_query(engine,'qmd',readiness['intent']['positive_text'],list(by_id),12,
                                   timeout=timeout,view=view)
    selected=select(query,docs,response['candidates'],native_selection=native_selection)
    if annotation_policy:
        selected=prefer_unique_recorded_method_point(selected,docs,by_id,query)
    return selected,{'model_used':True,'runtime_reused':response.get('runtime_reused'),
        'reference_version':reference['version'],'model':engine['model'],
        'query_embedding_network':'remote_disabled','personal_annotation_index_read':annotation_policy,
        'raw_user_utterances_read':False,'not_current_learner_judgment':True}
