"""Read reviewed formula references without creating any learner evidence.

The manifest authenticates small shards. A ready practice link requires both a
local mathematical review and a locally checked, exact mathematics-I anchor.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
BASE = '错题知识网络/个人知识点索引/做题方法/公式结论'
MANIFEST = BASE + '/manifest.json'
SCHEMA = 'math-formula-registry-v1'
SHARD_SCHEMA = 'math-formula-shard-v1'
ENTRY_PATTERN = re.compile(r'^FCE-A\d{2}-\d{4,}$')
SHA_PATTERN = re.compile(r'^[0-9a-f]{64}$')
VIEWS = {'protected', 'after_attempt', 'direct'}
MAX_SHARD_BYTES = 16 * 1024 * 1024


class FormulaError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def safe_relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise FormulaError('formula_source_path_invalid')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '.' in path.parts:
        raise FormulaError('formula_source_path_invalid')
    return value


def manifest_version(value):
    return digest({k: v for k, v in value.items() if k not in {'version', 'generated_at'}})


def formula_practice_ready(entry):
    review = entry.get('local_review', {})
    ids = review.get('verified_question_ids', [])
    return (entry.get('status') == 'verified_math1_mapping'
            and review.get('math_status') in {'accepted', 'corrected'}
            and review.get('mapping_status') == 'verified_anchor'
            and bool(ids) and all(isinstance(x, str) and x.startswith('MATH1-') for x in ids)
            and entry.get('source_binding_status') == 'verified'
            and not entry.get('runtime_hold_reasons'))


def formula_reference_ready(entry):
    """Mathematical reference readiness is independent of an exam anchor.

    This predicate never opens archived entries or changes practice selection.
    A reference reader must additionally authenticate its source bindings.
    """
    return (entry.get('local_review', {}).get('math_status') in {'accepted', 'corrected'}
            and entry.get('source_binding_status') == 'verified'
            and bool(entry.get('source_refs'))
            and not entry.get('runtime_hold_reasons'))


def teaching_reference(record):
    """Keep mathematical content and variants, omit duplicated audit payloads.

    This is a read projection only. Full source/evidence records stay available
    through the same query without --compact; protected output stays protected.
    """
    value = copy.deepcopy(record)
    if value.get('status') == 'protected':
        return value
    for key in ('display', 'provenance', 'original_source_refs', 'cross_shard_refs',
                'deduplication', 'question_variants', 'source_refs'):
        value.pop(key, None)
    if isinstance(value.get('exam_links'), list):
        # Keep source identities; a specific exam application can be requested
        # through the full view when that is the actual current question.
        link_identity_fields = {'question_id', 'part', 'variant_entry_id', 'verification'}
        value['exam_links'] = [{k: v for k, v in link.items() if k in link_identity_fields}
                               for link in value['exam_links']]
    if isinstance(value.get('variants'), list):
        value['variants'] = [teaching_reference(variant) for variant in value['variants']]
    value['projection'] = 'teaching_reference'
    value['detail_lookup'] = 'query the same entry without --compact for complete source evidence'
    return value


class FormulaRegistry:
    def __init__(self, root=ROOT, *, read_bytes: Callable[[str], bytes] | None = None):
        self.root = Path(root)
        self._reader = read_bytes or self._local_read
        try:
            raw = self._reader(MANIFEST)
        except (OSError, ValueError) as exc:
            raise FormulaError('formula_registry_unavailable') from exc
        if len(raw) > 8 * 1024 * 1024:
            raise FormulaError('formula_manifest_too_large')
        value = json.loads(raw)
        if value.get('schema') != SCHEMA or value.get('version') != manifest_version(value):
            raise FormulaError('formula_manifest_version_invalid')
        self.manifest, self.manifest_sha256 = value, hashlib.sha256(raw).hexdigest()
        self.index = value.get('entries', {})
        self.shards = {r['shard_id']: r for r in value.get('shards', [])}
        self._loaded = {}
        self.aliases = value.get('aliases', {}) if value.get('library_mode') == 'practice_only' else {}
        if any(k in self.index or v not in self.index or k == v for k, v in self.aliases.items()):
            raise FormulaError('formula_active_alias_invalid')
        if value.get('library_mode') == 'practice_only' and any(not r.get('practice_ready') for r in self.index.values()):
            raise FormulaError('formula_active_registry_contains_reference_only')
        if not isinstance(self.index, dict) or len(self.shards) != len(value.get('shards', [])):
            raise FormulaError('formula_manifest_index_invalid')
        for identity, meta in self.index.items():
            if not ENTRY_PATTERN.fullmatch(identity) or meta.get('shard_id') not in self.shards:
                raise FormulaError('formula_manifest_identity_invalid')
        for shard in self.shards.values():
            path = safe_relative(shard.get('path'))
            if not path.startswith(BASE + '/') or not SHA_PATTERN.fullmatch(shard.get('sha256', '')):
                raise FormulaError('formula_shard_binding_invalid')

    def _local_read(self, relative):
        path = self.root / safe_relative(relative)
        current = self.root
        for part in PurePosixPath(relative).parts:
            current /= part
            if current.is_symlink():
                raise FormulaError('formula_hot_source_symlink_forbidden')
        return path.read_bytes()

    @property
    def version(self):
        return self.manifest['version']

    def summary(self):
        return {'schema': SCHEMA, 'version': self.version,
                'batch_id': self.manifest.get('batch_id'),
                'coverage': copy.deepcopy(self.manifest.get('coverage', {})),
                'counts': copy.deepcopy(self.manifest.get('counts', {})),
                'manifest_path': MANIFEST, 'manifest_sha256': self.manifest_sha256,
                'learning_write_count': 0}

    def _shard(self, shard_id):
        binding = self.shards[shard_id]
        raw = self._reader(binding['path'])
        if len(raw) > MAX_SHARD_BYTES or hashlib.sha256(raw).hexdigest() != binding['sha256']:
            raise FormulaError('formula_shard_hash_mismatch:' + shard_id)
        if shard_id not in self._loaded:
            value = json.loads(raw)
            records = value.get('entries')
            if value.get('schema') != SHARD_SCHEMA or value.get('shard_id') != shard_id or not isinstance(records, list):
                raise FormulaError('formula_shard_schema_invalid')
            result = {r.get('entry_id'): r for r in records}
            expected = {key for key, meta in self.index.items() if meta['shard_id'] == shard_id}
            if len(result) != len(records) or set(result) != expected:
                raise FormulaError('formula_shard_coverage_mismatch')
            for key, record in result.items():
                if formula_practice_ready(record) != self.index[key].get('practice_ready'):
                    raise FormulaError('formula_ready_state_mismatch:' + key)
            self._loaded[shard_id] = result
        return self._loaded[shard_id]

    def resolve_id(self, entry_id):
        if entry_id in self.manifest.get('archived_entries', {}):
            raise FormulaError('formula_archived_not_for_daily_use:' + str(entry_id))
        canonical_id = self.aliases.get(entry_id, entry_id)
        if canonical_id not in self.index:
            raise FormulaError('formula_entry_not_found:' + str(entry_id))
        return canonical_id

    def get(self, entry_id, *, view='protected'):
        if view not in VIEWS:
            raise FormulaError('formula_view_invalid')
        canonical_id = self.resolve_id(entry_id)
        if view == 'protected':
            return {'id': entry_id, 'object_role': 'conclusion_reference', 'status': 'protected'}
        record = copy.deepcopy(self._shard(self.index[canonical_id]['shard_id'])[canonical_id])
        record['practice_ready'] = formula_practice_ready(record)
        record['registry_version'] = self.version
        if entry_id != canonical_id:
            record['requested_alias_id'] = entry_id
        return record

    def query(self, ids=None, *, question_id=None, view='protected', offset=0, limit=20, compact=False):
        if view not in VIEWS or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise FormulaError('formula_query_options_invalid')
        if question_id is not None:
            if not isinstance(question_id, str) or not re.fullmatch(r'MATH[123]-[A-Za-z0-9-]+', question_id):
                raise FormulaError('formula_question_identity_invalid')
            selected = list(self.manifest.get('by_question', {}).get(question_id, []))
            if ids is not None:
                wanted = {self.resolve_id(x) for x in ids}
                selected = [x for x in selected if x in wanted]
        elif ids is not None:
            if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)):
                raise FormulaError('formula_ids_invalid')
            selected = ids
        else:
            selected = sorted(self.index)
        for key in selected:
            self.resolve_id(key)
        stop = min(len(selected), offset + limit)
        records = [self.get(x, view=view) for x in selected[offset:stop]]
        if compact:
            records = [teaching_reference(record) for record in records]
        return {**self.summary(), 'view': view, 'question_id': question_id,
                'records': records,
                'total_records': len(selected), 'next_offset': stop if stop < len(selected) else None,
                'eof': stop == len(selected), 'evidence_policy': 'reference_only_not_learner_mastery'}

    def practice_questions(self):
        """Authoritative candidate links; no scheduling or eligibility inference."""
        by_question = self.manifest.get('by_question', {})
        needed = set()
        for entry_ids in by_question.values():
            if not isinstance(entry_ids, list) or not entry_ids or len(entry_ids) != len(set(entry_ids)):
                raise FormulaError('formula_question_index_invalid')
            for entry_id in entry_ids:
                if entry_id not in self.index:
                    raise FormulaError('formula_question_has_unknown_entry')
                needed.add(self.index[entry_id]['shard_id'])
        # Authenticate each involved shard once, even for a direct local call.
        # A manifest's ready flag cannot substitute for the actual record.
        checked = {shard_id: self._shard(shard_id) for shard_id in sorted(needed)}
        out = []
        for question_id, entry_ids in sorted(by_question.items()):
            if not question_id.startswith('MATH1-'):
                raise FormulaError('formula_practice_requires_math1')
            source_version = self.manifest.get('question_source_versions', {}).get(question_id)
            if not isinstance(source_version, str) or not SHA_PATTERN.fullmatch(source_version):
                raise FormulaError('formula_question_source_version_missing:' + question_id)
            if not entry_ids or any(not self.index.get(x, {}).get('practice_ready') for x in entry_ids):
                raise FormulaError('formula_question_has_unready_entry')
            for entry_id in entry_ids:
                record = checked[self.index[entry_id]['shard_id']][entry_id]
                if (not formula_practice_ready(record)
                        or question_id not in record.get('local_review', {}).get('verified_question_ids', [])
                        or not any(link.get('question_id') == question_id and link.get('verification') == 'verified'
                                   for link in record.get('exam_links', []))):
                    raise FormulaError('formula_question_link_not_locally_verified:' + entry_id)
            out.append({'question_id': question_id, 'formula_entry_ids': list(entry_ids),
                        'source_record_sha256': source_version,
                        'registry_version': self.version,
                        'eligibility': 'must_check_current_native_activity_and_source_guards'})
        return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, default=ROOT)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    sub.add_parser('practice-questions')
    q = sub.add_parser('query')
    q.add_argument('--id', action='append', dest='ids')
    q.add_argument('--question-id')
    q.add_argument('--view', choices=sorted(VIEWS), default='protected')
    q.add_argument('--offset', type=int, default=0)
    q.add_argument('--limit', type=int, default=20)
    q.add_argument('--compact', action='store_true', help='Keep formulas, conditions and variants; omit duplicated source audit bodies')
    args = p.parse_args()
    try:
        registry = FormulaRegistry(args.repo)
        if args.command == 'status':
            result = registry.summary()
        elif args.command == 'practice-questions':
            result = {**registry.summary(), 'questions': registry.practice_questions()}
        else:
            result = registry.query(args.ids, question_id=args.question_id, view=args.view,
                                    offset=args.offset, limit=args.limit, compact=args.compact)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc), 'learning_write_count': 0}, ensure_ascii=False))
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
