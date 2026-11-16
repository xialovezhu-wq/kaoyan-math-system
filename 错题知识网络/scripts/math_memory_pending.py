"""Derived, role-preserving access to saved but uncurated math conversations.

Only ``refresh_pending`` writes this disposable projection. Queries neither
repair it nor change Capture/formal/score records. The immutable package and
the existing quick-intake ledger remain the authority.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from zoneinfo import ZoneInfo

BASE = Path('错题知识网络/个人知识点索引/待整理证据')
INDEX = BASE / 'index.json'
LEDGER = Path('数学一回滚复习系统/快速入库事件.jsonl')
SCHEMA = 'math-pending-memory-v1'
MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
_WRITER = None


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def stamp(path):
    try:
        s = path.stat()
        return [s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino]
    except FileNotFoundError:
        return None


def _path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('pending_source_outside_repository')
    target = root / relative
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError('pending_source_outside_repository')
    return target


def _read(root, ref):
    path = _path(root, ref['path'])
    if not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError('pending_source_missing_or_too_large')
    before = stamp(path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref['sha256'] or stamp(path) != before:
        raise ValueError('pending_source_changed')
    return json.loads(raw), before


def _writer():
    global _WRITER
    if _WRITER is None:
        path = Path(__file__).resolve().parents[2] / '数学一回滚复习系统/scripts/quick_intake.py'
        if str(path.parent) not in sys.path:
            sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location('_math_memory_pending_writer', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _WRITER = module
    return _WRITER


@contextmanager
def _lock(root):
    directory = _path(root, BASE)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / '.projection.lock'
    if lock.is_symlink():
        raise ValueError('pending_projection_unsafe')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic(path, value):
    data = (canonical(value) + '\n').encode()
    if path.exists() and path.read_bytes() == data:
        return False
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def _load_index(root):
    path = _path(root, INDEX)
    if not path.is_file():
        return None
    value = json.loads(path.read_text())
    if value.get('schema') != SCHEMA or not isinstance(value.get('entries'), list):
        raise ValueError('pending_projection_invalid')
    if value.get('version') != digest(value['entries']):
        raise ValueError('pending_projection_hash_mismatch')
    return value


def _project(root, capture, amendments):
    qi = _writer()
    item = qi.pending_item(capture, amendments)
    bundle = item.get('conversation_package') or item.get('source_bundle') or {}
    result = {'capture_id': capture['event_id'], 'capture_sha256': capture['content_hash'],
              'study_date': capture['study_date'], 'recorded_at': capture['recorded_at'],
              'formal_id': item.get('formal_id'), 'package_id': bundle.get('package_id'),
              'basis': 'raw_unadjudicated', 'is_mastery_evidence': False,
              'amendment_ids': item.get('amendment_event_ids', [])}
    if not bundle.get('package_id'):
        return {**result, 'status': 'legacy_no_conversation', 'turns': []}
    ref = {'path': bundle['manifest_path'], 'sha256': bundle['manifest_hash']}
    manifest, manifest_stamp = _read(root, ref)
    if (manifest.get('package_id') != bundle['package_id']
            or manifest.get('canonical_sha256') != bundle.get('package_sha256')
            or manifest.get('study_date') != capture['study_date']
            or manifest.get('subject') != 'math'):
        raise ValueError('pending_package_binding_mismatch')
    source_identity = manifest.get('source_identity', {})
    if source_identity.get('capture_identity') not in (None, capture['attempt_id']):
        raise ValueError('pending_capture_identity_mismatch')
    conversation_ref = manifest['files']['conversation']
    conversation, conversation_stamp = _read(root, conversation_ref)
    if conversation.get('package_id') != manifest['package_id'] or conversation.get('subject') != 'math':
        raise ValueError('pending_conversation_identity_mismatch')
    turns = conversation.get('turns')
    if not isinstance(turns, list) or not turns:
        raise ValueError('pending_conversation_missing')
    for position, turn in enumerate(turns, 1):
        if (turn.get('role') not in ('user', 'assistant')
                or turn.get('sequence') != position or not isinstance(turn.get('text'), str)):
            raise ValueError('pending_conversation_roles_invalid')
    return {**result, 'status': 'ready', 'source_question_id': source_identity.get('question_id'),
            'turns': turns, 'source_ref': conversation_ref,
            'manifest_ref': ref, 'source_stamps': {
                ref['path']: manifest_stamp, conversation_ref['path']: conversation_stamp},
            'artifacts': manifest.get('artifacts', []),
            'missing_attachments': manifest.get('missing_fields', []),
            'search_text': '\n'.join(t['text'] for t in turns if t['role'] == 'user')}


def refresh_pending(repo_root, capture_id=None):
    """Incrementally refresh changed pending packages from the verified ledger.

    A completed Capture is never replayed. Existing unchanged package projections
    are reused. Closed captures are removed even when their archive is offline.
    """
    root = Path(repo_root).resolve()
    ledger = _path(root, LEDGER)
    qi = _writer()
    with _lock(root):
        before = stamp(ledger)
        events = qi.load_jsonl(ledger)
        state = qi.replay(events)
        if capture_id and capture_id not in state['captures']:
            raise ValueError('pending_capture_unknown')
        old = _load_index(root)
        old_rows = {r['capture_id']: r for r in (old or {}).get('entries', [])}
        rows, changed_ids, failures = [], [], []
        for cid, capture in state['captures'].items():
            if cid in state['closed_by']:
                continue
            amendments = state['amendments'][cid]
            previous = old_rows.get(cid)
            reusable = (previous and previous.get('status') == 'ready'
                        and previous.get('capture_sha256') == capture['content_hash']
                        and previous.get('amendment_ids') == [a['event_id'] for a in amendments]
                        and all(stamp(_path(root, p)) == s for p, s in previous.get('source_stamps', {}).items()))
            if reusable:
                row = previous
            else:
                try:
                    row = _project(root, capture, amendments)
                except (OSError, KeyError, ValueError, TypeError) as exc:
                    row = {'capture_id': cid, 'capture_sha256': capture['content_hash'],
                           'study_date': capture['study_date'], 'recorded_at': capture['recorded_at'],
                           'formal_id': capture.get('target', {}).get('formal_id'),
                           'status': 'source_unavailable', 'reason': type(exc).__name__,
                           'basis': 'raw_unadjudicated', 'is_mastery_evidence': False, 'turns': []}
                    failures.append(cid)
                changed_ids.append(cid)
            rows.append(row)
        if stamp(ledger) != before:
            raise ValueError('pending_ledger_changed_during_refresh')
        rows.sort(key=lambda r: (r['study_date'], r['recorded_at'], r['capture_id']))
        value = {'schema': SCHEMA, 'ledger_stamp': before, 'entries': rows, 'version': digest(rows)}
        changed = _atomic(_path(root, INDEX), value)
    return {'status': 'partial' if failures else 'ready' if changed else 'noop',
            'version': value['version'], 'pending_count': len(rows), 'updated_capture_ids': changed_ids,
            'removed_closed_count': len(set(old_rows) - {r['capture_id'] for r in rows}),
            'unavailable_capture_ids': failures, 'projection_path': str(INDEX),
            'formal_write_count': 0, 'score_write_count': 0, 'model_call_count': 0}


def refresh_capture(repo_root, capture_id):
    return refresh_pending(repo_root, capture_id=capture_id)


def _cutoff(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('invalid_memory_time')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        date.fromisoformat(value)
        return value + 'T23:59:59.999999+08:00'
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('memory_time_requires_timezone')
    return parsed.astimezone(ZoneInfo('Asia/Shanghai')).isoformat()


def _before(value, cutoff):
    if cutoff is None:
        return True
    if not value:
        return False
    if len(value) == 10:
        return value <= cutoff[:10]
    return datetime.fromisoformat(value.replace('Z', '+00:00')) <= datetime.fromisoformat(cutoff)


def _terms(query, concepts):
    texts = [query or '', *(concepts or [])]
    terms = []
    for text in texts:
        if not isinstance(text, str) or text.startswith('MATH-CONCEPT-'):
            continue
        for token in re.findall(r'[A-Za-z0-9_-]{3,}|[\u3400-\u9fff]{2,}', text.casefold()):
            terms.append(token)
            if len(token) > 3 and re.search(r'[\u3400-\u9fff]', token):
                terms.extend(token[i:i+2] for i in range(len(token)-1))
    return list(dict.fromkeys(terms))[:40]


def validate_selection(sequences=None, hint_sequences=None, spans=None, whole_capture=False):
    """Explicit message selections authorize complete messages, not keywords.

    Spans use Python Unicode-character offsets, with an exclusive end. Callers
    must already know that the selected text belongs to the unlocked subquestion;
    uncertain boundaries are a locator-only request, never an inferred scope.
    """
    if type(whole_capture) is not bool:
        raise ValueError('pending_whole_capture_must_be_boolean')
    groups = []
    for values in (sequences, hint_sequences):
        values = [] if values is None else values
        if (not isinstance(values, (list, tuple)) or len(values) > 128
                or any(type(n) is not int or n < 1 for n in values)
                or len(values) != len(set(values))):
            raise ValueError('pending_sequences_must_be_unique_positive_integers')
        groups.append(sorted(values))
    user, hints = groups
    if set(user) & set(hints):
        raise ValueError('pending_sequence_role_conflict')
    spans = [] if spans is None else spans
    if not isinstance(spans, (list, tuple)) or len(spans) > 128:
        raise ValueError('pending_spans_must_be_bounded_array')
    selected_spans = []
    for span in spans:
        if (not isinstance(span, dict) or set(span) != {'sequence', 'start', 'end'}
                or any(type(span[k]) is not int for k in span)
                or span['sequence'] < 1 or span['start'] < 0 or span['end'] <= span['start']):
            raise ValueError('pending_span_invalid')
        if span['sequence'] in user or span['sequence'] in hints:
            raise ValueError('pending_span_and_whole_message_conflict')
        if any(old['sequence'] == span['sequence'] and max(old['start'], span['start']) < min(old['end'], span['end'])
               for old in selected_spans):
            raise ValueError('pending_spans_overlap')
        selected_spans.append(dict(span))
    selected_spans.sort(key=lambda s: (s['sequence'], s['start'], s['end']))
    if whole_capture and (user or hints or selected_spans):
        raise ValueError('pending_whole_capture_and_partial_scope_conflict')
    return user, hints, selected_spans


def query_pending(repo_root, query='', *, formal_id=None, source_id=None, capture_id=None, concepts=None,
                  view='protected', valid_at=None, known_at=None, limit=3, max_bytes=3000,
                  sequences=None, hint_sequences=None, spans=None, whole_capture=False):
    """Locate saved turns; raw text needs direct view and an explicit text scope."""
    if view not in ('protected', 'after_attempt', 'direct') or not 1 <= limit <= 10:
        raise ValueError('invalid_pending_query')
    valid, known = _cutoff(valid_at), _cutoff(known_at)
    selected_users, selected_hints, selected_spans = validate_selection(
        sequences, hint_sequences, spans, whole_capture)
    explicit_scope = bool(selected_users or selected_hints or selected_spans or whole_capture)
    root = Path(repo_root).resolve()
    base = {'status': 'not_indexed', 'records': [], 'basis': 'raw_unadjudicated',
            'is_mastery_evidence': False, 'view': view, 'omitted_turns': 0}
    if view == 'after_attempt':
        base['raw_text_status'] = 'raw_text_requires_direct_view'
    elif view == 'direct' and not (formal_id or source_id or capture_id):
        base['raw_text_status'] = 'raw_text_requires_exact_identity'
    elif view == 'direct' and not explicit_scope:
        base['raw_text_status'] = 'raw_text_requires_explicit_turn_scope'
    if valid_at or known_at:
        base['history_scope'] = 'current_unclosed_captures_only'
        base['history_gaps'] = ['historical_pending_membership_not_reconstructed']
        base['known_at_semantics'] = 'capture_recorded_at_not_formal_adjudication_time'
    # Protection is checked before opening the raw projection, including a
    # request that carries an accidentally overbroad direct-text selection.
    if view == 'protected':
        return {**base, 'status': 'protected', 'version': digest([SCHEMA, 'protected'])}
    projection = _load_index(root)
    if projection is None:
        return base
    base['version'] = projection['version']
    if projection['ledger_stamp'] != stamp(_path(root, LEDGER)):
        return {**base, 'status': 'stale', 'reason': 'pending_projection_refresh_required'}
    unsearchable = sum(row.get('status') != 'ready' for row in projection['entries'])
    base['coverage'] = {'pending_total': len(projection['entries']),
                        'catalog_unsearchable_count': unsearchable}
    terms = _terms(query, concepts)
    if not formal_id and not source_id and not capture_id and not terms:
        return {**base, 'status': 'scope_required'}
    ranked = []
    for row in projection['entries']:
        if capture_id and row.get('capture_id') != capture_id:
            continue
        if formal_id and row.get('formal_id') != formal_id:
            continue
        if source_id and row.get('source_question_id') != source_id:
            continue
        if not _before(row.get('study_date'), valid) or not _before(row.get('recorded_at'), known):
            continue
        text = row.get('search_text', '').casefold()
        score = sum(len(t) for t in terms if t in text)
        if not formal_id and not source_id and not capture_id and not score:
            continue
        ranked.append((score, row))
    ranked.sort(key=lambda pair: (pair[0], pair[1]['study_date'], pair[1]['recorded_at']), reverse=True)
    unavailable = 0
    base['status'] = 'available'
    for _, row in ranked[:limit]:
        if row.get('status') != 'ready':
            unavailable += 1
            continue
        try:
            conversation, _ = _read(root, row['source_ref'])
            manifest, _ = _read(root, row['manifest_ref'])
        except (OSError, KeyError, ValueError, TypeError):
            unavailable += 1
            continue
        turns = conversation['turns']
        by_sequence = {t['sequence']: t for t in turns}
        exact_identity = bool(formal_id or source_id or capture_id)
        unique_capture = bool(capture_id) or exact_identity and len(ranked) == 1
        allow_raw = view == 'direct' and exact_identity and unique_capture and explicit_scope
        scope_problem = None
        if allow_raw and not whole_capture:
            if any(n not in by_sequence or by_sequence[n]['role'] != 'user' for n in selected_users):
                scope_problem = 'pending_user_sequence_not_found_or_role_mismatch'
            elif any(n not in by_sequence or by_sequence[n]['role'] != 'assistant' for n in selected_hints):
                scope_problem = 'pending_hint_sequence_not_found_or_role_mismatch'
            elif any(s['sequence'] not in by_sequence or s['end'] > len(by_sequence[s['sequence']]['text'])
                     for s in selected_spans):
                scope_problem = 'pending_span_outside_message'
            if scope_problem:
                allow_raw = False
        if allow_raw:
            chosen = set(selected_users) | set(selected_hints) | {s['sequence'] for s in selected_spans}
            matched = [t for t in turns if whole_capture or t['sequence'] in chosen]
        else:
            matched = [t for t in turns if t['role'] == 'user' and (exact_identity
                       or any(term in t['text'].casefold() for term in terms))]
        # The parent evidence remains complete; bounded replies omit whole turns.
        item = {k: row[k] for k in ('capture_id', 'package_id', 'study_date', 'recorded_at',
                'formal_id', 'source_question_id', 'basis', 'is_mastery_evidence') if k in row}
        raw_status = ('available' if allow_raw else 'raw_text_scope_invalid' if scope_problem
                      else 'raw_text_requires_direct_view' if view != 'direct'
                      else 'raw_text_requires_exact_identity' if not exact_identity
                      else 'raw_text_requires_exact_capture' if not unique_capture
                      else 'raw_text_requires_explicit_turn_scope')
        item.update(source_ref=row['source_ref'], user_turns=[],
                    requires_scope_check=not exact_identity,
                    hint_dependence='unadjudicated_do_not_infer_independence',
                    raw_text_status=raw_status)
        if scope_problem:
            item['scope_problem'] = scope_problem
        if allow_raw:
            item['raw_scope'] = {'capture_id': row['capture_id'], 'package_sha256': manifest['canonical_sha256'],
                                 'user_sequences': selected_users, 'hint_sequences': selected_hints,
                                 'spans': selected_spans, 'whole_capture': whole_capture}
            item['hint_turns'] = []
        if allow_raw and whole_capture:
            item['attachment_refs'] = [{'role': a['role'], 'path': a['path'], 'sha256': a['sha256']}
                                      for a in row.get('artifacts', [])]
        else:
            item['attachment_roles'] = [a['role'] for a in row.get('artifacts', [])]
            item['attachment_scope'] = 'requires_separate_authorized_binding'
        base['records'].append(item)
        for turn in matched:
            projected = dict(turn) if allow_raw else {'sequence': turn['sequence'], 'role': 'user',
                'text_sha256': hashlib.sha256(turn['text'].encode()).hexdigest(),
                'text_status': item['raw_text_status']}
            preceding = [t for t in turns if t['role'] == 'assistant' and t['sequence'] < turn['sequence']]
            projected['preceding_assistant_sequences'] = [t['sequence'] for t in preceding]
            turn_spans = [s for s in selected_spans if s['sequence'] == turn['sequence']]
            pieces = []
            if allow_raw and turn_spans:
                for span in turn_spans:
                    pieces.append({**projected, 'text': turn['text'][span['start']:span['end']],
                                   'character_range': [span['start'], span['end']],
                                   'whole_message': False,
                                   'message_text_sha256': hashlib.sha256(turn['text'].encode()).hexdigest()})
            else:
                pieces.append({**projected, **({'whole_message': True} if allow_raw else {})})
            target = 'hint_turns' if allow_raw and turn['role'] == 'assistant' else 'user_turns'
            for piece in pieces:
                item[target].append(piece)
                if len(canonical(base).encode()) > max_bytes:
                    item[target].pop()
                    base['omitted_turns'] += 1
        if not item['user_turns'] and not item.get('hint_turns'):
            base['records'].pop()
    if unavailable:
        base.update(status='partial', unavailable_count=unavailable)
    elif unsearchable:
        base.update(status='partial', reason='some_pending_sources_are_not_searchable')
    if len(canonical(base).encode()) > max_bytes:
        return {'status': 'budget_too_small', 'records': [], 'version': projection['version'],
                'basis': 'raw_unadjudicated', 'is_mastery_evidence': False}
    return base


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    sub = parser.add_subparsers(dest='command', required=True)
    refresh = sub.add_parser('refresh')
    refresh.add_argument('--capture-id')
    args = parser.parse_args(argv)
    result = refresh_pending(args.repo, capture_id=args.capture_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in ('ready', 'noop') else 1


if __name__ == '__main__':
    raise SystemExit(main())
