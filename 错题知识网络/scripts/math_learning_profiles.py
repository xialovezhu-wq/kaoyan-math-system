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
from functools import lru_cache
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
PREFERENCE_BASES = {'explicit_preference', 'observed_helpful', 'familiar_route'}
PREFERENCE_FOCUS = {'explanation', 'method', 'both'}
PREFERENCE_FOCUS_TEXT = {'explanation': '讲法', 'method': '解法', 'both': '讲法与解法'}
ANSWER_MARKER = re.compile(
    r'标准答案|正确答案|最终答案|最终结果|答案\s*(?:为|是|[:：])|(?:故|应|只)选\s*[A-DＡ-Ｄ]|\\boxed|answer\s*[:=]',
    re.I)


def _verified_solution_connections(row, concept_names):
    """An ordered solution link has its own sources, not propagated mastery."""
    values = row.get('solution_connections', [])
    if not isinstance(values, list) or len(values) > 8:
        raise ValueError('profile_solution_connections_array_required')
    for link in values:
        if not isinstance(link, dict) or set(link) != {'from', 'to', 'condition', 'handoff', 'source_refs'}:
            raise ValueError('profile_solution_connection_fields')
        start, end = link['from'], link['to']
        if (not isinstance(start, str) or not isinstance(end, str)
                or start == end or start not in concept_names or end not in concept_names
                or row['concept_key'] not in (start, end)
                or any(not isinstance(link[k], str) or not link[k].strip() for k in ('condition', 'handoff'))):
            raise ValueError('profile_solution_connection_scope')
        refs = link['source_refs']
        if not isinstance(refs, list) or not refs or not all(ref in row.get('source_refs', []) for ref in refs):
            raise ValueError('profile_solution_connection_source_required')
    return values


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def evidence_basis(record):
    return digest({k:record.get(k) for k in ('kind','formal_id','summary','history','text')})


def _matches_maintenance_basis(expected, records):
    """Check the original indexed records that prepare_updates actually froze."""
    if not isinstance(expected, dict) or set(expected) != {row['record_id'] for row in records}:
        return False
    for row in records:
        saved = expected[row['record_id']]
        if saved == evidence_basis(row):
            continue
        if row['kind'] == 'formal_concept_observation' and row['summary'].get('recorded_at'):
            # Old snapshots predate the addition of committed time to this
            # projection. Require every other field to match the saved hash.
            legacy = {**row, 'summary': {k: v for k, v in row['summary'].items() if k != 'recorded_at'}}
            if saved == evidence_basis(legacy):
                continue
        return False
    return True


def record_event(record):
    return record.get('summary',{}).get('event_id') or record.get('metadata',{}).get('closeout_id')


def _closeout_source_proof(events, root=None):
    """Only committed closeouts can own newly indexed non-personal sources."""
    artifacts, captures, formal_ids, capture_sources = {}, set(), set(), {}
    for event in events:
        if event.get('event_type') != 'closeout':
            continue
        formal_ids.update(row.get('formal_id') for row in event.get('formal_results', [])
                          if row.get('formal_id'))
        captures.update(row.get('capture_event_id') for row in event.get('capture_results', [])
                        if row.get('capture_event_id'))
        for ref in event.get('verified_artifacts', []):
            if isinstance(ref, dict) and isinstance(ref.get('path'), str) and isinstance(ref.get('sha256'), str):
                artifacts.setdefault(ref['path'], set()).add(ref['sha256'])
        for target in (event.get('concept_observations') or {}).get('targets', []):
            for cid, package in target.get('packages', {}).items():
                for ref in package.get('source_refs', []):
                    if str(ref.get('path', '')).endswith('/manifest.json'):
                        capture_sources.setdefault(cid, set()).add((ref['path'], ref.get('sha256')))
    # A closeout's point observations may cite only the latest supplemental
    # package. The original frozen Capture bindings still authenticate every
    # other package in that same transaction. Never substitute another Capture
    # merely because its artifact also occurs in the batch.
    ledger = root/'数学一回滚复习系统/快速入库事件.jsonl' if root is not None else None
    if ledger is not None and ledger.is_file():
        rows = {}
        try:
            for line in ledger.read_text().split('\n'):
                if not line.strip():
                    continue
                value = json.loads(line)
                rid = value.get('event_id')
                if rid in rows:
                    raise ValueError('duplicate_ledger_identity')
                rows[rid] = value
            def authentic(value, kind):
                return (isinstance(value, dict) and value.get('event_type') == kind
                        and value.get('content_hash') == digest({
                            k: v for k, v in value.items() if k != 'content_hash'}))
            for event in events:
                if event.get('event_type') != 'closeout':
                    continue
                freeze = rows.get(event.get('freeze_id'))
                if not authentic(freeze, 'freeze'):
                    continue
                result_targets = {r.get('capture_event_id'): r.get('formal_id')
                                  for r in event.get('capture_results', [])}
                frozen_targets = {cid: target.get('formal_id')
                                  for target in freeze.get('targets', [])
                                  for cid in target.get('capture_event_ids', [])}
                for snapshot in freeze.get('capture_snapshots', []):
                    cid = snapshot.get('capture_event_id')
                    capture = rows.get(cid)
                    if (cid not in result_targets or frozen_targets.get(cid) != result_targets[cid]
                            or snapshot.get('amendment_event_ids')
                            or not authentic(capture, 'capture')
                            or snapshot.get('capture_content_hash') != capture.get('content_hash')
                            or capture.get('study_date') != freeze.get('study_date')):
                        continue
                    package = capture.get('conversation_package') or {}
                    binding = (package.get('manifest_path'), package.get('manifest_hash'))
                    if binding[1] in artifacts.get(binding[0], set()):
                        capture_sources.setdefault(cid, set()).add(binding)
        except (OSError, ValueError, TypeError, AttributeError):
            # Point-observation proofs above remain valid independently. A bad
            # optional ledger read never grants an additional source exemption.
            pass
    return {'artifacts': artifacts, 'capture_ids': captures, 'formal_ids': formal_ids,
            'capture_sources': capture_sources, 'checked_bytes': {}}


def _owned_closeout_source(root, record, proof):
    """Revalidate an exact derived source, never waive another learner event.

    Source adapters deliberately leave formal_id unset.  Their stable assets,
    Wiki memberships and first-user excerpts appear only after the closeout's
    index refresh, but are not independent evidence arriving after preparation.
    The committed artifact hashes and source bytes establish that distinction.
    """
    kind = record.get('kind')
    if (kind not in ('general_learning_material', 'accepted_conversation_excerpt', 'accepted_capture_reference')
            or record.get('formal_id') is not None
            or record.get('summary') or record.get('history')
            or record.get('association') != 'learning_material_not_personal_error'
            or record.get('not_proof_of_same_error') is not True):
        return False

    def artifact(path, expected):
        if expected not in proof['artifacts'].get(path, set()):
            return None
        identity = (path, expected)
        if identity not in proof['checked_bytes']:
            safe_source(root, {'path': path, 'sha256': expected})
            proof['checked_bytes'][identity] = (root/path).read_bytes()
        return proof['checked_bytes'][identity]

    try:
        refs = record.get('source_refs', [])
        if not refs:
            return False
        for ref in refs:
            safe_source(root, ref)
        meta = record.get('metadata') or {}
        if kind in ('accepted_conversation_excerpt', 'accepted_capture_reference'):
            ids = meta.get('capture_ids')
            if (not isinstance(ids, list) or not ids
                    or not set(ids) <= proof['capture_ids']
                    or meta.get('personal_evidence') is not False
                    or meta.get('conversation_complete') is not True
                    or meta.get('selection') != 'first_complete_user_turn'):
                return False
            binding = (meta.get('original_path'), meta.get('original_sha256'))
            if any(binding not in proof['capture_sources'].get(cid, set()) for cid in ids):
                return False
            raw = artifact(meta.get('original_path'), meta.get('original_sha256'))
            if raw is None:
                return False
            manifest = json.loads(raw)
            descriptor = manifest.get('files', {}).get('conversation', {})
            raw = artifact(descriptor.get('path'), descriptor.get('sha256'))
            if raw is None:
                return False
            turns = json.loads(raw).get('turns', [])
            first = next((turn.get('text') for turn in turns
                          if turn.get('role') == 'user' and isinstance(turn.get('text'), str)
                          and turn['text'].strip()), None)
            if kind == 'accepted_capture_reference':
                # A rejected raw wrong/recurrence request is retained as an
                # empty reference, not promoted into a personal error excerpt.
                # Its exact capture, manifest and conversation are still owned
                # by this committed batch and must not look like outside drift.
                return (first is not None and record.get('text') == ''
                        and meta.get('role') == 'raw_unadjudicated_not_new_wrong_cause'
                        and meta.get('coverage') == 'full_bytes'
                        and meta.get('status') == 'verified')
            return first is not None and record.get('text') == first

        # Native Wiki material rows retain the exact Markdown body; only a
        # cluster actually verified by this closeout may change its membership.
        for ref in refs:
            path = ref['path']
            if path.startswith('错题知识网络/wiki/') and '/knowledge_clusters/' in path:
                raw = artifact(path, ref['sha256'])
                if raw is not None:
                    import wrongnet
                    return record.get('text') == wrongnet.split_front_matter(raw.decode('utf-8'))[1]
        # Binary display sources have no invented semantic/OCR text.  An exact
        # verified path under one of this closeout's final targets is required.
        if record.get('text') != '' or meta.get('personal_evidence') is not False:
            return False
        for ref in refs:
            parts = Path(ref['path']).parts
            if (len(parts) >= 5 and parts[:3] == ('错题知识网络', 'assets', 'visual_wrong_questions')
                    and parts[3] in proof['formal_ids']
                    and artifact(ref['path'], ref['sha256']) is not None):
                return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False
    return False


def _static_reference_for_new_membership(root, record, baseline):
    """A new concept can cause a fresh cache of a previously frozen reference."""
    meta = record.get("metadata") or {}
    if (record.get("kind") != "general_learning_material"
            or record.get("formal_id") is not None or record.get("summary") or record.get("history")
            or record.get("association") != "learning_material_not_personal_error"
            or record.get("not_proof_of_same_error") is not True
            or meta.get("personal_evidence") is not False
            or meta.get("role") != "reference_only_not_mastery"):
        return False
    refs = record.get("source_refs") or []
    prefix = (BASE / "source_cache").as_posix() + "/"
    caches = [ref for ref in refs if ref["path"].startswith(prefix)]
    originals = [ref for ref in refs if not ref["path"].startswith(prefix)]
    if (len(caches) != 1 or not originals
            or not all(baseline.get(ref["path"], {}).get("sha256") == ref["sha256"] for ref in originals)
            or not any((ref["path"], ref["sha256"]) == (meta.get("original_path"), meta.get("original_sha256"))
                       for ref in originals)):
        return False
    try:
        for ref in refs:
            safe_source(root, ref)
        cache = json.loads((root / caches[0]["path"]).read_bytes())
        return (cache.get("source_kind") == "general_learning_material" and cache.get("text") == record.get("text")
                and all(cache.get("metadata", {}).get(key) == meta.get(key)
                        for key in ("original_path", "original_sha256", "personal_evidence", "role")))
    except (OSError, ValueError, TypeError, KeyError):
        return False


def _previously_indexed_capture_reference(root, record, prior_hashes, prior_sources):
    """Allow a late concept link to already frozen, non-personal source text."""
    kind = record.get('kind')
    meta = record.get('metadata') or {}
    refs = record.get('source_refs') or []
    if (kind not in ('accepted_capture_reference', 'accepted_conversation_excerpt')
            or record.get('formal_id') is not None or record.get('summary') or record.get('history')
            or record.get('association') != 'learning_material_not_personal_error'
            or record.get('not_proof_of_same_error') is not True
            or meta.get('personal_evidence') is not False or meta.get('status') != 'verified'
            or evidence_basis(record) not in prior_hashes.get(record.get('record_id'), ())
            or len(refs) != 1):
        return False
    try:
        ref = refs[0]
        path = ref['path']
        if path not in prior_sources or Path(path).parent != BASE / 'source_cache':
            return False
        safe_source(root, ref)
        cache = json.loads((root / path).read_bytes())
        return (cache.get('source_kind') == kind and cache.get('text') == record.get('text')
                and cache.get('metadata') == meta)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


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


def _turn_text(value):
    """Decode message text without treating another role's turn as the user's."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(_turn_text(v) for v in value)
    if isinstance(value, dict):
        return _turn_text(value.get('text', value.get('content', '')))
    return ''


def _role_quote_matches(value, ref, role):
    if isinstance(value, list):
        return any(_role_quote_matches(v, ref, role) for v in value)
    if not isinstance(value, dict):
        return False
    if value.get('role') == role:
        sequence_ok = 'sequence' not in ref or value.get('sequence') == ref['sequence']
        if sequence_ok and ref['quote'] in _turn_text(value):
            return True
        # Do not interpret arbitrary objects embedded inside a turn as new roles.
        return False
    if isinstance(value.get('role'), str) and value['role'] in {'user', 'assistant', 'system', 'developer', 'tool'}:
        return False
    return any(_role_quote_matches(v, ref, role) for v in value.values() if isinstance(v, (list, dict)))


def _user_quote_matches(value, ref):
    return _role_quote_matches(value, ref, 'user')


def compact_preferences(preferences):
    return [{k: value[k] for k in ('basis', 'scope', 'approach', 'avoid', 'focus') if k in value}
            for value in preferences]


def _validate_preferences(root, row):
    """Optional additive contract; an explicit preference needs actual user words."""
    if 'teaching_preferences' not in row:
        return
    values = row['teaching_preferences']
    if not isinstance(values, list) or len(values) > 3:
        raise ValueError('teaching_preferences_must_be_bounded_array')
    for value in values:
        required = {'basis', 'scope', 'approach', 'avoid', 'source_refs'}
        if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - {'focus'}:
            raise ValueError('teaching_preference_fields_required')
        if 'focus' in value and (not isinstance(value['focus'], str) or value['focus'] not in PREFERENCE_FOCUS):
            raise ValueError('teaching_preference_focus_invalid')
        if not isinstance(value['basis'], str) or value['basis'] not in PREFERENCE_BASES:
            raise ValueError('teaching_preference_evidence_basis_required')
        if any(not isinstance(value[k], str) or not value[k].strip() for k in ('scope', 'approach')):
            raise ValueError('teaching_preference_scope_and_approach_required')
        if not isinstance(value['avoid'], str):
            raise ValueError('teaching_preference_avoid_must_be_text')
        refs = value['source_refs']
        if not isinstance(refs, list) or not refs or len(refs) > 4:
            raise ValueError('teaching_preference_user_evidence_required')
        for ref in refs:
            safe_source(root, ref)
            if (ref.get('role') != 'user' or not isinstance(ref.get('quote'), str)
                    or not ref['quote'].strip() or not isinstance(ref.get('locator'), str)
                    or not ref['locator'].strip()):
                raise ValueError('teaching_preference_user_quote_required')
            if 'sequence' in ref and (type(ref['sequence']) is not int or ref['sequence'] < 0):
                raise ValueError('teaching_preference_sequence_invalid')
            try:
                evidence = json.loads((root/ref['path']).read_text())
            except (ValueError, UnicodeError):
                raise ValueError('teaching_preference_structured_user_source_required')
            if not _user_quote_matches(evidence, ref):
                raise ValueError('teaching_preference_user_quote_mismatch:'+ref['path'])
    size = len(canonical(compact_preferences(values)).encode()) if values else 0
    if size > 1300 or size + len(row.get('short_summary', '').encode()) > 2600:
        raise ValueError('teaching_preferences_exceed_teaching_budget')


def _prepare_preferences(root, row):
    """A later legacy update may omit preferences, but may not silently erase them."""
    row = copy.deepcopy(row)
    path = root/SEMANTIC/(row['concept_key']+'.json')
    old = json.loads(path.read_text()) if path.is_file() else {}
    previous = old.get('teaching_preferences', [])
    if 'teaching_preferences' not in row and previous:
        row['teaching_preferences'] = copy.deepcopy(previous)
    elif previous:
        _validate_preferences(root, row)
        # The A input adapter relocates verified references into its immutable
        # evidence cache.  A path change with identical bytes and user quote is
        # not a revision of the teaching preference.
        def retained(old, new):
            fields = ('basis', 'scope', 'approach', 'avoid')
            if any(old.get(key) != new.get(key) for key in fields):
                return False
            if 'focus' in old and old['focus'] != new.get('focus'):
                return False
            def evidence(ref):
                return canonical({key: ref.get(key) for key in
                                  ('sha256', 'role', 'sequence', 'quote')})
            return {evidence(ref) for ref in old.get('source_refs', [])} <= {
                evidence(ref) for ref in new.get('source_refs', [])}
        removed = [old for old in previous if not any(
            retained(old, new) for new in row.get('teaching_preferences', []))]
        reason = row.get('teaching_preferences_revision_reason')
        if removed and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError('teaching_preferences_revision_reason_required')
    _validate_preferences(root, row)
    refs = row.get('source_refs', [])
    if not isinstance(refs, list) or any(not isinstance(r, dict) or
            not isinstance(r.get('path'), str) or not isinstance(r.get('sha256'), str) for r in refs):
        raise ValueError('profile_source_reference_required')
    existing = {(r['path'], r['sha256']) for r in refs}
    for preference in row.get('teaching_preferences', []):
        for ref in preference['source_refs']:
            identity = (ref['path'], ref['sha256'])
            if identity not in existing:
                # Quotes/role stay in the typed preference, hashes also join the
                # native preparation and publication provenance contract.
                refs.append({'path': ref['path'], 'sha256': ref['sha256']})
                existing.add(identity)
    row['source_refs'] = refs
    return row


def _validated_preferences(root, candidate, read_source):
    """Preference evidence ages independently of the concept's event summary."""
    values = candidate.get('teaching_preferences', [])
    if not isinstance(values, list) or len(values) > 3:
        return [], ['teaching_preferences_must_be_bounded_array']
    accepted, issues = [], []
    for position, value in enumerate(values):
        try:
            # The original authored row's combined summary budget is checked on
            # acceptance. An unrelated stale overview does not revoke a quote.
            _validate_preferences(root, {'teaching_preferences': [value]})
            for ref in value['source_refs']:
                read_source(root/ref['path'], 'external')
            accepted.append(copy.deepcopy(value))
        except (ValueError, OSError) as exc:
            issues.append({'preference_index': position, 'reason': str(exc)})
    if accepted and len(canonical(compact_preferences(accepted)).encode()) > 1300:
        return [], issues + ['teaching_preferences_exceed_teaching_budget']
    return accepted, issues


def _validate_step_evidence(root, row):
    """Validate typed IDs and source bytes; never classify text as proficiency."""
    from math_exam_profile import STEP_STATES
    values = row.get('step_evidence', [])
    if not isinstance(values, list) or len(values) > 64:
        raise ValueError('step_evidence_must_be_bounded_array')
    for value in values:
        required = {'step_ids', 'state', 'scope', 'source_refs'}
        optional = {'user_evidence', 'hint_evidence', 'coverage'}
        if (not isinstance(value, dict) or not required <= value.keys()
                or set(value) - required - optional):
            raise ValueError('step_evidence_fields_required')
        ids = value['step_ids']
        if (not isinstance(ids, list) or not ids or len(ids) > 64
                or any(not isinstance(x, str) or not x.strip() or len(x) > 160 for x in ids)
                or len(ids) != len(set(ids))):
            raise ValueError('step_evidence_exact_unique_step_ids_required')
        if not isinstance(value['state'], str) or value['state'] not in STEP_STATES:
            raise ValueError('step_evidence_state_invalid')
        if not isinstance(value['scope'], str) or not value['scope'].strip():
            raise ValueError('step_evidence_scope_required')
        if 'coverage' in value and value['coverage'] not in ('full_operation', 'partial_operation'):
            raise ValueError('step_evidence_coverage_invalid')
        for field in ('user_evidence', 'hint_evidence'):
            text = value.get(field, '')
            structured_quotes = isinstance(text, list) and all(
                isinstance(atom, dict) and set(atom) == {'sequence', 'quote'}
                and type(atom['sequence']) is int and atom['sequence'] >= 0
                and isinstance(atom['quote'], str) and atom['quote'].strip()
                for atom in text)
            if not (text is None or isinstance(text, str) or
                    isinstance(text, list) and all(isinstance(x, str) for x in text)
                    or structured_quotes):
                raise ValueError('step_evidence_body_must_be_text_or_sequence_quotes:'+field)
        refs = value['source_refs']
        if not isinstance(refs, list) or not refs or len(refs) > 8:
            raise ValueError('step_evidence_source_required')
        for ref in refs:
            safe_source(root, ref)
            if 'quote' in ref:
                if not isinstance(ref['quote'], str) or not ref['quote'].strip():
                    raise ValueError('step_evidence_source_quote_required')
                if 'sequence' in ref and (type(ref['sequence']) is not int or ref['sequence'] < 0):
                    raise ValueError('step_evidence_source_sequence_invalid')
                if ref.get('role') in ('user', 'assistant'):
                    try:
                        source = json.loads((root/ref['path']).read_text())
                    except (ValueError, UnicodeError):
                        raise ValueError('step_evidence_structured_turn_source_required')
                    if not _role_quote_matches(source, ref, ref['role']):
                        raise ValueError('step_evidence_source_quote_mismatch:'+ref['path'])
        # Typed turn quotes are evidence claims, not authored summaries. Check
        # their exact role and sequence while preserving legacy prose forms.
        for field, role in (('user_evidence', 'user'), ('hint_evidence', 'assistant')):
            atoms = value.get(field)
            if not isinstance(atoms, list) or not atoms or not isinstance(atoms[0], dict):
                continue
            sources = []
            for ref in refs:
                try:
                    sources.append(json.loads((root/ref['path']).read_text()))
                except (ValueError, UnicodeError):
                    continue
            if any(not any(_role_quote_matches(source, atom, role) for source in sources) for atom in atoms):
                raise ValueError('step_evidence_turn_quote_mismatch:'+field)
    return copy.deepcopy(values)


def _step_evidence_sources(value):
    # A verified cache relocation does not create a new observation. These
    # fields identify the original bytes and any exact attributed turn.
    return {canonical({key: ref.get(key) for key in ('sha256', 'role', 'sequence', 'quote')})
            for ref in value.get('source_refs', [])}


def _removed_step_evidence(previous, values):
    def retained(old, new):
        fields = ('step_ids', 'state', 'scope', 'coverage', 'user_evidence', 'hint_evidence')
        return (all(old.get(key) == new.get(key) for key in fields)
                and _step_evidence_sources(old) <= _step_evidence_sources(new))
    return [old for old in previous if not any(retained(old, new) for new in values)]


def _validate_new_step_order(root, values, previous):
    for value in values:
        if value in previous or value['state'] not in ('independent_performed', 'corrected_after_hint'):
            continue
        user, hints = value.get('user_evidence'), value.get('hint_evidence')
        if not user or not hints or not all(isinstance(atom, dict) for atom in [*user, *hints]):
            continue  # legacy prose and single-role observations require local semantic review
        # Sequence numbers only order turns from the same source conversation.
        # Require the exact learner and hint turns in that source before
        # deciding whether the displayed action followed the stated hint.
        same_transcript = False
        earlier_hint = False
        for path in {ref['path'] for ref in value['source_refs']}:
            try:
                source = json.loads((root/path).read_text())
            except (ValueError, UnicodeError):
                continue
            users = [atom['sequence'] for atom in user if _role_quote_matches(source, atom, 'user')]
            assistance = [atom['sequence'] for atom in hints if _role_quote_matches(source, atom, 'assistant')]
            if users and assistance:
                same_transcript = True
                earlier_hint |= min(assistance) < max(users)
        if value['state'] == 'corrected_after_hint' and not earlier_hint:
            raise ValueError('step_evidence_requires_earlier_hint_in_same_transcript')
        if value['state'] == 'independent_performed' and same_transcript and earlier_hint:
            raise ValueError('step_evidence_independent_action_follows_cited_hint')


def _prepare_step_evidence(root, row):
    """Keep valid historical observations unless an explicit revision replaces them."""
    row = copy.deepcopy(row)
    path = root/SEMANTIC/(row['concept_key']+'.json')
    old = json.loads(path.read_text()) if path.is_file() else {}
    previous = old.get('step_evidence', [])
    if 'step_evidence' not in row and previous:
        row['step_evidence'] = copy.deepcopy(previous)
    values = _validate_step_evidence(root, row)
    if 'step_evidence' not in row:
        return row
    _validate_new_step_order(root, values, previous)
    if _removed_step_evidence(previous, values):
        reason = row.get('step_evidence_revision_reason')
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('step_evidence_revision_reason_required')
    for before in previous:
        if before.get('coverage') != 'partial_operation':
            continue
        for after in values:
            if (after.get('coverage') == 'full_operation'
                    and set(before.get('step_ids', [])) & set(after.get('step_ids', []))
                    and _step_evidence_sources(before) == _step_evidence_sources(after)
                    and all(before.get(key) == after.get(key)
                            for key in ('user_evidence', 'hint_evidence'))):
                # A revision reason cannot turn the very same partial action
                # into a complete one. Additional real turns in the same file
                # may support a correction; a new source file is not required.
                raise ValueError('step_evidence_partial_to_full_requires_distinct_evidence')
    row['step_evidence'] = values
    existing = {(r['path'], r['sha256']) for r in row['source_refs']}
    for value in values:
        for ref in value['source_refs']:
            identity = (ref['path'], ref['sha256'])
            if identity not in existing:
                row['source_refs'].append({'path': ref['path'], 'sha256': ref['sha256']})
                existing.add(identity)
    return row


def _source_guards(refs):
    return [{'path': r['path'], 'sha256': r['sha256']} for r in refs]


def _read_only_uri(path):
    """Keep mode=ro without importing urllib.request through Path.as_uri on POSIX."""
    path = Path(path)
    if os.name == 'posix' and path.is_absolute():
        return 'file://' + quote(path.as_posix(), safe='/') + '?mode=ro'
    return path.as_uri() + '?mode=ro'


def _source_lookup(conn):
    """Memoize indexed rows only within the caller's one SQLite read snapshot.

    Filesystem stamps are deliberately not cached here. Every existing source
    guard still checks its current file state, and no row survives this resolve.
    """
    rows = {}

    def lookup(path):
        if path not in rows:
            row = conn.execute('SELECT stamp,sha256 FROM sources WHERE path=?', (path,)).fetchone()
            rows[path] = (json.loads(row[0]), row[1]) if row is not None else None
        return rows[path]

    return lookup


def _checked_personal_context(root, conn, value, *, source_lookup=None):
    """Hot reads use indexed hashes plus stat guards, never reopen raw evidence."""
    import math_concept_index as native
    result = copy.deepcopy(value)

    def current(refs):
        for ref in refs:
            saved = source_lookup(ref['path']) if source_lookup else None
            if source_lookup is None:
                row = conn.execute('SELECT stamp,sha256 FROM sources WHERE path=?', (ref['path'],)).fetchone()
                saved = (json.loads(row[0]), row[1]) if row is not None else None
            if (saved is None or saved[1] != ref['sha256']
                    or native._stamp(root/ref['path']) != saved[0]):
                return False
        return True

    if result.get('object_role') in ('step_reference', 'conclusion_reference'):
        guards = result.pop('_reference_guards', [])
        if not guards or not current(guards):
            result.pop(result['object_role'], None)
            result['status'] = 'source_changed'
            result['reference_status'] = 'stale'
            result['reason'] = 'reference_sources_changed;maintenance_refresh_required'
        return result

    exam_guards = result.pop('_exam_guards', None)
    if exam_guards is not None and not current(exam_guards):
        import math_exam_context
        result['exam_context'] = math_exam_context.stale(result.get('exam_context'))

    if '_preference_guards' in result:
        preferences, guards = result.get('teaching_preferences', []), result.pop('_preference_guards')
        accepted = [p for i, p in enumerate(preferences) if i < len(guards) and current(guards[i])]
        if len(accepted) != len(preferences):
            result['teaching_preferences_status'] = 'partial' if accepted else 'source_changed'
        if accepted:
            result['teaching_preferences'] = accepted
        else:
            result.pop('teaching_preferences', None)
    semantic_guards = result.pop('_semantic_guards', None)
    if semantic_guards is not None and not current(semantic_guards):
        result['status'] = 'semantic_stale'
        result['short_summary'] = '语义概况的引用已变化，需更新后使用；有效讲法偏好独立核验。'
        result['progress'] = []
        result['next_check'] = '依据本轮真实作答核对条件和当前步骤。'
    if result.get('status') != 'semantic_current':
        result.pop('step_evidence', None)
        result.pop('solution_connections', None)
        result['step_evidence_status'] = 'semantic_not_current'
    else:
        evidence = result.get('step_evidence', [])
        accepted = [e for e in evidence if current(e.get('source_refs', []))]
        if len(accepted) != len(evidence):
            result['step_evidence_status'] = 'source_changed'
        if accepted:
            result['step_evidence'] = accepted
        else:
            result.pop('step_evidence', None)
    return result


def _after_attempt_personal_context(value):
    """An attempt unlocks scoped observations, not their raw answer turns."""
    if value.get('object_role') in ('step_reference', 'conclusion_reference'):
        return value
    withheld = set()
    for field in ('short_summary', 'next_check', 'progress', 'solution_connections', 'teaching_preferences'):
        if value.get(field) and ANSWER_MARKER.search(canonical(value[field])):
            value.pop(field)
            withheld.add(field)
    # These states can still be used with their conditions and coverage. A raw
    # user or assistant quote may contain the result or another subquestion.
    for atom in value.get('step_evidence', []):
        atom_withheld = ('user_evidence', 'hint_evidence', 'source_refs')
        for field in atom_withheld:
            if field in atom:
                atom.pop(field)
                withheld.add('step_evidence.' + field)
    if any(ANSWER_MARKER.search(atom['scope']) for atom in value.get('step_evidence', [])):
        value.pop('step_evidence')
        withheld.add('step_evidence')
    if withheld:
        value['personal_fields_withheld'] = sorted(withheld)
    return value


def _low_budget_personal(base, personal, frequency, max_bytes):
    """Keep one complete reviewed short summary if the combined math bundle cannot fit."""
    if not personal or base.get('status') != 'budget_too_small':
        return None
    # Keep the required size for the original combined request. This limited
    # view can guide diagnosis, but does not claim the method was loaded.
    slim = {key: base[key] for key in ('version', 'source_version', 'identity', 'view',
                                      'total', 'required_min_bytes') if key in base}
    slim.update(status='available', records=[personal], returned=1, truncated=True,
                material_status='combined_context_omitted_for_budget',
                detail_lookup='same_identity_concepts_and_view_with_required_budget')
    if frequency:
        slim['exam_frequency'] = frequency
        if len(canonical(slim).encode()) > max_bytes:
            slim.pop('exam_frequency')
    return slim if len(canonical(slim).encode()) <= max_bytes else None


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


def _automatic_revision_archive(root, path, old):
    """Every replacement preserves its verified predecessor, including new events."""
    previous = old.get('content_sha256')
    if (not isinstance(previous, str) or not re.fullmatch(r'[0-9a-f]{64}', previous)
            or previous != digest({k: v for k, v in old.items() if k != 'content_sha256'})):
        raise ValueError('profile_revision_predecessor_invalid:'+old.get('concept_key', ''))
    raw = path.read_bytes()
    if json.loads(raw) != old:
        raise ValueError('profile_revision_predecessor_changed')
    archived = root/SEMANTIC/'历史版本'/old['concept_key']/(previous+'.json')
    if archived.exists() and archived.read_bytes() != raw:
        raise ValueError('profile_revision_archive_conflict:'+old['concept_key'])
    return archived, raw


def _profile_derived_path(path):
    # The maintenance journal has its own exact optimistic version guard. It
    # cannot be treated as outside evidence that our own commit invalidates.
    return any(path == str(base) or path.startswith(str(base)+'/')
               for base in (SEMANTIC, PAGES, BASE/'记忆维护'))


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


def prepare_updates(repo_root, payload, *, prospective_concepts=()):
    root = Path(repo_root).resolve()
    if (not isinstance(payload, dict) or payload.get('schema') != SCHEMA
            or not isinstance(payload.get('updates'), list)
            or not (payload['updates'] or payload.get('memory_corrections'))):
        raise ValueError('profile_update_schema_required')
    import math_memory_lifecycle as memory
    correction_keys = {row.get('concept_key') for row in payload.get('memory_corrections', []) if isinstance(row, dict)}
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
        for row in [*payload['updates'], *({'concept_key': key} for key in correction_keys)]:
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
        if (key not in known and key not in prospective_concepts) or key in seen:
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
        row = memory.prepare_claims(root, _prepare_step_evidence(root, _prepare_preferences(root, row)))
        if 'solution_connections' not in row:
            old_path = root/SEMANTIC/(key+'.json')
            if old_path.is_file():
                old_connections = json.loads(old_path.read_text()).get('solution_connections', [])
                if old_connections:
                    row['solution_connections'] = old_connections
                    for link in old_connections:
                        for ref in link['source_refs']:
                            if ref not in row['source_refs']:
                                row['source_refs'].append(ref)
        _verified_solution_connections(row, known | set(prospective_concepts))
        refs = [safe_source(root, ref) for ref in row['source_refs']]
        updates.append({**row, 'source_refs':refs})
    corrections = memory.prepare_corrections(root, payload, known)
    for row in updates:
        memory.validate_acknowledgments(root, row, corrections)
    if payload.get('batch_contributions') is not None:
        import math_A_profile_merge
        math_A_profile_merge.validate(root, {**payload, 'updates': updates})
    cited_sources = {ref['path']: {'sha256': ref['sha256'], 'stamp': native._stamp(root/ref['path'])}
                     for row in [*updates, *corrections] for ref in row['source_refs']}
    profile_versions = {}
    for key in seen | correction_keys:
        path = root/SEMANTIC/(key+'.json')
        profile_versions[key] = json.loads(path.read_text()).get('content_sha256') if path.is_file() else None
    extension = {'memory_corrections': corrections} if corrections else {}
    return {**payload, **extension, **maintenance_basis, '_basis_cited_sources': cited_sources,
            '_basis_profile_versions': profile_versions, '_basis_memory_version': memory.version(root),
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


def _maintenance_id(payload, reason):
    return 'MATH-PROFILE-MAINT-'+digest({'prepared': payload, 'maintenance_reason': reason})


def _accept_maintenance(root, payload, maintenance_reason):
    if not isinstance(payload, dict):
        raise ValueError('profile_update_schema_required')
    if payload.get('_deferred_batch_merge'):
        raise ValueError('topic_shard_profile_requires_consolidation_before_acceptance')
    if payload.get('batch_contributions') is not None:
        raise ValueError('batch_contributions_require_formal_accept')
    reason = maintenance_reason if maintenance_reason is not None else payload.get('maintenance_reason')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('profile_maintenance_reason_required')
    required = ('basis_version', '_basis_records', '_basis_review_event_ids',
                '_basis_evidence_version', '_basis_sources', '_basis_store_stamps', '_basis_directories',
                '_basis_cited_sources')
    if any(field not in payload for field in required) or not payload['basis_version']:
        raise ValueError('profile_maintenance_must_be_prepared')
    prepared = prepare_updates(root, {**payload, 'basis_version': None})
    import math_memory_lifecycle as memory
    keys = {row['concept_key'] for row in prepared['updates']} | {row['concept_key'] for row in prepared.get('memory_corrections', [])}
    for field in ('_basis_records', '_basis_review_event_ids'):
        if not isinstance(payload[field], dict) or set(payload[field]) != keys:
            raise ValueError('profile_maintenance_exact_basis_required:'+field)
        if payload[field] != prepared[field]:
            raise ValueError('profile_point_changed_since_preparation:'+field)
    for field in required[3:]:
        previous = payload[field]
        current = prepared[field]
        if field == '_basis_sources':
            # A successful refresh can make the exact newly cited sources
            # part of the index for the first time. Their bytes were already
            # frozen in _basis_cited_sources; unrelated index changes still fail.
            current = {path: value for path, value in current.items()
                       if path in previous or payload['_basis_cited_sources'].get(path) != value}
        if previous != current:
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
    maintenance_id = _maintenance_id(payload, reason)
    reserved = {'schema', 'status', 'event_id', 'event_ids', 'maintenance_id', 'maintenance_reason',
                'basis_version', 'through_event_ids', 'card_evidence_versions',
                'evidence_record_versions', 'evidence_review_event_ids', 'content_sha256', 'memory_recorded_at', 'memory_predecessor'}
    plans = []
    transaction = memory.prepare_transaction(root, payload, prepared.get('memory_corrections', []), maintenance_id)
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
            path = root/SEMANTIC/(key+'.json')
            old = json.loads(path.read_text()) if path.exists() else None
            recorded_at = old.get('memory_recorded_at') if old and old.get('maintenance_id') == maintenance_id else memory.now()
            stored = {**row, 'schema': SCHEMA, 'status': 'accepted_semantic_maintenance',
                      'maintenance_id': maintenance_id, 'maintenance_reason': reason,
                      'basis_version': payload['basis_version'],
                      'through_event_ids': sorted({str(record_event(v)) for v in values if record_event(v)}),
                      'card_evidence_versions': {v['record_id']: evidence_basis(v) for v in values if v.get('kind') == 'personal_card'},
                      'evidence_record_versions': prepared['_basis_records'][key],
                      'evidence_review_event_ids': prepared['_basis_review_event_ids'][key],
                      'memory_recorded_at': recorded_at,
                      'memory_predecessor': old.get('memory_predecessor') if old and old.get('maintenance_id') == maintenance_id else old.get('content_sha256') if old else None}
            stored['content_sha256'] = digest(stored)
            archive = None
            unchanged = old == stored
            if old is not None and not unchanged:
                if ('_basis_profile_versions' in payload and
                        payload['_basis_profile_versions'].get(key) != old.get('content_sha256')):
                    raise ValueError('profile_revision_predecessor_changed:'+key)
                archive = _semantic_revision_archive(root, path, old, row)
            elif old is None and row.get('supersedes_content_sha256'):
                raise ValueError('profile_revision_predecessor_missing:'+key)
            plans.append((path, stored, archive, unchanged))
    noop = all(plan[3] for plan in plans) and (transaction is None or transaction['unchanged'])
    if prepared['basis_version'] != payload['basis_version'] and not noop:
        raise ValueError('profile_basis_version_changed')
    # No validation below this boundary. A failed replacement can be retried
    # against the same prepared bytes; already-installed rows become no-ops.
    # Publish the correction first: an interrupted profile replacement then
    # fails closed as stale rather than exposing the old contradicted claim.
    if transaction and not transaction['unchanged']:
        write_changed(transaction['path'], transaction['value'])
    for path, stored, archive, unchanged in plans:
        if archive:
            write_changed(*archive)
    for path, stored, archive, unchanged in plans:
        if not unchanged:
            write_changed(path, stored)
    return {'status': 'noop' if noop else 'accepted', 'maintenance_id': maintenance_id,
            'concept_keys': sorted(keys),
            'memory_version': memory.version(root, keys),
            'profile_version': digest(prepared['updates']), 'refresh_required': True}


def recover_maintenance(repo_root, payload, reason):
    """Prove the prepared request is already durable before refreshing only."""
    import math_memory_lifecycle as memory
    root = Path(repo_root).resolve()
    identity = _maintenance_id(payload, reason)
    if not payload.get('basis_version') or not (payload.get('updates') or payload.get('memory_corrections')):
        raise ValueError('profile_maintenance_must_be_prepared')
    keys = set()
    for row in payload['updates']:
        key = row['concept_key']
        if not re.fullmatch(r'MATH-CONCEPT-[0-9a-f]{24}', key):
            raise ValueError('profile_maintenance_unknown_concept')
        saved = memory._safe_json(root, root/SEMANTIC/(key+'.json'))
        if (saved.get('maintenance_id') != identity or saved.get('status') != 'accepted_semantic_maintenance'
                or saved.get('content_sha256') != digest({k: v for k, v in saved.items() if k != 'content_sha256'})
                or any(saved.get(k) != v for k, v in row.items())):
            raise ValueError('profile_maintenance_missing_or_superseded:'+key)
        keys.add(key)
    if payload.get('memory_corrections'):
        transaction = memory.prepare_transaction(root, payload, payload['memory_corrections'], identity)
        if not transaction['unchanged'] or transaction['value'].get('maintenance_id') != identity:
            raise ValueError('profile_maintenance_corrections_not_accepted')
        keys.update(row['concept_key'] for row in payload['memory_corrections'])
    return {'status': 'recovered', 'maintenance_id': identity, 'concept_keys': sorted(keys),
            'memory_version': memory.version(root, keys),
            'profile_version': digest(payload['updates']), 'refresh_required': True}


def finish_maintenance(repo_root, result, refresh_only=False, *, publish=False):
    """Refresh local projections and publish a replica on explicit request."""
    if refresh_only and publish:
        raise ValueError("profile_maintenance_refresh_only_conflicts_with_publication")
    root = Path(repo_root).resolve()
    import math_concept_index as native
    refreshed = native.build_index(root)
    result = {**result, 'refresh': {k: refreshed[k] for k in ('status', 'version', 'concept_count', 'record_count')},
              'refresh_required': False}
    # Semantic corrections change the same read generation as formal intake.
    # Refresh their bounded discovery/record projections without a new event.
    try:
        import math_memory_record_scopes
        result['personal_record_scopes'] = math_memory_record_scopes.refresh(root, refreshed['version'])
    except (ImportError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
        result['personal_record_scopes'] = {'status':'pending','reason':type(exc).__name__}
    try:
        import math_memory_utterances
        result['user_utterances'] = math_memory_utterances.refresh(root, refreshed['version'])
    except (ImportError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
        result['user_utterances'] = {'status':'pending','reason':type(exc).__name__}
    try:
        import math_memory_backends
        result['retrieval_backend'] = math_memory_backends.refresh_selected(root, version=refreshed['version'])
    except (ImportError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
        result['retrieval_backend'] = {'status':'pending','reason':type(exc).__name__}
    if publish:
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
    if payload.get('memory_corrections'):
        raise ValueError('memory_corrections_require_accept_maintenance')
    import math_memory_lifecycle as memory
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
    import math_formal_quality
    quality_owned = math_formal_quality.require_profile(root, payload, events)
    events.sort(key=lambda e:(e.get('closed_at') or e.get('recorded_at',''),e['event_id']))
    event_ids=[e['event_id'] for e in events]
    event=events[-1]
    event_id=event['event_id']
    # Preparation is before the writer. Recheck cited bytes after that commit;
    # its own index refresh may legitimately have advanced the global version.
    prepared = prepare_updates(root, {**payload, 'basis_version':None})
    contributions = {}
    if prepared.get('batch_contributions') is not None:
        import math_A_profile_merge
        contributions = math_A_profile_merge.validate(root, prepared, event_ids=event_ids)
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
    own_source_proof = _closeout_source_proof(events, root)
    prior_hashes = {}
    if quality_owned:
        for records in payload.get('_basis_records', {}).values():
            for record_id, fingerprint in records.items():
                prior_hashes.setdefault(record_id, set()).add(fingerprint)
    with closing(sqlite3.connect((root/native.INDEX).as_uri()+'?mode=ro',uri=True)) as conn:
        through={}
        card_versions={}
        record_versions={}
        for row in prepared['updates']:
            values=[json.loads(p) for p, in conn.execute('SELECT r.payload FROM records r JOIN membership m ON r.id=m.record_id WHERE m.key=?',(row['concept_key'],))]
            previous=payload.get('_basis_records',{}).get(row['concept_key'])
            if previous is None:
                raise ValueError('profile_update_must_be_prepared_before_commit')
            own_ids={r.get('formal_id') for e in events for r in e.get('formal_results',[])}
            for value in values:
                rid=value['record_id']
                own=record_event(value) in event_ids or value.get('formal_id') in own_ids
                if (not own and previous.get(rid)!=evidence_basis(value)
                        and not _owned_closeout_source(root, value, own_source_proof)
                        and not (quality_owned and rid not in previous
                                 and _previously_indexed_capture_reference(
                                     root, value, prior_hashes, payload.get('_basis_sources', {})))
                        and not (quality_owned and previous == {}
                                 and _static_reference_for_new_membership(
                                     root, value, payload.get("_basis_sources", {})))):
                    raise ValueError('profile_point_changed_since_preparation:'+row['concept_key'])
                previous_reviews=payload.get('_basis_review_event_ids',{}).get(row['concept_key'],{}).get(rid)
                if previous_reviews is not None:
                    current_reviews=sorted(str(item.get('event',{}).get('event_id')) for item in value.get('history',{}).get('review_events',[]) if item.get('event',{}).get('event_id'))
                    if current_reviews!=previous_reviews:
                        raise ValueError('new_actual_review_since_profile_preparation:'+rid)
            through[row['concept_key']]=sorted(set(event_ids)|{str(record_event(v)) for v in values if record_event(v)})
            card_versions[row['concept_key']]={v['record_id']:evidence_basis(v) for v in values if v.get('kind')=='personal_card'}
            record_versions[row['concept_key']]={v['record_id']:evidence_basis(v) for v in values}
    plans = []
    for row in prepared['updates']:
        path=root/SEMANTIC/(row['concept_key']+'.json')
        old = json.loads(path.read_text()) if path.exists() else None
        provenance = contributions.get(row['concept_key'])
        if (old and old.get('event_ids', [old.get('event_id')]) == event_ids
                and old.get('batch_contribution_sources') == provenance
                and all(old.get(k)==v for k,v in row.items())):
            keys.append(row['concept_key'])
            continue
        if ('_basis_profile_versions' in payload and
                payload['_basis_profile_versions'].get(row['concept_key']) != (old.get('content_sha256') if old else None)):
            raise ValueError('profile_revision_predecessor_changed:'+row['concept_key'])
        stored = {**row, 'schema':SCHEMA, 'event_id':event_id,
                  'event_ids':event_ids, 'card_evidence_versions':card_versions[row['concept_key']],
                  'evidence_record_versions':record_versions[row['concept_key']],
                  'basis_version':payload.get('basis_version'), 'status':'accepted_semantic_update',
                  'through_event_ids':through[row['concept_key']],
                  'memory_recorded_at': memory.now(),
                  'memory_predecessor': old.get('content_sha256') if old else None}
        if provenance:
            stored['batch_contribution_sources'] = provenance
        stored['content_sha256']=digest(stored)
        archive = None
        if old:
            archive = (_semantic_revision_archive(root, path, old, row) if old.get('event_id') == event_id
                       else _automatic_revision_archive(root, path, old))
        plans.append((path, stored, archive))
        keys.append(row['concept_key'])
    for path, stored, archive in plans:
        if archive:
            write_changed(*archive)
    for path, stored, archive in plans:
        write_changed(path, stored)
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


def _observation_locator(item):
    """A non-semantic locator; never infer independence from missing hints."""
    return (f"{item['date'] or '日期未记录'}；{item['source_record_id']}；"
            f"证据版本 {item['observation_version']}；outcome={item['kind']}；"
            f"hint_dependency={item['hint_dependency']}。")


def enrich_index(root, concepts, records, sources, membership, read_source, *,
                 only_keys=None, refresh_registry=True, dependency_sets=None):
    """Run only in the existing cold index transaction, before version hashing."""
    selected = set(concepts) if only_keys is None else set(only_keys) & set(concepts)
    active_key = '__registry__'
    original_reader = read_source
    def read_source(path, kind):
        source = original_reader(path, kind)
        if dependency_sets is not None:
            dependency_sets.setdefault(active_key, set()).add(source['path'])
        return source
    import math_problem_methods as methods
    import math_exam_profile as exam
    import math_exam_context as exam_context
    exam_registry = exam_context.load_registry(root, read_source)
    registry = methods.load_registry(root, read_source, concepts,
        [rid for rid, record in records.items() if record.get('kind') == 'personal_card'])
    if registry and refresh_registry:
        for formal_id, bindings in registry['formal_bindings'].items():
            # Metadata is excluded from protected full-evidence views. It is
            # also outside evidence_basis: textbook routes are not new learning.
            records[formal_id].setdefault('metadata', {})['problem_solving'] = methods.project(
                registry, bindings, 'exact_formal_card')
        for formal_id, exclusion in registry['formal_exclusions'].items():
            records[formal_id].setdefault('metadata', {})['problem_solving'] = methods.exclusion_projection(
                registry, exclusion, 'exact_formal_card')
    members={}
    for key,rid in membership:
        members.setdefault(key,[]).append(rid)
    links={}
    selected_formal = {fid for key in selected for fid in concepts[key]['formal_ids']}
    for rid,record in records.items():
        if rid in selected_formal and record.get('kind')=='personal_card':
            refs=[r['path'] for r in record['source_refs'] if '/错题卡/' in r['path']]
            if refs:
                links[rid]=_link(root,rid,refs[0])
    page_index=['# 数学知识点学习路径','',
                '原始学习证据保留完整；未有已接受语义成稿的页面明确标记为证据整理，不推断独立掌握。','']
    hot_rows=[]
    choice_refinement_cache={}
    for key,concept in concepts.items():
        if key not in selected:
            continue
        active_key = key
        objective_exam = exam_context.project(exam_registry, key)
        method_profile = methods.project(registry,
            registry['concept_bindings'].get(key, []) if registry else [], 'concept_candidate')
        if registry and key in registry['concept_exclusions']:
            method_profile = methods.exclusion_projection(registry, registry['concept_exclusions'][key], 'concept_exclusion')
        choice_material=[]
        if registry and method_profile:
            for mid in _linked_refinement_ids([method_profile]):
                source_method=registry['methods'].get(mid)
                if not source_method or not methods.is_reviewed_choice_fill(source_method):
                    continue
                if mid not in choice_refinement_cache:
                    alias=registry['aliases'].get(methods.alias_key(mid),{})
                    bindings=[b for b in alias.get('bindings',[]) if b['method_id']==mid]
                    choice_refinement_cache[mid]=methods.project(registry,bindings,'linked_refinement_candidate')
                if choice_refinement_cache[mid]:choice_material.append(choice_refinement_cache[mid])
        choice_summary=exam.choice_fill_guidance(None,([method_profile] if method_profile else [])+choice_material)
        frequency_summary=exam_context.announcement(objective_exam) if objective_exam else None
        import math_memory_projection
        raw_rows = [records[rid] for rid in members.get(key, [])]
        rows=math_memory_projection.effective_point_records(root, raw_rows, key)
        reference_anchors=sorted([r['metadata']['reference_anchor'] for r in rows
            if r.get('metadata',{}).get('reference_anchor',{}).get('concept_key')==key],key=lambda a:a['path'])
        timeline=[]
        card_evidence=[]
        for record in rows:
            kind=record.get('kind')
            if kind=='personal_card':
                hist=record.get('history',{})
                # Card-level statements remain inspectable without becoming
                # dated learning events or errors attributed to every label.
                statements=[]
                if hist.get('wrong_point'):
                    statements.append({'heading':'原卡 wrong_point','text':_text(hist['wrong_point'])})
                for section in hist.get('personal_sections',[]):
                    if section.get('text'):
                        statements.append({'heading':section.get('heading','原卡个人记录'),
                                           'text':_text(section['text'])})
                if statements:
                    card_evidence.append({'question':record['formal_id'], 'statements':statements,
                        'evidence_origin':record.get('evidence_origin',{}),
                        'source_refs':[ref for ref in record['source_refs'] if '/错题卡/' in ref['path']]})
                for field in ('wrong_history','mastery_history'):
                    values=hist.get(field,[])
                    values=values if isinstance(values,list) else [values]
                    for pos,value in enumerate(values):
                        if not value:
                            continue
                        timeline.append({'date':_date(value),'question':record['formal_id'],
                            'scope':'相关题记录，未据此推断该知识点同错', 'kind':field,
                            'text':_text(value),'source_refs':record['source_refs'][:1],
                            'position':pos, 'source_record_id':record['record_id']+':'+field})
                for item in hist.get('review_events',[]):
                    event=item.get('event',{})
                    timeline.append({'date':_date(event),'question':record['formal_id'],
                        'scope':item.get('attribution','真实题级复习'), 'kind':'review_event',
                        'text':_text(event),'source_refs':record['source_refs'], 'position':item.get('ordinal'),
                        'source_record_id':record['record_id']+':review_events'})
            elif kind in ('formal_concept_observation','concept_review'):
                summary=record.get('summary',{})
                for pos,item in enumerate(summary.get('observations',[])):
                    # These observations, unlike a card association, bind the point.
                    outcome = item.get('outcome', 'unresolved')
                    hint_fields = ('hint_evidence', 'hint_turn_indices')
                    hint_dependency = ('assisted' if outcome == 'corrected_after_hint'
                        or any(item.get(field) for field in hint_fields)
                        else 'none_recorded' if any(field in item for field in hint_fields) else 'unknown')
                    timeline.append({'date':summary.get('study_date'),
                        'question':record.get('formal_id') or item.get('question_ref'),
                        'scope':'正式逐知识点观察','kind':outcome,
                        'text':_text(item.get('error_detail') or item.get('correction_text') or outcome),
                        'correction_text':(item.get('correction_text')
                                           if item.get('error_detail') else None),
                        'source_refs':record['source_refs'], 'position':pos,
                        'source_record_id':record['record_id'],
                        'observation_version':item['observation_sha256'], 'hint_dependency':hint_dependency})
        card_evidence.sort(key=lambda x:x['question'])
        # Only positions within one source record have a known order. In
        # particular, question labels "...9" and "...39" are not timestamps.
        timeline.sort(key=lambda x:(x['date'] is None, x['date'] or '',
            x.get('source_record_id', ''),
            x['position'] if isinstance(x['position'], int) else -1,
            str(x['question']), x['kind'], x['scope'], digest(x)))
        dated=[x for x in timeline if x['date']]
        explicit=[x for x in timeline if x['scope']=='正式逐知识点观察']
        linked=[links[x] for x in concept['formal_ids'] if x in links]
        overview=f'关联 {len(linked)} 道正式题；整理 {len(timeline)} 条已记录历史，其中 {len(explicit)} 条明确绑定本知识点。'
        if dated:
            overview+=f" 记录时间 {dated[0]['date']} 至 {dated[-1]['date']}。"
        semantic=None
        semantic_stale_reason=None
        preferences=[]
        preference_issues=[]
        step_evidence=[]
        step_evidence_issue=None
        semantic_ref=None
        semantic_path=root/SEMANTIC/(key+'.json')
        if semantic_path.is_file():
            semantic_source=read_source(semantic_path,'external')
            semantic_ref={'path':str(semantic_path.relative_to(root)), 'sha256':semantic_source['sha256']}
            candidate=json.loads(semantic_path.read_text())
            preferences, preference_issues = _validated_preferences(root, candidate, read_source)
            try:
                for ref in candidate.get('source_refs',[]):
                    safe_source(root,ref)
                    read_source(root/ref['path'], 'external')
                _validate_preferences(root, candidate)
                current_events={record_event(r) for r in rows if record_event(r)}
                if not current_events <= set(candidate.get('through_event_ids',[])):
                    raise ValueError('new_observations_require_profile_update')
                current_cards={r['record_id']:evidence_basis(r) for r in rows if r.get('kind')=='personal_card'}
                if candidate.get('card_evidence_versions')!=current_cards:
                    raise ValueError('new_card_or_review_requires_profile_update')
                if (candidate.get('status') == 'accepted_semantic_maintenance'
                        or 'evidence_record_versions' in candidate):
                    if not _matches_maintenance_basis(candidate.get('evidence_record_versions'), raw_rows):
                        raise ValueError('changed_evidence_requires_profile_update')
                if candidate.get('status') == 'accepted_semantic_maintenance':
                    acknowledged = set(candidate.get('memory_correction_ids', []))
                    if any(correction['correction_id'] not in acknowledged for row in rows
                           for correction in row.get('summary', {}).get('memory_corrections', [])):
                        raise ValueError('memory_correction_requires_profile_update')
                import math_memory_lifecycle
                memory_state=math_memory_lifecycle.resolve_memory_claims(root,[key],view='direct')
                if key in memory_state['invalidated_concept_keys']:
                    raise ValueError('memory_correction_requires_profile_update')
                semantic=candidate
            except (ValueError,OSError) as exc:
                semantic_stale_reason=str(exc)
            if semantic:
                try:
                    step_evidence = _validate_step_evidence(root, semantic)
                    for value in step_evidence:
                        for ref in value['source_refs']:
                            read_source(root/ref['path'], 'external')
                except (ValueError, OSError) as exc:
                    # A malformed additive field is not evidence of not knowing
                    # a step. Keep it out rather than inferring another state.
                    step_evidence_issue = str(exc)
                    step_evidence = []
        if semantic:
            overview=semantic['overview']
        dated_explicit=[x for x in explicit if x['date']]
        latest=([(dated_explicit or explicit)[-1]] if explicit else [])
        latest_history=(dated or timeline)[-1] if timeline else None
        if latest_history and (not latest or digest(latest[-1])!=digest(latest_history)):
            latest.append(latest_history)
        short=semantic['short_summary'] if semantic else (('原语义概况尚未覆盖最新记录；以下为当前事实整理。\n' if semantic_stale_reason else '')+overview)
        if not semantic and (latest or card_evidence):
            # Free-form prose can combine a misconception, the correction and
            # an exception, or depend on a different observation. Length and
            # source order cannot establish that a piece is safe to teach.
            short += '\n历史摘要不足，未纳入观察正文；原证据按需可追溯。'
            if explicit:
                short += '\n历史定位（仅证据状态）：' + _observation_locator(latest[0])
        page=PAGES/(key+'.md')
        next_check=semantic.get('next_check') if semantic else '依据当前真实作答核对相关具体操作；无记录不能推断掌握或错误。'
        lines=['# '+concept['label']+'｜学习路径','',
               '## 当前个性化短摘要','',short,'',
               '> [!summary] 当前个人概况',
               '> '+overview.replace('\n','\n> '),'',
               '概况状态：'+('已接受语义成稿' if semantic else '原语义成稿已过期；当前采用最新证据整理' if semantic_stale_reason else '完整证据整理；尚无跨事件语义进步裁决')+'。','',
               '## 下一次只检查','',next_check,'',
               '下方保留适用方法、个人证据与原学习日期。','']
        if frequency_summary:
            lines += ['## 讲题考频播报','']+exam_context.announcement_lines(frequency_summary)+['']
        lines += _choice_guidance_lines(choice_summary)
        lines += methods.page_lines(method_profile) + ['## 进步与待验证','']
        progress=semantic.get('progress',[]) if semantic else []
        lines += ['- '+x for x in progress] or ['尚未有经审核的跨事件进步对照；提示后完成与独立完成分别依据原始记录判断。']
        semantic_status='semantic_current' if semantic else 'semantic_stale' if semantic_stale_reason else 'evidence_digest_only'
        solution_connections = []
        if semantic:
            try:
                solution_connections = _verified_solution_connections(semantic, concepts)
            except ValueError:
                pass
        if solution_connections:
            lines += ['', '## 解题步骤之间的联系', '']
            for link in solution_connections:
                start, end = (concepts[link[k]]['label'] for k in ('from', 'to'))
                lines += [f"- {start} → {end}。{link['handoff']}。条件：{link['condition']}。"]
        exam_brief = exam.brief(method_profile, preferences, step_evidence, next_check,
                                semantic_status=semantic_status)
        lines += exam.page_lines(exam_brief)
        lines += exam_context.page_lines(objective_exam)
        if preferences:
            lines += ['','## 熟悉的讲法与偏向的解法','',
                '明确偏好、提示后有用的方式、已自主使用的路线分开记录；均不等于独立掌握。当前明确请求与数学适用条件优先。','']
            if semantic_stale_reason:
                lines += ['语义概况待更新；以下偏好的本人原话与来源哈希仍有效，因此继续保留，不代表旧概况已更新。', '']
            basis_names={'explicit_preference':'本人明确偏好','observed_helpful':'具体作答支持的有效帮助','familiar_route':'已有自主使用证据的熟悉路线'}
            for preference in preferences:
                lines += ['### '+basis_names[preference['basis']], '',
                    '适用：'+preference['scope'], '采用：'+preference['approach']]
                if 'focus' in preference:
                    lines += ['用途：'+PREFERENCE_FOCUS_TEXT[preference['focus']]]
                if preference['avoid']:
                    lines += ['避免：'+preference['avoid']]
                for ref in preference['source_refs']:
                    lines += ['', '本人原话：'+ref['quote'],
                        '来源：`'+ref['path']+'`；'+ref['locator']+'；SHA-256 `'+ref['sha256']+'`。']
        if preference_issues:
            lines += ['', '部分讲法偏好来源失效，已停止使用：', canonical(preference_issues), '']
        if step_evidence:
            lines += ['', '## 经核验的步骤证据', '',
                      '状态只绑定明确步骤ID和记录范围；不从知识点整体表现推到全部动作。', '']
            for evidence in step_evidence:
                lines += ['- '+canonical(evidence)]
        elif step_evidence_issue:
            lines += ['', '步骤证据未通过来源/字段校验：'+step_evidence_issue, '']
        lines += ['','## 涉及题目','']+[x['wikilink'] for x in linked]
        if reference_anchors:
            lines += ['','## 通用知识锚点资料','', '这些资料说明知识范围与条件，不代表本人已经学过或掌握。','']
            lines += ['- [['+a['path'].removesuffix('.md')+'|'+concept['label']+'：知识范围、公式与来源]]' for a in reference_anchors]
        if card_evidence:
            lines += ['','## 关联题卡级证据','',
                      '以下按卡级关联保留原卡中的错点与个人记录；本区不将它们归因为本知识点错误，不增加逐点错误次数、学习次数或学习日期。','']
            for item in card_evidence:
                q=links.get(item['question'],{}).get('wikilink',item['question'])
                lines += ['### '+q,'']
                origins={k:v for k,v in item['evidence_origin'].items() if v}
                if origins:
                    lines += ['原卡证据来源标记：'+canonical(origins),'']
                for statement in item['statements']:
                    lines += [statement['heading'],'',statement['text'],'']
                for ref in item['source_refs']:
                    lines += ['来源：[['+ref['path'].removesuffix('.md')+']]；SHA-256 `'+ref['sha256']+'`。','']
        lines += ['','## 完整已记录时间路径','',
                  '按已知日期和同一来源内的位置排列；同日不同来源的展示顺序不证明作答先后。','']
        for item in timeline:
            ref=item['source_refs'][0] if item['source_refs'] else None
            q=links.get(item['question'],{}).get('wikilink',str(item['question'] or '知识点复盘'))
            lines += ['### '+str(item['date'] or '时间未记录')+' · '+q,
                      item['scope']+' / '+item['kind'],'',item['text'],'']
            if item.get('observation_version'):
                if item.get('correction_text'):
                    lines += ['记录中的纠正：'+item['correction_text'], '']
                lines += [_observation_locator(item), '']
            if ref:
                lines += ['来源：[['+ref['path'].removesuffix('.md')+']]；记录位置 '+str(item['position'])+'。','']
        if not timeline:
            lines += ['暂无可归入本点的带日期学习事件；卡级证据见上节，不据此推断逐点表现。' if card_evidence
                      else '暂无可归入本点的个人学习历史；仅有相关资料或标签，不推断个人表现。']
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
            'status':semantic_status,
            'timeline_count':len(timeline),'explicit_observation_count':len(explicit),
            'first_date':dated[0]['date'] if dated else None,'latest_date':dated[-1]['date'] if dated else None,
            'page':str(page),'obsidian_url':'obsidian://open?vault=kaoyan-math&file='+quote(str(page),safe=''),
            'representative_questions':[links[x['question']] for x in reversed(latest) if x['question'] in links],
            'source_refs':[{'path':str(page),'sha256':page_source['sha256']}],
            'scope':'all_saved_matching_evidence;card_association_is_not_point_error'}
        concept['learning_profile']=profile
        if objective_exam:
            profile['exam_context'] = copy.deepcopy(objective_exam)
            profile['exam_frequency'] = copy.deepcopy(frequency_summary)
        if choice_summary.get('question_routes') or choice_summary.get('technique_candidates'):
            profile['choice_fill_guidance'] = copy.deepcopy(choice_summary)
        if method_profile:
            # Native publication copies this profile into each concept shard.
            # Keep the shared v2 graph at its method source instead of embedding
            # it repeatedly; the teaching cache below retains full route data.
            has_v2 = any('step_graph' in route or 'direct_conclusions' in route
                         for route in method_profile.get('routes', []))
            profile['problem_solving'] = methods.compact(method_profile, candidates_only=has_v2)
        if preferences:
            profile['teaching_preferences']=copy.deepcopy(preferences)
        profile['teaching_preferences_status']=('partial' if preferences and preference_issues else
            'current' if preferences else 'source_invalid' if preference_issues else 'not_recorded')
        if preference_issues:
            profile['teaching_preference_issues']=preference_issues
        if step_evidence:
            profile['step_evidence']=copy.deepcopy(step_evidence)
        if solution_connections:
            profile['solution_connections'] = copy.deepcopy(solution_connections)
        profile['step_evidence_status']=('source_invalid' if step_evidence_issue else
            'current' if step_evidence else 'not_recorded' if semantic else 'semantic_not_current')
        profile['exam_brief']=exam.reference_brief(exam_brief, profile.get('problem_solving'))
        if reference_anchors:
            concept['reference_anchors']=reference_anchors
        for view in ('protected','after_attempt','direct'):
            value={k:profile[k] for k in ('concept_key','concept_name','short_summary','progress','next_check','status','first_date','latest_date','page')}
            value['questions']=[{'formal_id':x['formal_id'],'obsidian_url':x['obsidian_url']} for x in profile['representative_questions'][:1]]
            value['progress']=value['progress'][:2]
            if reference_anchors:
                value['reference_pages']=[a['path'] for a in reference_anchors]
            if preferences and view!='protected':
                value['teaching_preferences']=compact_preferences(preferences)
                value['_preference_guards']=[_source_guards(p['source_refs'])+[semantic_ref] for p in preferences]
            if view!='protected':
                if objective_exam:
                    value['exam_context'] = exam_context.compact_context(objective_exam)
                    value['_exam_guards'] = copy.deepcopy(exam_registry['source_refs'])
                value['teaching_preferences_status']=profile['teaching_preferences_status']
                value['step_evidence_status']=profile['step_evidence_status']
                value['exam_brief']=copy.deepcopy(exam_brief)
                if semantic:
                    value['_semantic_guards']=_source_guards(semantic.get('source_refs',[]))+[semantic_ref]
                if step_evidence:
                    value['step_evidence']=copy.deepcopy(step_evidence)
                if solution_connections:
                    value['solution_connections'] = [
                        {**{k: link[k] for k in ('from', 'to', 'condition', 'handoff')},
                         'from_name': concepts[link['from']]['label'],
                         'to_name': concepts[link['to']]['label']}
                        for link in solution_connections]
            if method_profile and view!='protected':
                # Keep source paths internally for exact stat guards. They are
                # removed before the query response is returned.
                value['problem_solving'] = copy.deepcopy(method_profile)
            if view=='protected':
                value={k:profile[k] for k in (
                'concept_key','concept_name','status','timeline_count','explicit_observation_count','first_date','latest_date')}
            hot_rows.append((key,view,canonical(value)))
    page_index += ['- [['+str(PAGES/(key+'.md')).removesuffix('.md')+'|'+concept['label']+']]'
                   for key,concept in concepts.items()]
    active_key = '__registry__'
    if registry and refresh_registry:
        # Exact step/conclusion IDs close the bounded-reader reference loop.
        # These are material objects, not new personal concepts or observations.
        reference_rows = []
        reference_keys = set()
        observed_hashes = {path: source['sha256'] for path, source in sources.items()}

        def observed_hash(path):
            if path not in observed_hashes:
                target = root/path
                observed_hashes[path] = read_source(target, 'external')['sha256'] if target.is_file() else None
            return observed_hashes[path]

        catalog_ref = {'path': str(methods.CATALOG), 'sha256': observed_hash(str(methods.CATALOG))}
        for field, id_field, role in (('steps', 'step_id', 'step_reference'),
                                     ('conclusions', 'conclusion_id', 'conclusion_reference')):
            for reference_id, node in registry.get(field, {}).items():
                key = methods.alias_key(reference_id)
                reference_keys.add(key)
                refs = node['source_refs']
                if not all(observed_hash(ref['path']) == ref['sha256'] for ref in refs):
                    continue
                reference_rows.append((key, {
                    'concept_key': key, 'reference_id': reference_id, 'object_role': role,
                    'status': 'source_based', 'reference_status': 'verified',
                    'personal_history_status': 'not_applicable',
                    'evidence_policy': 'reference_material_only;no_personal_learning_or_mastery_claim',
                    role: copy.deepcopy(node),
                    '_reference_guards': [catalog_ref] + _source_guards(refs),
                }))
        for key, alias in registry['aliases'].items():
            if key in reference_keys:
                # An explicit object ID has priority over an incidental method
                # name/trigger alias with the same normalized spelling.
                continue
            projected = methods.project(registry, alias['bindings'], 'method_alias_only')
            for view in ('after_attempt', 'direct'):
                hot_rows.append((key, view, canonical({
                    'concept_key': key, 'concept_name': alias['names'][0],
                    'status': 'source_based', 'personal_history_status': 'not_resolved',
                    'problem_solving': projected,
                    'exam_brief': exam.brief(projected, semantic_status='source_based')})))
        for key, value in reference_rows:
            for view in ('after_attempt', 'direct'):
                hot_rows.append((key, view, canonical(value)))
    write_changed(root/PAGES/'index.md','\n'.join(page_index)+'\n')
    return hot_rows


def _linked_refinement_ids(projections):
    """Only explicit children of the current guarded method families."""
    result=[]
    for projected in projections:
        if not projected or projected.get('status') not in ('available','partial'):
            continue
        for route in projected.get('routes',[]):
            if route.get('status')=='stale':
                continue
            candidates=list(route.get('refinement_ids',[]))
            candidates += [row.get('method_id') for row in route.get('refinement_candidates',[]) if row.get('status')!='stale']
            stale=set(route.get('refinement_stale_ids',[]))
            result.extend(mid for mid in candidates if isinstance(mid,str) and mid not in stale and mid not in result)
    return result


def _choice_guidance_lines(guidance):
    if not guidance or not (guidance.get('question_routes') or guidance.get('technique_candidates')):
        return []
    lines=['','## 可执行的选填技巧与二级结论','',
           '以下是已核资料候选；当前题须满足全部条件且足以定解才优先采用，不证明本人掌握，不自动选第一项。','']
    for row in guidance.get('question_routes',[]):
        lines += [row['specific_hint'],'']
    for row in guidance.get('technique_candidates',[]):
        lines += ['### '+row.get('name',row['method_id']),'',
                  '适用条件：'+'；'.join(row.get('conditions',[])),
                  '第一动作：'+row['first_action'],'']
        lines += [str(i)+'. '+step for i,step in enumerate(row.get('steps',[]),1)]
        for conclusion in row.get('direct_conclusions',[]):
            label='二级结论（须核条件）：' if conclusion.get('direct_use') else '来源结论（未标为可直接套用）：'
            lines += ['', label, '', '$$',conclusion['statement_latex'],'$$','',
                      '条件：'+'；'.join(conclusion.get('conditions',row.get('conditions',[])))]
            exceptions=conclusion.get('exceptions',row.get('pitfalls',[]) if conclusion.get('exceptions_ref') else [])
            if exceptions:lines += ['例外/边界：'+'；'.join(exceptions)]
    if guidance.get('status')=='bounded_candidates':
        lines += ['', '本页保留当前完整候选；未展示项不表示不适用。']
    return lines+['']


def _deduplicate_frequency_contexts(response):
    """All required years/counts remain in this response's unique frequency brief."""
    brief=response.get('exam_frequency')
    if not brief:
        return
    for context in brief.get('contexts',[]):
        if context.get('source_version')==brief.get('source_version'):
            context.pop('source_version',None)
        if context.get('relation') in ('exact','broader_topic') and context.get('scope_note'):
            context.pop('frequency_scope',None)
    for row in response.get('records',[]):
        context=row.get('exam_context')
        if context:
            row['exam_context']={'status':context.get('status'),
                'detail_ref':'response.exam_frequency'}


def _fallback_candidates(conn, queries, fallback_concepts, view, limit, exclude_keys=()):
    """Retrieve bounded references, never promote lexical similarity to identity.

    Exact declared aliases stay in the ordinary lookup. This second pass reads
    only current prepared profiles; every result still needs a live scope check.
    """
    import math_concept_index as native
    if limit <= 0:
        return []
    available = {key: label for key, label in conn.execute(
        'SELECT c.key,c.label FROM concepts c JOIN teaching_profiles t ON t.key=c.key WHERE t.view=?',
        (view,)) if key not in exclude_keys}
    ranked = {}
    for query in fallback_concepts or []:
        for key, in conn.execute('SELECT key FROM lookup WHERE name=? ORDER BY key', (native.normalize(query),)):
            if key in available:
                ranked[key] = (4, len(native.normalize(query)), 'explicit_scope_reference', query)
    aliases = list(conn.execute('SELECT name,key FROM lookup ORDER BY name,key'))
    for query in queries:
        normalized = native.normalize(query)
        if len(normalized) < 4 or normalized.startswith('math-concept-'):
            continue
        for name, key in aliases:
            if key not in available or len(name) < 4 or name.startswith('math-concept-'):
                continue
            if name in normalized:
                score = (3, len(name), 'contained_label_or_alias', query)
                if score > ranked.get(key, (0, 0, '', '')):
                    ranked[key] = score
        query_pairs = {normalized[i:i+2] for i in range(len(normalized)-1)}
        for key, label in available.items():
            name = native.normalize(label)
            pairs = {name[i:i+2] for i in range(len(name)-1)}
            overlap = len(query_pairs & pairs)
            similarity = difflib.SequenceMatcher(None, normalized, name).ratio()
            if overlap >= 2 and similarity >= 0.55:
                score = (2, similarity, 'similar_label_reference', query)
                if score > ranked.get(key, (0, 0, '', '')):
                    ranked[key] = score
    ordered = sorted(ranked, key=lambda key: (-ranked[key][0], -ranked[key][1], available[key], key))
    return [{'concept_key': key, 'concept_name': available[key],
             'query': ranked[key][3], 'basis': ranked[key][2],
             'requires_scope_check': True} for key in ordered[:limit]]


@lru_cache(maxsize=4)
def _visual_manifest_rows(path, mtime_ns, size):
    return json.loads(path.read_text(encoding='utf-8')).get('records', [])


def _formal_question_images(root, formal_id, card_path):
    from wrongnet import as_list, split_front_matter

    assets = root/'错题知识网络/assets/visual_wrong_questions'
    manifest = root/'错题知识网络/可视化错题详情/manifest.json'
    excluded = set()
    declared = []
    if manifest.is_file():
        stat = manifest.stat()
        for row in _visual_manifest_rows(manifest, stat.st_mtime_ns, stat.st_size):
            paths = as_list(row.get('question_assets'))
            suspect = row.get('link_status') == 'suspect_wrongnet_mismatch'
            if (formal_id in as_list(row.get('excluded_wrongnet_ids'))
                    or (suspect and row.get('wrongnet_id_original_suspect') == formal_id)):
                excluded.update((root/path).resolve() for path in paths)
            elif not suspect and row.get('wrongnet_id') == formal_id:
                declared.extend(paths)

    direct = {path.resolve() for path in (assets/formal_id).glob('question_*') if path.is_file()}
    visible = {path for path in direct - excluded if path.is_relative_to(assets)}
    if not visible:
        # A verified original can live under a historical card's asset folder.
        # Use only exact refs from the formal card and its registered sources.
        if card_path:
            meta, _ = split_front_matter((root/card_path).read_text(encoding='utf-8'))
            declared.extend(as_list(meta.get('lecture_refs')))
        for ref in declared:
            path = (root/ref).resolve()
            if (path.is_relative_to(assets) and path.name.startswith('question_')
                    and path not in excluded and path.is_file()):
                visible.add(path)
    return sorted(path.relative_to(root).as_posix() for path in visible)


def resolve(repo_root, concepts, view='protected', max_bytes=12000, known_version=None, formal_id=None, source_id=None,
            fallback_concepts=None):
    import math_concept_index as native
    import math_problem_methods as methods
    import math_exam_profile as exam
    import math_exam_context
    explicit_concepts = bool(concepts)
    root=Path(repo_root).resolve()
    with closing(sqlite3.connect(_read_only_uri(root/native.INDEX),uri=True)) as conn:
        conn.execute('BEGIN')
        source_lookup = _source_lookup(conn)
        meta={k:json.loads(v) for k,v in conn.execute("SELECT key,value FROM meta WHERE key IN ('version','implementation','store_stamps','directories','alias_problems','scope_notes','require_scope_check')")}
        import math_memory_projection
        freshness = math_memory_projection.check_query_dependencies(root, conn)
        changed = freshness['changed_sources']
        exam_changed = freshness['exam_changed']
        if changed:
            return {'status':'stale','reason':'formal_sources_changed','records':[]}
        identity=None
        exact_method = None
        formal_source = None
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
            formal_source = next((r for r in record['source_refs'] if '/错题卡/' in r['path']), None)
            if view != 'protected':
                exact_method = record.get('metadata', {}).get('problem_solving')
            if not concepts:
                concepts=record.get('labels',[])[:3]
            card=next((r['path'] for r in record['source_refs'] if '/错题卡/' in r['path']),None)
            identity={'kind':'formal_card','formal_id':formal_id,'card_path':card}
            identity['question_images']=_formal_question_images(root, formal_id, card)
        if view=='protected' and identity:
            # Formal filenames may contain the method or result in their title.
            # The neutral ID and original question images suffice before an attempt.
            identity={k:v for k,v in identity.items() if k!='card_path'}
        keys=[];unknown=[];ambiguous=[];suggestions={};query_key_groups=[]
        bad={native.normalize(x['alias']) for x in meta.get('alias_problems',[])}
        for q in concepts:
            if native.normalize(q) in bad:
                ambiguous.append(q);query_key_groups.append([]);continue
            found=[k for k, in conn.execute('SELECT l.key FROM lookup l JOIN concepts c ON c.key=l.key WHERE l.name=? ORDER BY (c.normalized=?) DESC,c.label,l.key',(native.normalize(q),native.normalize(q)))]
            if not found:
                unknown.append(q)
                # A named textbook method can still help with an unseen point.
                # Preserve the failed personal lookup rather than manufacturing
                # a personal profile for the method alias.
                if view != 'protected':
                    alias = methods.alias_key(q)
                    alias_row = conn.execute('SELECT payload FROM teaching_profiles WHERE key=? AND view=?', (alias, view)).fetchone()
                    if alias_row:
                        found = [alias]
                        if json.loads(alias_row[0]).get('object_role') in ('step_reference', 'conclusion_reference'):
                            unknown.remove(q)
            keys.extend(k for k in found if k not in keys)
            query_key_groups.append(found)
        recovery = _fallback_candidates(conn, unknown, fallback_concepts, view, 3-len(keys), keys) if unknown else []
        for candidate in recovery:
            if candidate['concept_key'] not in keys:
                keys.append(candidate['concept_key'])
            suggestions.setdefault(candidate['query'], []).append(candidate)
        freshness = math_memory_projection.check_query_dependencies(root, conn, keys)
        if freshness['changed_sources']:
            stale = {'status': 'stale', 'reason': 'selected_sources_changed', 'records': []}
            if view != 'protected':
                stale['changed_sources'] = freshness['changed_sources']
            return stale
        exam_changed = sorted(set(exam_changed + freshness['exam_changed']))
        rows = []
        method_states = []

        def prepared_method(value, card_source=None, preserve_routes=False):
            result = methods.checked_projection(root, conn, value, card_source,
                                                preserve_routes=preserve_routes, source_lookup=source_lookup)
            method_states.append({'status': result['status'], 'route_states': [
                [r['method_id'], r.get('status', 'available'), r.get('binding_status')] for r in result['routes']]})
            return result

        for key in keys:
            row=conn.execute('SELECT payload FROM teaching_profiles WHERE key=? AND view=?',(key,view)).fetchone()
            if not row:
                continue
            value=json.loads(row[0])
            candidate = next((item for item in recovery if item['concept_key'] == key), None)
            if candidate:
                value['retrieval_scope'] = {'role': 'candidate_reference',
                    'basis': candidate['basis'], 'requires_scope_check': True,
                    'not_proof_of_current_error': True}
            if view != 'protected':
                if (value.get('status') in {'evidence_digest_only', 'semantic_stale'}
                        and meta.get('implementation', 0) < native.ATOMIC_OBSERVATION_IMPLEMENTATION):
                    # A pre-upgrade cache may still contain an old prefix. Keep
                    # current references and semantic profiles usable; do not rebuild on read.
                    value['short_summary'] = '历史摘要版本较旧，未载入观察正文；原证据按需可追溯。'
                value = _checked_personal_context(root, conn, value, source_lookup=source_lookup)
                if view == 'after_attempt':
                    value = _after_attempt_personal_context(value)
                if exam_changed and value.get('object_role') not in ('step_reference', 'conclusion_reference'):
                    value['exam_context'] = math_exam_context.stale(value.get('exam_context'))
            else:
                value = {k: value[k] for k in ('concept_key', 'concept_name', 'status',
                    'timeline_count', 'explicit_observation_count', 'first_date', 'latest_date') if k in value}
            if value.get('problem_solving'):
                value['problem_solving'] = prepared_method(value['problem_solving'])
            rows.append(value)
        exact_method = prepared_method(exact_method, formal_source, preserve_routes=True) if exact_method else None
        guarded_methods=[row['problem_solving'] for row in rows if row.get('problem_solving')]
        # A family may expose only a few refinements in its compact view. Fetch
        # only its explicitly named children from the same local read transaction.
        # Authored review metadata, not an ID/name prefix, identifies techniques.
        extra_choice_methods=[]
        if view!='protected':
            ids=_linked_refinement_ids(([exact_method] if exact_method else [])+guarded_methods)
            alias_keys=[methods.alias_key(mid) for mid in ids]
            for start in range(0,len(alias_keys),400):
                part=alias_keys[start:start+400]
                placeholders=','.join('?' for _ in part)
                found=dict(conn.execute('SELECT key,payload FROM teaching_profiles WHERE view=? AND key IN ('+placeholders+')', [view]+part))
                for alias_key in part:
                    payload=found.get(alias_key)
                    if payload is None:continue
                    candidate=json.loads(payload).get('problem_solving')
                    if candidate and any(methods.is_reviewed_choice_fill(r) for r in candidate.get('routes',[])):
                        extra_choice_methods.append(prepared_method(candidate,preserve_routes=True))
        choice_budget=max(5000,max_bytes//2)
        choice_guidance=exam.choice_fill_guidance(exact_method,guarded_methods+extra_choice_methods,
            view=view,max_bytes=choice_budget) if view!='protected' else None
        if choice_guidance and choice_guidance.get('status')=='budget_too_small':
            # Material is already read and guarded. Keep one whole executable
            # atom in memory so the outer envelope can state its true minimum.
            needed=choice_guidance.get('required_min_bytes')
            if isinstance(needed,int):
                choice_guidance=exam.choice_fill_guidance(exact_method,guarded_methods+extra_choice_methods,
                    view=view,max_bytes=needed+512,max_candidates=1)
        frequency_brief=math_exam_context.brief_for_records(rows,view=view)
        exact_method, suppressed = methods.align_formal_to_current_concept(
            exact_method, rows, query_key_groups[0] if query_key_groups else [], explicit_concepts)
        for row in rows:
            if row['concept_key'] in suppressed:
                row.pop('problem_solving', None)
            if view != 'protected' and row.get('object_role') not in ('step_reference', 'conclusion_reference'):
                # Rebuild after all source guards and exact-card alignment, so
                # a stale or suppressed method cannot survive in a second copy.
                row['exam_brief'] = exam.brief(row.get('problem_solving'),
                    row.get('teaching_preferences', []), row.get('step_evidence', []),
                    row.get('next_check', ''), semantic_status=row.get('status'))
                row['exam_brief'].pop('selection_context', None)
                row['exam_brief']['selection_context_ref'] = 'response.selection_context'
        visible_methods = ([exact_method] if exact_method else []) + [
            row['problem_solving'] for row in rows if row.get('problem_solving')]
        method_states = [{'status': value['status'], 'route_states': [
            [route['method_id'], route.get('status', 'available'), route.get('binding_status')]
            for route in value.get('routes', [])]} for value in visible_methods]
        personal_states = [{k: row.get(k) for k in ('status', 'teaching_preferences_status',
            'teaching_preferences', 'step_evidence_status', 'step_evidence',
            'reference_status', 'exam_context')} for row in rows]
        query_version=digest(['chat-links-v9-scoped-personal-views',meta['version'],keys,view,identity,concepts,
                              fallback_concepts,recovery,
                              explicit_concepts,max_bytes,method_states,personal_states,frequency_brief,choice_guidance])
        base={'status':'available','version':query_version,'source_version':meta['version'], 'identity':identity,
              'unknown':unknown,'ambiguous':ambiguous,'view':view,'records':[],
              'total':len(keys),'returned':0,'truncated':bool(keys)}
        if method_states:
            states = {row['status'] for row in method_states}
            base['method_status'] = next(iter(states)) if len(states) == 1 else 'partial'
        if suggestions:base['suggestions']=suggestions
        if unknown:
            base['resolution'] = {'status': 'candidate_references' if recovery else 'no_candidate',
                'unmatched_queries': unknown, 'candidates': recovery,
                'requires_scope_check': bool(recovery),
                'policy': '候选摘要已读取；按当前题对象与操作核对后使用。相似名称不证明同一细点或本轮复发，父主题考次不冒充细点考次。'}
        if view!='protected':
            base['exam_frequency']=frequency_brief
            base['choice_fill_guidance']=choice_guidance
        if exact_method:
            base['problem_solving'] = exact_method
            base['exam_brief'] = exam.brief(exact_method)
            base['exam_brief'].pop('selection_context', None)
            base['exam_brief']['selection_context_ref'] = 'response.selection_context'
            base['exam_brief']['personal_context_refs'] = [r['concept_key'] for r in rows]
        if view != 'protected' and (exact_method or any(
                row.get('object_role') not in ('step_reference', 'conclusion_reference') for row in rows)):
            base['selection_context'] = copy.deepcopy(exam.SELECTION_CONTEXT)
        scope=meta.get('scope_notes',{})
        base['scope_notes']={q:scope[q] for q in concepts if q in scope} if view!='protected' else {}
        personal = None
        if view != 'protected' and len(rows) == 1 and not recovery and not unknown and not ambiguous:
            row = rows[0]
            if row.get('status') == 'semantic_current' and row.get('short_summary') and row.get('next_check'):
                personal = {key: row[key] for key in ('concept_key', 'concept_name', 'status', 'short_summary',
                                                     'next_check', 'personal_fields_withheld') if key in row}
        total=0
        for value in rows:
            total+=1
            for question in value.get('questions', []):
                formal = question.get('formal_id', '')
                if re.fullmatch(r'(?:GS|LA|PR)-\d+', formal) and question.get('obsidian_url'):
                    question['chat_link'] = f'{formal}（[在 Obsidian 打开](http://127.0.0.1:8765/open/{formal})）'
            base['records'].append(value)
            base['returned'] = len(base['records'])
            base['truncated'] = len(base['records']) < len(keys)
            if len(canonical(base).encode())>max_bytes:
                # Remove redundant navigation/progress metadata before reducing
                # source-backed teaching content. Never slice text or conditions.
                for item in base['records']:
                    if item.pop('progress', []):
                        item['progress_omitted'] = True
                    for field in ('questions', 'first_date', 'latest_date', 'reference_pages', 'page'):
                        item.pop(field, None)
                base.pop('suggestions', None)
                _deduplicate_frequency_contexts(base)
                # Deduplicate first, then defer bulky provenance/refinements,
                # then whole execution graphs/formulas. Short legacy steps stay
                # useful longer; every candidate's conditions remain intact.
                for level in range(6):
                    if len(canonical(base).encode()) <= max_bytes:
                        break
                    exam.apply_response_budget(base, level)
                if len(canonical(base).encode())>max_bytes:
                    required_bytes = len(canonical(base).encode())
                    base['records'].pop()
                    if not base['records']:
                        base.pop('problem_solving', None)
                        base.pop('exam_brief', None)
                        base['required_min_bytes'] = required_bytes
                    break
        base.update(total=len(keys),returned=len(base['records']),truncated=len(base['records'])<len(keys))
        if not base['records']:
            base['status']='budget_too_small' if total else 'unknown_concept' if not keys else 'index_missing'
            if exact_method and not keys and 'required_min_bytes' not in base:
                base['status'] = (exact_method['status'] if exact_method['status'] in ('source_hold', 'identity_alias')
                                  else 'source_based' if exact_method['status'] == 'available' else 'method_stale')
                for level in range(6):
                    if len(canonical(base).encode()) <= max_bytes:
                        break
                    exam.apply_response_budget(base, level)
                if len(canonical(base).encode()) > max_bytes:
                    base.pop('problem_solving', None)
                    base.pop('exam_brief', None)
                    base['status'] = 'budget_too_small'
            if base['status'] == 'budget_too_small':
                base.pop('selection_context', None)
        elif all(row.get('status') == 'source_based' for row in base['records']):
            base['status'] = 'source_based'
        elif all(row.get('object_role') in ('step_reference', 'conclusion_reference')
                 and row.get('reference_status') == 'stale' for row in base['records']):
            base['status'] = 'source_changed'
        slim = _low_budget_personal(base, personal, frequency_brief, max_bytes)
        if slim is not None:
            return slim
        if len(canonical(base).encode())>max_bytes:
            # Never claim a complete answer while silently dropping required
            # frequency years or a technique's conditions/formula.
            required=max(base.get('required_min_bytes',0),len(canonical(base).encode()))
            return {'status':'budget_too_small','version':query_version,'source_version':meta['version'],
                    'view':view,'records':[],'returned':0,'total':len(keys),'truncated':True,
                    'required_min_bytes':required,
                    'required_fields':['exam_frequency','choice_fill_guidance','personal_summary'],
                    'retry_scope':'same_identity_concepts_and_view_with_required_budget'}
        if (known_version == query_version and all(row['status'] == 'available' for row in method_states)
                and not any(row.get('exam_context', {}).get('status') == 'stale' for row in rows)):
            from math_teaching_delivery import has_delivery_gap
            if not has_delivery_gap(base):
                return {**{key: base[key] for key in ('version', 'source_version', 'identity', 'view') if key in base},
                        'status': 'unchanged', 'records': []}
        return base


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[2])
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('refresh')
    prep=sub.add_parser('prepare');prep.add_argument('--input',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    contributions=sub.add_parser('inspect-contributions',help='Read one original A batch and its exact staged receipts')
    contributions.add_argument('--batch-id',required=True)
    contributions.add_argument('--receipt',type=Path,action='append',default=[])
    accept=sub.add_parser('accept');accept.add_argument('--input',type=Path,required=True);accept.add_argument('--event-id',required=True,action='append',help='Repeat for all real closeouts of the same A batch')
    for command, help_text in (
        ('accept-maintenance', 'Rewrite summaries against unchanged prepared evidence; no learning event'),
        ('resume-maintenance', 'Verify the prepared request is already accepted and resume only its derived work'),
    ):
        maintenance=sub.add_parser(command,help=help_text)
        maintenance.add_argument('--input',type=Path,required=True)
        maintenance.add_argument('--maintenance-reason',required=True)
        publication=maintenance.add_mutually_exclusive_group()
        publication.add_argument('--refresh-only',action='store_true',help='Compatible spelling for the default local refresh')
        publication.add_argument('--publish',action='store_true',help='Request a replica for an authorized shared or external handoff')
    args=parser.parse_args()
    if args.command=='refresh':
        import math_concept_index
        result=math_concept_index.build_index(args.repo)
        result={k:result[k] for k in ('status','version','concept_count','record_count')}
    elif args.command=='prepare':
        result=prepare_updates(args.repo,json.loads(args.input.read_text()))
        write_changed(args.output,result);result={'status':'prepared','output':str(args.output),'concept_count':len(result['updates'])}
    elif args.command=='inspect-contributions':
        import math_A_profile_merge
        try:
            result=math_A_profile_merge.inspect(args.repo.resolve(),args.batch_id,args.receipt)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(canonical({'status':'error','reason':str(exc)}))
            return 1
    elif args.command in ('accept-maintenance', 'resume-maintenance'):
        prepared=json.loads(args.input.read_text())
        if args.command=='accept-maintenance':
            result=accept_maintenance(args.repo,prepared,args.maintenance_reason)
        else:
            result=recover_maintenance(args.repo,prepared,args.maintenance_reason)
        try:
            result=finish_maintenance(args.repo,result,refresh_only=args.refresh_only,publish=args.publish)
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            print(canonical({**result, 'accept_status':result['status'], 'status':'local_refresh_pending',
                             'reason':str(exc), 'retry_command':'resume-maintenance'}))
            return 1
    else:
        result=accept_updates(args.repo,json.loads(args.input.read_text()),args.event_id)
        import math_postcommit
        result['postcommit']=math_postcommit.run_after_commit(args.repo,result['event_id'])
    print(canonical(result))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
