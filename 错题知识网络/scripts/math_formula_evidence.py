"""Immutable, single-question formula presentation evidence.

This is presentation provenance, never an answer, grade, view count or mastery
event. A native confirmation proves rendering of the current question, not that
the learner read every card. No function in this module launches a window.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

BASE = Path('.private/formula-display/evidence')
SNAPSHOT_SCHEMA = 'math-formula-display-snapshot-v1'
OBSERVATION_SCHEMA = 'math-formula-display-observation-v1'
BUNDLE_SCHEMA = 'math-formula-capture-evidence-v1'
ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$')
SESSION = re.compile(r'^MATH-FORMULA-[A-Za-z0-9][A-Za-z0-9_-]{0,86}$')
SHA = re.compile(r'^[0-9a-f]{64}$')
MAX_BYTES = 16 * 1024 * 1024


class EvidenceError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _identifier(value, field):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise EvidenceError('formula_evidence_identity_invalid:' + field)
    return value


def normalize_context(value, *, required=False):
    if value is None:
        if required:
            raise EvidenceError('formula_evidence_capture_context_required')
        return None
    allowed = {'session_ref', 'attempt_id', 'start_line', 'queue_id', 'item_id', 'source_locator'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise EvidenceError('formula_evidence_capture_context_invalid')
    result = {key: item for key, item in value.items() if item is not None}
    _identifier(result.get('session_ref'), 'session_ref')
    for key in ('attempt_id', 'queue_id', 'item_id'):
        if key in result:
            _identifier(result[key], key)
    if 'source_locator' in result and (not isinstance(result['source_locator'], str)
            or not result['source_locator'].strip() or len(result['source_locator']) > 1000
            or any(ord(c) < 32 for c in result['source_locator'])):
        raise EvidenceError('formula_evidence_source_locator_invalid')
    if 'start_line' in result and (type(result['start_line']) is not int or result['start_line'] < 1):
        raise EvidenceError('formula_evidence_start_line_invalid')
    if 'attempt_id' not in result and 'start_line' not in result:
        raise EvidenceError('formula_evidence_attempt_or_start_boundary_required')
    if ('queue_id' in result) != ('item_id' in result):
        raise EvidenceError('formula_evidence_queue_and_item_required_together')
    return result


def context_key(session_id, question_id, context):
    if not isinstance(session_id, str) or not SESSION.fullmatch(session_id):
        raise EvidenceError('formula_evidence_display_session_invalid')
    _identifier(question_id, 'question_id')
    context = normalize_context(context)
    return digest({'session_id': session_id, 'question_id': question_id, 'capture_context': context})


def _guard_path(path, root):
    path, root = Path(path), Path(root).resolve()
    if not path.is_relative_to(root) or any(p.is_symlink() for p in (path, *path.parents)):
        raise EvidenceError('formula_evidence_path_invalid')
    return path


def _read(path, root):
    path = _guard_path(path, root)
    if path.stat().st_size > MAX_BYTES:
        raise EvidenceError('formula_evidence_too_large')
    data = path.read_bytes()
    value = json.loads(data)
    if canonical(value) + b'\n' != data:
        raise EvidenceError('formula_evidence_noncanonical_or_changed')
    return value


def _write_once(path, value, root):
    path = _guard_path(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _read(path, root) != value:
            raise EvidenceError('formula_evidence_immutable_conflict')
        return
    data = canonical(value) + b'\n'
    if len(data) > MAX_BYTES:
        raise EvidenceError('formula_evidence_too_large')
    fd, temporary = tempfile.mkstemp(prefix='.evidence-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, 0o400)
        # link is an atomic create-if-absent, unlike replacing an immutable file.
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _read(path, root) != value:
                raise EvidenceError('formula_evidence_immutable_conflict')
    finally:
        os.unlink(temporary)


def _validate_snapshot(value):
    required = {'schema', 'snapshot_id', 'session_id', 'question_id', 'capture_context', 'context_key',
                'display_revision', 'state_revision', 'stage', 'hint_level', 'registry_version',
                'question', 'prepared_at', 'source_state_sha256'}
    if not isinstance(value, dict) or set(value) != required or value.get('schema') != SNAPSHOT_SCHEMA:
        raise EvidenceError('formula_evidence_snapshot_schema_invalid')
    if value['snapshot_id'] != digest({k: v for k, v in value.items() if k != 'snapshot_id'}):
        raise EvidenceError('formula_evidence_snapshot_hash_mismatch')
    if value['context_key'] != context_key(value['session_id'], value['question_id'], value['capture_context']):
        raise EvidenceError('formula_evidence_context_key_mismatch')
    for key in ('display_revision', 'state_revision', 'source_state_sha256'):
        if not isinstance(value.get(key), str) or not SHA.fullmatch(value[key]):
            raise EvidenceError('formula_evidence_revision_invalid')
    if value['stage'] not in {'question', 'hint', 'solution'} or value['hint_level'] not in {0, 1}:
        raise EvidenceError('formula_evidence_stage_invalid')
    if value['stage'] == 'hint' and value['hint_level'] != 1:
        raise EvidenceError('formula_evidence_hint_invalid')
    question = value['question']
    if (not isinstance(question, dict) or question.get('question_id') != value['question_id']
            or question.get('stage') != value['stage'] or not isinstance(question.get('formulas'), list)):
        raise EvidenceError('formula_evidence_question_mismatch')
    if value['stage'] == 'question' and question['formulas']:
        raise EvidenceError('formula_evidence_protected_content')
    dt.datetime.fromisoformat(value['prepared_at'])


def prepare(root, state):
    """Seal a current-question slice; preparation is not native display."""
    root = Path(root).resolve()
    if state.get('state_revision') != digest({k: v for k, v in state.items() if k not in {'state_revision', 'updated_at'}}):
        raise EvidenceError('formula_evidence_state_hash_mismatch')
    qid = state['current_question_id']
    matches = [q for q in state['questions'] if q.get('question_id') == qid]
    if len(matches) != 1:
        raise EvidenceError('formula_evidence_current_question_missing')
    context = normalize_context(state.get('capture_context'))
    key = context_key(state['session_id'], qid, context)
    path = root / BASE / 'snapshots' / key / (state['state_revision'] + '.json')
    stable = {'schema': SNAPSHOT_SCHEMA, 'session_id': state['session_id'], 'question_id': qid,
              'capture_context': context, 'context_key': key, 'display_revision': state['display_revision'],
              'state_revision': state['state_revision'], 'stage': state['stage'], 'hint_level': state['hint_level'],
              'registry_version': state.get('registry_version'), 'question': copy.deepcopy(matches[0]),
              'source_state_sha256': hashlib.sha256(canonical({k: v for k, v in state.items() if k != 'updated_at'})).hexdigest()}
    if path.exists():
        saved = _read(path, root); _validate_snapshot(saved)
        if any(saved[k] != v for k, v in stable.items()):
            raise EvidenceError('formula_evidence_same_revision_changed')
    else:
        if (root / BASE / 'frozen' / (key + '.json')).exists():
            raise EvidenceError('formula_evidence_context_already_closed_use_new_boundary')
        saved = {**stable, 'prepared_at': state['updated_at']}
        saved['snapshot_id'] = digest(saved)
        _validate_snapshot(saved); _write_once(path, saved, root)
    return {'snapshot_path': str(path), 'snapshot_sha256': file_sha(path),
            'snapshot_id': saved['snapshot_id'], 'context_key': key,
            'capture_bound': context is not None, 'presentation_state': 'prepared_only'}


def native_confirmation_matches(snapshot, receipt):
    """Match the inspected native render, including its actually selected question."""
    try:
        _validate_snapshot(snapshot)
        metrics = receipt.get('formula_rendering', {})
        prepared = dt.datetime.fromisoformat(snapshot['prepared_at']).timestamp()
        request_id = digest({'schema': 'study-visual-screen-request-v1', 'action': 'show',
                             'viewer_kind': 'math_formulas', 'target_display_name': 'OpenDisplay — iPad',
                             'question_id': snapshot['session_id'], 'stage': snapshot['stage'],
                             'hint_level': snapshot['hint_level'], 'lesson_revision': snapshot['display_revision'],
                             'viewer_url': f"http://127.0.0.1:8769/study-formulas/{snapshot['session_id']}?revision={snapshot['display_revision']}"})
        return (receipt.get('schema') == 'study-visual-screen-status-v1'
                and receipt.get('request_id') == request_id
                and receipt.get('status') == 'shown' and receipt.get('shown') is True
                and receipt.get('window_opened') is True and receipt.get('inspected_ready') is True
                and receipt.get('viewer_kind') == 'math_formulas'
                and receipt.get('target_display_name') == 'OpenDisplay — iPad'
                and receipt.get('question_id') == snapshot['session_id']
                and receipt.get('lesson_revision') == snapshot['display_revision']
                and receipt.get('stage') == snapshot['stage']
                and receipt.get('hint_level') == snapshot['hint_level']
                and isinstance(receipt.get('written_at'), (int, float)) and not isinstance(receipt.get('written_at'), bool)
                and receipt['written_at'] >= prepared
                and metrics.get('state_revision') == snapshot['state_revision']
                and metrics.get('current_question_id') == snapshot['question_id']
                and metrics.get('displayed_question_id') == snapshot['question_id']
                and metrics.get('math_ready') is True
                and type(metrics.get('render_error_count')) is int and metrics['render_error_count'] == 0
                and type(metrics.get('raw_latex_text_count')) is int and metrics['raw_latex_text_count'] == 0
                and metrics.get('latest_update_rejected') is not True
                and metrics.get('rejected_state_revision') is None)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def observe(root, snapshot_reference, *, status, reason='', native_receipt=None):
    root = Path(root).resolve()
    path = Path(snapshot_reference['snapshot_path'])
    snapshot = _read(path, root); _validate_snapshot(snapshot)
    if file_sha(path) != snapshot_reference['snapshot_sha256']:
        raise EvidenceError('formula_evidence_snapshot_changed')
    if status not in {'displayed', 'deferred', 'not_installed', 'rejected', 'unconfirmed'}:
        raise EvidenceError('formula_evidence_observation_status_invalid')
    if status == 'displayed' and not native_confirmation_matches(snapshot, native_receipt):
        raise EvidenceError('formula_evidence_native_confirmation_mismatch')
    key = snapshot['context_key']
    if (root / BASE / 'frozen' / (key + '.json')).exists():
        return {'status': 'evidence_already_frozen', 'observation_saved': False}
    # First confirmation/status is immutable. Heartbeat timestamps do not add
    # another observation or change an already frozen Capture attachment.
    stable = {'snapshot_id': snapshot['snapshot_id'], 'snapshot_sha256': file_sha(path), 'status': status,
              'reason': reason if status != 'displayed' else 'native_current_question_render_confirmed'}
    out = root / BASE / 'observations' / key / (snapshot['snapshot_id'] + '-' + digest(stable) + '.json')
    if out.exists():
        value = _read(out, root)
        if any(value.get(k) != v for k, v in stable.items()):
            raise EvidenceError('formula_evidence_observation_path_binding_invalid')
    else:
        value = {'schema': OBSERVATION_SCHEMA, **stable, 'observed_at': now(),
                 'native_receipt': copy.deepcopy(native_receipt) if status == 'displayed' else None,
                 'native_receipt_sha256': digest(native_receipt) if status == 'displayed' else None}
        value['observation_id'] = digest(value)
        _write_once(out, value, root)
    _validate_observation(value, snapshot, stable['snapshot_sha256'])
    return {'status': status, 'observation_saved': True, 'observation_path': str(out),
            'observation_sha256': file_sha(out), 'observation_id': value['observation_id']}


def _validate_observation(value, snapshot, snapshot_sha256):
    fields = {'schema', 'snapshot_id', 'snapshot_sha256', 'status', 'reason', 'observed_at',
              'native_receipt', 'native_receipt_sha256', 'observation_id'}
    if (not isinstance(value, dict) or set(value) != fields or value.get('schema') != OBSERVATION_SCHEMA
            or value['snapshot_id'] != snapshot['snapshot_id'] or value['snapshot_sha256'] != snapshot_sha256
            or value['observation_id'] != digest({k: v for k, v in value.items() if k != 'observation_id'})):
        raise EvidenceError('formula_evidence_observation_hash_or_identity_invalid')
    if value['status'] == 'displayed':
        if value['native_receipt_sha256'] != digest(value['native_receipt']) or not native_confirmation_matches(snapshot, value['native_receipt']):
            raise EvidenceError('formula_evidence_native_confirmation_mismatch')
    elif value['status'] not in {'deferred', 'not_installed', 'rejected', 'unconfirmed'} or value['native_receipt'] is not None or value['native_receipt_sha256'] is not None:
        raise EvidenceError('formula_evidence_observation_status_invalid')


def validate_bundle_bytes(data, *, session_ref=None, question_ids=None, attempt_id=None,
                          start_line=None, queue_id=None, item_id=None, source_locator=None, expected_sha256=None):
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise EvidenceError('formula_capture_evidence_size_invalid')
    actual_sha = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and actual_sha != expected_sha256:
        raise EvidenceError('formula_capture_evidence_file_hash_mismatch')
    value = json.loads(data.decode('utf-8'))
    fields = {'schema', 'bundle_sha256', 'session_id', 'question_id', 'capture_context', 'context_key',
              'records', 'counts', 'confirmation_scope', 'evidence_grain', 'learning_write_count', 'score_write_count'}
    if (not isinstance(value, dict) or set(value) != fields or value.get('schema') != BUNDLE_SCHEMA
            or value.get('bundle_sha256') != digest({k: v for k, v in value.items() if k != 'bundle_sha256'})
            or canonical(value) + b'\n' != data):
        raise EvidenceError('formula_capture_evidence_schema_or_hash_invalid')
    context = normalize_context(value['capture_context'], required=True)
    if value['context_key'] != context_key(value['session_id'], value['question_id'], context):
        raise EvidenceError('formula_capture_evidence_context_key_mismatch')
    if session_ref is not None and context['session_ref'] != session_ref:
        raise EvidenceError('formula_capture_evidence_session_mismatch')
    if question_ids is not None:
        if question_ids and value['question_id'] not in set(question_ids):
            raise EvidenceError('formula_capture_evidence_question_mismatch')
        if not question_ids and (not context.get('source_locator') or context['source_locator'] != source_locator):
            raise EvidenceError('formula_capture_evidence_source_locator_required')
    if session_ref is not None and 'source_locator' in context and context['source_locator'] != source_locator:
        raise EvidenceError('formula_capture_evidence_source_locator_mismatch')
    for field, expected in [('attempt_id', attempt_id), ('start_line', start_line), ('queue_id', queue_id), ('item_id', item_id)]:
        # Capture callers pass real values. Both supplied boundaries must match;
        # a non-queue manual question cannot accept a queue-bound bundle.
        if session_ref is not None and field in context and context[field] != expected:
            raise EvidenceError('formula_capture_evidence_' + field + '_mismatch')
    records = value['records']
    if not isinstance(records, list) or not records or len(records) > 1000:
        raise EvidenceError('formula_capture_evidence_records_invalid')
    ids = set(); displayed = 0
    for row in records:
        if not isinstance(row, dict) or set(row) != {'snapshot', 'snapshot_sha256', 'observations', 'presentation_state'}:
            raise EvidenceError('formula_capture_evidence_record_invalid')
        snapshot = row['snapshot']; _validate_snapshot(snapshot)
        sh = hashlib.sha256(canonical(snapshot) + b'\n').hexdigest()
        if row['snapshot_sha256'] != sh or snapshot['context_key'] != value['context_key'] or snapshot['capture_context'] != context:
            raise EvidenceError('formula_capture_evidence_snapshot_binding_invalid')
        if snapshot['snapshot_id'] in ids:
            raise EvidenceError('formula_capture_evidence_duplicate_snapshot')
        ids.add(snapshot['snapshot_id'])
        observations = row['observations']
        if not isinstance(observations, list) or len(observations) > 32:
            raise EvidenceError('formula_capture_evidence_observations_invalid')
        seen = set(); confirmed = False
        for observation in observations:
            _validate_observation(observation, snapshot, sh)
            if observation['observation_id'] in seen:
                raise EvidenceError('formula_capture_evidence_duplicate_observation')
            seen.add(observation['observation_id'])
            confirmed |= observation['status'] == 'displayed'
        expected = 'native_display_confirmed' if confirmed else 'prepared_only_not_display_confirmed'
        if row['presentation_state'] != expected:
            raise EvidenceError('formula_capture_evidence_presentation_claim_invalid')
        displayed += int(confirmed)
    counts = {'prepared_revisions': len(records), 'display_confirmed_revisions': displayed,
              'prepared_only_revisions': len(records) - displayed}
    if value['counts'] != counts or value['learning_write_count'] != 0 or value['score_write_count'] != 0:
        raise EvidenceError('formula_capture_evidence_counts_or_learning_claim_invalid')
    if (value['confirmation_scope'] != 'native_rendered_current_question;not_every_card_viewed_or_learner_mastery'
            or value['evidence_grain'] != 'distinct_prepared_revisions;not_interaction_or_learning_count'):
        raise EvidenceError('formula_capture_evidence_claim_scope_invalid')
    return value, actual_sha


def freeze(root, session_id, question_id, context):
    root = Path(root).resolve(); context = normalize_context(context, required=True)
    key = context_key(session_id, question_id, context)
    out = root / BASE / 'frozen' / (key + '.json')
    if out.exists():
        value, sh = validate_bundle_bytes(_guard_path(out, root).read_bytes())
        if (value['context_key'] != key or value['session_id'] != session_id
                or value['question_id'] != question_id or value['capture_context'] != context):
            raise EvidenceError('formula_evidence_frozen_context_mismatch')
        return {'status': 'already_frozen', 'path': str(out), 'sha256': sh, 'bundle_sha256': value['bundle_sha256'],
                'counts': value['counts'], 'learning_write_count': 0, 'score_write_count': 0}
    records = []
    snapshot_root = root / BASE / 'snapshots' / key
    for path in sorted(snapshot_root.glob('*.json')):
        snapshot = _read(path, root); _validate_snapshot(snapshot)
        if snapshot['context_key'] != key or snapshot['capture_context'] != context:
            raise EvidenceError('formula_evidence_snapshot_context_mismatch')
        sh = file_sha(path); observations = []
        for observed_path in sorted((root / BASE / 'observations' / key).glob(snapshot['snapshot_id'] + '-*.json')):
            observation = _read(observed_path, root); _validate_observation(observation, snapshot, sh)
            observations.append(observation)
        confirmed = any(x['status'] == 'displayed' for x in observations)
        records.append({'snapshot': snapshot, 'snapshot_sha256': sh, 'observations': observations,
                        'presentation_state': 'native_display_confirmed' if confirmed else 'prepared_only_not_display_confirmed'})
    records.sort(key=lambda r: (r['snapshot']['prepared_at'], r['snapshot']['snapshot_id']))
    if not records:
        raise EvidenceError('formula_evidence_no_bound_question_snapshots')
    confirmed = sum(r['presentation_state'] == 'native_display_confirmed' for r in records)
    value = {'schema': BUNDLE_SCHEMA, 'session_id': session_id, 'question_id': question_id,
             'capture_context': context, 'context_key': key, 'records': records,
             'counts': {'prepared_revisions': len(records), 'display_confirmed_revisions': confirmed,
                        'prepared_only_revisions': len(records) - confirmed},
             'confirmation_scope': 'native_rendered_current_question;not_every_card_viewed_or_learner_mastery',
             'evidence_grain': 'distinct_prepared_revisions;not_interaction_or_learning_count',
             'learning_write_count': 0, 'score_write_count': 0}
    value['bundle_sha256'] = digest(value)
    validate_bundle_bytes(canonical(value) + b'\n')
    _write_once(out, value, root)
    return {'status': 'frozen', 'path': str(out), 'sha256': file_sha(out), 'bundle_sha256': value['bundle_sha256'],
            'counts': value['counts'], 'learning_write_count': 0, 'score_write_count': 0}
