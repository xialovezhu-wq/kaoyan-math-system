"""Compile and read authored mathematical recaps without learner-state writes.

Topics reuse existing reference identities. A source-checked reference is not a
practice authorization or evidence that its conditions hold in today's problem.
Only ``build`` writes derived files; query and attach are read-only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = Path('错题知识网络/个人知识点索引/做题方法/回顾')
MANIFEST = BASE / 'manifest.json'
DISPLAY = Path('错题知识网络/公式结论库')
SCHEMA = 'math-recap-registry-v1'
TOPIC_SCHEMA = 'math-recap-topic-v1'
RESPONSE_SCHEMA = 'math-recap-v1'
SECTIONS = ('basic_formulas', 'secondary_conclusions', 'solution_methods')
LABELS = dict(zip(SECTIONS, ('基础公式', '二级结论', '解题思路')))
SHA = re.compile(r'^[0-9a-f]{64}$')
ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$')
MAX_TOPIC_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_HASH_CACHE = {}


class RecapError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def manifest_version(value):
    return digest({k: v for k, v in value.items() if k not in ('version', 'generated_at')})


def _relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise RecapError('recap_source_path_invalid')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '.' in path.parts:
        raise RecapError('recap_source_path_invalid')
    return path.as_posix()


def _signature(path):
    stat = path.stat()
    if not path.is_file():
        raise RecapError('recap_source_not_file')
    return {'resolved_path': str(path.resolve()), 'size': stat.st_size,
            'mtime_ns': stat.st_mtime_ns, 'ctime_ns': stat.st_ctime_ns,
            'inode': stat.st_ino, 'device': stat.st_dev}


def _hash_file(path, signature=None):
    before = signature or _signature(path)
    key = tuple(sorted(before.items()))
    if key not in _HASH_CACHE:
        sha = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                sha.update(block)
        if _signature(path) != before:
            raise RecapError('recap_source_changed_during_read')
        _HASH_CACHE[key] = sha.hexdigest()
    return _HASH_CACHE[key]


def _texts(value, label, *, required=False):
    if (not isinstance(value, list) or (required and not value)
            or any(not isinstance(x, str) or not x.strip() for x in value)):
        raise RecapError('recap_invalid_' + label)
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise RecapError('recap_invalid_' + label)
    return value


def reference_ready(entry):
    review = entry.get('review', {})
    return (review.get('status') == 'verified' and bool(review.get('basis'))
            and bool(review.get('reviewed_at')) and bool(entry.get('source_refs'))
            and not entry.get('hold_reasons') and not entry.get('runtime_hold_reasons'))


def _entry_keys(entry):
    return list(dict.fromkeys([entry['entry_id'], entry['name'],
                              *entry.get('source_record_ids', []), *entry.get('concept_keys', [])]))


def validate_topic(topic):
    if topic.get('schema') != TOPIC_SCHEMA or not ID.fullmatch(str(topic.get('topic_id', ''))):
        raise RecapError('recap_topic_identity_invalid')
    for key in ('title', 'subject', 'chapter'):
        _text(topic.get(key), key)
    _texts(topic.get('concept_keys'), 'concept_keys', required=True)
    if topic.get('selection_mode', 'topic_bundle') not in ('topic_bundle', 'matched_entries'):
        raise RecapError('recap_selection_mode_invalid')
    entries = topic.get('entries')
    entry_refs = _texts(topic.get('entry_refs', []), 'entry_refs')
    if not isinstance(entries, list) or (not entries and not entry_refs):
        raise RecapError('recap_entries_required')
    identities = set()
    for entry in entries:
        identity = entry.get('entry_id')
        if not isinstance(identity, str) or not ID.fullmatch(identity) or identity in identities:
            raise RecapError('recap_entry_identity_invalid')
        identities.add(identity)
        if entry.get('section') not in SECTIONS or entry.get('relation', 'core') not in ('core', 'direct_related'):
            raise RecapError('recap_entry_role_invalid:' + identity)
        allowed = entry.get('allowed_views', ['direct'])
        if not isinstance(allowed, list) or not allowed or not set(allowed) <= {'direct', 'after_attempt'}:
            raise RecapError('recap_entry_allowed_views_invalid:' + identity)
        for key in ('name', 'content'):
            _text(entry.get(key), key)
        for key in ('conditions', 'symbol_roles', 'triggers', 'steps', 'exceptions', 'source_record_ids'):
            _texts(entry.get(key, []), key, required=(key == 'conditions'))
        for key in ('concept_keys', 'direct_related_entry_ids', 'basic_dependency_ids', 'runtime_hold_reasons'):
            _texts(entry.get(key, []), key)
        if 'direct_use' in entry and type(entry['direct_use']) is not bool:
            raise RecapError('recap_direct_use_invalid')
        if not entry.get('source_record_ids') and not identity.startswith('MRC-'):
            raise RecapError('recap_new_identity_must_be_explicit:' + identity)
        if entry['section'] == 'solution_methods':
            _text(entry.get('first_action'), 'first_action')
            _texts(entry.get('steps'), 'steps', required=True)
        refs = entry.get('source_refs')
        if not isinstance(refs, list):
            raise RecapError('recap_source_refs_invalid')
        for ref in refs:
            _relative(ref.get('path'))
            if not SHA.fullmatch(str(ref.get('sha256', ''))):
                raise RecapError('recap_source_sha_invalid')
            page = ref.get('pdf_page')
            if page is not None and (type(page) is not int or page < 1):
                raise RecapError('recap_source_page_invalid')
            if ref.get('printed_page') is not None and not isinstance(ref['printed_page'], (str, int)):
                raise RecapError('recap_printed_page_invalid')
        if not isinstance(entry.get('review', {}), dict):
            raise RecapError('recap_review_invalid')
    if set(entry_refs) & identities or len(entry_refs) != len(set(entry_refs)):
        raise RecapError('recap_duplicate_entry_ref')
    identities.update(entry_refs)
    aliases = topic.get('entry_aliases', {})
    if not isinstance(aliases, dict) or any(
            not isinstance(old, str) or not old.strip()
            or not isinstance(target, str) or target not in identities
            or (old in identities and old != target)
            for old, target in aliases.items()):
        raise RecapError('recap_entry_alias_invalid')
    alias_policies = topic.get('entry_alias_policies', {})
    if not isinstance(alias_policies, dict) or not set(alias_policies) <= set(aliases):
        raise RecapError('recap_alias_policies_invalid')
    for policy in alias_policies.values():
        if not isinstance(policy, dict) or ('direct_use' in policy and type(policy['direct_use']) is not bool):
            raise RecapError('recap_alias_policy_invalid')
        for key in ('runtime_hold_reasons', 'practice_hold_reasons'):
            _texts(policy.get(key, []), key)
    bindings = topic.get('question_bindings', [])
    if not isinstance(bindings, list):
        raise RecapError('recap_question_bindings_invalid')
    for binding in bindings:
        _text(binding.get('question_id'), 'question_id')
        _text(binding.get('rationale'), 'binding_rationale')
        selected = _texts(binding.get('entry_ids'), 'binding_entry_ids', required=True)
        if not set(selected) <= identities:
            raise RecapError('recap_binding_unknown_entry')
        if binding.get('operation') is not None:
            _text(binding['operation'], 'operation')
        _texts(binding.get('operation_aliases', []), 'operation_aliases')
        if binding.get('operation_aliases') and not binding.get('operation'):
            raise RecapError('recap_operation_alias_requires_part')
        refs = binding.get('source_refs')
        if not isinstance(refs, list) or not refs:
            raise RecapError('recap_question_source_refs_required')
        for ref in refs:
            _relative(ref.get('path'))
            if not SHA.fullmatch(str(ref.get('sha256', ''))):
                raise RecapError('recap_question_source_sha_invalid')
    return topic


def _atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == raw:
        return
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _obsidian_math(value, *, block_long=False):
    def replace(match):
        formula = match.group(1).strip()
        if block_long and (len(formula) > 100 or '\\begin{' in formula or '\n' in formula):
            return '\n\n$$\n' + formula + '\n$$\n\n'
        return '$' + formula + '$'
    return re.sub(r'\\\((.*?)\\\)', replace, str(value), flags=re.S)


def _display_math(value, *, remove_duplicate_prefix=False):
    from math_formula_text import MATH_SPAN, TEX_MARKER, normalize_latex, normalize_rich_text
    value = str(value)
    if remove_duplicate_prefix and '$$' in value:
        prefix, tail = value.split('$$', 1)
        expressions = {normalize_latex(expression) for expression in
                       re.findall(r'\$\$(.*?)\$\$', value, flags=re.S) if expression.strip()}
        # Remove a duplicate complete inline span, including its delimiters.
        # Replacing just its body would leave an accidental empty $$ opener.
        prefix = MATH_SPAN.sub(lambda match: '' if normalize_latex(match[0]) in expressions else match[0], prefix)
        for expression in expressions:
            prefix = re.sub(r'([：:])\s*' + re.escape(expression) + r'\s*[。.;；]?\s*$', r'\1', prefix)
        prefix = re.sub(r'(?:具体结论|公式|结论)\s*[：:]\s*[。；]?\s*$', '', prefix)
        prefix = re.sub(r'[:：；，]\s*$', '。\n\n', prefix)
        value = prefix + '$$' + tail
    # Reuse the existing non-guessing formatter. Do not apply it to identifiers,
    # file paths, source snapshots or provenance dictionaries.
    if (TEX_MARKER.search(MATH_SPAN.sub('', value))
            or re.search(r'(?<![\\$])\$(?!\$)[^$\n]+\$(?!\$)', value)
            or re.search(r'\^\s*\(', value)):
        return normalize_rich_text(value)
    return value


def _display_entry(entry):
    entry = copy.deepcopy(entry)
    for field in ('content','conditions','symbol_roles','triggers','first_action','steps','exceptions',
                  'scope_restriction','question_mapping_rationale'):
        if field not in entry:
            continue
        value = entry[field]
        if isinstance(value, str):
            entry[field] = _display_math(value, remove_duplicate_prefix=(field == 'content'))
        elif isinstance(value, list):
            entry[field] = [_display_math(item) if isinstance(item, str) else item for item in value]
    return entry


def _topic_markdown(topic):
    out = ['---', 'type: math_recap_reference', 'topic_id: ' + topic['topic_id'],
           'source_role: reference_not_learner_evidence', '---', '', '# ' + topic['title'], '',
           '本页由同源结构化资料生成。条目核验不表示本题条件已满足，也不表示本人已掌握。', '']
    for section in SECTIONS:
        out += ['## ' + LABELS[section], '']
        entries = [e for e in topic['entries'] if e['section'] == section and reference_ready(e)]
        if not entries:
            out += ['当前没有已核验条目。', '']
        for entry in entries:
            entry = _display_entry(entry)
            out += ['### ' + entry['name'], '', _obsidian_math(entry['content'], block_long=True), '',
                    '- 条目：`' + entry['entry_id'] + '`',
                    '- 条件：' + _obsidian_math('；'.join(entry['conditions']))]
            for key, label in (('symbol_roles', '符号'), ('triggers', '识别线索'), ('exceptions', '例外')):
                if entry.get(key):
                    out += ['- ' + label + '：' + _obsidian_math('；'.join(entry[key]))]
            if entry.get('first_action'):
                out += ['- 第一动作：' + _obsidian_math(entry['first_action'])]
            if entry.get('steps'):
                out += ['', *[str(i) + '. ' + _obsidian_math(step) for i, step in enumerate(entry['steps'], 1)]]
            out += ['', '来源：']
            for ref in entry['source_refs']:
                page = '#page=' + str(ref['pdf_page']) if ref.get('pdf_page') else ''
                out += ['- [[' + ref['path'] + page + '|' + Path(ref['path']).name +
                        (' · PDF ' + str(ref['pdf_page']) if ref.get('pdf_page') else '') + ']]' +
                        ('；书内页码 ' + str(ref['printed_page']) if ref.get('printed_page') is not None else '')]
            out += ['']
            bindings = [b for b in topic.get('question_bindings', []) if entry['entry_id'] in b['entry_ids']]
            # The public reference table is not an answer sheet for an
            # unstarted question. Exact use steps stay in guarded bindings.
            out += ['关联真题：' + ('；'.join(b['question_id'] +
                    (' / ' + b['operation'] if b.get('operation') else '')
                    for b in bindings) if bindings else '尚未建立本条目的逐题映射。'), '']
    return '\n'.join(out).encode()


def build(root=ROOT):
    """Compile only explicitly reviewed content; never infer audit completion."""
    root = Path(root)
    paths = sorted((root / BASE / 'topics').glob('*.json'))
    if not paths:
        raise RecapError('recap_no_topics')
    topics = []
    topic_values = {}
    source_guards = {}
    all_ids = {}
    entry_catalog = {}
    entry_owners = {}
    for path in paths:
        raw = path.read_bytes()
        if len(raw) > MAX_TOPIC_BYTES:
            raise RecapError('recap_topic_too_large')
        topic = validate_topic(json.loads(raw))
        if topic['topic_id'] in {row['topic_id'] for row in topics}:
            raise RecapError('recap_duplicate_topic')
        for entry in topic['entries']:
            previous_entry = all_ids.get(entry['entry_id'])
            if previous_entry and previous_entry != digest(entry):
                raise RecapError('recap_conflicting_entry:' + entry['entry_id'])
            all_ids[entry['entry_id']] = digest(entry)
            entry_catalog[entry['entry_id']] = entry
            entry_owners.setdefault(entry['entry_id'], topic['topic_id'])
            if not reference_ready(entry):
                continue
            for ref in entry['source_refs']:
                rel = ref['path']
                previous = source_guards.get(rel)
                if previous and previous['sha256'] != ref['sha256']:
                    raise RecapError('recap_conflicting_source_versions:' + rel)
                signature = _signature(root / rel)
                if _hash_file(root / rel, signature) != ref['sha256']:
                    raise RecapError('recap_source_hash_mismatch:' + rel)
                source_guards[rel] = {'sha256': ref['sha256'], 'stat': signature}
        for binding in topic.get('question_bindings', []):
            for ref in binding['source_refs']:
                rel = ref['path']
                previous = source_guards.get(rel)
                if previous and previous['sha256'] != ref['sha256']:
                    raise RecapError('recap_conflicting_source_versions:' + rel)
                signature = _signature(root / rel)
                if _hash_file(root / rel, signature) != ref['sha256']:
                    raise RecapError('recap_question_source_hash_mismatch:' + rel)
                source_guards[rel] = {'sha256': ref['sha256'], 'stat': signature}
        topic_values[topic['topic_id']] = topic
        topics.append({'topic_id': topic['topic_id'], 'path': path.relative_to(root).as_posix(),
                       'sha256': hashlib.sha256(raw).hexdigest(),
                       'concept_keys': topic['concept_keys'],
                       'question_bindings': topic.get('question_bindings', []),
                       'selection_mode': topic.get('selection_mode', 'topic_bundle'),
                       'entry_refs': topic.get('entry_refs', []),
                       'entry_aliases': topic.get('entry_aliases', {}),
                       'entry_alias_policies': topic.get('entry_alias_policies', {}),
                       'entry_count': len(topic['entries']) + len(topic.get('entry_refs', []))})
    for topic in topic_values.values():
        for identity in topic.get('entry_refs', []):
            if identity not in entry_catalog:
                raise RecapError('recap_unknown_entry_ref:' + identity)
        topic['entries'] = topic['entries'] + [entry_catalog[x] for x in topic.get('entry_refs', [])]
    for entry in entry_catalog.values():
        for identity in entry.get('direct_related_entry_ids', []) + entry.get('basic_dependency_ids', []):
            if identity not in entry_catalog:
                raise RecapError('recap_unknown_related_entry:' + identity)
    for meta in topics:
        meta['reference_ready_count'] = sum(reference_ready(e) for e in topic_values[meta['topic_id']]['entries'])
        meta['entry_keys'] = {entry['entry_id']: _entry_keys(entry) for entry in topic_values[meta['topic_id']]['entries']}
        for alias, target in meta.get('entry_aliases', {}).items():
            if alias in entry_catalog and alias != target:
                raise RecapError('recap_alias_conflicts_with_entry:' + alias)
            meta['entry_keys'][target] = list(dict.fromkeys([*meta['entry_keys'][target], alias]))
    manifest = {'schema': SCHEMA, 'topics': topics, 'sources': source_guards,
                'entry_owners': entry_owners,
                'coverage_policy': 'authored_topic_coverage_only_not_full_textbook_or_exam_review',
                'practice_policy': 'existing_practice_registry_unchanged'}
    manifest['version'] = manifest_version(manifest)
    public_bindings = {}
    for topic in topic_values.values():
        for binding in topic.get('question_bindings', []):
            key = (binding['question_id'], binding.get('operation', ''))
            for identity in binding['entry_ids']:
                public_bindings.setdefault(identity, {})[key] = {
                    'question_id': binding['question_id'],
                    **({'operation': binding['operation']} if binding.get('operation') else {}),
                    'entry_ids': [identity]}
    table = ['# 数学三段回顾总表', '',
             '本表和专题正文由已核结构化条目生成。未配真题不妨碍教材参考；练习资格另由原入口判定。', '',
             '| 学科 | 章节 | 小专题 | 条目类型 | 名称／完整内容 | 适用条件 | 识别与调用 | 来源定位 | 关联真题 | 核验状态 |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    # Validate every captured topic before touching any published view. A writer
    # leaving an incomplete JSON, or changing a later topic while we hash PDFs,
    # must not replace the old manifest or publish an earlier subset.
    for meta in topics:
        if hashlib.sha256((root / meta['path']).read_bytes()).hexdigest() != meta['sha256']:
            raise RecapError('recap_topic_changed_during_build')
    outputs = []
    for meta in topics:
        topic = topic_values[meta['topic_id']]
        for entry in topic['entries']:
            # The master table lists each canonical definition once. Reused
            # references and alias topics remain available for navigation.
            if meta['topic_id'] != entry_owners[entry['entry_id']]:
                continue
            links = [b['question_id'] + (' / ' + b['operation'] if b.get('operation') else '')
                     for b in public_bindings.get(entry['entry_id'], {}).values()]
            entry = _display_entry(entry)
            table.append('| ' + ' | '.join(_cell(_obsidian_math(x)) for x in (
                topic['subject'], topic['chapter'],
                topic['title'], LABELS[entry['section']],
                '[[专题/' + topic['topic_id'] + '#' + entry['name'] + '|' + entry['name'] + ']]',
                '；'.join(entry['conditions']),
                '；'.join(entry.get('triggers', [])) + (' → ' + entry['first_action'] if entry.get('first_action') else ''),
                '；'.join('[[' + ref['path'] + ('#page=' + str(ref['pdf_page']) if ref.get('pdf_page') else '') +
                          '|' + Path(ref['path']).name + (' PDF ' + str(ref['pdf_page']) if ref.get('pdf_page') else '') + ']]'
                          for ref in entry['source_refs']),
                '；'.join(links) if links else '待逐题映射',
                '已核验' if reference_ready(entry) else '待核验／保留')) + ' |')
        display_topic = dict(topic)
        display_topic['question_bindings'] = [
            binding for entry in topic['entries']
            for binding in public_bindings.get(entry['entry_id'], {}).values()]
        outputs.append((root / DISPLAY / '专题' / (topic['topic_id'] + '.md'), _topic_markdown(display_topic)))
    for path, data in outputs:
        _atomic(path, data)
    _atomic(root / DISPLAY / '三段回顾总表.md', ('\n'.join(table) + '\n').encode())
    _atomic(root / MANIFEST, canonical(manifest) + b'\n')
    return {'status': 'built', 'version': manifest['version'], 'topic_count': len(topics),
            'entry_count': len(all_ids),
            'reference_ready_count': sum(reference_ready(e) for e in entry_catalog.values()),
            'manifest_path': MANIFEST.as_posix(), 'learning_write_count': 0}


def _empty(status, **extra):
    return {'schema': RESPONSE_SCHEMA, 'status': status, **{s: [] for s in SECTIONS},
            'policy': 'verified_reference_candidates_require_current_condition_check',
            'practice_policy': 'does_not_grant_practice_eligibility',
            'learning_write_count': 0, **extra}


def _key(value):
    # Same mathematical object; do not conflate a sequence with its series.
    return re.sub(r'\s+', '', str(value)).casefold().replace('等比级数', '几何级数')


def _context_keys(value):
    """Use current point/route identities, not every nested reference ID.

    A larger response can expose step graphs, cited conclusions and refinement
    candidates. Those are not a request to expand this recap into other topics.
    Root route IDs survive native budget projections, so retrying with more
    bytes keeps the same mathematical scope.
    """
    if isinstance(value, list):
        return list(dict.fromkeys(key for row in value for key in _context_keys(row)))
    if not isinstance(value, dict):
        return []
    scope = value.get('retrieval_scope')
    if isinstance(scope, dict) and scope.get('role') == 'candidate_reference':
        return []
    found = [value[key] for key in ('concept_key', 'concept_name', 'method_id', 'conclusion_id', 'step_id')
             if isinstance(value.get(key), str)]
    method = value.get('problem_solving')
    if isinstance(method, dict):
        for route in method.get('routes', []):
            if isinstance(route, dict) and route.get('status') != 'stale' and isinstance(route.get('method_id'), str):
                found.append(route['method_id'])
    return list(dict.fromkeys(found))


def query(root=ROOT, *, concepts=(), formal_id=None, source_id=None, operation=None,
          view='protected', context=None):
    if view not in ('protected', 'after_attempt', 'direct'):
        raise RecapError('recap_view_invalid')
    if view == 'protected':
        return _empty('protected', view=view)
    root = Path(root)
    try:
        raw = (root / MANIFEST).read_bytes()
        if len(raw) > MAX_MANIFEST_BYTES:
            raise RecapError('recap_manifest_too_large')
        manifest = json.loads(raw)
        if manifest.get('schema') != SCHEMA or manifest.get('version') != manifest_version(manifest):
            raise RecapError('recap_manifest_invalid')
        requested_concepts = list(dict.fromkeys(concepts))
        explicit_keys = {_key(x) for x in requested_concepts}
        keys = explicit_keys
        identities = {x for x in (formal_id, source_id) if x}
        native_id = (context or {}).get('identity') or {}
        identities.update(x for x in (native_id.get('formal_id'), native_id.get('source_question_id')) if x)
        exact = []
        has_question_binding = False
        for meta in manifest['topics']:
            for binding in meta.get('question_bindings', []):
                if binding['question_id'] in identities:
                    has_question_binding = True
                operation_keys = {_key(binding.get('operation') or ''),
                                  *(_key(x) for x in binding.get('operation_aliases', []))}
                if binding['question_id'] in identities and _key(operation or '') in operation_keys:
                    if not binding.get('source_refs'):
                        raise RecapError('recap_question_source_binding_missing')
                    for ref in binding['source_refs']:
                        guard = manifest['sources'].get(ref['path'])
                        if not guard or guard['sha256'] != ref['sha256']:
                            raise RecapError('recap_question_source_binding_invalid')
                        current = _signature(root / ref['path'])
                        if current != guard['stat'] and _hash_file(root / ref['path'], current) != ref['sha256']:
                            raise RecapError('recap_question_source_changed')
                    exact.append((meta, set(binding['entry_ids']), binding['rationale']))
        if has_question_binding and not exact:
            return _empty('scope_unresolved', view=view, version=manifest['version'],
                          reason='exact_question_operation_not_matched;do_not_expand_to_other_parts')
        def select_candidates(selected_keys):
            # An explicitly requested method/topic is the scope, not permission
            # to walk every related method already present in native context.
            # Provenance aliases are a fallback; they must not outrank an
            # intentionally authored topic bundle for that exact concept.
            selected = {}
            matched_keys = set()
            owners = {_key(identity): (identity, owner)
                      for identity, owner in manifest.get('entry_owners', {}).items()}
            topics_by_id = {meta['topic_id']: meta for meta in manifest['topics']}

            def add(meta, chosen, token):
                matched_keys.add(token)
                identity = meta['topic_id']
                if identity not in selected:
                    selected[identity] = (meta, chosen, None)
                elif chosen is None or selected[identity][1] is None:
                    selected[identity] = (meta, None, None)
                else:
                    selected[identity][1].update(chosen)

            for token in sorted(selected_keys):
                direct = [meta for meta in manifest['topics']
                          if token in {_key(x) for x in [meta['topic_id'], *meta['concept_keys']]}]
                if direct:
                    for meta in direct:
                        add(meta, None, token)
                    continue
                if token in owners:
                    identity, owner = owners[token]
                    add(topics_by_id[owner], {identity}, token)
                    continue
                for meta in manifest['topics']:
                    chosen = {identity for identity, aliases in meta.get('entry_keys', {}).items()
                              if token in {_key(alias) for alias in aliases}}
                    if chosen:
                        add(meta, chosen, token)
            return list(selected.values()), matched_keys

        candidates, matched_keys = select_candidates(explicit_keys) if not exact else (exact, set())
        context_fallback = False
        if not candidates:
            keys = {_key(x) for x in _context_keys((context or {}).get('records', []))}
            candidates, _ = select_candidates(keys)
            context_fallback = bool(candidates)
        # One resolved label must not hide another missing prerequisite.
        coverage = {
            'question_binding': 'matched' if exact else 'unmapped' if identities else 'not_requested',
            'selection_scope': 'exact_question' if exact else 'context_fallback' if context_fallback else 'explicit_concepts',
            'matched_concepts': [x for x in requested_concepts if _key(x) in matched_keys],
            'unmatched_concepts': [] if exact else [x for x in requested_concepts if _key(x) not in matched_keys],
        }
        if not candidates:
            return _empty('no_match', view=view, version=manifest['version'], query_coverage=coverage,
                          reason='no_exact_concept_or_alias_match')
        result = _empty('available', view=view, version=manifest['version'],
                        selection='exact_question_operation' if exact else 'exact_concept_candidate',
                        query_coverage=coverage)
        matched_alias_policies = {}
        for meta, _, _ in candidates:
            for alias, target in meta.get('entry_aliases', {}).items():
                policy = meta.get('entry_alias_policies', {}).get(alias)
                if policy and _key(alias) in keys:
                    matched_alias_policies.setdefault(target, []).append({'alias': alias, **policy})
        seen = set()
        held = 0
        view_restricted = 0
        loaded = {}
        by_topic = {meta['topic_id']: meta for meta in manifest['topics']}

        def load_topic(meta):
            if meta['topic_id'] in loaded:
                return loaded[meta['topic_id']]
            path = _relative(meta['path'])
            if not path.startswith(BASE.as_posix() + '/topics/'):
                raise RecapError('recap_topic_path_invalid')
            raw = (root / path).read_bytes()
            if len(raw) > MAX_TOPIC_BYTES or hashlib.sha256(raw).hexdigest() != meta['sha256']:
                raise RecapError('recap_topic_source_changed')
            topic = validate_topic(json.loads(raw))
            if topic['topic_id'] != meta['topic_id']:
                raise RecapError('recap_topic_identity_changed')
            loaded[meta['topic_id']] = topic
            return topic

        for meta, chosen, rationale in candidates:
            topic = load_topic(meta)
            entries = list(topic['entries'])

            def load_entry(identity):
                owner_id = manifest.get('entry_owners', {}).get(identity)
                if owner_id not in by_topic:
                    raise RecapError('recap_entry_owner_missing')
                owner = load_topic(by_topic[owner_id])
                matches = [entry for entry in owner['entries'] if entry['entry_id'] == identity]
                if len(matches) != 1:
                    raise RecapError('recap_entry_owner_invalid')
                return matches[0]

            for identity in topic.get('entry_refs', []):
                entries.append(load_entry(identity))
            if chosen is None and topic.get('selection_mode') == 'matched_entries' and _key(topic['topic_id']) not in keys:
                chosen = {entry['entry_id'] for entry in entries
                          if keys & {_key(x) for x in meta.get('entry_keys', {}).get(entry['entry_id'], _entry_keys(entry))}}
            if chosen is not None:
                by_entry = {entry['entry_id']: entry for entry in entries}
                pending = list(chosen)
                traversed = set()
                while pending:
                    identity = pending.pop()
                    if identity in traversed:
                        continue
                    traversed.add(identity)
                    entry = by_entry.get(identity) or load_entry(identity)
                    by_entry[identity] = entry
                    for dependency in entry.get('direct_related_entry_ids', []) + entry.get('basic_dependency_ids', []):
                        if dependency not in chosen:
                            chosen.add(dependency)
                            pending.append(dependency)
                entries = list(by_entry.values())
            for entry in entries:
                if entry['entry_id'] in seen or (chosen is not None and entry['entry_id'] not in chosen):
                    continue
                alias_policies = matched_alias_policies.get(entry['entry_id'], [])
                if not reference_ready(entry) or any(p.get('runtime_hold_reasons') for p in alias_policies):
                    held += 1
                    continue
                if view not in entry.get('allowed_views', ['direct']):
                    view_restricted += 1
                    continue
                for ref in entry['source_refs']:
                    guard = manifest['sources'].get(ref['path'])
                    if not guard or guard['sha256'] != ref['sha256']:
                        raise RecapError('recap_source_binding_invalid')
                    current = _signature(root / ref['path'])
                    if current != guard['stat'] and _hash_file(root / ref['path'], current) != ref['sha256']:
                        raise RecapError('recap_reference_source_changed')
                value = copy.deepcopy(entry)
                if alias_policies:
                    value['matched_alias_policies'] = copy.deepcopy(alias_policies)
                    if any(p.get('direct_use') is False for p in alias_policies):
                        value['direct_use'] = False
                    restrictions = [p['scope_restriction'] for p in alias_policies if p.get('scope_restriction')]
                    if restrictions:
                        value['matched_alias_scope_restrictions'] = restrictions
                    practice_holds = [reason for p in alias_policies for reason in p.get('practice_hold_reasons', [])]
                    if practice_holds:
                        value['practice_hold_reasons'] = list(dict.fromkeys([
                            *value.get('practice_hold_reasons', []), *practice_holds]))
                value.update(topic_id=topic['topic_id'], topic_title=topic['title'],
                             reference_ready=True, applicability='requires_current_condition_check',
                             practice_status='not_evaluated_use_existing_practice_reader')
                if rationale and view == 'direct':
                    value['question_mapping_rationale'] = rationale
                elif rationale:
                    value['question_mapping_rationale_status'] = 'requires_direct_view'
                result[entry['section']].append(value)
                seen.add(entry['entry_id'])
        result['held_entry_count'] = held
        result['view_restricted_entry_count'] = view_restricted
        if not seen:
            result['status'] = 'view_restricted' if view_restricted else 'no_verified_match'
        return result
    except FileNotFoundError:
        return _empty('unavailable', view=view, reason='recap_or_source_missing')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _empty('source_changed', view=view, reason=str(exc))


def teaching_recap(value):
    """Project teaching content, keeping complete mathematics and usage limits.

    Historical review transcripts stay in the authored source and standalone
    query. They are provenance, not prerequisites for a quick recap response.
    """
    value = copy.deepcopy(value)
    for section in SECTIONS:
        value[section] = [_display_entry(entry) for entry in value.get(section, [])]
        for entry in value[section]:
            for key in ('prior_review', 'prior_alias_reviews', 'prior_source_record', 'legacy_related_ids',
                        'source_audit', 'review_history', 'source_record_snapshot',
                        'original_source_refs', 'current_source_review', 'variants', 'aliases'):
                entry.pop(key, None)
            if isinstance(entry.get('review'), dict):
                entry['review'] = {k:v for k,v in entry['review'].items()
                                   if k in ('status','reviewed_at','source_relation')}
            entry['detail_lookup'] = ('math_recap.py query --concept ' + entry['entry_id'] +
                                      ' --view ' + value.get('view', 'protected'))
    value['projection'] = 'teaching_reference'
    return value


def attach(result, root=ROOT, *, concepts=(), formal_id=None, source_id=None,
           operation=None, view='protected', known_version=None, max_bytes=12000):
    recap = teaching_recap(query(root, concepts=concepts, formal_id=formal_id, source_id=source_id,
                                operation=operation, view=view, context=result))
    value = copy.deepcopy(result)
    value['recap'] = recap
    if recap['status'] == 'available' and result.get('status') in ('unknown_concept', 'no_match', 'unknown_source_id'):
        value['status'] = 'source_based'
        value['personal_context_status'] = result.get('status')
    value['version'] = digest(['teaching-with-recap-v2-profile-first', result.get('version'), recap,
                               list(concepts), formal_id, source_id, operation, view, max_bytes])
    combined_version = value['version']

    def combine(native, reference):
        return {**native, 'version': combined_version, 'recap': reference}

    def fit(native, reference):
        """Reuse existing whole-field projections, preserving personal facts."""
        candidate = combine(copy.deepcopy(native), reference)
        if len(canonical(candidate)) <= max_bytes:
            return candidate
        compact = copy.deepcopy(native)
        compact.pop('visual_dispatch', None)
        for row in compact.get('records', []):
            for field in ('questions', 'first_date', 'latest_date', 'reference_pages', 'progress', 'page'):
                row.pop(field, None)
        import math_learning_profiles as profiles
        import math_exam_profile as exam
        profiles._deduplicate_frequency_contexts(compact)
        for level in range(5):
            exam.apply_response_budget(compact, level)
            candidate = combine(compact, reference)
            native_budget = max_bytes - (len(canonical(candidate)) - len(canonical(compact)))
            if native_budget > 0 and isinstance(compact.get('memory_context'), dict):
                from math_memory_context import _bound
                bounded = _bound(copy.deepcopy(compact), native_budget)
                if bounded.get('status') != 'budget_too_small':
                    candidate = combine(bounded, reference)
            if len(canonical(candidate)) <= max_bytes:
                return candidate
        return combine(compact, reference)

    value = fit({key: item for key, item in value.items() if key != 'recap'}, recap)
    required = len(canonical(value))
    if result.get('status') == 'budget_too_small':
        required = max(required, result.get('required_min_bytes', 0) +
                       len(canonical(value)) - len(canonical(result)))
    if required > max_bytes:
        # Recap is an optional addition to the mandatory personal read. Do not
        # erase an already readable summary because its reference bundle is big.
        if result.get('status') in ('available', 'source_based') and result.get('records'):
            deferred = _empty('budget_too_small', required_min_bytes=required,
                              query_coverage=recap.get('query_coverage'),
                              reason='complete_recap_requires_larger_combined_budget')
            retained = fit(result, deferred)
            if len(canonical(retained)) <= max_bytes:
                retained['version'] = digest(['partial-recap-v1', combined_version])
                return retained
        return {'status': 'budget_too_small', 'version': combined_version,
                'source_version': result.get('source_version'), 'view': view,
                'identity': result.get('identity'), 'records': [],
                'required_min_bytes': max(required, result.get('required_min_bytes', 0)),
                'recap': _empty('budget_too_small', required_min_bytes=required),
                'reason': 'whole_recap_and_existing_context_exceed_budget'}
    reusable = (value.get('status') in ('available', 'source_based')
                and recap['status'] in ('available', 'no_match', 'protected'))
    if known_version == combined_version and reusable:
        from math_teaching_delivery import has_delivery_gap
        if not has_delivery_gap(value):
            return {'status': 'unchanged', 'version': combined_version,
                    'source_version': result.get('source_version'), 'view': view,
                    'identity': value.get('identity'), 'records': [],
                    'memory_context': {'status': 'unchanged'}, 'recap': _empty('unchanged')}
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('build')
    reader = sub.add_parser('query')
    reader.add_argument('--concept', action='append', default=[])
    reader.add_argument('--formal-id')
    reader.add_argument('--source-question-id')
    reader.add_argument('--operation')
    reader.add_argument('--view', choices=('protected', 'after_attempt', 'direct'), default='protected')
    reader.add_argument('--teaching', action='store_true', help='Return complete teaching content/conditions while omitting historical audit payloads')
    args = parser.parse_args()
    try:
        result = (build(args.repo) if args.command == 'build' else query(args.repo,
                  concepts=args.concept, formal_id=args.formal_id, source_id=args.source_question_id,
                  operation=args.operation, view=args.view))
        if args.command == 'query' and args.teaching:
            result = teaching_recap(result)
    except (OSError, ValueError) as exc:
        result = {'status': 'error', 'reason': str(exc), 'learning_write_count': 0}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result['status'] == 'error' else 0


if __name__ == '__main__':
    raise SystemExit(main())
