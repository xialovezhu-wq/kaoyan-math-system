"""One bounded read contract for math teaching and source-backed memory.

The native reader owns identity and answer protection. Optional search locates
candidate keys only; lifecycle and pending evidence keep their distinct roles.
This module never builds, refreshes, accepts, publishes, or scores anything.
"""
from __future__ import annotations

import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

SCHEMA = 'math-memory-context-v1'
CONTEXT_REVISION = '2026-11-16.evidence-bound-delivery'
KEY = re.compile(r'MATH-CONCEPT-[0-9a-f]{24}')
PERSONAL = ('short_summary', 'overview', 'progress', 'next_check',
            'exam_brief', 'latest_date', 'first_date', 'timeline_count', 'explicit_observation_count')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _index_version(root):
    import math_concept_index as native
    from math_learning_profiles import _read_only_uri
    path = root / native.INDEX
    if not path.is_file():
        return None
    with closing(sqlite3.connect(_read_only_uri(path), uri=True)) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        return json.loads(row[0]) if row else None


def _candidate_keys(result, native_version):
    if native_version is None or result.get('source_version') not in (None, native_version):
        return [], 'candidate_projection_stale'
    keys = []
    for row in result.get('candidates', []):
        if row.get('source_version', result.get('source_version')) != native_version:
            continue
        key = row.get('concept_key')
        if isinstance(key, str) and KEY.fullmatch(key) and key not in keys:
            keys.append(key)
    return keys[:1], None


def _eligible_point(title, *, allow_unclassified=False):
    import math_memory_catalog
    value = math_memory_catalog.classify_title(title or '')
    return value.get('kind') != 'artifact' and (allow_unclassified or value.get('kind') != 'unclassified')


def _eligible_rows(value, allow_unclassified_keys=()):
    rejected = []
    kept = []
    for row in value.get('records', []):
        key = str(row.get('concept_key', ''))
        if KEY.fullmatch(key) and not _eligible_point(row.get('concept_name'), allow_unclassified=key in allow_unclassified_keys):
            rejected.append(row.get('concept_key'))
        else:
            if KEY.fullmatch(key) and not _eligible_point(row.get('concept_name')):
                row['classification_status'] = 'unclassified'
                row['not_a_qualified_knowledge_point'] = True
            kept.append(row)
    value['records'] = kept
    return rejected


def _eligible_selected_keys(root, keys):
    """A backend selection cannot bypass the native catalog's type gate."""
    import math_concept_index as index
    from math_learning_profiles import _read_only_uri
    with closing(sqlite3.connect(_read_only_uri(root/index.INDEX),uri=True)) as conn:
        return [key for key in keys if (row:=conn.execute('SELECT label FROM concepts WHERE key=?',(key,)).fetchone())
                and _eligible_point(row[0])]


def _catalog_kinds(root,keys):
    import math_concept_index as index
    import math_memory_catalog as catalog
    from math_learning_profiles import _read_only_uri
    result={}
    try:
        with closing(sqlite3.connect(_read_only_uri(root/index.INDEX),uri=True)) as conn:
            for key in keys:
                row=conn.execute('SELECT label FROM concepts WHERE key=?',(key,)).fetchone()
                if row:result[key]=catalog.classify_title(row[0])['kind']
    except (OSError,sqlite3.Error):
        pass
    return result


def _as_parent_reference(value,view):
    """Topic navigation is not a fine-point personal profile."""
    result={k:value[k] for k in ('version','source_version','identity') if k in value}
    result.update(status='source_based',view=view,
        records=[{'concept_key':r['concept_key'],'concept_name':r.get('concept_name'),
                  'object_role':'topic_reference','reference_only':True,'fine_point':False,
                  'personal_evidence_eligible':False,'personal_history_status':'not_applicable_to_parent_reference'}
                 for r in value.get('records',[])],
        resolution={'status':'reference_only','fine_point':False,'current_point_confirmed':False},
        returned=len(value.get('records',[])),total=len(value.get('records',[])),truncated=False)
    return result


def _neutral_protected(value):
    if value.get('view') != 'protected':
        return
    for row in value.get('records', []):
        for field in ('timeline_count', 'explicit_observation_count', 'first_date', 'latest_date',
                      'personal_count', 'questions', 'source_refs', 'short_summary', 'overview',
                      'progress', 'next_check', 'step_evidence', 'teaching_preferences'):
            row.pop(field, None)


def _registered_method_names(root, requested, view):
    """An explicit reference ID/name may lack a protected teaching row."""
    if view == 'protected':
        return []
    import math_concept_index as index
    import math_problem_methods as methods
    from math_learning_profiles import _read_only_uri
    result = []
    try:
        with closing(sqlite3.connect(_read_only_uri(root/index.INDEX), uri=True)) as conn:
            for term in requested:
                if isinstance(term, str) and conn.execute(
                    'SELECT 1 FROM teaching_profiles WHERE key=? AND view=?',
                    (methods.alias_key(term), view)).fetchone():
                    result.append(term)
    except (OSError, sqlite3.Error):
        return []
    return result


def _all_exact_eligible_names(root, requested):
    """A neutral SQL preflight lets ordinary exact calls keep one reader call."""
    if not requested:
        return False
    import math_concept_index as index
    import math_memory_catalog as catalog
    from math_learning_profiles import _read_only_uri
    try:
        with closing(sqlite3.connect(_read_only_uri(root/index.INDEX),uri=True)) as conn:
            row=conn.execute("SELECT value FROM meta WHERE key='alias_problems'").fetchone()
            bad={index.normalize(item.get('alias','')) for item in json.loads(row[0])} if row else set()
            for term in requested:
                name=index.normalize(term)
                found=list(conn.execute('SELECT c.key,c.label FROM lookup l JOIN concepts c ON c.key=l.key WHERE l.name=?',(name,)))
                if name in bad or len({key for key,label in found})!=1 or not all(_eligible_point(label) and catalog.classify_title(label)['kind']=='concept' for key,label in found):
                    return False
        return True
    except (OSError,sqlite3.Error,ValueError,TypeError):
        return False


def _clear_unqualified(value, status, *, disambiguation=(), reason=None):
    """No old fuzzy row or its method summary may bypass a precision refusal."""
    identity = value.get('identity')
    result = {key: value[key] for key in ('version', 'source_version', 'view') if key in value}
    result.update(status='ambiguous_concept' if status == 'ambiguous' else 'unknown_concept',
                  records=[], returned=0, total=0, truncated=False, identity=identity,
                  resolution={'status': status, 'current_point_confirmed': False,
                              'requires_scope_check': True, 'reason': reason})
    if disambiguation:
        result['resolution']['disambiguation_candidates'] = [
            {k: row[k] for k in ('concept_key', 'concept_name', 'title', 'match_kind') if k in row}
            for row in disambiguation[:2]]
    return result


def _native_candidate_keys(value):
    keys = {row.get('concept_key') for row in value.get('resolution', {}).get('candidates', [])
            if isinstance(row, dict)}
    for values in value.get('suggestions', {}).values():
        if isinstance(values, list):
            keys.update(row.get('concept_key') for row in values if isinstance(row, dict))
    keys.update(row.get('concept_key') for row in value.get('records', []) if row.get('retrieval_scope'))
    return {key for key in keys if isinstance(key, str)}


def _mark_native_candidates(value):
    candidates = _native_candidate_keys(value)
    if candidates:
        value.setdefault('resolution', {}).update(requires_scope_check=True, current_point_confirmed=False)
    for row in value.get('records', []):
        if row.get('concept_key') in candidates:
            row['retrieval_scope'] = {'role': 'candidate_reference', 'basis': 'native_lexical_candidate',
                                      'requires_scope_check': True, 'not_proof_of_current_error': True}
    return candidates


def _exact_requested_keys(root, requested, value):
    """A trimmed protected row is not proof of an exact lookup.

    Verify exact keys/names/registered aliases against the native lookup table,
    and exclude every key the original response explicitly marked candidate.
    """
    import math_concept_index as native
    from math_learning_profiles import _read_only_uri
    candidates = _native_candidate_keys(value)
    present = {row.get('concept_key') for row in value.get('records', [])}
    exact = set()
    try:
        with closing(sqlite3.connect(_read_only_uri(root / native.INDEX), uri=True)) as conn:
            conn.execute('BEGIN')
            for query in requested:
                exact.update(key for key, in conn.execute('SELECT key FROM lookup WHERE name=?',
                                                          (native.normalize(query),)))
    except (OSError, sqlite3.Error):
        # Safe fallback for a degraded/isolated reader: explicit canonical ID
        # or exact visible name only. An unknown alias is never guessed exact.
        names = {native.normalize(query) for query in requested}
        exact = {row.get('concept_key') for row in value.get('records', [])
                 if native.normalize(row.get('concept_key', '')) in names
                 or native.normalize(row.get('concept_name', '')) in names}
    return [row['concept_key'] for row in value.get('records', [])
            if row.get('concept_key') in exact & present - candidates]


def _unmatched_natural_query(requested, value):
    """Bridge old --concept callers without semantically guessing stable IDs."""
    unresolved = set(value.get('unknown', [])) | set(value.get('ambiguous', []))
    terms = []
    for term in requested:
        if not isinstance(term, str) or term not in unresolved:
            continue
        text = term.strip()
        if not text or len(text) > 1000:
            continue
        if re.fullmatch(r'(?i)(?:math-concept-|math-method-|method:|step:|conclusion:|(?:gs|la|pr|mx)-|math[123]-|fce-)[A-Za-z0-9_.:/-]+', text):
            continue
        # Printed IDs and method/step codes are identity requests, including
        # unknown codes. Their absence cannot authorize a semantic substitute.
        if re.fullmatch(r'[A-Za-z0-9_.:/-]+', text) and re.search(r'\d', text):
            continue
        if len('\n'.join([*terms, text])) > 1000:
            break
        if text not in terms:
            terms.append(text)
        if len(terms) == 3:
            break
    return '\n'.join(terms) or None


def _claim_context(root, keys, view, valid_at, known_at):
    try:
        import math_memory_lifecycle as lifecycle
        result = lifecycle.resolve_memory_claims(root, keys, valid_at=valid_at,
                                                 known_at=known_at, view=view)
        if view == 'after_attempt':
            from math_learning_profiles import ANSWER_MARKER
            visible = []
            for claim in result['claims']:
                if ANSWER_MARKER.search(claim['content']) or ANSWER_MARKER.search(claim['scope']):
                    continue
                visible.append({**claim, 'source_refs': [
                    {k: ref[k] for k in ('sha256', 'role', 'sequence') if k in ref}
                    for ref in claim['source_refs']]})
            if result['claims']:
                result['claim_source_view'] = 'role_sequence_and_hash_only'
            if len(visible) != len(result['claims']):
                result['claims_withheld'] = len(result['claims']) - len(visible)
            result['claims'] = visible
        return result
    except ImportError:
        return {'status': 'unavailable', 'claims': [], 'conflicts': [], 'missing': ['lifecycle_module']}
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        return {'status': 'unavailable', 'claims': [], 'conflicts': [],
                'missing': ['lifecycle_read_failed'], 'reason': type(exc).__name__}


def _utterance_lookup(root,query,scope,view,valid_at,known_at):
    intent=scope.get('request_intent',{})
    if view=='protected':
        return {'status':'protected','selection_status':'not_requested','records':[]}
    if not intent.get('history_search') or not intent.get('pinpoint_record'):
        return {'status':'not_requested','selection_status':'not_requested','records':[]}
    if scope.get('date_gap'):
        return {'status':'date_scope_required','selection_status':'no_match','records':[],
                'reason':scope['date_gap']}
    dates=list(scope.get('dates',[]))
    if valid_at:
        year,month,day=map(int,valid_at[:10].split('-'))
        dates.append({'year':year,'month':month,'day':day,'mode':'through'})
    try:
        import math_memory_utterances
        expected_version = _index_version(root)
        result=math_memory_utterances.search(root,query,view=view,explicit_history_request=True,
            concept_keys=(),formal_ids=scope.get('formal_ids',()),dates=dates,known_at=known_at,
            excluded_formal_ids=scope.get('excluded_formal_ids',()),
            excluded_dates=scope.get('excluded_dates',()),limit=1)
        if result.get('status')=='available' and result.get('native_version')!=expected_version:
            return {'status':'stale','selection_status':'no_match','records':[],
                    'reason':'utterance_and_native_generations_differ'}
        return result
    except (ImportError,OSError,ValueError,TypeError,KeyError,sqlite3.Error) as error:
        return {'status':'unavailable','selection_status':'no_match','records':[],
                'reason':type(error).__name__,'maintenance_required':True}


def _historical_evidence(root, keys, view, valid_at, known_at, *, expected_version=None, max_bytes=4000):
    """Only an explicit temporal request reads bounded point-event metadata.

    The maintenance reader has full evidence. None of its question, answer,
    quote, error-detail, or raw-source text crosses this projection.
    """
    if view == 'protected':
        return {'status': 'protected', 'points': []}
    if not (valid_at or known_at):
        return {'status': 'not_requested', 'points': []}
    if not keys:
        return {'status': 'scope_required', 'points': []}
    import math_concept_index as index
    try:
        result = index.point_history(root, keys, valid_at=valid_at, known_at=known_at)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        return {'status': 'unavailable', 'reason': type(exc).__name__, 'points': []}
    if result.get('status') != 'ready':
        return {'status': result.get('status', 'unavailable'), 'points': [],
                'reason': result.get('reason', 'point_history_unavailable')}
    if expected_version is not None and result.get('version') != expected_version:
        return {'status': 'stale', 'reason': 'history_snapshot_changed', 'points': []}

    def event_metadata(event):
        value = {k: event[k] for k in ('event_id', 'event_type', 'study_date', 'recorded_at',
            'episode_id', 'outcomes', 'related_formal_ids', 'memory_status') if k in event}
        refs = event.get('source_refs', [])
        value['source_handles'] = [{'source_key': 'source:' + digest(ref.get('path'))[:24],
                                    'sha256': ref.get('sha256')} for ref in refs[:2]]
        value['source_ref_count'] = len(refs)
        if len(refs) > 2:
            value['source_refs_omitted'] = len(refs) - 2
        return value

    points = []
    for point in result.get('points', []):
        events = point.get('events', [])
        gaps = point.get('history_gaps', [])
        value = {k: point[k] for k in ('concept_key', 'point_source_version', 'memory_version',
            'wrong_episode_count', 'known_wrong_episode_count', 'history_complete') if k in point}
        value.update(status='partial' if gaps else 'available' if events else 'no_formal_event_in_scope',
                     events=[event_metadata(event) for event in events[-3:]],
                     event_count=len(events), events_omitted=max(0, len(events)-3),
                     history_gaps=[{k: gap[k] for k in ('event_id', 'reason') if k in gap} for gap in gaps[-3:]],
                     history_gaps_total=len(gaps), history_gaps_omitted=max(0, len(gaps)-3))
        points.append(value)
    response = {'status': 'available', 'source_version': result.get('version'),
                'count_scope': result.get('count_scope'), 'points': points,
                'valid_at': valid_at, 'known_at': known_at,
                'scope': 'accepted_point_observations_only',
                'known_at_semantics': 'formal_closeout_closed_at_or_concept_review_commit_time',
                'raw_capture_known_time_is_separate': True,
                'absence_does_not_prove_no_study_or_no_saved_capture': True,
                'evidence_role': 'recorded_observation_not_global_mastery'}
    # Omit complete events, retaining count/gap semantics; never chop statements
    # or disguise an unknown count as zero.
    while len(canonical(response).encode()) > max_bytes:
        nonempty = [point for point in points if point['events']]
        if not nonempty:
            return {'status': 'budget_too_small', 'source_version': result.get('version'),
                    'points': [], 'required_min_bytes': len(canonical(response).encode())}
        longest = max(nonempty, key=lambda point: len(point['events']))
        longest['events'].pop(0)
        longest['events_omitted'] += 1
    return response


def _evidence_quotes(value):
    quotes = set()
    for atom in value.get('user_evidence', []) if isinstance(value.get('user_evidence'), list) else []:
        if isinstance(atom, dict) and isinstance(atom.get('quote'), str):
            quotes.add((atom.get('sequence'), atom['quote']))
    for atom in value.get('source_refs', []):
        if atom.get('role') == 'user' and isinstance(atom.get('quote'), str):
            quotes.add((atom.get('sequence'), atom['quote']))
    return quotes


def _affected_step(step, observation):
    target = {'event_id': observation.get('event_id'),
              'observation_sha256': observation.get('observation_sha256')}
    if target in step.get('observation_refs', []):
        return True
    references = {(r.get('path'), r.get('sha256')) for r in step.get('source_refs', [])}
    source_match = bool(references & {(r.get('path'), r.get('sha256')) for r in observation.get('source_refs', [])})
    # Sharing a package alone does not mean a different step was corrected.
    return source_match and bool(_evidence_quotes(step) & _evidence_quotes(observation))


def _uncertain_step_dependency(step, observations):
    references = {(r.get('path'), r.get('sha256')) for r in step.get('source_refs', [])}
    if not references:
        return True
    if step.get('observation_refs'):
        return False
    for observation in observations:
        source_match = bool(references & {(r.get('path'), r.get('sha256'))
                                         for r in observation.get('source_refs', [])})
        if source_match and not (_evidence_quotes(step) and _evidence_quotes(observation)):
            return True
    return False


def _strip_invalidated(native, invalidated, temporal, affected_observations=()):
    """An old fluent summary cannot bypass an observation-level correction."""
    for row in native.get('records', []):
        key = row.get('concept_key')
        if key not in invalidated and not temporal:
            continue
        for field in PERSONAL:
            row.pop(field, None)
        if temporal:
            row.pop('teaching_preferences', None)
            row.pop('step_evidence', None)
            for field in ('questions', 'representative_questions', 'page', 'obsidian_url', 'source_refs'):
                row.pop(field, None)
            row['teaching_preferences_status'] = 'historical_view_requires_versioned_evidence'
        else:
            steps = row.get('step_evidence', [])
            relevant = [o for o in affected_observations if o.get('concept_key') == key]
            retained = [step for step in steps if not any(
                _affected_step(step, observation) for observation in relevant)]
            uncertain = 0
            for step in retained:
                if _uncertain_step_dependency(step, relevant):
                    step['state'] = 'unknown'
                    step['memory_status'] = 'correction_dependency_unknown'
                    uncertain += 1
            if len(retained) != len(steps):
                row['step_evidence'] = retained
                row['step_evidence_status'] = 'partial_after_correction' if retained else 'invalidated'
                row['step_evidence_omitted_after_correction'] = len(steps) - len(retained)
            elif uncertain:
                row['step_evidence_status'] = 'correction_dependency_unknown'
        row['status'] = 'semantic_stale' if key in invalidated else 'historical_personal_view'
        row.pop('solution_connections', None)
        if temporal:
            row['step_evidence_status'] = 'historical_view'
    if invalidated or temporal:
        native.pop('exam_brief', None)


def _levels(native, view):
    levels = {'entry': {'identity_ref': 'response.identity'},
              'current_point': [], 'evidence': {'mode': 'exact_source_on_demand'}}
    if view == 'protected':
        levels['evidence']['mode'] = 'protected'
        return levels
    preferences = []
    for position, row in enumerate(native.get('records', [])):
        prefix = f'response.records[{position}]'
        item = {'concept_key': row.get('concept_key'), 'profile_ref': prefix}
        if row.get('problem_solving'):
            item['material_ref'] = prefix + '.problem_solving'
        if row.get('step_evidence'):
            item['evidence_ref'] = prefix + '.step_evidence'
        if row.get('teaching_preferences'):
            preferences.append(prefix + '.teaching_preferences')
        levels['current_point'].append(item)
    if preferences:
        levels['entry']['preference_refs'] = preferences
    return levels


def _bound(value, max_bytes):
    """Omit whole optional evidence atoms, never conditions or formula fragments."""
    size = len(canonical(value).encode())
    if size <= max_bytes:
        return value
    context = value['memory_context']
    temporal = context.get('temporal', {})
    record_query = context.get('record_query', False)
    if temporal.get('valid_at') or temporal.get('known_at') or record_query:
        # This request explicitly asks for historical memory. Current textbook
        # routes are secondary and may not consume the budget needed to answer
        # that question. Omit complete current-material atoms, never formulas.
        omitted = []
        for field in ('problem_solving', 'choice_fill_guidance', 'exam_frequency', 'selection_context',
                      'method_status', 'scope_notes', 'detail_lookup'):
            if field in value:
                value.pop(field)
                omitted.append('response.' + field)
        for position, row in enumerate(value.get('records', [])):
            for field in ('problem_solving', 'exam_context', 'exam_frequency', 'choice_fill_guidance',
                          'step_reference', 'conclusion_reference', 'reference_pages', 'solution_connections'):
                if field in row:
                    row.pop(field)
                    omitted.append(f'response.records[{position}].{field}')
        if omitted:
            temporal['knowledge_scope'] = 'whole_current_materials_omitted_for_requested_records' if record_query else 'whole_current_materials_omitted_for_requested_history'
            context['current_materials_omitted'] = omitted
            context['levels'] = _levels(value, value.get('view', 'protected'))
        if len(canonical(value).encode()) <= max_bytes:
            return value
    # References and static role descriptions are useful when there is room,
    # but are not another copy of evidence and must not evict native conditions.
    compact = {'schema': SCHEMA, 'status': 'compact'}
    lifecycle = context.get('personal_judgments', {})
    compact['personal_judgments'] = {k: lifecycle[k] for k in
        ('status', 'claims', 'conflicts', 'missing', 'history_gaps', 'invalidated_concept_keys',
         'affected_observation_count', 'claim_source_view', 'claims_withheld')
        if k in lifecycle and (k == 'status' or lifecycle[k])}
    pending = context.get('pending_evidence', {})
    compact['pending_evidence'] = {k: pending[k] for k in
        ('status', 'records', 'raw_text_status', 'omitted_turns', 'unavailable_count', 'reason',
         'history_scope', 'history_gaps', 'known_at_semantics') if k in pending and (k == 'status' or pending[k])}
    if context.get('personal_records', {}).get('status') not in ('not_requested', None):
        compact['personal_records'] = context['personal_records']
        compact['record_query'] = record_query
    utterance=context.get('utterance_lookup',{})
    if utterance.get('status') not in ('not_requested','protected',None):
        compact['utterance_lookup']={key:utterance[key] for key in
            ('status','selection_status','records','concept_keys','point_selection_status','reason','version','native_version','source_changed_count')
            if key in utterance}
    retrieval = context.get('retrieval', {})
    if retrieval.get('mode') != 'native':
        compact['retrieval'] = retrieval
    temporal = context.get('temporal', {})
    if temporal.get('valid_at') or temporal.get('known_at'):
        compact['temporal'] = temporal
        compact['historical_evidence'] = context.get('historical_evidence', {'status': 'not_requested'})
        if context.get('current_materials_omitted'):
            compact['current_materials_omitted'] = context['current_materials_omitted']
    value['memory_context'] = context = compact
    if len(canonical(value).encode()) <= max_bytes:
        return value
    context['required_full_bytes'] = size
    personal = context.get('personal_records', {})
    while personal.get('records') and len(canonical(value).encode()) > max_bytes:
        personal['records'].pop()
        personal['omitted_count'] = personal.get('omitted_count', 0)+1
        personal['status'] = 'partial' if personal['records'] else 'budget_too_small'
    pending = context.get('pending_evidence', {})
    while pending.get('records') and len(canonical(value).encode()) > max_bytes:
        removed = pending['records'].pop()
        pending['omitted_turns'] = pending.get('omitted_turns', 0) + len(removed.get('user_turns', []))
        pending['omitted_records'] = pending.get('omitted_records', 0) + 1
    lifecycle = context.get('personal_judgments', {})
    for field in ('claims', 'conflicts'):
        while lifecycle.get(field) and len(canonical(value).encode()) > max_bytes:
            lifecycle[field].pop()
            lifecycle[field + '_omitted'] = lifecycle.get(field + '_omitted', 0) + 1
    if len(canonical(value).encode()) > max_bytes:
        # The original reader already enforces complete native teaching atoms.
        # Preserve that result, with an explicit unavailable memory extension.
        value['memory_context'] = {'schema': SCHEMA, 'status': 'budget_too_small',
                                   'required_full_bytes': size, 'omission_is_not_absence': True}
    if len(canonical(value).encode()) > max_bytes:
        # At the exact native budget boundary even the small extension envelope
        # may not fit. A tiny top-level marker is preferable to discarding the
        # whole previously readable method/profile. Empty routing metadata and
        # aggregate counts derivable from the retained records are expendable.
        value.pop('memory_context', None)
        value['memory_omitted'] = True
        for field in ('unknown', 'ambiguous', 'scope_notes', 'identity'):
            if len(canonical(value).encode()) <= max_bytes:
                return value
            if field in value and value[field] in (None, [], {}):
                value.pop(field)
        for field in ('returned', 'method_status'):
            if len(canonical(value).encode()) <= max_bytes:
                return value
            value.pop(field, None)
        if len(canonical(value).encode()) <= max_bytes:
            return value
    if len(canonical(value).encode()) > max_bytes:
        return {'status': 'budget_too_small', 'version': value.get('version'),
                'source_version': value.get('source_version'), 'records': [],
                'view': value.get('view'), 'required_min_bytes': size, 'truncated': True}
    return value


def _structured_query_targets_episode(query):
    """Point-level record requests may accompany a mathematical scope query.

    Quotations, dated episodes and verification of personal claims retain their
    original evidence route; the mere word 'record' does not identify an episode.
    """
    import math_memory_evidence as evidence
    intent=evidence.request_intent(query)
    if (intent.get('historical_statement')
            or intent.get('history_goal') in {'quote_lookup','claim_verification'}
            or re.search(r'说过|写过|首答|那句|那条|哪次|那次|上次|某次',query)):
        return True
    return bool(intent.get('history_search') and (
        evidence._dates(query)
        or re.search(r'今天|昨天|前天|昨晚|今早|上周|本周|去年|今年',query)))


def resolve(repo_root, concepts=None, view='protected', max_bytes=12000, *,
            known_version=None, formal_id=None, source_id=None, fallback_concepts=None,
            query=None, operation=None, include_pending=False, valid_at=None, known_at=None,
            backend=None, pending_capture_id=None, pending_sequences=None,
            pending_hint_sequences=None, pending_spans=None, pending_whole_capture=False,
            backend_config=None, structured_math=False, confirmed_concept=None,
            selection_receipt=None, selection_basis=None, selection_abstain=None,
            point_records=False):
    import math_concept_index as index
    import math_learning_profiles as profiles
    if view not in ('protected', 'after_attempt', 'direct'):
        raise ValueError('invalid_view')
    if type(structured_math) is not bool or structured_math and not query:
        raise ValueError('invalid_structured_math_query')
    if structured_math and _structured_query_targets_episode(query):
        raise ValueError('structured_math_cannot_replace_personal_evidence_query')
    if structured_math and (valid_at or known_at):
        raise ValueError('structured_math_discovery_is_not_a_historical_state_query')
    if not isinstance(max_bytes, int) or max_bytes < 64:
        raise ValueError('invalid_context_budget')
    if pending_capture_id is not None and not re.fullmatch(r'MFI-CAP-[0-9a-f]{24}', pending_capture_id):
        raise ValueError('invalid_pending_capture_id')
    for text in (query, operation):
        if text is not None and (not isinstance(text, str) or not text.strip() or len(text) > 1000):
            raise ValueError('invalid_memory_query')
    from math_memory_pending import _cutoff, validate_selection
    _cutoff(valid_at)
    _cutoff(known_at)
    pending_sequences, pending_hint_sequences, pending_spans = validate_selection(
        pending_sequences, pending_hint_sequences, pending_spans, pending_whole_capture)
    root = Path(repo_root).resolve()
    if structured_math and not formal_id and not source_id and not concepts:
        from math_memory_scope_selection import discover,validate_selection
        if selection_abstain is not None:
            if selection_abstain not in {'ambiguous','no_match'} or not selection_basis or not selection_receipt:
                raise ValueError('invalid_math_scope_abstention')
            validate_selection(root,query,None,selection_receipt,view=view,config_path=backend_config)
            return {'status':selection_abstain,'records':[],'view':view,
                'resolution':{'status':selection_abstain,'reason':selection_basis},
                'memory_context':{'retrieval':{'selection_status':selection_abstain},
                    'personal_records':{'status':'not_requested','records':[]}},
                'selection_owner':'current_assistant','does_not_prove_no_learning':True}
        if confirmed_concept is None:
            return discover(root,query,view=view,config_path=backend_config,
                            max_bytes=min(64000,max_bytes))
        if not selection_receipt or not isinstance(selection_basis,str) or not 4<=len(selection_basis)<=500:
            raise ValueError('mathematical_scope_selection_basis_required')
        proof=validate_selection(root,query,confirmed_concept,selection_receipt,
                                 view=view,config_path=backend_config)
        selected=resolve(root,[confirmed_concept],view,max_bytes,operation=operation or query,
            backend_config=backend_config,include_pending=include_pending,pending_capture_id=pending_capture_id,
            pending_sequences=pending_sequences,pending_hint_sequences=pending_hint_sequences,
            pending_spans=pending_spans,pending_whole_capture=pending_whole_capture,
            point_records=point_records)
        selected['scope_selection']={'status':'source_identity_selected_by_current_assistant',
            'concept_key':confirmed_concept,'query':query,'basis':selection_basis,
            'source_version':proof['source_version'],'not_a_mastery_assessment':True,
            'mathematical_correctness_not_proven_by_index':True}
        selected['version']=digest([selected.get('version'),proof['query_sha256'],confirmed_concept,view])
        selected_size=len(canonical(selected).encode())
        if selected_size>max_bytes:
            return {'status':'budget_too_small','version':selected['version'],
                'source_version':selected.get('source_version'),'records':[],
                'view':view,'required_min_bytes':max(selected_size,selected.get('required_min_bytes',0))}
        return selected
    if any(value is not None for value in (confirmed_concept,selection_receipt,selection_basis,selection_abstain)):
        raise ValueError('selection_arguments_require_unscoped_structured_math_query')
    config_identity = None
    if backend_config is not None:
        config_path = Path(backend_config).expanduser().resolve()
        try:
            if config_path.stat().st_size > 1024 * 1024:
                raise ValueError('backend_config_too_large')
            config_identity = digest([str(config_path), hashlib.sha256(config_path.read_bytes()).hexdigest()])
        except (OSError, ValueError):
            config_identity = digest(['unavailable_config', str(config_path)])
    original_concepts = list(concepts or [])
    if point_records and (len(original_concepts)!=1 or not KEY.fullmatch(original_concepts[0])):
        raise ValueError('point_history_requires_one_exact_concept_key')
    requested = original_concepts or ([query] if query else [])
    # Preserve the existing complete native teaching atom. Reserving extension
    # bytes up front can turn a previously readable 11.5 KB method into an empty
    # 12 KB response. Optional memory layers use the remainder or report omission.
    native_budget = max_bytes

    import math_memory_evidence as evidence
    scope_query = query or '\n'.join(original_concepts)
    scope = evidence.query_scope(root, scope_query, formal_id=formal_id, source_id=source_id)
    intent=scope.get('request_intent',evidence.request_intent(scope_query))
    if point_records:
        scope={**scope,'personal_requested':True,'explicit_personal_requested':True,
               'point_history_requested':True,'request_intent':{**intent,'history_search':True,
               'history_goal':'record_lookup','pinpoint_record':False,'historical_statement':False}}
        intent=scope['request_intent']
    if structured_math:
        if _structured_query_targets_episode(scope_query):
            raise ValueError('structured_math_cannot_replace_personal_evidence_query')
        # An operation's "before" or a random experiment's "record" is not
        # a request for the learner's past. Explicit temporal API fields remain
        # independent and still disable current annotation discovery below.
        intent={**intent,'history_search':False,'history_goal':'general','historical_statement':False,
                'historical_spans':[],'requires_statement_verification':False,'pinpoint_record':False}
        scope={**scope,'request_intent':intent,'personal_requested':False,'explicit_personal_requested':False}
    # An unseen printed question ID is normal during tutoring. It does not
    # negate the independently requested point's accepted personal summary.
    # Historical/dated/point-record queries still require their exact identity;
    # conflicts and ambiguous IDs never take this reference fallback.
    new_source_point_context = bool(
        scope.get('status') == 'unknown_source_id' and source_id and not formal_id
        and original_concepts and not point_records and not valid_at and not known_at
        and not intent.get('history_search') and not scope.get('personal_requested'))
    if new_source_point_context:
        scope = {**scope, 'status': 'unscoped', 'source_identity_status': 'unmapped',
                 'personal_context_scope': 'requested_knowledge_point_not_source_attempt_history'}
    if scope.get('status') in ('identity_conflict', 'multiple_identities', 'unknown_formal_id',
                               'ambiguous_identity', 'unknown_source_id', 'identity_scope_too_large','invalid_date_scope'):
        return {'status': scope['status'], 'records': [], 'view': view,
                'resolution': {'status': scope['status'], 'current_point_confirmed': False}}
    if scope.get('exact_identity'):
        formal_id = scope['formal_ids'][0] if len(scope['formal_ids']) == 1 else None
    source_first_request=bool(view!='protected' and intent.get('history_search') and intent.get('pinpoint_record'))
    record_scoped = bool(scope.get('personal_requested') and
                         (scope.get('exact_identity') or scope.get('dates') or scope.get('date_gap') or valid_at or known_at
                          or source_first_request))
    source_lookup=({'status':'not_requested','selection_status':'not_requested','records':[]}
                   if point_records else _utterance_lookup(root,scope_query,scope,view,valid_at,known_at))

    def read(selected, read_view=None):
        if not (root / index.INDEX).is_file():
            return {'status': 'stale', 'reason': 'prepared_index_missing', 'records': [], 'view': view}
        try:
            actual_view=read_view or ('protected' if record_scoped else view)
            value = profiles.resolve(root, selected, actual_view,
                                     max(native_budget,32000) if point_records else native_budget, None, formal_id, source_id,
                                     fallback_concepts=fallback_concepts)
            if point_records and actual_view!='protected':
                needed=value.get('required_min_bytes',0)
                if value.get('status')=='budget_too_small' and 32000<needed<=128000:
                    value=profiles.resolve(root,selected,actual_view,needed,None,formal_id,source_id,
                                           fallback_concepts=fallback_concepts)
                for row in value.get('records',[]):
                    for field in ('problem_solving','choice_fill_guidance','exam_frequency','selection_context',
                                  'exam_context','problem_solving_source_refs'):
                        row.pop(field,None)
                value['mathematical_materials_omitted']='explicit_point_record_request;whole_blocks_not_truncated_conditions'
            _neutral_protected(value)
            return value
        except (OSError, sqlite3.Error) as exc:
            return {'status': 'stale', 'reason': 'prepared_index_unavailable',
                    'error_type': type(exc).__name__, 'records': [], 'view': view}

    # Discover identity using neutral prepared rows; a weak name match must not
    # open private history first and only be discarded after a failed rank.
    precise_input = _all_exact_eligible_names(root,requested)
    route_reconsider = bool(query and intent.get('current_constraint_active'))
    if intent.get('historical_statement'):
        route_reconsider=True
    discovery_view = view if precise_input and not record_scoped and not route_reconsider else 'protected'
    discovery = copy.deepcopy(read(requested, discovery_view))
    _neutral_protected(discovery)
    explicitly_named_keys = [term for term in requested if isinstance(term,str) and KEY.fullmatch(term)]
    rejected = _eligible_rows(discovery, explicitly_named_keys)
    unclassified = {row['concept_key'] for row in discovery.get('records', [])
                    if row.get('classification_status') == 'unclassified'}
    if unclassified:
        record_scoped = True
    weak_keys = _mark_native_candidates(discovery)
    exact = _exact_requested_keys(root, requested, discovery)
    kinds=_catalog_kinds(root,exact)
    parent_keys=[key for key in exact if kinds.get(key)=='parent']
    if not requested and scope.get('exact_identity') and len(discovery.get('records',[]))==1 and not weak_keys:
        only=discovery['records'][0].get('concept_key')
        if only and KEY.fullmatch(only):
            exact=[only]
    references = _registered_method_names(root, requested, view)
    unknown_identity = [term for term in requested if term in discovery.get('unknown', [])
                        and isinstance(term,str) and (KEY.fullmatch(term) or
                        re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:/-]*\d[A-Za-z0-9_.:/-]*',term))
                        and term not in references]
    if scope.get('exact_identity'):
        unknown_identity = [term for term in unknown_identity if not evidence.FORMAL.fullmatch(term)]
    natural = (intent['current_constraint_text'] if query and intent.get('historical_statement') else query) or _unmatched_natural_query(original_concepts, discovery)
    query_origin = ('assistant_structured_math' if structured_math else 'explicit_query') if query else 'unmatched_concept' if natural else None
    reconsider = route_reconsider
    native = discovery
    retrieval = {'mode': 'native', 'status': discovery.get('status'), 'candidate_keys': [],
                 'selection_status': 'exact' if exact else 'unresolved'}
    if exact and not reconsider and len(parent_keys)==len(exact):
        native=_as_parent_reference(discovery,view)
        retrieval.update(selection_status='reference_only',reference_only=True,
                         personal_evidence_eligible=False,fine_point=False,candidate_keys=parent_keys)
    elif exact and not reconsider:
        exact=[key for key in exact if key not in parent_keys]
        native = (discovery if discovery_view==view and not unclassified else
                  read(exact, 'protected' if unclassified else None) if view != 'protected' else discovery)
        native = copy.deepcopy(native)
        _eligible_rows(native, explicitly_named_keys)
        native['records'] = [row for row in native.get('records', [])
                             if row.get('concept_key') in exact]
        retrieval['candidate_keys'] = exact
        if discovery.get('unknown'):
            native['unknown']=discovery['unknown']
            native['resolution']={'status':'partial_exact','selected_keys':exact,
                                  'unmatched_queries':discovery['unknown'],'current_point_confirmed':True}
        if unclassified:
            native['status'] = 'classification_unknown'
            native['resolution'] = {'status':'classification_unknown', 'exact_record_identity':True,
                                    'current_point_confirmed':False}
    elif references and not natural and not rejected:
        native = copy.deepcopy(read(references))
        retrieval.update(selection_status='reference_only', mode='exact_reference')
    elif references and set(references) == set(requested) and not query and not rejected:
        native = copy.deepcopy(read(references))
        retrieval.update(selection_status='reference_only', mode='exact_reference')
    else:
        blocked = discovery.get('status') in ('stale', 'ambiguous_identity', 'identity_conflict',
                                               'unknown_formal_id', 'budget_too_small')
        if natural and not blocked and not rejected and not unknown_identity:
            try:
                import math_memory_backends
                discovered = math_memory_backends.candidate_query(root,
                    natural + ('\n当前操作：' + operation if operation else ''),
                    concept_keys=scope.get('concept_keys'), formal_id=formal_id,
                    view=view, limit=3, timeout=8.0, backend=backend,
                    reference_allowed=not (valid_at or known_at),
                    structured_math=structured_math,
                    config_path=config_path if backend_config is not None else None)
                keys, stale = _candidate_keys(discovered, _index_version(root))
                selection = discovered.get('selection_status', 'ambiguous' if keys else 'no_match')
                reference_only=bool(discovered.get('reference_only') or any(
                    row.get('reference_only') or row.get('personal_evidence_eligible') is False
                    for row in discovered.get('candidates',[])))
                selection_reasons=discovered.get('selection_reasons',
                    discovered.get('selection_reason',discovered.get('reasons',[]))) or []
                if isinstance(selection_reasons,str):
                    selection_reasons=[selection_reasons]
                retrieval = {'mode': 'precision_search', 'backend': discovered.get('backend'),
                             'status': discovered.get('status'), 'selection_status': selection,
                             'candidate_keys': keys if selection == 'matched' else [],
                             'query_origin': query_origin, 'source_version': discovered.get('source_version'),
                             'retrieval_version': discovered.get('retrieval_version'),
                             'constraints': discovered.get('query_constraints',discovered.get('constraints', {})),
                             'reasons': selection_reasons,
                             'semantic_reference':discovered.get('semantic_reference'),
                             'degraded': stale or discovered.get('degraded'),
                             'requires_scope_check': True}
                if reference_only:
                    retrieval.update(reference_only=True,personal_evidence_eligible=False,fine_point=False)
                if selection == 'matched' and keys and not stale:
                    keys = _eligible_selected_keys(root,keys[:1])
                    hydrated = copy.deepcopy(read(keys[:1],'protected' if reference_only else None)) if keys else _clear_unqualified(
                        discovery,'no_match',reason='selected_identity_not_a_knowledge_point')
                    _eligible_rows(hydrated)
                    if hydrated.get('source_version') != discovered.get('source_version'):
                        hydrated = {'status':'stale','reason':'candidate_generation_changed_before_hydration',
                                    'records':[],'view':view,'source_version':hydrated.get('source_version')}
                    if reference_only and hydrated.get('records'):
                        native=_as_parent_reference(hydrated,view)
                    elif hydrated.get('status') not in ('stale', 'identity_conflict', 'unknown_formal_id') and hydrated.get('records'):
                        for row in hydrated['records']:
                            row['retrieval_scope'] = {'role': 'qualified_point_match',
                                'basis': 'precision_ranked_and_native_verified', 'requires_scope_check': True,
                                'not_proof_of_current_error': True}
                        hydrated['resolution'] = {'status': 'matched', 'selected_keys': keys[:1],
                            'requires_scope_check': True, 'current_point_confirmed': False,
                            'not_proof_of_current_error': True}
                        native = hydrated
                    else:
                        native = hydrated if hydrated.get('status') == 'stale' else _clear_unqualified(
                            discovery, 'no_match', reason='qualified_point_not_available')
                else:
                    native = _clear_unqualified(discovery, 'ambiguous' if selection == 'ambiguous' else 'no_match',
                        disambiguation=discovered.get('disambiguation_candidates', []),
                        reason=stale or discovered.get('degraded') or 'no_reliable_specific_point')
            except (ImportError, OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error) as exc:
                retrieval = {'mode': 'precision_search', 'status': 'degraded',
                             'selection_status': 'no_match', 'degraded': type(exc).__name__,
                             'candidate_keys': [], 'query_origin': query_origin}
                native = _clear_unqualified(discovery, 'no_match', reason='precision_reader_unavailable')
        elif not blocked:
            native = _clear_unqualified(discovery, 'no_match',
                reason='not_a_knowledge_point' if rejected else 'unknown_explicit_identity' if unknown_identity else 'unresolved_exact_identity_or_point')
            retrieval['selection_status'] = 'no_match'
    native['view'] = view
    _neutral_protected(native)
    search_query = natural
    if native.get('status') == 'budget_too_small' and max_bytes < 2000:
        return native
    keys = [row['concept_key'] for row in native.get('records', []) if KEY.fullmatch(str(row.get('concept_key',''))) and row.get('personal_evidence_eligible') is not False]
    evidence_keys = [key for key in keys if KEY.fullmatch(key)]
    semantic_keys=list(evidence_keys)
    # An atomic refresh can land after the utterance lookup's own check but
    # before this read. Do not mix a prior generation's quotes or identifiers
    # into the result from the newer native reader.
    if (source_lookup.get('status') == 'available'
            and source_lookup.get('native_version') != native.get('source_version')):
        source_lookup = {'status': 'stale', 'selection_status': 'no_match', 'records': [],
                         'reason': 'utterance_and_native_generations_differ'}
    source_bindings=source_lookup.get('original_bindings',[]) if source_lookup.get('selection_status')=='matched' else []
    bound_keys=list(dict.fromkeys(row.get('concept_key') for row in source_bindings
                                 if isinstance(row.get('concept_key'),str) and KEY.fullmatch(row['concept_key'])))
    source_ids=list(dict.fromkeys(row.get('record_id') for row in source_bindings
                                 if row.get('kind') in {'formal_concept_observation','concept_review'} and row.get('record_id')))
    if source_first_request and bound_keys:
        evidence_keys=bound_keys
    dated_record_scope = scope.get('explicit_personal_requested') and any(d['year'] and d['mode']=='on' for d in scope.get('dates', []))
    if not evidence_keys and not unknown_identity and (scope.get('exact_identity') or dated_record_scope) and scope.get('personal_requested') and view != 'protected':
        try:
            observed = evidence.observed_point_scope(root, scope, view=view, valid_at=valid_at, known_at=known_at)
            with closing(sqlite3.connect((root/index.INDEX).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
                eligible = []
                for key in observed:
                    row = conn.execute('SELECT label FROM concepts WHERE key=?', (key,)).fetchone()
                    if row and _eligible_point(row[0]):
                        eligible.append(key)
            evidence_keys = eligible or observed
            if len(eligible) == 1:
                exact_event = copy.deepcopy(read(eligible, 'protected'))
                exact_event['view'] = view
                exact_event['resolution'] = {'status':'matched', 'basis':'exact_observed_record_scope',
                    'selected_keys':eligible, 'current_point_confirmed':True,
                    'not_proof_of_current_error':True}
                native = exact_event
                keys = eligible
                retrieval.update(selection_status='record_scope_matched', candidate_keys=eligible,
                                 mode='exact_personal_record_scope')
            elif eligible:
                native['status'] = 'needs_point_discrimination'
                native['resolution'] = {'status':'needs_point_discrimination',
                    'basis':'multiple_actual_observed_points_in_exact_record_scope',
                    'current_point_confirmed':False}
                retrieval.update(selection_status='record_scope_matched', candidate_keys=[],
                                 mode='exact_personal_record_scope')
            elif observed:
                native['status'] = 'record_scope_matched'
                native['resolution'] = {'status':'classification_unknown', 'exact_record_identity':True,
                    'current_point_confirmed':False, 'not_a_qualified_knowledge_point':True}
        except (OSError, ValueError, KeyError, sqlite3.Error):
            evidence_keys = []
    lifecycle = (_claim_context(root, keys, view, valid_at, known_at) if keys and not record_scoped else
                 {'status':'record_scoped' if record_scoped else 'point_scope_required','claims':[], 'conflicts':[]})
    try:
        personal_records = evidence.locate(root, evidence_keys, query='' if point_records else scope_query, scope=scope,
            view=view, expected_version=native.get('source_version'), valid_at=valid_at, known_at=known_at,
            max_bytes=min(6000,max_bytes//2), profile_rows=native.get('records',[]),
            source_first=source_first_request and bool(scope.get('exact_identity') or scope.get('dates')),
            preferred_concept_keys=semantic_keys,record_ids=source_ids)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        personal_records = {'status':'unavailable','records':[], 'reason':type(exc).__name__}
    located_keys=personal_records.get('matched_concept_keys',[])
    if (source_lookup.get('selection_status')=='matched' and not personal_records.get('records') and
            len(source_bindings)==1 and source_bindings[0].get('kind')=='teaching_preference'):
        personal_records={'status':'available','records':[source_bindings[0]],'matched_record_count':1,
            'matched_concept_keys':bound_keys,'record_selection_status':'matched','source_version':source_lookup.get('native_version'),
            'scope':'verified_historical_preference_statement','not_current_mastery':True,'raw_text_returned':False}
    if (not native.get('records') and scope.get('exact_identity') and
            personal_records.get('status')=='available' and not personal_records.get('record_scan_truncated') and
            len(located_keys)==1 and _eligible_selected_keys(root,located_keys)):
        actual=copy.deepcopy(read(located_keys,'protected'))
        actual['view']=view
        actual['resolution']={'status':'matched','basis':'unique_verified_personal_record_point',
                              'selected_keys':located_keys,'current_point_confirmed':True,
                              'not_proof_of_current_error':True}
        native=actual
        keys=located_keys
        retrieval.update(selection_status='record_scope_matched',candidate_keys=located_keys,
                         mode='exact_personal_record_scope')
    located_keys=personal_records.get('matched_concept_keys',[])
    if (source_first_request and personal_records.get('status')=='available' and
            not personal_records.get('record_scan_truncated') and len(located_keys)==1):
        target=located_keys[0]
        target_kind=_catalog_kinds(root,[target]).get(target)
        old_kinds=_catalog_kinds(root,semantic_keys)
        if target_kind=='parent' and any(kind=='concept' for kind in old_kinds.values()):
            personal_records['status']='parent_reference'
            personal_records['record_selection_status']='reference_only'
            for row in personal_records.get('records',[]):
                row.update(record_scope='parent_reference',target_concept_keys=semantic_keys,
                           target_point_observation_confirmed=False)
        elif target_kind=='concept' and (not semantic_keys or target not in semantic_keys):
            actual=copy.deepcopy(read([target],'protected'))
            if actual.get('source_version')==personal_records.get('source_version'):
                actual['view']=view
                actual['resolution']={'status':'matched','basis':'verified_source_then_observed_point',
                    'selected_keys':[target],'current_point_confirmed':True,'not_proof_of_current_error':True,
                    'replaced_concept_hints':semantic_keys}
                native=actual;keys=[target]
                retrieval.update(selection_status='record_scope_matched',candidate_keys=[target],
                                 mode='verified_source_first',source_index_version=source_lookup.get('version'))
    source_point_ambiguous=bool(source_lookup.get('selection_status')=='matched'
                               and source_lookup.get('point_selection_status')=='ambiguous')
    if source_point_ambiguous:
        native=_clear_unqualified(native,'ambiguous',reason='unique_utterance_has_multiple_point_bindings')
        keys=[]
        retrieval.update(selection_status='ambiguous',candidate_keys=[],
                         unique_utterance_is_not_unique_mathematical_point=True)
    elif (source_first_request and personal_records.get('status') not in {'available','parent_reference'}
            and source_lookup.get('selection_status')!='matched'):
        references=[{key:row[key] for key in ('concept_key','concept_name') if key in row}
                    for row in native.get('records',[])]
        if references and semantic_keys:
            # Mathematical qualification and a historical assertion have
            # distinct outcomes. References remain available for a mixed
            # request, but are not the requested historical record result.
            native=_clear_unqualified(native,'ambiguous' if personal_records.get('status') in
                                      {'ambiguous_records','ambiguous_date'} or source_lookup.get('selection_status')=='ambiguous'
                                      else 'no_match',reason='historical_record_not_verified_in_requested_scope')
            native['knowledge_references']=[{**row,'object_role':'knowledge_reference',
                'reference_only':True,'fine_point':True,'personal_evidence_eligible':False,
                'personal_history_status':'not_verified_in_requested_scope'} for row in references]
            retrieval.update(selection_status='record_not_verified',candidate_keys=[],
                             knowledge_selection_status='matched',knowledge_reference_keys=semantic_keys,
                             personal_record_status='not_verified')
        else:
            native=_clear_unqualified(native,'ambiguous' if personal_records.get('status') in
                                      {'ambiguous_records','ambiguous_date'} or source_lookup.get('selection_status')=='ambiguous'
                                      else 'no_match',reason='historical_record_not_verified_in_requested_scope')
            retrieval.update(selection_status='record_not_verified',candidate_keys=[])
        keys=[]
        retrieval['mathematical_reference_is_not_record_identity']=True
    invalidated = set(lifecycle.get('invalidated_concept_keys', []))
    _strip_invalidated(native, invalidated, bool(valid_at or known_at or record_scoped), lifecycle.get('affected_observations', []))
    # Raw affected observations are an internal dependency check, not a new
    # unbounded route for exposing old answers in a teaching response.
    if 'affected_observations' in lifecycle:
        lifecycle['affected_observation_count'] = len(lifecycle.pop('affected_observations'))
    historical = _historical_evidence(root, keys, view, valid_at, known_at,
        expected_version=native.get('source_version'), max_bytes=min(4000, max_bytes // 3))
    candidate_scope = {row['concept_key']: row['retrieval_scope'] for row in native.get('records', [])
                       if row.get('concept_key') and row.get('retrieval_scope')}
    for point in historical.get('points', []):
        if point.get('concept_key') in candidate_scope:
            point['retrieval_scope'] = candidate_scope[point['concept_key']]
    pending = {'status': 'not_requested', 'records': []}
    if include_pending and (scope.get('exact_identity') or source_id or pending_capture_id):
        try:
            import math_memory_pending
            identity = native.get('identity') or {}
            pending = math_memory_pending.query_pending(root, query=query or operation or '',
                formal_id=identity.get('formal_id') or formal_id,
                source_id=identity.get('source_question_id') or source_id,
                capture_id=pending_capture_id,
                sequences=pending_sequences, hint_sequences=pending_hint_sequences,
                spans=pending_spans, whole_capture=pending_whole_capture,
                concepts=[r.get('concept_name', '') for r in native.get('records', [])] + original_concepts,
                view=view, valid_at=valid_at, known_at=known_at, max_bytes=min(3000, max_bytes // 3))
            if len(pending.get('records',[]))>1 and not pending_capture_id:
                pending.update(status='ambiguous_pending_records',record_selection_status='ambiguous',
                               not_a_unique_current_record=True)
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
            pending = {'status': 'unavailable', 'records': [], 'reason': type(exc).__name__}
    elif include_pending:
        pending = {'status':'unresolved_scope','records':[], 'reason':'pending_requires_exact_saved_identity'}
    # References preserve existing complete teaching fields without copying them
    # into an extra envelope and spending the same token budget twice.
    context = {'schema': SCHEMA, 'view': view, 'levels': _levels(native, view),
               'personal_judgments': lifecycle, 'pending_evidence': pending,
               'personal_records':personal_records, 'record_query':bool(scope.get('personal_requested')),
               'utterance_lookup':source_lookup,
               'retrieval': retrieval, 'temporal': {'valid_at': valid_at, 'known_at': known_at},
               'roles': {'knowledge': 'problem_solving', 'observations': 'records.step_evidence',
                         'preferences': 'records.teaching_preferences',
                         'judgments': 'memory_context.personal_judgments',
                         'unadjudicated': 'memory_context.pending_evidence'},
               'freshness': {'native': native.get('status'), 'judgments': lifecycle.get('status'),
                             'pending': pending.get('status'), 'personal_records':personal_records.get('status')},
               'current_work_overrides_history': True}
    if valid_at or known_at:
        context['temporal']['knowledge_scope'] = 'current_verified_reference_not_historical_personal_state'
        context['historical_evidence'] = historical
        context['freshness']['history'] = historical.get('status')
    if view != 'protected':
        context['scope'] = {'query': query, 'operation': operation}
    if (new_source_point_context and native.get('status') in ('available', 'source_based')
            and (native.get('identity') or {}).get('kind') == 'new_source'):
        native['source_identity_status'] = 'unmapped'
        native['personal_context_scope'] = 'requested_knowledge_point_not_source_attempt_history'
    query_version = digest([SCHEMA, CONTEXT_REVISION, native.get('version'), native.get('source_version'),
        original_concepts, formal_id, source_id, query, search_query, query_origin, operation, view, valid_at, known_at,
        include_pending, structured_math, point_records, pending_capture_id, pending_sequences, pending_hint_sequences,
        pending_spans, pending_whole_capture, config_identity, max_bytes, lifecycle, pending, retrieval, historical,
        scope, personal_records,source_lookup])
    native.update(version=query_version, memory_context=context)
    if native.get('status') == 'stale':
        native['lookup_refresh'] = {'status': 'required', 'attempts': 0, 'query_is_read_only': True}
    reusable = (native.get('status') in ('available', 'source_based')
                and lifecycle.get('status') not in ('unavailable', 'stale')
                and pending.get('status') not in ('stale', 'unavailable')
                and historical.get('status') not in ('stale', 'unavailable')
                and not invalidated)
    delivered = _bound(native, max_bytes)
    if known_version == query_version and reusable:
        from math_teaching_delivery import has_delivery_gap
        if not has_delivery_gap(delivered):
            return {'status': 'unchanged', 'version': query_version, 'source_version': native.get('source_version'),
                    'view': view, 'identity': delivered.get('identity'), 'records': [],
                    'memory_context': {'schema': SCHEMA, 'status': 'unchanged'}}
    return delivered
