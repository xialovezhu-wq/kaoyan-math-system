"""Evidence-bound memory revisions and two-time reads.

The existing profile writer is the only mutation entry. This module never
creates a study, score, Capture, or formal closeout. Corrections are immutable
maintenance transactions; original observations remain available verbatim.
"""
from __future__ import annotations

import copy
from contextlib import closing
from datetime import datetime, time, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from zoneinfo import ZoneInfo

BASE = Path('错题知识网络/个人知识点索引')
SEMANTIC = BASE / '语义概况'
TRANSACTIONS = BASE / '记忆维护/transactions'
SCHEMA = 'math-memory-maintenance-v1'
CLAIM_BASES = {'user_observed', 'user_confirmed', 'self_reported', 'assistant_inferred', 'source_verified'}
CLAIM_STATES = {'active', 'candidate', 'superseded', 'retracted', 'conflicted'}
OUTCOMES = {'wrong', 'unresolved', 'corrected_after_hint', 'independent_correct'}
HEX = re.compile(r'[a-f0-9]{64}')
IDENTITY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}')
SHANGHAI = ZoneInfo('Asia/Shanghai')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _moment(value, *, end=False):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('memory_time_must_be_iso_text_or_null')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        day = datetime.strptime(value, '%Y-%m-%d').date()
        return datetime.combine(day, time.max if end else time.min, SHANGHAI)
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('memory_timestamp_timezone_required')
    return parsed


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('memory_text_required:' + field)
    return value


def _id(value, field):
    if not isinstance(value, str) or not IDENTITY.fullmatch(value):
        raise ValueError('memory_identity_invalid:' + field)
    return value


def _safe_json(root, path):
    root, path = Path(root).resolve(), Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('memory_path_outside_repository')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('memory_object_required')
    return value


def observation_hash(observation):
    """Hash the immutable source observation, never its derived correction view."""
    if isinstance(observation, dict) and isinstance(observation.get('raw_observation'), dict):
        observation = observation['raw_observation']
    ignored = {'observation_sha256', 'memory_status', 'memory_correction_ids', 'raw_observation'}
    return digest({k: v for k, v in observation.items() if k not in ignored})


def claim_hash(claim):
    return digest({k: v for k, v in claim.items()
                   if k not in {'claim_sha256', 'memory_status', 'memory_correction_ids',
                                'recorded_at', 'profile_revision'}})


def _source_refs(root, refs, *, user_quote=False, native_user=False):
    import math_learning_profiles as profiles
    if not isinstance(refs, list) or not refs or len(refs) > 16:
        raise ValueError('memory_evidence_required')
    has_user = False
    checked = []
    for ref in refs:
        checked.append(profiles.safe_source(Path(root).resolve(), ref))
        if 'quote' in ref:
            _text(ref['quote'], 'quote')
            if ref.get('role') not in {'user', 'assistant'}:
                raise ValueError('memory_quote_role_required')
            source = json.loads((Path(root) / ref['path']).read_text())
            if not profiles._role_quote_matches(source, ref, ref['role']):
                raise ValueError('memory_quote_or_role_mismatch')
            has_user |= (ref['role'] == 'user' and (not native_user or
                         profiles._recorded_role_quote(Path(root).resolve(), ref, 'user')))
    if user_quote and not has_user:
        raise ValueError('memory_correction_user_quote_required')
    return copy.deepcopy(checked)


def _indexed_observations(root, keys):
    import math_concept_index as native
    import math_learning_profiles as profiles
    result = []
    if not keys:
        return result
    with closing(sqlite3.connect(profiles._read_only_uri(Path(root)/native.INDEX), uri=True)) as conn:
        conn.execute('BEGIN')
        for key in sorted(set(keys)):
            for body, in conn.execute('SELECT r.payload FROM records r JOIN membership m ON r.id=m.record_id WHERE m.key=?', (key,)):
                row = json.loads(body)
                if row.get('kind') not in {'formal_concept_observation', 'concept_review'}:
                    continue
                summary = row.get('summary', {})
                for observation in summary.get('observations', []):
                    refs = copy.deepcopy(row.get('source_refs', []))
                    history = row.get('history', {})
                    for package in history.get('packages', {}).values():
                        refs.extend(copy.deepcopy(package.get('source_refs', [])))
                    refs = list({(r['path'], r['sha256']): r for r in refs}.values())
                    quotes = copy.deepcopy(observation.get('user_evidence', []))
                    conversation = history.get('conversation', [])
                    for position in observation.get('user_turn_indices', []):
                        if type(position) is int and 0 <= position < len(conversation):
                            turn = conversation[position]
                            if turn.get('role') == 'user' and isinstance(turn.get('text'), str):
                                quotes.append({'turn_index': position, 'quote': turn['text']})
                    result.append({'concept_key': key, 'event_id': summary['event_id'],
                                   'observation_sha256': observation_hash(observation),
                                   'observation': observation, 'study_date': summary.get('study_date'),
                                   'source_refs': refs, 'user_evidence': quotes})
    return result


def _check_claim_revision_scope(row, previous, claims):
    targets = row.get('claim_revision_targets', {})
    if (not isinstance(targets, dict) or len(targets) > 64
            or any(not isinstance(cid, str) or not IDENTITY.fullmatch(cid)
                   or not isinstance(sha, str) or not HEX.fullmatch(sha)
                   for cid, sha in targets.items())):
        raise ValueError('memory_claim_revision_targets_invalid')

    current = {claim['claim_id']: claim for claim in claims}
    removed = previous.keys() - current.keys()
    affected = set(removed)
    for cid, claim in current.items():
        if previous.get(cid) == claim:
            continue
        if cid in previous:
            affected.add(cid)
        # A new or revised edge can change a predecessor while its row is identical.
        if claim['basis'] != 'assistant_inferred' and claim['status'] in {'active', 'conflicted'}:
            affected.update(claim.get('conflicts_with', []))
            if claim['status'] == 'active':
                affected.update(claim.get('supersedes', []))
    if affected and not str(row.get('claims_revision_reason', '')).strip():
        raise ValueError('memory_claims_revision_reason_required')
    unauthorized = {cid for cid in affected if targets.get(cid) != claim_hash(previous[cid])}
    if unauthorized:
        raise ValueError('memory_claim_revision_scope_violation:'+','.join(sorted(unauthorized)))

    # Withdrawal of a live claim uses the native exact correction and leaves
    # its row available to the effective-time reader. Prune only retired rows.
    cutoff = datetime.now(timezone.utc)
    for cid in sorted(removed):
        claim = previous[cid]
        end = _moment(claim.get('valid_to'))
        if claim['status'] not in {'retracted', 'superseded'} and (end is None or end > cutoff):
            raise ValueError('memory_claim_removal_requires_retirement:'+cid)


def prepare_claims(root, row):
    """Keep implicit claims and validate the scope of explicit revisions."""
    row = copy.deepcopy(row)
    path = Path(root)/SEMANTIC/(row['concept_key']+'.json')
    old = _safe_json(root, path) if path.is_file() else {}
    previous = old.get('claims', [])
    if 'claims' not in row and not previous and 'claim_revision_targets' not in row:
        return row
    values = row.get('claims', previous)
    if not isinstance(values, list) or len(values) > 64:
        raise ValueError('memory_claims_must_be_bounded_array')
    observations = _indexed_observations(root, [row['concept_key']])
    known_observations = {(v['event_id'], v['observation_sha256']): v for v in observations}
    known_claims = {c['claim_id']: c for c in previous}
    seen, prepared = set(), []
    required = {'claim_id', 'content', 'scope', 'basis', 'status', 'source_refs', 'observation_refs'}
    optional = {'valid_from', 'valid_to', 'supersedes', 'conflicts_with'}
    for value in values:
        if not isinstance(value, dict) or not required <= value.keys() or set(value)-required-optional:
            raise ValueError('memory_claim_fields_required')
        cid = _id(value['claim_id'], 'claim_id')
        if cid in seen:
            raise ValueError('memory_duplicate_claim_id')
        seen.add(cid)
        for field in ('content', 'scope'):
            _text(value[field], field)
        if value['basis'] not in CLAIM_BASES or value['status'] not in CLAIM_STATES:
            raise ValueError('memory_claim_basis_or_status_invalid')
        if value['basis'] == 'assistant_inferred' and value['status'] == 'active':
            raise ValueError('memory_inference_cannot_be_confirmed_fact')
        refs = _source_refs(root, value['source_refs'])
        bindings = value['observation_refs']
        if not isinstance(bindings, list) or len(bindings) > 64:
            raise ValueError('memory_observation_refs_required')
        for ref in bindings:
            if not isinstance(ref, dict) or set(ref) != {'event_id', 'observation_sha256'}:
                raise ValueError('memory_exact_observation_reference_required')
            if (ref['event_id'], ref['observation_sha256']) not in known_observations:
                raise ValueError('memory_observation_binding_not_in_concept')
        if value['basis'] in {'user_observed', 'user_confirmed', 'self_reported'}:
            new = value != known_claims.get(cid)
            if not bindings:
                _source_refs(root, refs, user_quote=True, native_user=new)
            elif new:
                observed_sources = {r['sha256'] for ref in bindings for r in known_observations[
                    (ref['event_id'], ref['observation_sha256'])]['source_refs']}
                if not observed_sources.intersection(r['sha256'] for r in refs):
                    raise ValueError('memory_claim_requires_native_observation_source')
        start, stop = _moment(value.get('valid_from')), _moment(value.get('valid_to'))
        if start and stop and stop <= start:
            raise ValueError('memory_claim_time_range_invalid')
        for field in ('supersedes', 'conflicts_with'):
            relations = value.get(field, [])
            if not isinstance(relations, list) or len(relations) != len(set(relations)):
                raise ValueError('memory_claim_relation_array_required')
            for predecessor in relations:
                _id(predecessor, field)
                if predecessor == cid or predecessor not in known_claims:
                    raise ValueError('memory_claim_predecessor_unknown')
        prepared.append({**value, 'source_refs': refs})
    _check_claim_revision_scope(row, known_claims, prepared)
    row['claims'] = prepared
    refs = row['source_refs']
    present = {(r['path'], r['sha256']) for r in refs}
    for claim in prepared:
        for ref in claim['source_refs']:
            if (ref['path'], ref['sha256']) not in present:
                refs.append({'path': ref['path'], 'sha256': ref['sha256']})
                present.add((ref['path'], ref['sha256']))
    return row


def transactions(root):
    """Read immutable native maintenance receipts, rejecting corrupt identities."""
    root = Path(root).resolve()
    directory = root/TRANSACTIONS
    if not directory.exists():
        return []
    if directory.is_symlink():
        raise ValueError('memory_transaction_directory_unsafe')
    values = []
    for path in sorted(directory.glob('*.json')):
        value = _safe_json(root, path)
        expected = value.get('content_sha256')
        if (value.get('schema') != SCHEMA or not isinstance(expected, str)
                or expected != digest({k: v for k, v in value.items() if k != 'content_sha256'})
                or not isinstance(value.get('request_id'), str)
                or not isinstance(value.get('corrections'), list)
                or not isinstance(value.get('recorded_at'), str)
                or path.name != digest(value.get('request_id'))+'.json'):
            raise ValueError('memory_transaction_integrity_invalid')
        _moment(value.get('recorded_at'))
        values.append(value)
    return sorted(values, key=lambda x: (x['recorded_at'], x['request_id']))


def version(root, concept_keys=None):
    keys = set(concept_keys) if concept_keys is not None else None
    parts = [v['content_sha256'] for v in transactions(root)
             if keys is None or any(c['concept_key'] in keys for c in v['corrections'])]
    return digest(parts)


def _verify_observation_sources(root, refs):
    """Verify an immutable target even after shipped attachments move to T9."""
    import math_learning_profiles as profiles

    package_root = Path("数学一回滚复习系统/快速入库来源")
    checked = {}
    for ref in refs:
        try:
            profiles.safe_source(root, ref)
            continue
        except FileNotFoundError:
            relative = Path(ref["path"])
            if (relative.parts[:2] != package_root.parts or len(relative.parts) != 6
                    or relative.parts[4] != "attachments"
                    or not re.fullmatch(r"MATHPKG-[0-9a-f]{24}", relative.parts[3])):
                raise
        # Only a missing member of the original package can follow its native
        # pointer. A present file with invalid bytes still fails above.
        manifest_path = str(Path(*relative.parts[:4]) / "manifest.json")
        if manifest_path not in checked:
            scripts = Path(__file__).resolve().parents[2] / "数学一回滚复习系统/scripts"
            if str(scripts) not in sys.path:
                sys.path.insert(0, str(scripts))
            import quick_intake

            if quick_intake.REPO_ROOT.resolve() != root:
                raise ValueError("memory_observation_archive_repository_mismatch")
            document, _, _ = quick_intake.validate_source_bundle_manifest(
                manifest_path, "memory_observation_archive"
            )
            if document.get("schema_version") != quick_intake.CONVERSATION_PACKAGE_SCHEMA:
                raise ValueError("memory_observation_not_a_conversation_package")
            checked[manifest_path] = {a["path"]: a["sha256"] for a in document["artifacts"]}
        if checked[manifest_path].get(relative.as_posix()) != ref["sha256"]:
            raise ValueError("memory_observation_archive_member_mismatch:" + ref["path"])


def prepare_corrections(root, payload, known_concepts):
    values = payload.get('memory_corrections', [])
    if not isinstance(values, list) or len(values) > 64:
        raise ValueError('memory_corrections_must_be_bounded_array')
    if not values:
        return []
    _id(payload.get('request_id'), 'request_id')
    keys = {v.get('concept_key') for v in values if isinstance(v, dict)}
    if len(keys) == 0 or not keys <= known_concepts:
        raise ValueError('memory_correction_concept_unknown')
    indexed = _indexed_observations(root, keys)
    all_transactions = transactions(root)
    ids = {c['correction_id']: c for t in all_transactions for c in t['corrections']}
    prepared, seen = [], set()
    required = {'correction_id', 'concept_key', 'target_kind', 'target', 'action', 'reason', 'source_refs', 'effective_at'}
    optional = {'replacement', 'supersedes', '_target_evidence'}
    for value in values:
        if not isinstance(value, dict) or not required <= value.keys() or set(value)-required-optional:
            raise ValueError('memory_correction_fields_required')
        cid = _id(value['correction_id'], 'correction_id')
        if cid in seen:
            raise ValueError('memory_duplicate_correction_id')
        seen.add(cid)
        if cid in ids and {k: v for k, v in ids[cid].items() if k != '_target_evidence'} != {k: v for k, v in value.items() if k != '_target_evidence'}:
            raise ValueError('memory_correction_identity_conflict')
        _text(value['reason'], 'reason')
        if value['action'] not in {'retract', 'replace', 'conflict'}:
            raise ValueError('memory_correction_action_invalid')
        _moment(value['effective_at'])
        if value['effective_at'] is None:
            raise ValueError('memory_correction_effective_time_required')
        refs = _source_refs(root, value['source_refs'], user_quote=True, native_user=cid not in ids)
        target = value['target']
        target_evidence = None
        if value['target_kind'] == 'observation':
            if not isinstance(target, dict) or set(target) != {'event_id', 'observation_sha256'}:
                raise ValueError('memory_exact_observation_target_required')
            matches = [v for v in indexed if v['concept_key'] == value['concept_key'] and
                       v['event_id'] == target['event_id'] and v['observation_sha256'] == target['observation_sha256']]
            if len(matches) != 1:
                raise ValueError('memory_observation_target_not_unique')
            target_evidence = copy.deepcopy(matches[0])
            if '_target_evidence' in value and value['_target_evidence'] != target_evidence:
                raise ValueError('memory_target_evidence_changed')
            # Freeze the immutable source too, not just the corrective user quote.
            _verify_observation_sources(Path(root).resolve(), matches[0]['source_refs'])
            if value['action'] == 'replace':
                replacement = value.get('replacement')
                if not isinstance(replacement, dict) or set(replacement) != {'outcome', 'error_detail'}:
                    raise ValueError('memory_replacement_observation_fields_required')
                if replacement['outcome'] not in OUTCOMES or not isinstance(replacement['error_detail'], str):
                    raise ValueError('memory_replacement_observation_invalid')
                if replacement['outcome'] in {'wrong', 'unresolved'} and not replacement['error_detail'].strip():
                    raise ValueError('memory_replacement_error_detail_required')
                # Correcting attribution must not erase the real hint sequence.
                old = matches[0]['observation']
                if replacement['outcome'] == 'independent_correct' and (old.get('hint_evidence') or old.get('hint_turn_indices')):
                    raise ValueError('memory_correction_cannot_erase_hint_dependency')
                if replacement['outcome'] == 'corrected_after_hint' and not (old.get('hint_evidence') or old.get('hint_turn_indices')):
                    raise ValueError('memory_correction_hint_evidence_required')
        elif value['target_kind'] == 'claim':
            if not isinstance(target, dict) or set(target) != {'claim_id', 'claim_sha256'}:
                raise ValueError('memory_exact_claim_target_required')
            versions, _ = _profile_versions(root, value['concept_key'])
            matches = {claim_hash(c) for profile in versions
                       for c in profile.get('claims', []) if c['claim_id'] == target['claim_id'] and claim_hash(c) == target['claim_sha256']}
            if len(matches) != 1:
                raise ValueError('memory_claim_target_not_unique')
            if value['action'] == 'replace':
                raise ValueError('memory_claim_replacement_requires_profile_update')
        else:
            raise ValueError('memory_correction_target_kind_invalid')
        if value['action'] != 'replace' and 'replacement' in value:
            raise ValueError('memory_unexpected_replacement')
        predecessor = value.get('supersedes')
        if predecessor is not None:
            if predecessor not in ids or ids[predecessor]['target'] != target or ids[predecessor]['concept_key'] != value['concept_key']:
                raise ValueError('memory_correction_predecessor_mismatch')
        prepared.append({**value, 'source_refs': refs,
                         **({'_target_evidence': target_evidence} if target_evidence else {})})
    return prepared


def validate_acknowledgments(root, row, additional_corrections=()):
    """A refreshed summary must bind the actual decisions it says it reviewed."""
    if 'memory_correction_ids' not in row:
        return
    identifiers = row['memory_correction_ids']
    if (not isinstance(identifiers, list) or any(not isinstance(v, str) for v in identifiers)
            or len(identifiers) != len(set(identifiers))):
        raise ValueError('memory_correction_acknowledgments_invalid')
    decisions = {c['correction_id']: c for t in transactions(root) for c in t['corrections']}
    decisions.update({c['correction_id']: c for c in additional_corrections})
    sources = {(r['path'], r['sha256']) for r in row['source_refs']}
    for identifier in identifiers:
        value = decisions.get(identifier)
        if not value or value['concept_key'] != row['concept_key']:
            raise ValueError('memory_correction_acknowledgment_unknown')
        if not {(r['path'], r['sha256']) for r in value['source_refs']} <= sources:
            raise ValueError('memory_correction_acknowledgment_missing_evidence')
    if identifiers and not str(row.get('revision_reason', '')).strip():
        raise ValueError('memory_correction_acknowledgment_reason_required')


def prepare_transaction(root, payload, corrections, maintenance_id):
    """Validate before the profile writer's first write; return bytes or a noop."""
    if not corrections:
        return None
    request_id = payload['request_id']
    path = Path(root)/TRANSACTIONS/(digest(request_id)+'.json')
    request_hash = digest({'corrections': corrections, 'request_id': request_id,
                           'updates': payload.get('updates', []),
                           'basis_version': payload.get('basis_version'),
                           'basis_records': payload.get('_basis_records'),
                           'basis_profile_versions': payload.get('_basis_profile_versions')})
    existing = _safe_json(root, path) if path.is_file() else None
    if existing:
        if existing.get('request_hash') != request_hash:
            raise ValueError('memory_request_id_content_conflict')
        if existing not in transactions(root):
            raise ValueError('memory_transaction_integrity_invalid')
        return {'path': path, 'value': existing, 'unchanged': True}
    if payload.get('_basis_memory_version') != version(root):
        raise ValueError('memory_version_conflict')
    value = {'schema': SCHEMA, 'request_id': request_id, 'request_hash': request_hash,
             'maintenance_id': maintenance_id, 'recorded_at': now(),
             'corrections': corrections, 'basis_memory_version': payload['_basis_memory_version']}
    value['content_sha256'] = digest(value)
    return {'path': path, 'value': value, 'unchanged': False}


def _corrections_at(root, *, valid_at=None, known_at=None, concept_keys=None):
    valid, known = _moment(valid_at, end=True), _moment(known_at, end=True)
    keys = set(concept_keys) if concept_keys is not None else None
    rows = []
    for transaction in transactions(root):
        if known is not None and _moment(transaction['recorded_at']) > known:
            continue
        for item in transaction['corrections']:
            if keys is not None and item['concept_key'] not in keys:
                continue
            if valid is not None and _moment(item['effective_at']) > valid:
                continue
            _source_refs(root, item['source_refs'], user_quote=True)
            rows.append({**item, 'recorded_at': transaction['recorded_at'], 'transaction_sha256': transaction['content_sha256']})
    superseded = {r['supersedes'] for r in rows if r.get('supersedes')}
    # A repeated immutable decision in another maintenance request is still
    # one decision, with its first real recording time.
    unique = {}
    for row in rows:
        if row['correction_id'] not in superseded:
            unique.setdefault(row['correction_id'], row)
    return list(unique.values())


def apply_observation_corrections(root, events, *, valid_at=None, known_at=None, concept_key=None):
    """Return an effective view; unknown known-times never pass a history cutoff."""
    valid, known = _moment(valid_at, end=True), _moment(known_at, end=True)
    corrections = _corrections_at(root, valid_at=valid_at, known_at=known_at,
                                  concept_keys=[concept_key] if concept_key else None)
    rows = []
    for original in events:
        event = copy.deepcopy(original)
        date = _moment(event.get('study_date'))
        if valid is not None and (date is None or date > valid):
            continue
        recorded = event.get('recorded_at') or event.get('closed_at') or event.get('history', {}).get('recorded_at')
        if known is not None and recorded is not None and _moment(recorded) > known:
            # An as-of reader must not even receive the future raw transcript.
            continue
        if known is not None and recorded is None:
            rows.append({'event_id': event.get('event_id'), 'memory_status': 'known_time_unknown',
                         'observations': [], 'outcomes': [], 'error_details': []})
            continue
        raw = copy.deepcopy(event.get('raw_observations', event.get('observations', [])))
        effective, decisions = [], []
        for observation in raw:
            key = observation_hash(observation)
            matched = [c for c in corrections if c['target_kind'] == 'observation'
                       and c['target'] == {'event_id': event.get('event_id'), 'observation_sha256': key}
                       and (concept_key is None or c['concept_key'] == concept_key)]
            value = {**observation, 'observation_sha256': key}
            if not matched:
                effective.append(value)
                continue
            decisions.extend(matched)
            value.update(raw_observation=copy.deepcopy(observation), memory_correction_ids=[c['correction_id'] for c in matched])
            signatures = {digest([c['action'], c.get('replacement')]) for c in matched}
            if len(signatures) > 1 or any(c['action'] == 'conflict' for c in matched):
                value.update(memory_status='conflicted', outcome='unresolved', error_detail='证据归因存在未解决冲突')
                effective.append(value)
            elif matched[0]['action'] == 'replace':
                value.update(matched[0]['replacement'], memory_status='corrected')
                effective.append(value)
            # Retracted source remains in raw_observations, outside valid counts.
        event.update(raw_observations=raw, observations=effective,
                     outcomes=[r['outcome'] for r in effective],
                     error_details=[r.get('error_detail', '') for r in effective if r.get('error_detail')])
        if decisions:
            event['memory_corrections'] = decisions
            event['memory_status'] = 'conflicted' if any(r.get('memory_status') == 'conflicted' for r in effective) else 'corrected'
        rows.append(event)
    return rows


def _profile_versions(root, key, *, include_history=True, include_decisions=False):
    directory = Path(root)/SEMANTIC
    current_path = directory/(key+'.json')
    current = _safe_json(root, current_path) if current_path.is_file() else None
    values = []
    if include_history or (include_decisions and current and current.get('claims')):
        values = [_safe_json(root, path) for path in (directory/'历史版本'/key).glob('*.json')]
    if current is not None:
        values.append(current)
    for value in values:
        if value.get('concept_key') != key or value.get('content_sha256') != digest({k: v for k, v in value.items() if k != 'content_sha256'}):
            raise ValueError('memory_profile_integrity_invalid')
    return values, current


def _profiles_known_at(versions, current, key, known, gaps):
    if known is None:
        return versions, current
    available = [v for v in versions if v.get('memory_recorded_at') and _moment(v['memory_recorded_at']) <= known]
    latest = max(available, key=lambda v: (_moment(v['memory_recorded_at']), v == current)) if available else None
    if not available and all(v.get('memory_recorded_at') for v in versions):
        gaps.append({'concept_key': key, 'reason': 'no_profile_known_by_cutoff'})
    elif any(not v.get('memory_recorded_at') for v in versions):
        gaps.append({'concept_key': key, 'reason': 'legacy_profile_recorded_time_unknown'})
    return available, latest


def _check_claim(root, original, profile, relevant, source_checks):
    claim = {**copy.deepcopy(original), 'concept_key': profile['concept_key'],
             'claim_sha256': claim_hash(original), 'recorded_at': profile.get('memory_recorded_at'),
             'profile_revision': profile['content_sha256']}
    acknowledged = set(profile.get('memory_correction_ids', []))
    # Acknowledging the review refreshes the overview. An exact withdrawal
    # continues to apply to the immutable claim it names.
    affected = [c for c in relevant if
                (c['target_kind'] == 'claim' and c['target'] ==
                 {'claim_id': claim['claim_id'], 'claim_sha256': claim['claim_sha256']})
                or (c['target_kind'] == 'observation' and c['correction_id'] not in acknowledged
                    and c['target'] in claim.get('observation_refs', []))]
    if affected:
        disputed = any(c['action'] == 'conflict' for c in affected)
        withdrawn = any(c['target_kind'] == 'claim' and c['action'] == 'retract' for c in affected)
        claim.update(memory_status='conflicted' if disputed else 'retracted' if withdrawn else 'evidence_corrected',
                     status='conflicted' if disputed else 'retracted' if withdrawn else 'candidate',
                     memory_correction_ids=[c['correction_id'] for c in affected])
    elif not claim.get('observation_refs'):
        # A raw quote without an observation binding needs dependency rechecking.
        source_hashes = {r.get('sha256') for r in claim['source_refs']}
        raw_dependencies = [c['correction_id'] for c in relevant if c['target_kind'] == 'observation'
                            and c['correction_id'] not in acknowledged and source_hashes &
                            {r.get('sha256') for r in c.get('_target_evidence', {}).get('source_refs', [])}]
        if raw_dependencies:
            claim.update(memory_status='dependency_unknown', status='candidate', memory_correction_ids=raw_dependencies)
    source_key = digest(claim['source_refs'])
    if source_key not in source_checks:
        try:
            _source_refs(root, claim['source_refs'])
        except (OSError, ValueError):
            source_checks[source_key] = False
        else:
            source_checks[source_key] = True
    if not source_checks[source_key]:
        claim['memory_status'] = 'source_changed'
        if claim['status'] == 'active':
            claim['status'] = 'candidate'
    if claim['status'] == 'active' and claim['basis'] == 'assistant_inferred':
        claim['status'] = 'candidate'
    if original['status'] in {'retracted', 'superseded'} and claim['status'] == 'candidate':
        claim['status'] = original['status']
    return claim


def _replacement_decisions(profiles, checked, *, dated_only):
    """Resolve edges for one concept before they can affect a predecessor."""
    decisions = {}
    for profile in profiles:
        claims = profile.get('claims', [])
        disputed = {cid for peer in claims if peer['status'] in {'active', 'conflicted'}
                    and peer['basis'] != 'assistant_inferred' for cid in peer.get('conflicts_with', [])}
        for claim in claims:
            targets = claim.get('supersedes', [])
            if (not targets or claim['status'] != 'active' or claim['basis'] not in CLAIM_BASES - {'assistant_inferred'}
                    or claim.get('conflicts_with') or claim['claim_id'] in disputed):
                continue
            start = _moment(claim.get('valid_from'))
            if start is None and dated_only:
                continue
            status = checked(claim, profile)['status']
            if status == 'active':
                decision = 'confirmed'
            elif profile.get('memory_recorded_at'):
                # A committed active edge may have taken effect before its
                # evidence changed. Keep the predecessor open to review.
                decision = 'unverified'
            else:
                continue
            for target in targets:
                decisions.setdefault(target, set()).add((start, decision))
    return decisions


def _applicable_replacements(claim, replacements):
    start = _moment(claim.get('valid_from'))
    return [(when, decision) for when, decision in replacements.get(claim['claim_id'], ())
            if start is None or when is None or when >= start]


def _claims_at(available, latest, key, valid, gaps, replacements):
    """Separate fact validity from which revisions had actually been recorded."""
    if latest is None:
        return []
    if valid is None:
        return [(claim, latest) for claim in latest.get('claims', [])]
    by_id = {}
    for profile in available:
        for claim in profile.get('claims', []):
            by_id.setdefault(claim['claim_id'], []).append((claim, profile))
    latest_ids = {c['claim_id'] for c in latest.get('claims', [])}
    selected = []
    for cid, variants in by_id.items():
        candidates = []
        for claim, profile in variants:
            start, stop = _moment(claim.get('valid_from')), _moment(claim.get('valid_to'))
            if start is None:
                gaps.append({'concept_key': key, 'claim_id': cid, 'reason': 'claim_valid_time_unknown'})
                continue
            # A later explicitly effective version of the same claim supplies
            # a boundary. Its acceptance timestamp is never used as valid time.
            successors = [_moment(other.get('valid_from')) for other, other_profile in variants
                          if claim_hash(other) != claim_hash(claim) and other.get('valid_from')
                          and _moment(other['valid_from']) > start
                          and (other_profile is latest or
                               profile.get('memory_recorded_at') and other_profile.get('memory_recorded_at')
                               and _moment(other_profile['memory_recorded_at']) > _moment(profile['memory_recorded_at']))]
            successors += [when for when, decision in _applicable_replacements(claim, replacements)
                           if decision == 'confirmed']
            if successors:
                inferred_stop = min(successors)
                stop = min(stop, inferred_stop) if stop is not None else inferred_stop
            if cid not in latest_ids and stop is None:
                gaps.append({'concept_key': key, 'claim_id': cid, 'reason': 'removed_claim_validity_end_unknown'})
                continue
            if start > valid or stop is not None and valid >= stop:
                continue
            candidates.append((claim, profile))
        if candidates:
            def precedence(pair):
                profile = pair[1]
                stamp = _moment(profile.get('memory_recorded_at'))
                return (stamp is not None, stamp or datetime.min.replace(tzinfo=timezone.utc), profile is latest)
            selected.append(max(candidates, key=precedence))
    return selected


def resolve_memory_claims(root, concept_keys, *, valid_at=None, known_at=None, view='protected'):
    if view not in {'protected', 'after_attempt', 'direct'}:
        raise ValueError('invalid view')
    keys = sorted(set(concept_keys))
    valid, known = _moment(valid_at, end=True), _moment(known_at, end=True)
    if view == 'protected':
        # Do not open semantic prose or quoted evidence just to redact it later.
        return {'status': 'protected', 'version': digest([version(root, keys), valid_at, known_at, view]),
                'claims': [], 'conflicts': [], 'missing': [], 'history_gaps': [],
                'invalidated_concept_keys': [], 'affected_observations': [],
                'valid_at': valid_at, 'known_at': known_at}
    revisions, gaps, missing, claims, conflicts, invalidated = [], [], [], [], [], set()
    source_checks = {}
    cutoff = valid if valid is not None else datetime.now(timezone.utc)
    corrections = _corrections_at(root, valid_at=valid_at, known_at=known_at, concept_keys=keys)
    affected_observations = list({(c['concept_key'], c['target']['event_id'], c['target']['observation_sha256']):
                                 copy.deepcopy(c['_target_evidence']) for c in corrections
                                 if c['target_kind'] == 'observation' and c.get('_target_evidence')}.values())
    for key in keys:
        # Only the requested point's structured claims need prior decisions.
        versions, current = _profile_versions(root, key, include_history=bool(valid or known), include_decisions=True)
        if current is None:
            missing.append(key)
            continue
        available, latest = _profiles_known_at(versions, current, key, known, gaps)
        relevant = [c for c in corrections if c['concept_key'] == key]
        # A newer maintenance profile can explicitly acknowledge every decision
        # when compiling a fresh overview. Unacknowledged legacy prose is stale.
        acknowledged = set(current.get('memory_correction_ids', []))
        unseen = [c for c in relevant if c['correction_id'] not in acknowledged]
        # Even with some structured claims, the overview and short summary
        # have no per-sentence dependencies. A new correction must fail that
        # prose closed until it is explicitly reconciled.
        if unseen:
            invalidated.add(key)
        verified = {}

        def checked(original, profile):
            cache_key = (profile['content_sha256'], original['claim_id'])
            if cache_key not in verified:
                verified[cache_key] = _check_claim(root, original, profile, relevant, source_checks)
            return verified[cache_key]

        replacements = _replacement_decisions(available, checked, dated_only=valid is not None)
        pairs = _claims_at(available, latest, key, valid, gaps, replacements)
        revision_ids = {profile['content_sha256'] for _, profile in pairs}
        if replacements:
            revision_ids.update(p['content_sha256'] for p in available)
        if not pairs and valid is None and known is None:
            revision_ids.add(current['content_sha256'])
        revisions.extend(sorted(revision_ids))
        for original, profile in pairs:
            claim = checked(original, profile).copy()
            if claim.get('memory_status'):
                invalidated.add(key)
            if claim['status'] == 'active':
                decisions = {decision for when, decision in _applicable_replacements(original, replacements)
                             if when is None or when <= cutoff}
                stop = _moment(original.get('valid_to'))
                if 'confirmed' in decisions:
                    claim['status'] = 'superseded'
                elif stop is not None and stop <= cutoff:
                    continue
                elif 'unverified' in decisions:
                    reason = 'supersession_unverified'
                    claim.update(memory_status=reason, status='conflicted')
                    gaps.append({'concept_key': key, 'claim_id': claim['claim_id'], 'reason': reason})
                    invalidated.add(key)
            if claim['status'] == 'conflicted' or claim.get('conflicts_with'):
                conflicts.append({'concept_key': key, 'claim_id': claim['claim_id']})
            claims.append(claim)
    result = {'status': 'available' if claims else 'legacy_unstructured' if revisions and not (valid_at or known_at) else 'history_unknown' if gaps else 'not_recorded',
              'version': digest([version(root, keys), revisions, valid_at, known_at, view]),
              'claims': claims, 'conflicts': conflicts, 'missing': missing,
              'history_gaps': gaps, 'invalidated_concept_keys': sorted(invalidated),
              'affected_observations': affected_observations,
              'valid_at': valid_at, 'known_at': known_at}
    return result
