"""Private point locators compiled from accepted annotations, not learner claims.

Only explicit maintenance builds this corpus. A query may load an authenticated
build in an unprotected view; it never compiles, repairs, or updates learning.
Formal summaries are selected with SQL JSON projections, without loading the
record's history/packages. Source objects are used only for observation identity
checks; their conversations, evidence quotations and outcomes are not exported.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import math_memory_lifecycle as lifecycle
import math_memory_reference_catalog as references
import math_memory_utterances as utterances

SCHEMA = 'math-point-context-retrieval-v1'
CONTENT_POLICY = 'accepted_point_annotations_and_math_references'
COMPILER_VERSION = 'math-point-context-compiler-v1'
MAX_TEXT_CHARS = 2400
ALLOWED_VIEWS = {'after_attempt', 'direct'}
ANNOTATION_ROLE = 'accepted_point_annotation'
REFERENCE_ROLE = 'mathematical_reference'
# Keep this query projected. SELECT payload would bring original conversations
# into this compiler even though no original conversation is needed here.
RECORD_SQL = """SELECT id,
    json_extract(payload,'$.concept_key'),
    json_extract(payload,'$.formal_id'),
    json_extract(payload,'$.summary'),
    json_extract(payload,'$.source_refs')
    FROM records WHERE json_extract(payload,'$.kind')='formal_concept_observation'
    ORDER BY id"""


class PointContextError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _compiler_dependencies():
    return {name: _sha(Path(module.__file__).read_bytes()) for name, module in (
        ('math_memory_utterances', utterances), ('math_memory_lifecycle', lifecycle),
        ('math_memory_reference_catalog', references))}


def require_point_context_view(view):
    """Must run before resolving or opening any supplied path."""
    if view not in ALLOWED_VIEWS:
        raise PointContextError('point_context_view_forbidden:' + str(view))


def _native(root, *, with_records=True):
    path = utterances._inside(root, utterances.NATIVE)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('BEGIN')
        row = conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        if not row:
            raise PointContextError('point_context_native_version_missing')
        selected = conn.execute(RECORD_SQL).fetchall() if with_records else []
        source_hashes = dict(conn.execute('SELECT path,sha256 FROM sources')) if with_records else {}
    return json.loads(row[0]), selected, source_hashes


def _native_stamp(root):
    path = root / utterances.NATIVE
    return {suffix: utterances._stamp(Path(str(path) + suffix)) for suffix in ('', '-wal')}


def _transaction_paths(root):
    base = utterances._inside(root, utterances.CORRECTIONS)
    return [str(path.relative_to(root)) for path in sorted(base.glob('*.json'))]


def _input(value):
    if isinstance(value, dict):
        return value, None
    path = Path(value).resolve()
    raw = path.read_bytes()
    return json.loads(raw), {'path': str(path), 'sha256': _sha(raw), 'stamp': utterances._stamp(path)}


def _discovery_documents(discovery):
    if (discovery.get('schema') != 'math-memory-corpus-v1'
            or discovery.get('content_policy') != 'safe_discovery_metadata_only'
            or not isinstance(discovery.get('documents'), list)):
        raise PointContextError('point_context_discovery_invalid')
    result = {}
    for doc in discovery['documents']:
        key = doc.get('concept_key')
        if (not isinstance(key, str) or not key or key in result
                or not isinstance(doc.get('title'), str) or not doc['title'].strip()
                or doc.get('id', key) != key or not doc.get('discovery_eligible', True)
                or not all(isinstance(doc.get(field, []), list)
                           and all(isinstance(x, str) for x in doc.get(field, []))
                           for field in ('aliases', 'formal_ids'))):
            raise PointContextError('point_context_discovery_document_invalid')
        result[key] = doc
    return result


def _source_refs(record):
    values = record['source_refs']
    if not isinstance(values, list) or not values:
        raise PointContextError('point_context_source_refs_required')
    refs = []
    for ref in values:
        if not isinstance(ref, dict) or not isinstance(ref.get('path'), str):
            raise PointContextError('point_context_source_ref_invalid')
        # The checked reader validates the digest syntax and repository scope.
        refs.append({'path': ref['path'], 'sha256': ref.get('sha256')})
    return sorted({digest(ref): ref for ref in refs}.values(), key=canonical)


def _verified_observations(record, source_values):
    """Only inspect formal observation lists; never packages or conversations."""
    summary = record['summary']
    event, date = summary.get('event_id'), summary.get('study_date')
    if not event or not date or not record.get('formal_id'):
        return set()
    found = set()
    for source in source_values:
        if not isinstance(source, dict) or source.get('closeout_id') != event:
            continue
        projection = source.get('concept_observations', {})
        if not isinstance(projection, dict):
            continue
        for target in projection.get('targets', []):
            if (not isinstance(target, dict) or target.get('formal_id') != record['formal_id']
                    or target.get('study_date') != date):
                continue
            for observation in target.get('observations', []):
                if isinstance(observation, dict):
                    found.add(lifecycle.observation_hash(observation))
    return found


def export_point_context(repo_root, public_discovery, reference_corpus, destination=None, *,
                         max_text_chars=MAX_TEXT_CHARS):
    """Explicit, read-only maintenance. Callers own output storage/registration.

    Annotation strings are indivisible. Deduplication saves text only: every
    source event binding, including one omitted from text by budget, is retained.
    A point with accepted annotations never mixes in mathematical references.
    """
    if type(max_text_chars) is not int or not 200 <= max_text_chars <= MAX_TEXT_CHARS:
        raise PointContextError('point_context_text_budget_invalid')
    root = Path(repo_root).resolve()
    discovery, discovery_input = _input(public_discovery)
    docs = _discovery_documents(discovery)
    native_version, rows, native_sources = _native(root)
    native_stamp = _native_stamp(root)
    if discovery.get('source_version') != native_version:
        raise PointContextError('point_context_discovery_not_current')
    reference, reference_input = _input(reference_corpus)
    references.validate_references(root, reference, discovery=discovery)
    reference_docs = {d['concept_key']: d for d in reference['documents']}
    if len(reference_docs) != len(reference['documents']) or set(reference_docs) != set(docs):
        raise PointContextError('point_context_reference_identity_mismatch')
    sources = utterances._Sources(root)
    transactions = _transaction_paths(root)
    for relative in transactions:
        raw = references._read(root, relative)
        sources.read({'path': relative, 'sha256': _sha(raw)})
    grouped, excluded, counts = defaultdict(dict), [], Counter()
    for rid, key, formal_id, summary_json, refs_json in rows:
        counts['formal_records'] += 1
        if key not in docs:
            excluded.append({'record_id': rid, 'reason': 'concept_outside_discovery'})
            continue
        summary = json.loads(summary_json) if summary_json else {}
        record = {'record_id': rid, 'concept_key': key, 'formal_id': formal_id,
                  'summary': summary, 'source_refs': json.loads(refs_json) if refs_json else []}
        refs = _source_refs(record)
        for ref in refs:
            if native_sources.get(ref['path']) != ref['sha256']:
                raise PointContextError('point_context_source_not_indexed:' + rid)
        try:
            source_values = [sources.read(ref) for ref in refs]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise PointContextError('point_context_source_invalid:' + rid) from error
        verified = _verified_observations(record, source_values)
        observations = summary.get('observations', [])
        if not isinstance(observations, list):
            raise PointContextError('point_context_observations_invalid:' + rid)
        for ordinal, observation in enumerate(observations):
            counts['observations'] += 1
            reason = None
            if not isinstance(observation, dict):
                reason = 'observation_not_object'
            elif observation.get('concept_key', key) != key:
                reason = 'observation_concept_mismatch'
            elif lifecycle.observation_hash(observation) not in verified:
                reason = 'no_verified_observation_with_exact_event_scope'
            if reason:
                excluded.append({'record_id': rid, 'observation_ordinal': ordinal, 'reason': reason})
                continue
            assessment = utterances._assessment(root, record, observation)
            correction_refs = assessment['correction_source_refs']
            for ref in correction_refs:
                sources.read(ref)
            annotation, status = assessment['effective_annotation'], assessment['assessment_status']
            if status not in {'accepted', 'corrected'}:
                reason = 'assessment_' + str(status)
            elif not isinstance(annotation, str) or not annotation.strip():
                reason = 'empty_effective_annotation'
            if reason:
                excluded.append({'record_id': rid, 'observation_ordinal': ordinal, 'reason': reason})
                continue
            annotation_sha = _sha(annotation.encode())
            item = grouped[key].setdefault(annotation_sha, {'text': annotation, 'bindings': []})
            # Deliberately do not copy the whole assessment, summary, or source
            # observation: these carry outcomes and quoted teaching evidence.
            binding = {'record_id': rid, 'concept_key': key, 'formal_id': formal_id,
                'event_id': summary.get('event_id'), 'study_date': summary.get('study_date'),
                'recorded_at': summary.get('recorded_at'),
                'capture_id': observation.get('capture_event_id'),
                'observation_id': observation.get('observation_id'),
                'observation_ordinal': ordinal,
                'observation_sha256': assessment['observation_sha256'],
                'assessment_status': status, 'source_refs': refs,
                'correction_source_refs': correction_refs}
            item['bindings'].append(binding)
            counts['accepted_bindings'] += 1
    result = []
    for key, doc in sorted(docs.items()):
        annotations = grouped.get(key, {})
        handles, omitted = [], []
        if annotations:
            role = ANNOTATION_ROLE
            prefix = ('规范知识点：' + doc['title'] + '\n已接受的历史逐点注释，仅用于定位；'
                      '不作为用户原话、数学结论或当前错误及掌握度的证明。')
            if len(prefix) > max_text_chars:
                raise PointContextError('point_context_identity_exceeds_budget:' + key)
            parts, used = [prefix], len(prefix)
            # Stable event order; no query-specific case text or learned aliases.
            ordered = sorted(annotations.items(), key=lambda pair: (
                min(canonical(b) for b in pair[1]['bindings']), pair[0]))
            for annotation_sha, item in ordered:
                included = used + 2 + len(item['text']) <= max_text_chars
                if included:
                    parts.append(item['text']); used += 2 + len(item['text'])
                    counts['annotations_in_text'] += 1
                else:
                    omitted.append({'annotation_sha256': annotation_sha, 'reason': 'whole_annotation_budget'})
                handles.append({'content_role': role, 'annotation_sha256': annotation_sha,
                                'included_in_text': included,
                                'bindings': sorted(item['bindings'], key=canonical)})
            text = '\n\n'.join(parts)
        else:
            role = REFERENCE_ROLE
            refdoc = reference_docs[key]
            if (refdoc.get('title') != doc['title'] or refdoc.get('aliases', []) != doc.get('aliases', [])
                    or refdoc.get('formal_ids', []) != doc.get('formal_ids', [])):
                raise PointContextError('point_context_reference_identity_mismatch:' + key)
            # Preserve the validated mathematical body whole, including its
            # conditions. Never trim a formula's conditions to fit this budget.
            text = refdoc['text']
            if len(text) > max_text_chars:
                text = '规范知识点：' + doc['title']
                omitted.append({'reason': 'whole_reference_budget'})
            handles = [{'content_role': role, 'reference_version': reference['version'],
                        'reference_document_id': key, 'reference_text_sha256': _sha(refdoc['text'].encode()),
                        'included_in_text': not omitted,
                        'source_refs': refdoc.get('source_refs', [])}]
        result.append({'id': key, 'concept_key': key, 'title': doc['title'], 'text': text,
                       'aliases': list(doc.get('aliases', [])),
                       'formal_ids': list(doc.get('formal_ids', [])),
                       'content_role': role, 'source_handles': handles, 'omitted': omitted,
                       'text_chars': len(text), 'not_current_mastery': True,
                       'not_user_quote': True})
    dependencies = {entry['path']: entry['sha256'] for entry in reference['dependencies']}
    for path, info in sources.dependencies.items():
        if path in dependencies and dependencies[path] != info['sha256']:
            raise PointContextError('point_context_dependency_conflict:' + path)
        dependencies[path] = info['sha256']
    counts.update(documents=len(result), points_with_annotations=len(grouped),
                  reference_fallback_points=len(result)-len(grouped),
                  unique_annotations=sum(len(values) for values in grouped.values()),
                  excluded_observations=len(excluded))
    corpus = {'schema': SCHEMA, 'content_policy': CONTENT_POLICY, 'source_version': native_version,
              'compiler_version': COMPILER_VERSION, 'compiler_sha256': _sha(Path(__file__).read_bytes()),
              'compiler_dependencies': _compiler_dependencies(),
              'discovery_sha256': digest(discovery), 'discovery_revision': discovery.get('retrieval_revision'),
              'discovery_input': discovery_input, 'reference_input': reference_input,
              'reference_version': reference['version'], 'reference_sha256': digest(reference),
              'reference_content_policy': reference['content_policy'],
              'native_records_sha256': digest(rows), 'native_stamp': native_stamp,
              'correction_transaction_paths': transactions,
              'dependencies': [{'path': path, 'sha256': sha,
                                'stamp': utterances._stamp(utterances._inside(root, path))}
                               for path, sha in sorted(dependencies.items())],
              'max_text_chars': max_text_chars, 'documents': result,
              'coverage': dict(counts), 'excluded': excluded, 'learning_write_count': 0}
    corpus['version'] = digest(corpus)
    validate_point_context(root, corpus, discovery=discovery, verify_hashes=True)
    if destination is not None:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_bytes(canonical(corpus) + b'\n')
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    return corpus


def validate_point_context(repo_root, corpus, *, discovery=None, verify_hashes=False):
    """Validate an existing private build. Never rebuild or repair on reads."""
    if (corpus.get('schema') != SCHEMA or corpus.get('content_policy') != CONTENT_POLICY
            or corpus.get('version') != digest({k: v for k, v in corpus.items() if k != 'version'})):
        raise PointContextError('point_context_corpus_invalid')
    if (corpus.get('compiler_version') != COMPILER_VERSION
            or corpus.get('compiler_sha256') != _sha(Path(__file__).read_bytes())
            or corpus.get('compiler_dependencies') != _compiler_dependencies()):
        raise PointContextError('point_context_compiler_changed')
    root = Path(repo_root).resolve()
    check_records = verify_hashes or _native_stamp(root) != corpus.get('native_stamp')
    version, rows, _ = _native(root, with_records=check_records)
    if version != corpus.get('source_version'):
        raise PointContextError('point_context_source_version_changed')
    if check_records and digest(rows) != corpus.get('native_records_sha256'):
        raise PointContextError('point_context_native_records_changed')
    if discovery is not None and digest(discovery) != corpus.get('discovery_sha256'):
        raise PointContextError('point_context_discovery_changed')
    if _transaction_paths(root) != corpus.get('correction_transaction_paths'):
        raise PointContextError('point_context_corrections_changed')
    dependencies = corpus.get('dependencies', [])
    paths = [entry['path'] for entry in dependencies]
    if (len(paths) != len(set(paths))
            or not {references.CATALOG, references.BINDINGS, references.MANIFEST} <= set(paths)
            or not set(corpus['correction_transaction_paths']) <= set(paths)):
        raise PointContextError('point_context_dependencies_incomplete')
    for entry in dependencies:
        path = utterances._inside(root, entry['path'])
        stamp = utterances._stamp(path)
        if ((verify_hashes or stamp != entry.get('stamp'))
                and (_sha(references._read(root, entry['path'])) != entry['sha256']
                     or utterances._stamp(path) != stamp)):
            raise PointContextError('point_context_dependency_changed:' + entry['path'])
    for field in ('discovery_input', 'reference_input'):
        value = corpus.get(field)
        if value is not None:
            path = Path(value['path'])
            if not verify_hashes and utterances._stamp(path) == value.get('stamp'):
                continue
            raw = path.read_bytes()
            if _sha(raw) != value['sha256']:
                raise PointContextError('point_context_' + field + '_changed')
            saved = json.loads(raw)
            if (field == 'reference_input' and
                    (saved.get('version') != corpus['reference_version']
                     or digest(saved) != corpus['reference_sha256'])):
                raise PointContextError('point_context_reference_changed')
    return True


def load_point_context(repo_root, path, *, view=None, discovery=None):
    require_point_context_view(view)  # Before Path(), resolve(), exists(), reads.
    corpus = json.loads(Path(path).read_bytes())
    validate_point_context(repo_root, corpus, discovery=discovery)
    return corpus


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--discovery', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    corpus = export_point_context(args.repo, args.discovery, args.reference, args.output)
    print(json.dumps({'schema': SCHEMA, 'version': corpus['version'],
                      'coverage': corpus['coverage'], 'learning_write_count': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
