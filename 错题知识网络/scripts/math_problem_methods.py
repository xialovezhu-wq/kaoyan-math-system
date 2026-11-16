"""Source-backed problem-solving routes, separate from personal learning evidence.

The index builder reads and authenticates this registry. Teaching reads only use
its prepared SQLite projection and exact source stat guards; they never open a
textbook or reclassify a learner's past performance.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import unicodedata


BASE = Path('错题知识网络/个人知识点索引/做题方法')
CATALOG = BASE / 'catalog.json'
BINDINGS = BASE / 'bindings.json'
SOURCE_CACHE = BASE / 'source_cache'
DERIVED_PREFIXES = ('错题知识网络/wiki/maps/',
                    '错题知识网络/wiki/topics/knowledge_clusters/',
                    '错题知识网络/知识树/')
CATALOG_SCHEMA = 'math-problem-methods-v1'
CATALOG_SCHEMA_V2 = 'math-problem-methods-v2'
BINDINGS_SCHEMA = 'math-problem-bindings-v1'
POLICY = 'source_method_is_not_personal_error_or_mastery;match_current_problem_conditions_first'
SELECTION_POLICY = (
    'check_mathematical_applicability;preserve_current_correct_prefix;'
    'respect_explicit_preference;reuse_evidence_backed_familiar_steps;'
    'no_familiarity_ratio_score;no_evidence_does_not_mean_known;'
    'teaching_model_checks_current_attempt_before_choosing')
REFINEMENT_DETAIL_LIMIT = 8
CHOICE_FILL_REVIEW_ROLE = 'verified_choice_fill_technique_conditional_reference'
METHOD_FIELDS = ('method_id', 'name', 'subject', 'triggers', 'first_action',
                 'conditions', 'steps', 'branches', 'pitfalls', 'source_refs')


def is_reviewed_choice_fill(route):
    """Use authored review identity, never a name/prefix or keyword guess."""
    review = route.get('review_metadata', {})
    return (isinstance(review, dict)
            and review.get('role') == CHOICE_FILL_REVIEW_ROLE
            and review.get('review_decision') == 'adopt'
            and bool(set(review.get('question_types', [])) & {'选择题', '填空题'}))


def choice_fill_execution(route):
    """A complete execution atom after the caller's normal source guards.

    Only provenance and duplicate wording are removed. Formula conditions and
    exceptions either remain complete or reference an equal list in this atom.
    The source graph remains available in the guarded projection; its ordered
    actions include prerequisite steps, without repeating IDs and citations.
    """
    if (not is_reviewed_choice_fill(route)
            or route.get('status') == 'stale'
            or route.get('binding_status')
            or not str(route.get('source_status', '')).startswith('verified_')):
        return None
    graph = route.get('step_graph', [])
    actions = ([row['action'] for row in graph]
               if graph and all(isinstance(row.get('action'), str) for row in graph)
               else copy.deepcopy(route.get('steps', [])))
    conditions = route.get('conditions', [])
    declared = set(route.get('conclusion_ids', [])) | set(route.get('direct_conclusion_ids', []))
    present = {row.get('conclusion_id') for row in route.get('direct_conclusions', [])}
    if (not actions or not conditions or not route.get('first_action')
            or not declared <= present):
        return None
    result = {key: copy.deepcopy(route[key]) for key in
              ('method_id', 'name', 'goal', 'first_action', 'conditions',
               'specific_hint', 'applicability', 'branches', 'pitfalls') if route.get(key)}
    result['steps'] = actions
    result['direct_conclusions'] = []
    for source in route.get('direct_conclusions', []):
        conclusion = {key: copy.deepcopy(value) for key, value in source.items()
                      if key not in ('source_refs',)}
        if conclusion.get('conditions') == conditions:
            conclusion.pop('conditions')
            conclusion['conditions_ref'] = 'conditions'
        if conclusion.get('exceptions') == result.get('pitfalls'):
            conclusion.pop('exceptions')
            conclusion['exceptions_ref'] = 'pitfalls'
        result['direct_conclusions'].append(conclusion)
    result['reference_role'] = 'verified_source_candidate_requires_current_condition_check'
    return result


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def alias_key(value):
    name = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value))).casefold()
    return 'MATH-METHOD-ALIAS-' + hashlib.sha256(name.encode()).hexdigest()[:24]


def _text(value, field, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError('problem_method_text_required:' + field)
    return value


def _texts(value, field, empty=True):
    if not isinstance(value, list) or (not empty and not value):
        raise ValueError('problem_method_array_required:' + field)
    for item in value:
        _text(item, field)
    return value


def _ids(value, field):
    _texts(value, field)
    if len(set(value)) != len(value) or any(
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', x) for x in value):
        raise ValueError('problem_method_duplicate_or_invalid_reference:' + field)
    return value


def _dependency_order(nodes, field, label):
    """Validate all references and return dependency-first order without recursion."""
    degree = {}
    following = {key: [] for key in nodes}
    for key, node in nodes.items():
        refs = node.get(field, [])
        degree[key] = len(refs)
        for ref in refs:
            if ref not in nodes:
                raise ValueError('problem_method_unknown_' + label + ':' + ref)
            following[ref].append(key)
    ready = [key for key in nodes if degree[key] == 0]
    order = []
    while ready:
        key = ready.pop()
        order.append(key)
        for child in following[key]:
            degree[child] -= 1
            if not degree[child]:
                ready.append(child)
    if len(order) != len(nodes):
        raise ValueError('problem_method_' + label + '_cycle')
    return order


def _route_refs(route):
    refs = list(route.get('source_refs', []))
    for field in ('step_graph', 'direct_conclusions'):
        for item in route.get(field, []):
            refs.extend(item.get('source_refs', []))
    return refs


def _source_guards(refs):
    return [{'path': path, 'sha256': sha} for path, sha in
            sorted({(ref['path'], ref['sha256']) for ref in refs})]


def formula_reference_candidates(root, identities, *, view='protected', limit=16):
    """Link existing methods to full reviewed formula records without flattening them.

    These are source-reference candidates, not a new assertion that they apply
    to the current problem or that the learner has mastered them.
    """
    if view == 'protected':
        return None
    from math_formula_registry import FormulaRegistry, FormulaError, MANIFEST
    if not (Path(root) / MANIFEST).is_file():
        return None
    try:
        registry = FormulaRegistry(root)
        by_legacy = registry.manifest.get('existing_to_entries', {})
        found = sorted({entry_id for identity in identities for entry_id in by_legacy.get(identity, [])
                        if registry.index.get(entry_id, {}).get('practice_ready')})
        if not found:
            return None
        return {'status': 'reference_candidates', 'ids': found[:limit], 'total_candidates': len(found),
                'has_more': len(found) > limit, 'registry_version': registry.version,
                'registry_source': {'path': MANIFEST, 'sha256': registry.manifest_sha256},
                'content_query': {'domain': 'math_methods', 'ids': found[:limit], 'view': view},
                'local_reader': '错题知识网络/scripts/math_formula_registry.py',
                'content_fields': ['formula_latex', 'conditions', 'derivation', 'exam_links', 'memory', 'local_review'],
                'applicability': 'check_current_question_conditions;legacy_method_match_is_not_an_exam_link',
                'learning_write_count': 0}
    except (OSError, ValueError, FormulaError) as exc:
        return {'status': 'unavailable', 'reason': str(exc), 'ids': [], 'learning_write_count': 0}


def _relative(value):
    _text(value, 'source.path')
    path = Path(value)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('problem_method_source_outside_repository')
    return path


def _snapshot_kind(root, path, ref):
    """Authenticate an immutable copied version, not today's mutable original."""
    role = ref['source_role']
    expected = SOURCE_CACHE / (ref['sha256'] + '.md')
    if path != expected:
        raise ValueError('problem_method_snapshot_content_address_required')
    original = _relative(ref.get('original_path'))
    if ref.get('original_sha256') != ref['sha256']:
        raise ValueError('problem_method_snapshot_original_hash_mismatch')
    if original.suffix != '.md':
        raise ValueError('problem_method_snapshot_original_kind_invalid')
    if role == 'formal_card_snapshot':
        if not str(original).startswith('错题知识网络/错题卡/'):
            raise ValueError('problem_method_snapshot_original_kind_invalid')
        kind = 'formal_card'
    else:
        if not str(original).startswith(DERIVED_PREFIXES):
            raise ValueError('problem_method_snapshot_original_kind_invalid')
        kind = 'derived_reference'
    if ref.get('pdf_pages') not in (None, []):
        raise ValueError('problem_method_snapshot_must_not_claim_pdf_pages')
    target = Path(root) / path
    cache = Path(root) / SOURCE_CACHE
    if target.is_symlink() or cache.is_symlink() or not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('problem_method_snapshot_symlink_or_escape')
    return kind


def load_registry(root, read_source, concept_keys, formal_ids):
    """Cold-build validation; no writes and no learning-event identities."""
    root = Path(root)
    present = [(root / path).is_file() for path in (CATALOG, BINDINGS)]
    if not any(present):
        return None
    if not all(present):
        raise ValueError('problem_method_registry_incomplete')
    source_paths = set()

    def read(path):
        source = read_source(root / path, 'external')
        source_paths.add(str(path))
        return source

    for path in (CATALOG, BINDINGS):
        read(path)
    catalog = json.loads((root / CATALOG).read_text())
    bindings = json.loads((root / BINDINGS).read_text())
    schema = catalog.get('schema')
    if schema not in (CATALOG_SCHEMA, CATALOG_SCHEMA_V2) or not isinstance(catalog.get('methods'), list):
        raise ValueError('problem_method_catalog_schema_required')
    if bindings.get('schema') != BINDINGS_SCHEMA:
        raise ValueError('problem_method_bindings_schema_required')
    is_v2 = schema == CATALOG_SCHEMA_V2
    methods = {}
    aliases = {}
    verified_sources = {}
    source_statuses = {
        frozenset({'textbook'}): 'verified_textbook',
        frozenset({'formal_card'}): 'verified_formal_card_method',
        frozenset({'derived_reference'}): 'verified_derived_reference',
        frozenset({'textbook', 'formal_card'}): 'verified_textbook_and_formal_card',
        frozenset({'textbook', 'derived_reference'}): 'verified_textbook_with_derived_reference',
        frozenset({'formal_card', 'derived_reference'}): 'verified_formal_card_with_derived_reference',
        frozenset({'textbook', 'formal_card', 'derived_reference'}): 'verified_textbook_formal_card_and_derived_reference',
    }

    def verify_refs(refs):
        if not isinstance(refs, list) or not refs:
            raise ValueError('problem_method_source_refs_required')
        source_kinds = set()
        sources_match = True
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValueError('problem_method_source_reference_required')
            path = _relative(ref.get('path'))
            if not re.fullmatch(r'[0-9a-f]{64}', str(ref.get('sha256', ''))):
                raise ValueError('problem_method_source_hash_required')
            if ref.get('source_role') in ('formal_card_snapshot', 'derived_reference_snapshot'):
                source_kinds.add(_snapshot_kind(root, path, ref))
            elif path.suffix.lower() == '.pdf':
                pages = ref.get('pdf_pages')
                if not isinstance(pages, list) or not pages or any(type(p) is not int or p < 1 for p in pages):
                    raise ValueError('problem_method_pdf_pages_required')
                source_kinds.add('textbook')
            elif (path.suffix == '.md' and ref.get('source_role') == 'derived_reference'
                  and str(path).startswith(DERIVED_PREFIXES)):
                if ref.get('pdf_pages') not in (None, []):
                    raise ValueError('problem_method_derived_reference_must_not_claim_pdf_pages')
                source_kinds.add('derived_reference')
            elif path.suffix == '.md' and str(path).startswith('错题知识网络/错题卡/'):
                if ref.get('pdf_pages') not in (None, []):
                    raise ValueError('problem_method_card_must_not_claim_pdf_pages')
                source_kinds.add('formal_card')
            else:
                raise ValueError('problem_method_source_kind_unsupported:' + str(path))
            _text(ref.get('section'), 'source.section')
            # Missing references must also be retained in freshness provenance.
            source_paths.add(str(path))
            if str(path) not in verified_sources:
                verified_sources[str(path)] = read(path)['sha256'] if (root / path).is_file() else None
            if verified_sources[str(path)] != ref['sha256']:
                sources_match = False
        return source_kinds, sources_match

    all_ids = set()

    def claim_id(value, label):
        _text(value, label)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', value) or value in all_ids:
            raise ValueError('problem_method_duplicate_or_invalid_id:' + value)
        all_ids.add(value)

    steps = {}
    conclusions = {}
    node_auth = {}
    if is_v2:
        for field, id_field, output in (('steps', 'step_id', steps),
                                        ('conclusions', 'conclusion_id', conclusions)):
            values = catalog.get(field)
            if not isinstance(values, list):
                raise ValueError('problem_method_v2_array_required:' + field)
            for item in values:
                if not isinstance(item, dict):
                    raise ValueError('problem_method_object_required')
                key = item.get(id_field)
                claim_id(key, id_field)
                if field == 'steps':
                    _text(item.get('title'), 'step.title')
                    _text(item.get('action'), 'step.action')
                    _ids(item.get('prerequisite_step_ids'), 'step.prerequisite_step_ids')
                    fields = ('step_id', 'title', 'action', 'prerequisite_step_ids', 'source_refs')
                else:
                    _text(item.get('statement_latex'), 'conclusion.statement_latex')
                    _texts(item.get('conditions'), 'conclusion.conditions', empty=False)
                    _texts(item.get('exceptions'), 'conclusion.exceptions')
                    if type(item.get('direct_use')) is not bool:
                        raise ValueError('problem_method_conclusion_direct_use_boolean_required')
                    fields = ('conclusion_id', 'statement_latex', 'conditions',
                              'direct_use', 'exceptions', 'source_refs')
                node_auth[key] = verify_refs(item.get('source_refs'))
                output[key] = {name: copy.deepcopy(item[name]) for name in fields}
        order = _dependency_order(steps, 'prerequisite_step_ids', 'step_dependency')
    else:
        order = []

    for item in catalog['methods']:
        if not isinstance(item, dict):
            raise ValueError('problem_method_object_required')
        for field in ('method_id', 'name', 'subject', 'first_action'):
            _text(item.get(field), field)
        mid = item['method_id']
        claim_id(mid, 'method_id')
        for field in ('triggers', 'conditions', 'steps'):
            _texts(item.get(field), field, empty=False)
        for field in ('aliases', 'pitfalls'):
            _texts(item.get(field, []), field)
        branches = item.get('branches', [])
        if not isinstance(branches, list) or any(not isinstance(x, (str, dict)) or not x for x in branches):
            raise ValueError('problem_method_branches_required')
        kinds, sources_match = verify_refs(item.get('source_refs'))
        method = {field: copy.deepcopy(item.get(field, [])) for field in METHOD_FIELDS}
        if is_v2:
            for field in ('step_ids', 'conclusion_ids', 'refinement_ids'):
                method[field] = copy.deepcopy(_ids(item.get(field, []), field))
            if 'goal' in item:
                method['goal'] = _text(item['goal'], 'goal')
            if 'review_metadata' in item:
                if not isinstance(item['review_metadata'], dict):
                    raise ValueError('problem_method_review_metadata_object_required')
                method['review_metadata'] = copy.deepcopy(item['review_metadata'])
            required = set()
            pending = list(method['step_ids'])
            while pending:
                sid = pending.pop()
                if sid not in steps:
                    raise ValueError('problem_method_unknown_step:' + sid)
                if sid not in required:
                    required.add(sid)
                    pending.extend(steps[sid]['prerequisite_step_ids'])
            for cid in method['conclusion_ids']:
                if cid not in conclusions:
                    raise ValueError('problem_method_unknown_conclusion:' + cid)
            graph_order = []
            visited = set()
            pending = [(sid, False) for sid in reversed(method['step_ids'])]
            while pending:
                sid, expanded = pending.pop()
                if sid in visited:
                    continue
                if expanded:
                    visited.add(sid)
                    graph_order.append(sid)
                else:
                    pending.append((sid, True))
                    pending.extend((dep, False) for dep in reversed(steps[sid]['prerequisite_step_ids']))
            method['step_graph'] = [copy.deepcopy(steps[sid]) for sid in graph_order]
            method['step_graph_ids'] = graph_order
            method['direct_conclusions'] = [copy.deepcopy(conclusions[cid]) for cid in method['conclusion_ids']]
            method['direct_conclusion_ids'] = [c['conclusion_id'] for c in method['direct_conclusions'] if c['direct_use']]
            for key in required | set(method['conclusion_ids']):
                dep_kinds, dep_match = node_auth[key]
                kinds.update(dep_kinds)
                sources_match = sources_match and dep_match
        method['source_status'] = source_statuses[frozenset(kinds)] if sources_match else 'stale_source'
        methods[mid] = method
        # Exact aliases only. Shared words/trigger sentences keep all candidates;
        # neither token overlap nor a first row becomes a personal method choice.
        names = [item['name']] + item.get('aliases', [])
        if is_v2:
            names += [mid] + item['triggers']
        for alias in names:
            row = aliases.setdefault(alias_key(alias), {'names': [], 'bindings': []})
            if alias not in row['names']:
                row['names'].append(alias)
            if not any(x['method_id'] == mid for x in row['bindings']):
                row['bindings'].append({'method_id': mid, 'applicability': '按当前题面核对教材适用条件。',
                                        'specific_hint': '', 'role': 'candidate'})
    if is_v2:
        _dependency_order(methods, 'refinement_ids', 'refinement')
        for method in methods.values():
            candidates = []
            guards = {}
            for mid in method['refinement_ids']:
                refined = methods[mid]
                guards[mid] = _source_guards(_route_refs(refined))
                row = {field: copy.deepcopy(refined[field]) for field in
                       ('method_id', 'name', 'goal', 'conditions', 'first_action', 'refinement_ids') if field in refined}
                row['role'] = 'candidate'
                row['source_status'] = refined['source_status']
                if refined['source_status'] == 'stale_source':
                    row = {'method_id': mid, 'name': refined['name'], 'status': 'stale',
                           'role': 'candidate', 'reason': 'refinement_source_hash_mismatch_or_missing'}
                candidates.append(row)
            method['refinement_candidates'] = candidates[:REFINEMENT_DETAIL_LIMIT]
            method['refinement_candidates_omitted_ids'] = method['refinement_ids'][REFINEMENT_DETAIL_LIMIT:]
            method['refinement_detail_status'] = ('complete' if len(candidates) <= REFINEMENT_DETAIL_LIMIT else
                'additional_ids_queryable_by_exact_method_id;no_candidate_auto_selected')
            method['_refinement_source_guards'] = guards
            method['_refinement_stale_ids'] = [row['method_id'] for row in candidates if row.get('status') == 'stale']

    normalized = {}
    for field, known in (('concept_bindings', set(concept_keys)), ('formal_bindings', set(formal_ids))):
        values = bindings.get(field)
        if not isinstance(values, dict):
            raise ValueError('problem_method_binding_map_required:' + field)
        normalized[field] = {}
        for key, rows in values.items():
            if key not in known:
                raise ValueError('problem_method_binding_unknown_identity:' + key)
            if not isinstance(rows, list) or not rows:
                raise ValueError('problem_method_binding_array_required:' + key)
            seen = set()
            normalized[field][key] = []
            for row in rows:
                if not isinstance(row, dict) or row.get('method_id') not in methods:
                    raise ValueError('problem_method_binding_unknown_route:' + key)
                if row['method_id'] in seen:
                    raise ValueError('problem_method_binding_duplicate_route:' + key)
                seen.add(row['method_id'])
                _text(row.get('applicability'), 'binding.applicability')
                _text(row.get('specific_hint', ''), 'binding.specific_hint', empty=True)
                role = row.get('role', 'candidate')
                if role not in ('primary', 'alternative', 'candidate'):
                    raise ValueError('problem_method_binding_role_invalid')
                if row.get('card_sha256') and not re.fullmatch(r'[0-9a-f]{64}', str(row['card_sha256'])):
                    raise ValueError('problem_method_binding_card_hash_invalid')
                normalized[field][key].append({**row, 'role': role})
            if sum(row['role'] == 'primary' for row in normalized[field][key]) > 1:
                raise ValueError('problem_method_multiple_primary_routes:' + key)
    exclusions = bindings.get('formal_exclusions', {})
    if not isinstance(exclusions, dict):
        raise ValueError('problem_method_formal_exclusions_map_required')
    for formal_id, row in exclusions.items():
        if formal_id not in formal_ids or not isinstance(row, dict):
            raise ValueError('problem_method_exclusion_unknown_identity:' + formal_id)
        if formal_id in normalized['formal_bindings']:
            raise ValueError('problem_method_exclusion_conflicts_with_binding:' + formal_id)
        if row.get('status') not in ('source_hold', 'identity_alias'):
            raise ValueError('problem_method_exclusion_status_required')
        _text(row.get('reason'), 'exclusion.reason')
        if row.get('canonical_id') and row['canonical_id'] not in formal_ids:
            raise ValueError('problem_method_exclusion_canonical_identity_unknown')
    concept_exclusions = bindings.get('concept_exclusions', {})
    if not isinstance(concept_exclusions, dict):
        raise ValueError('problem_method_concept_exclusions_map_required')
    for key, row in concept_exclusions.items():
        if key not in concept_keys or not isinstance(row, dict):
            raise ValueError('problem_method_concept_exclusion_unknown_identity:' + key)
        if key in normalized['concept_bindings']:
            raise ValueError('problem_method_concept_exclusion_conflicts_with_binding:' + key)
        if row.get('status') not in ('non_problem_concept', 'source_hold'):
            raise ValueError('problem_method_concept_exclusion_status_required')
        _text(row.get('reason'), 'concept_exclusion.reason')
    return {'schema': schema, 'methods': methods, 'steps': steps, 'conclusions': conclusions,
            'aliases': aliases, **normalized,
            'formal_exclusions': copy.deepcopy(exclusions),
            'concept_exclusions': copy.deepcopy(concept_exclusions),
            'source_paths': sorted(source_paths),
            'version': hashlib.sha256(canonical([catalog, bindings]).encode()).hexdigest()}


def exclusion_projection(registry, exclusion, binding_scope):
    """Only explicitly authored exclusions count; unmatched points stay gaps."""
    return {**copy.deepcopy(exclusion),
            'source': 'concept_exclusion' if binding_scope == 'concept_exclusion' else 'formal_source_exclusion',
            'binding_scope': binding_scope, 'version': registry['version'],
            'evidence_policy': POLICY, 'routes': [],
            '_source_paths': [str(CATALOG), str(BINDINGS)]}


def project(registry, bindings, binding_scope, *, view=None):
    if view == 'protected' or not registry or not bindings:
        return None
    routes = []
    paths = {str(CATALOG), str(BINDINGS)}
    for binding in bindings:
        route = copy.deepcopy(registry['methods'][binding['method_id']])
        paths.update(ref['path'] for ref in _route_refs(route))
        for guards in route.get('_refinement_source_guards', {}).values():
            paths.update(ref['path'] for ref in guards)
        route.update({key: binding.get(key, '') for key in ('applicability', 'specific_hint', 'role')})
        if binding.get('card_sha256'):
            route['_binding_card_sha256'] = binding['card_sha256']
        if route['source_status'] == 'stale_source':
            route = {'method_id': route['method_id'], 'name': route['name'], 'status': 'stale',
                     'source_status': 'stale_source', 'role': 'candidate',
                     'reason': 'method_source_hash_mismatch_or_missing;maintenance_review_required'}
        elif route.get('_refinement_stale_ids'):
            route['status'] = 'partial'
            route['refinement_status'] = 'partial'
            route['refinement_stale_ids'] = route['_refinement_stale_ids']
        routes.append(route)
    explicit = next((r['method_id'] for r in routes if r['role'] == 'primary'), None)
    # Refinements are candidates, never a silent replacement for the existing
    # route or proof that this learner knows any of its individual steps.
    source_statuses = {route['source_status'] for route in routes}
    source = ('verified_textbooks' if source_statuses == {'verified_textbook'} else
              'verified_formal_card_methods' if source_statuses == {'verified_formal_card_method'} else
              'verified_derived_references' if source_statuses == {'verified_derived_reference'} else
              'verified_mixed_method_sources')
    available = sum(route.get('status') != 'stale' for route in routes)
    result = {'status': 'available' if available == len(routes) and not any(
                    r.get('status') == 'partial' for r in routes) else 'partial' if available else 'stale',
              'source': source, 'evidence_policy': POLICY,
              'binding_scope': binding_scope, 'version': registry['version'],
              'selection_status': 'primary_route_requires_condition_check' if explicit else
                  'single_candidate_requires_condition_check' if len(routes) == 1 else 'needs_discrimination',
              'primary_method_id': explicit, 'routes': routes,
              '_source_paths': sorted(paths),
              '_registry_source_paths': [str(CATALOG), str(BINDINGS)]}
    if registry.get('schema') == CATALOG_SCHEMA_V2:
        result['selection_policy'] = SELECTION_POLICY
    return result


def candidate(route):
    """Keep complete conditions and IDs; omit only entire execution objects."""
    fields = ('method_id', 'name', 'goal', 'triggers', 'first_action', 'conditions',
              'applicability', 'specific_hint', 'status', 'source_status', 'source_refs',
              'step_ids', 'step_graph_ids', 'conclusion_ids', 'direct_conclusion_ids',
              'refinement_ids', 'refinement_candidates', 'refinement_candidates_omitted_ids',
              'refinement_detail_status', 'refinement_status', 'refinement_stale_ids',
              'review_metadata')
    result = {key: copy.deepcopy(route[key]) for key in fields if key in route}
    # An alternative remains a candidate; that does not make its executable
    # steps or conditional conclusion disposable. The small response compiler
    # needs these objects before it can select complete, bounded guidance atoms.
    if is_reviewed_choice_fill(route):
        for key in ('steps', 'step_graph', 'direct_conclusions', 'branches', 'pitfalls'):
            if key in route:
                result[key] = copy.deepcopy(route[key])
        result.update(detail_status='reviewed_choice_fill_execution_preserved',
                      omitted_fields=[key for key in route.get('omitted_fields', [])
                                      if key not in result])
        return result
    omitted = list(dict.fromkeys(route.get('omitted_fields', []) + [
        key for key in ('steps', 'step_graph', 'direct_conclusions', 'branches', 'pitfalls') if key in route]))
    result.update(detail_status='candidate_only;execution_details_omitted_as_whole_objects',
                  omitted_fields=omitted)
    return result


def _public(value):
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items() if not key.startswith('_')}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return copy.deepcopy(value)


def compact(value, candidates_only=False, compact_alternatives=True, *, view=None,
            omit_conclusions=False, refinement_ids_only=False):
    if view == 'protected' or value.get('view') == 'protected':
        return {'status': 'protected', 'routes': [], 'detail_status': 'answer_protection'}
    result = _public(value)
    primary = result.get('primary_method_id')
    if candidates_only:
        result['routes'] = [route if route.get('status') == 'stale' else candidate(route) for route in result['routes']]
        result['detail_status'] = 'conditions_preserved;execution_steps_and_conclusions_omitted_for_budget'
    elif primary and compact_alternatives:
        result['routes'] = [route if route['method_id'] == primary or route.get('status') == 'stale' else candidate(route)
                            for route in result['routes']]
    for route in result['routes']:
        if omit_conclusions and 'direct_conclusions' in route:
            route.pop('direct_conclusions')
            route.setdefault('omitted_fields', []).append('direct_conclusions')
            route['conclusion_detail_status'] = 'whole_list_omitted_for_budget;query_exact_method_id_for_conditions_and_formulas'
        if refinement_ids_only and route.get('refinement_candidates'):
            route['refinement_candidates'] = []
            route['refinement_candidates_omitted_ids'] = list(route.get('refinement_ids', []))
            route['refinement_detail_status'] = 'all_ids_queryable_by_exact_method_id;details_omitted_for_budget'
    return result


def checked_projection(root, conn, projected, formal_source=None, preserve_routes=False, *, view=None,
                       source_lookup=None):
    """Invalidate affected routes/children using source stats, never source bytes."""
    import math_concept_index as native
    if view == 'protected' or projected.get('view') == 'protected':
        return {'status': 'protected', 'routes': [], 'detail_status': 'answer_protection'}
    current_cache = {}

    def current(path, expected_hash=None):
        key = (path, expected_hash)
        if key not in current_cache:
            row = source_lookup(path) if source_lookup else None
            if source_lookup is None:
                raw = conn.execute('SELECT stamp,sha256 FROM sources WHERE path=?', (path,)).fetchone()
                row = (json.loads(raw[0]), raw[1]) if raw is not None else None
            current_cache[key] = (row is not None and native._stamp(Path(root) / path) == row[0]
                                 and (expected_hash is None or row[1] == expected_hash))
        return current_cache[key]

    result = copy.deepcopy(projected)
    registry_paths = projected.get('_registry_source_paths', projected.get('_source_paths', []))
    registry_current = all(current(path) for path in registry_paths)
    if projected.get('status') in ('source_hold', 'identity_alias', 'non_problem_concept'):
        if not registry_current:
            return {'status': 'stale', 'source': projected.get('source', 'explicit_method_exclusion'),
                    'reason': 'method_registry_changed;maintenance_refresh_required', 'routes': []}
        return compact(result)
    checked = []
    for route in result['routes']:
        if route.get('status') == 'stale':
            checked.append(route)
            continue
        if not registry_current or not all(current(ref['path'], ref['sha256']) for ref in _route_refs(route)):
            checked.append({'method_id': route['method_id'], 'name': route['name'], 'status': 'stale',
                            'reason': 'method_sources_changed;maintenance_refresh_required'})
            continue
        guards = route.get('_refinement_source_guards', {})
        stale_refinements = set(route.get('_refinement_stale_ids', []))
        stale_refinements.update(mid for mid, refs in guards.items()
                                 if not all(current(ref['path'], ref['sha256']) for ref in refs))
        if stale_refinements:
            route['status'] = 'partial'
            route['refinement_status'] = 'partial'
            route['refinement_stale_ids'] = sorted(stale_refinements)
            route['refinement_candidates'] = [
                {'method_id': row['method_id'], 'name': row['name'], 'role': 'candidate', 'status': 'stale',
                 'reason': 'refinement_sources_changed;maintenance_refresh_required'}
                if row['method_id'] in stale_refinements else row for row in route.get('refinement_candidates', [])]
        if formal_source and route.get('_binding_card_sha256') and (
                route['_binding_card_sha256'] != formal_source.get('sha256') or not current(formal_source['path'])):
            route['role'] = 'candidate'
            route['specific_hint'] = ''
            route['applicability'] = '原逐卡绑定版本已变化；重新核对当前题与该教材路线的条件。'
            route['binding_status'] = 'card_changed_candidate_only'
            if result.get('primary_method_id') == route['method_id']:
                result['primary_method_id'] = None
            result['selection_status'] = 'card_changed_requires_discrimination'
        checked.append(route)
    result['routes'] = checked
    available = sum(route.get('status') != 'stale' for route in checked)
    result['status'] = ('available' if available == len(checked) and not any(
        route.get('status') == 'partial' for route in checked) else 'partial' if available else 'stale')
    if result.get('primary_method_id') and any(r['method_id'] == result['primary_method_id'] and r.get('status') == 'stale' for r in checked):
        result['primary_method_id'] = None
        result['selection_status'] = 'primary_route_stale;recheck_remaining_candidates'
    result = compact(result, compact_alternatives=not preserve_routes)
    identities = []
    for route in result.get('routes', []):
        if route.get('status') != 'stale':
            identities.append(route.get('method_id'))
            identities.extend(row.get('conclusion_id') for row in route.get('direct_conclusions', []))
    formula_refs = formula_reference_candidates(root, [x for x in identities if x], view=view or 'after_attempt')
    if formula_refs is not None:
        result['formula_references'] = formula_refs
    return result


def align_formal_to_current_concept(formal, rows, first_query_keys, explicit_concepts):
    """Use the current point to select within a multi-part card, never vice versa.

    Return the top-level formal projection and the exact rows whose duplicate
    methods may be removed. Other points retain their own candidate methods.
    """
    if formal is None:
        return None, set()
    if formal.get('status') in ('source_hold', 'identity_alias'):
        return compact(formal), {row['concept_key'] for row in rows}
    if not explicit_concepts:
        return compact(formal), {row['concept_key'] for row in rows}
    result = copy.deepcopy(formal)
    active = {route['method_id']: route for route in result.get('routes', [])
              if route.get('status') != 'stale' and not route.get('binding_status')}
    current = next((row for row in rows if len(first_query_keys) == 1 and
                    row['concept_key'] == first_query_keys[0]), None)
    point = current.get('problem_solving') if current else None
    point_routes = {route['method_id']: route for route in (point or {}).get('routes', [])
                    if route.get('status') != 'stale'}
    common = set(active).intersection(point_routes)
    # A shared main route does not mean the whole concept projection is a
    # duplicate. New concept alternatives (including reviewed choice/fill
    # techniques) must remain visible until an exact-card binding covers them.
    covered_point = set(point_routes) <= set(active)
    point_primary = (point or {}).get('primary_method_id')
    chosen = None
    if point_primary:
        chosen = point_primary if point_primary in common else None
    elif len(common) == 1:
        chosen = next(iter(common))
    elif len(point_routes) > 1 and set(active) <= set(point_routes):
        # A structurally broad entry offers every formal candidate and has no
        # more specific choice; the existing whole-card primary is still useful.
        if result.get('primary_method_id') in common:
            result['selection_basis'] = 'broad_concept_keeps_formal_context'
            return compact(result), {current['concept_key']} if covered_point else set()
    if chosen:
        result['primary_method_id'] = chosen
        result['selection_status'] = 'current_concept_route_requires_condition_check'
        result['selection_basis'] = 'first_explicit_concept_then_matching_formal_binding'
        result['current_concept_key'] = current['concept_key']
        for route in result['routes']:
            route['role'] = 'primary' if route['method_id'] == chosen else 'alternative'
            if route['method_id'] == chosen:
                route['current_concept_applicability'] = point_routes[chosen].get('applicability', '')
                route['current_concept_hint'] = point_routes[chosen].get('specific_hint', '')
        # Place the selected full route first; no conditions or steps are cut.
        result['routes'].sort(key=lambda route: route['method_id'] != chosen)
        return compact(result), {current['concept_key']} if covered_point else set()
    result['primary_method_id'] = None
    for route in result.get('routes', []):
        route['role'] = 'candidate'
    if result.get('selection_status') != 'card_changed_requires_discrimination':
        result['selection_status'] = 'needs_discrimination'
    result['selection_basis'] = 'current_concept_not_uniquely_matched;concept_candidates_retained'
    return compact(result, candidates_only=len(result.get('routes', [])) > 1), set()


def page_lines(projected, *, view=None):
    if not projected or view == 'protected' or projected.get('view') == 'protected' or projected.get('status') == 'protected':
        return []
    if projected.get('status') in ('non_problem_concept', 'source_hold', 'identity_alias'):
        return ['', '## 做题路线适用性', '', '状态：`' + projected['status'] + '`。', '',
                projected['reason'], '', '保留该节点及原有个人证据；本项不生成教材方法，也不代表本人掌握或错误。', '']
    lines = ['', '## 做题路线与来源', '', '先按题设线索、条件和目标匹配路线；各路线区分教材、原卡与派生参考来源，不证明本人发生过相应错误或已经掌握。派生参考的哈希核验只证明该参考原文，不表示已经核读它引用的原书。', '']
    for route in projected['routes']:
        if route.get('status') == 'stale':
            lines += ['### ' + route['name'], '', '方法来源已变化或暂不可用；需重新核对，暂不展示旧操作步骤。', '']
            continue
        lines += ['### ' + route['name'], '', '方法 ID：`' + route['method_id'] + '`',
                  '适用范围：' + route.get('applicability', '按当前题目核对。')]
        if route.get('goal'):
            lines += ['目标：' + route['goal']]
        if route.get('specific_hint'):
            lines += ['本知识点切入：' + route['specific_hint']]
        lines += ['识别线索：' + '；'.join(route['triggers']),
                  '第一动作：' + route['first_action'], '', '必要条件：']
        lines += ['- ' + value for value in route['conditions']]
        if 'steps' in route:
            lines += ['', '操作流程：'] + [str(i) + '. ' + value for i, value in enumerate(route['steps'], 1)]
        if route.get('step_ids'):
            lines += ['', '本方法步骤入口：' + '、'.join(route['step_ids'])]
        if route.get('step_graph'):
            lines += ['', '可复用步骤与完整前置：']
            for step in route['step_graph']:
                lines += ['- `' + step['step_id'] + '` ' + step['title'] + '：' + step['action'],
                          '  - 前置：' + ('、'.join(step['prerequisite_step_ids']) or '无额外步骤前置。')]
        if route.get('direct_conclusions'):
            lines += ['', '结论与调用条件：']
            for conclusion in route['direct_conclusions']:
                lines += ['', '`' + conclusion['conclusion_id'] + '`（' + (
                    '条件满足时可直接用' if conclusion['direct_use'] else '暂不作为直接结论调用') + '）',
                          '', '$$', conclusion['statement_latex'], '$$', '', '使用条件：']
                lines += ['- ' + condition for condition in conclusion['conditions']]
                if conclusion['exceptions']:
                    lines += ['边界与例外：'] + ['- ' + exception for exception in conclusion['exceptions']]
        if route.get('conclusion_ids'):
            lines += ['', '完整结论引用：' + '、'.join(route['conclusion_ids'])]
        if route.get('refinement_ids'):
            lines += ['', '细分路线候选（须按当前题目选择，不自动替代本方法）：',
                      '全部 ID：' + '、'.join(route['refinement_ids'])]
            for child in route.get('refinement_candidates', []):
                if child.get('status') == 'stale':
                    lines += ['- `' + child['method_id'] + '` ' + child['name'] + '：来源待重新核验。']
                    continue
                lines += ['- `' + child['method_id'] + '` ' + child['name'],
                          '  - 目标：' + child.get('goal', '按方法名称和当前所求核对。'),
                          '  - 条件：' + '；'.join(child['conditions']),
                          '  - 第一动作：' + child['first_action']]
            if route.get('refinement_candidates_omitted_ids'):
                lines += ['其余候选详情可按精确方法 ID 查询：' + '、'.join(route['refinement_candidates_omitted_ids'])]
        if route.get('omitted_fields'):
            lines += ['', '此投影整体省略以下详情；未截断保留的公式或条件：' + '、'.join(route['omitted_fields'])]
        if route.get('review_metadata'):
            lines += ['', '来源审核元数据（不代表个人掌握）：' + canonical(route['review_metadata'])]
        if route.get('branches'):
            lines += ['', '分支：'] + ['- ' + (x if isinstance(x, str) else canonical(x)) for x in route['branches']]
        if route.get('pitfalls'):
            lines += ['', '边界与易错：'] + ['- ' + x for x in route['pitfalls']]
        lines += ['', '方法来源（' + route['source_status'] + '）：']
        seen_refs = set()
        for ref in _route_refs(route):
            if canonical(ref) in seen_refs:
                continue
            seen_refs.add(canonical(ref))
            lines += ['- `' + ref['path'] + '`' + ('，PDF页 ' + ', '.join(map(str, ref['pdf_pages'])) if ref.get('pdf_pages') else '') + '；' + ref['section']
                      + '；SHA-256 `' + ref['sha256'] + '`。']
            if ref.get('source_role') in ('formal_card_snapshot', 'derived_reference_snapshot'):
                lines += ['  - 不可变来源快照；原路径 `' + ref['original_path'] + '`；原版本 SHA-256 `'
                          + ref['original_sha256'] + '`。']
        lines += ['']
    return lines
