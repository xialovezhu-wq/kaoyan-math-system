"""Small, evidence-preserving exam guidance; never infer personal mastery.

This is a deterministic projection of reviewed methods and typed evidence.  The
teaching model still checks the current question and the user's actual work.
"""
from __future__ import annotations

import copy
import json

SCHEMA = 'math-exam-brief-v1'
CHOICE_FILL_SCHEMA = 'math-choice-fill-guidance-v1'
STEP_STATES = frozenset({
    'independent_performed', 'corrected_after_hint', 'exposed_only',
    'self_reported', 'unresolved', 'unknown', 'preference_only',
})
SELECTION_CONTEXT = {
    'order': [
        '先核题设与方法的适用条件',
        '保留本轮已正确的步骤前缀，由讲题模型依据实际作答判断',
        '在适用范围内遵循明确讲法偏好',
        '当前是选填时，先检查已核技巧或二级结论；满足全部条件、足以可靠完成且明显省步时优先，否则沿一般解法',
        '复用有证据的已做步骤，比较需补的前置；未知不算没学过',
        '前述条件相当时再比较运算成本',
    ],
    'policy': '默认讲一条主线；未明确选定时先辨候选。讲题须明示考点频次等级、去重考查次数及必要统计范围，不列具体年份或出现年份数；选填先核已核技巧与二级结论，满足条件且足够时优先。依据具体证据及当前反馈，已知环节简列，卡点只补必要连接；未知不从零重讲，未要求结论证明时只给条件及应用。不得按关键词把概念正确映成全部步骤已会；提示后、接触、自述和偏好均不等于独立完成。',
    'current_attempt_status': 'requires_live_judgement',
}


def _encoded_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':')).encode())


def choice_fill_guidance(formal_methods=None, concept_methods=(), *, view='direct',
                         max_bytes=5000, max_candidates=3):
    """Compile small, executable choice/fill guidance from guarded projections.

    The caller must run checked_projection first and call before exact-card
    duplicate suppression. No source reads, new applicability inference, method
    selection or learner assessment occur here. An exact-card short route is
    copied verbatim; generic techniques retain every condition, ordered action,
    formula, exception and branch. Budgeting accepts whole atoms only.
    """
    if view == 'protected':
        return {'schema': CHOICE_FILL_SCHEMA, 'status': 'protected'}
    import math_problem_methods as methods
    result = {'schema': CHOICE_FILL_SCHEMA, 'status': 'not_available',
        'selection_policy': '仅对当前获准讲解的选填题，核全部条件后，若可靠技巧足够完成且有明显省步收益则优先；保留有效原路线。有限特例只能排错，未唯一排除或填空未一般证明时回正解。',
        'personal_evidence': False, 'selected_method_id': None,
        'question_routes': [], 'technique_candidates': []}
    formal = formal_methods or {}
    if formal.get('status') in ('available', 'partial') and formal.get('binding_scope') == 'exact_formal_card':
        for route in formal.get('routes', []):
            hint = route.get('specific_hint', '')
            if (route.get('status') == 'stale' or route.get('binding_status')
                    or not str(route.get('source_status', '')).startswith('verified_')
                    or not isinstance(hint, str)
                    or '已核短路线：' not in hint or '适用条件：' not in hint):
                continue
            result['question_routes'].append({'method_id': route['method_id'],
                'binding_scope': 'exact_formal_card', 'specific_hint': hint,
                'applicability': route.get('applicability', '')})
    # Prefer exact-card material when present, but never designate its first
    # method as the main solution. The teaching model still checks the question.
    required_bytes = _encoded_bytes(result)
    if required_bytes > max_bytes and result['question_routes']:
        return {'schema': CHOICE_FILL_SCHEMA, 'status': 'budget_too_small',
                'required_min_bytes': required_bytes,
                'reason': 'complete_exact_question_guidance_must_not_be_truncated'}
    candidates = []
    seen = set()
    for projection in [formal] + list(concept_methods or ()):
        if not projection or projection.get('status') not in ('available', 'partial'):
            continue
        for route in projection.get('routes', []):
            core = methods.choice_fill_execution(route)
            if core and core['method_id'] not in seen:
                seen.add(core['method_id'])
                candidates.append(core)
    omitted = []
    smallest = None
    for core in candidates:
        tentative = copy.deepcopy(result)
        tentative['technique_candidates'].append(core)
        size = _encoded_bytes(tentative)
        smallest = min(smallest, size) if smallest is not None else size
        if len(result['technique_candidates']) < max_candidates and size <= max_bytes:
            result['technique_candidates'].append(core)
        else:
            omitted.append(core['method_id'])
    if result['question_routes'] or result['technique_candidates']:
        result['status'] = 'available' if not omitted else 'bounded_candidates'
        if omitted:
            result['other_candidate_count'] = len(omitted)
            result['other_candidate_ids'] = omitted
            result['coverage_note'] = '仅保留当前预算内完整候选；未展示项不表示不适用，不自动选择首候选。'
        # Envelope annotations also count. Discard optional audit labels before
        # sacrificing an otherwise complete technique already within budget.
        for field in ('other_candidate_ids', 'coverage_note'):
            if _encoded_bytes(result) > max_bytes:
                result.pop(field, None)
        # Only then defer an entire optional atom; never shave a condition or
        # a line of its mathematical conclusion.
        while _encoded_bytes(result) > max_bytes and result['technique_candidates']:
            omitted.append(result['technique_candidates'].pop()['method_id'])
            result.update(status='bounded_candidates', other_candidate_count=len(omitted))
            result.pop('other_candidate_ids', None)
            result.pop('coverage_note', None)
        if _encoded_bytes(result) > max_bytes:
            return {'schema': CHOICE_FILL_SCHEMA, 'status': 'budget_too_small',
                    'required_min_bytes': _encoded_bytes(result),
                    'reason': 'complete_exact_question_guidance_must_not_be_truncated'}
        if not result['question_routes'] and not result['technique_candidates']:
            return {'schema': CHOICE_FILL_SCHEMA, 'status': 'budget_too_small',
                    'required_min_bytes': smallest,
                    'reason': 'complete_technique_conditions_actions_and_conclusions_required'}
        return result
    if candidates:
        return {'schema': CHOICE_FILL_SCHEMA, 'status': 'budget_too_small',
                'required_min_bytes': smallest,
                'reason': 'complete_technique_conditions_actions_and_conclusions_required'}
    return result


def _deduplicate_choice_fill(response):
    """Remove only duplicate route fields already complete in this response."""
    guidance = response.get('choice_fill_guidance', {})
    if guidance.get('status') not in ('available', 'bounded_candidates'):
        return
    import math_problem_methods as methods
    exact = {r['method_id']: (i,r) for i,r in enumerate(guidance.get('question_routes', []))}
    cores = {r['method_id']: (i,r) for i,r in enumerate(guidance.get('technique_candidates', []))}
    for item in [response] + response.get('records', []):
        method = item.get('problem_solving')
        if not method:
            continue
        for route in method.get('routes', []):
            mid = route['method_id']
            if mid in exact:
                i, copy_row = exact[mid]
                if route.get('specific_hint') == copy_row.get('specific_hint'):
                    route.pop('specific_hint', None)
                    route['choice_fill_guidance_ref'] = f'response.choice_fill_guidance.question_routes[{i}]'
            if mid in cores:
                i, core = cores[mid]
                if route.get('conditions') != core.get('conditions') or route.get('first_action') != core.get('first_action'):
                    continue
                execution = methods.choice_fill_execution(route)
                if execution is None or any(execution.get(field) != core.get(field) for field in
                        ('steps', 'direct_conclusions', 'branches', 'pitfalls')):
                    continue
                route['choice_fill_guidance_ref'] = f'response.choice_fill_guidance.technique_candidates[{i}]'
                # Every execution object is preserved in the complete core;
                # ordinary methods remain untouched by this deduplication.
                for field in ('steps', 'step_graph', 'direct_conclusions', 'branches', 'pitfalls'):
                    route.pop(field, None)
                if route.get('specific_hint') == core.get('specific_hint'):
                    route.pop('specific_hint', None)


def _ids(values, key):
    return list(dict.fromkeys(v[key] for v in values if isinstance(v, dict)
                             and isinstance(v.get(key), str)))


def brief(methods=None, preferences=(), step_evidence=(), next_check='',
          view='direct', semantic_status='evidence_digest_only'):
    """Keep conditions whole, use only explicit IDs, and select no implicit route."""
    if view == 'protected':
        return None
    routes = (methods or {}).get('routes', [])
    candidates = []
    for route in routes:
        if route.get('status') == 'stale':
            continue
        steps = route.get('step_ids') or _ids(route.get('step_graph', []), 'step_id')
        conclusions = route.get('direct_conclusion_ids') or _ids(
            route.get('direct_conclusions', []), 'conclusion_id')
        candidates.append({
            'method_id': route['method_id'],
            'clues': copy.deepcopy(route.get('triggers', [])),
            'first_action': route.get('first_action', ''),
            'necessary_conditions': copy.deepcopy(route.get('conditions', [])),
            'applicability': route.get('applicability', ''),
            'step_ids': list(steps),
            'direct_conclusion_ids': list(conclusions),
        })
    explicit = (methods or {}).get('primary_method_id')
    if explicit not in {row['method_id'] for row in candidates}:
        explicit = None
    # Only the caller's non-stale, individually validated evidence is eligible.
    evidence = step_evidence if semantic_status == 'semantic_current' else ()
    known = []
    for i, row in enumerate(evidence):
        if row.get('state') not in STEP_STATES:
            continue
        item = {'evidence_index': i, 'step_ids': list(row['step_ids']),
                'state': row['state'], 'scope': row['scope']}
        if 'coverage' in row:
            item['coverage'] = row['coverage']
        if row.get('coverage') == 'partial_operation':
            item['whole_step_independence_supported'] = False
            item['evidence_limit'] = '仅局部动作；不得据此认定整个步骤已独立完成。'
        known.append(item)
    return {
        'schema': SCHEMA,
        'primary_method_id': explicit,
        'selection_status': ('explicit_route_requires_condition_check' if explicit else
                             'candidate_requires_live_selection' if candidates else
                             'no_verified_method'),
        'selection_context': copy.deepcopy(SELECTION_CONTEXT),
        'candidates': candidates,
        'preference_refs': [{'preference_index': i, 'basis': row['basis'],
                             'scope': row['scope']} for i, row in enumerate(preferences)],
        'known_operation_evidence': known,
        'step_knowledge_status': 'scoped_evidence_only' if known else 'not_established',
        'next_check': next_check or '依据本轮实际作答检查下一处条件或动作；没有步骤证据不推断不会。',
    }


def reference_brief(value, methods):
    """Remove only content duplicated in an accompanying complete route atom."""
    result = copy.deepcopy(value)
    routes = {r['method_id']: r for r in (methods or {}).get('routes', [])}
    for row in result.get('candidates', []):
        route = routes.get(row['method_id'], {})
        if (route.get('conditions') == row.get('necessary_conditions')
                and route.get('first_action') == row.get('first_action')
                and route.get('triggers') == row.get('clues')
                and route.get('applicability', '') == row.get('applicability', '')):
            for field in ('necessary_conditions', 'first_action', 'clues', 'applicability'):
                row.pop(field, None)
            row['content_ref'] = 'problem_solving.routes:' + row['method_id']
    return result


def compact_step_evidence(values):
    """Preserve structured turn quotes intact; omit only prose explanations."""
    result = []
    for row in values:
        item = {key: copy.deepcopy(row[key]) for key in
                ('step_ids', 'state', 'scope', 'coverage', 'source_refs') if key in row}
        for field in ('user_evidence', 'hint_evidence'):
            body = row.get(field)
            if isinstance(body, list) and body and all(isinstance(atom, dict) for atom in body):
                # A sequence/quote pair is one source-located atom. Do not turn
                # it into plain text or discard its turn number when compacting.
                item[field] = copy.deepcopy(body)
        result.append(item)
    return result


def _omit(value, fields):
    """Drop whole fields and record the exact omission; never slice content."""
    omitted = list(value.get('omitted_fields', []))
    for field in fields:
        if field in value:
            value.pop(field)
            if field not in omitted:
                omitted.append(field)
    if omitted:
        value['omitted_fields'] = omitted


def budget_method(value, level=1):
    """Hot-only projection after source verification, in increasing detail tiers.

    Provenance and audit payloads go first. Conditions and the first action of
    every candidate remain complete, including when no primary is selected.
    """
    result = copy.deepcopy(value)
    _omit(result, ('source', 'version', 'selection_policy', 'evidence_policy'))
    result['detail_lookup'] = 'query_exact_method_id_with_larger_max_bytes'
    keep = {
        'method_id', 'name', 'subject', 'role', 'status', 'source_status',
        'conditions', 'first_action', 'triggers', 'steps', 'branches', 'pitfalls',
        'applicability', 'specific_hint', 'current_concept_applicability',
        'current_concept_hint', 'binding_status', 'reason', 'step_graph',
        'step_ids', 'step_graph_ids', 'direct_conclusions', 'conclusion_ids',
        'direct_conclusion_ids', 'refinement_ids', 'refinement_stale_ids',
        'detail_status', 'omitted_fields',
        'choice_fill_guidance_ref',
    }
    for route in result.get('routes', []):
        refinement_ids = list(route.get('refinement_ids', []))
        stale_ids = list(route.get('refinement_stale_ids', []))
        for child in route.get('refinement_candidates', []):
            mid = child.get('method_id')
            if mid and mid not in refinement_ids:
                refinement_ids.append(mid)
            if mid and child.get('status') == 'stale' and mid not in stale_ids:
                stale_ids.append(mid)
        for mid in route.get('refinement_candidates_omitted_ids', []):
            if mid not in refinement_ids:
                refinement_ids.append(mid)
        if refinement_ids:
            route['refinement_ids'] = refinement_ids
        if stale_ids:
            route['refinement_stale_ids'] = stale_ids
        _omit(route, tuple(field for field in route if field not in keep))
        # Shared citations can dominate a small response. Their exact bytes are
        # still available from the full method/object lookup; guards ran first.
        for field in ('step_graph', 'direct_conclusions'):
            for node in route.get(field, []):
                _omit(node, ('source_refs',))
        if level >= 2:
            if 'step_graph' in route:
                route.setdefault('step_graph_ids', _ids(route['step_graph'], 'step_id'))
            if 'direct_conclusions' in route:
                route.setdefault('conclusion_ids', _ids(route['direct_conclusions'], 'conclusion_id'))
                route.setdefault('direct_conclusion_ids', _ids(
                    [c for c in route['direct_conclusions'] if c.get('direct_use')], 'conclusion_id'))
            _omit(route, ('step_graph', 'direct_conclusions'))
        if level >= 3:
            _omit(route, ('branches', 'pitfalls', 'subject'))
        if level >= 4:
            _omit(route, ('steps', 'triggers', 'specific_hint', 'applicability',
                          'current_concept_hint', 'current_concept_applicability', 'name', 'role'))
            if set(route.get('step_graph_ids', [])) == set(route.get('step_ids', [])):
                _omit(route, ('step_graph_ids',))
            if route.get('conclusion_ids') == route.get('direct_conclusion_ids'):
                _omit(route, ('conclusion_ids',))
            if not route.get('refinement_ids'):
                route.pop('refinement_ids', None)
        route['detail_status'] = 'omitted' if level >= 4 else 'budget_projection'
    # Describe common omissions once instead of spending the teaching budget on
    # the same long audit-field list for every candidate. Paths are explicit.
    omitted = list(result.get('omitted_fields', []))
    for route in result.get('routes', []):
        for field in route.pop('omitted_fields', []):
            path = 'routes[].' + field
            if path not in omitted:
                omitted.append(path)
    result['omitted_fields'] = omitted
    result['omission_scope'] = 'whole_fields_where_present'
    result['conditions_and_first_action_complete'] = True
    if level >= 4:
        # One explicit category list replaces a long repeated audit transcript.
        # Every non-core field is still available from the same exact method ID.
        result['omitted_fields'] = ['source_refs', 'review_metadata', 'refinement_candidates',
                                    'step_graph', 'direct_conclusions', 'steps', 'metadata']
        for key in ('binding_scope', 'conditions_and_first_action_complete', 'detail_lookup',
                    'omission_scope', 'selection_status'):
            result.pop(key, None)
    return result


def budget_evidence(values):
    """Keep scoped findings whole while deferring full quotations/provenance."""
    result = []
    for row in values:
        item = {key: copy.deepcopy(row[key]) for key in
                ('step_ids', 'state', 'scope', 'coverage') if key in row}
        item['omitted_fields'] = [key for key in ('user_evidence', 'hint_evidence', 'source_refs') if key in row]
        item['detail_lookup'] = 'same_concept_with_larger_max_bytes'
        if row.get('coverage') == 'partial_operation':
            item['whole_step_independence_supported'] = False
            item['evidence_limit'] = '仅局部动作；不得据此认定整个步骤已独立完成。'
        result.append(item)
    return result


def budget_brief(value, item, has_response_method=False):
    """Use explicit sibling references instead of repeating teaching content."""
    result = {key: copy.deepcopy(value[key]) for key in
              ('selection_context_ref', 'personal_context_refs') if key in value}
    if item.get('problem_solving'):
        result['method_selection_ref'] = 'problem_solving'
        result['candidates'] = [{
            'method_id': row['method_id'],
            'content_ref': 'problem_solving.routes:' + row['method_id'],
            'direct_conclusion_ids': list(row.get('direct_conclusion_ids', [])),
        } for row in item['problem_solving'].get('routes', []) if row.get('status') != 'stale']
    else:
        result['candidates'] = []
        if has_response_method:
            result['method_selection_ref'] = 'response.problem_solving'
    if item.get('teaching_preferences'):
        result['teaching_preferences_ref'] = 'teaching_preferences'
    if item.get('step_evidence'):
        result['known_operation_evidence_ref'] = 'step_evidence'
    result['next_check_ref'] = 'next_check' if 'next_check' in item else 'records[].next_check'
    return result


def apply_response_budget(response, level):
    """Mutate only this ephemeral response, never cached or published material."""
    _deduplicate_choice_fill(response)
    if 'selection_context' in response:
        response['selection_context'] = {
            'order': ['适用条件', '本轮正确前缀（主模型判断）', '明确偏好',
                      '选填：已核且条件完整、足够可靠的省步技巧',
                      '有据的熟悉步骤与较少陌生前置', '运算成本'],
            'policy': '明示考频等级/去重考查次数/统计范围，不列具体年份；选填核条件。已知简列，卡点补连接，结论证明按请求；未知不等于没学过，不默认首候选。',
        }
    for item in [response] + response.get('records', []):
        if item.get('object_role') in ('step_reference', 'conclusion_reference'):
            # Exact references are indivisible: formula+conditions+exceptions
            # or action+direct prerequisites either all fit or fail the budget.
            continue
        if level >= 1 and item.get('problem_solving'):
            item['problem_solving'] = budget_method(item['problem_solving'], level)
        if level >= 3 and item.get('step_evidence'):
            item['step_evidence'] = budget_evidence(item['step_evidence'])
            omitted = list(item.get('step_evidence_omitted_fields', []))
            for evidence in item['step_evidence']:
                for field in evidence.pop('omitted_fields', []):
                    if field not in omitted:
                        omitted.append(field)
                evidence.pop('detail_lookup', None)
            item['step_evidence_omitted_fields'] = omitted
            item['step_evidence_detail_lookup'] = 'same_concept_with_larger_max_bytes'
        if item.get('exam_brief'):
            item['exam_brief'] = budget_brief(item['exam_brief'], item,
                has_response_method=bool(response.get('problem_solving')))
        if level >= 1 and item.get('exam_brief'):
            refs = {'methods': 'problem_solving' if item.get('problem_solving') else 'response.problem_solving',
                    'next_check': 'next_check' if 'next_check' in item else 'records[].next_check'}
            if item.get('teaching_preferences'):
                refs['preferences'] = 'teaching_preferences'
            if item.get('step_evidence'):
                refs['evidence'] = 'step_evidence'
            item['exam_brief'] = {'field_refs': list(refs.values())}
        if level >= 4:
            item.pop('step_evidence_detail_lookup', None)
            if item.pop('solution_connections', None):
                item['solution_connections_detail_lookup'] = 'same_concept_with_larger_max_bytes'
        if level >= 5 and item.get('step_evidence') and item.get('short_summary') and item.get('next_check'):
            # The reviewed short summary is the place for the current worked
            # prefix, correction, scope and next check. Keeping a leading
            # slice of the evidence array could show only an older error.
            item['step_evidence_omitted_count'] = len(item.pop('step_evidence'))
            item['step_evidence_status'] = 'budget_omitted'
            if item.get('exam_brief'):
                item['exam_brief']['field_refs'] = [
                    ref for ref in item['exam_brief'].get('field_refs', []) if ref != 'step_evidence']
    if level >= 4 and any(row.get('object_role') not in ('step_reference', 'conclusion_reference')
                          for row in response.get('records', [])):
        response['detail_lookup'] = 'exact_ID;more_bytes'
        response['selection_context'] = {
            'order': '条件→本轮正确前缀（主模型判断）→明确偏好→选填已核且足够的省步技巧→有据步骤/少量新前置→运算成本',
            'guard': '明示等级/去重考查次数/统计范围，不列具体年份；选填核条件。已知简列、卡点补连接；未知≠未学；结论证明按请求',
        }
        for key in ('identity', 'unknown', 'ambiguous', 'scope_notes'):
            if not response.get(key):
                response.pop(key, None)


def page_lines(value):
    if not value:
        return []
    lines = ['', '## 做题短摘要', '',
             '选法顺序：' + ' → '.join(SELECTION_CONTEXT['order']) + '。',
             SELECTION_CONTEXT['policy'], '']
    if not value['candidates']:
        lines += ['尚无经核验的方法绑定；不据关联标签补造解法或已会步骤。', '']
    elif not value['primary_method_id']:
        lines += ['下面保留候选条件，未将首条候选认定为首选主线。', '']
    for candidate in value['candidates']:
        lines += ['### ' + candidate['method_id'], '',
                  '线索：' + '；'.join(candidate['clues']),
                  '第一动作：' + candidate['first_action'], '必要条件：']
        lines += ['- ' + text for text in candidate['necessary_conditions']]
        if candidate['applicability']:
            lines += ['当前绑定范围：' + candidate['applicability']]
        if candidate['direct_conclusion_ids']:
            lines += ['直接结论引用：' + '、'.join(candidate['direct_conclusion_ids'])]
        lines += ['']
    if value['known_operation_evidence']:
        lines += ['步骤证据仅在所列范围有效：']
        lines += ['- ' + '、'.join(row['step_ids']) + '：' + row['state'] + '；' + row['scope']
                  + ('；覆盖：' + row['coverage'] if 'coverage' in row else '')
                  + ('；' + row['evidence_limit'] if row.get('evidence_limit') else '')
                  for row in value['known_operation_evidence']]
    else:
        lines += ['尚无当前有效的步骤级证据；这不表示尚未学过。']
    lines += ['', '下一检查：' + value['next_check'], '']
    return lines
