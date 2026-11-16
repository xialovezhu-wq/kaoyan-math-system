"""Rebuildable mathematical references for internal, unprotected retrieval.

This corpus is NOT safe discovery metadata and is never learner evidence. Only
allowlisted fields from authenticated method and active formula sources enter
it. Binding hints, personal profiles, exam applications and example answers do
not. Build explicitly; queries may validate/read a build but never compile one.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sqlite3

from math_formula_registry import FormulaRegistry, MANIFEST, formula_practice_ready

SCHEMA = 'math-memory-reference-retrieval-v1'
CONTENT_POLICY = 'mathematical_reference_no_learner_evidence'
COMPILER_VERSION = 'math-reference-compiler-v1'
BASE = '错题知识网络/个人知识点索引/做题方法'
CATALOG = BASE + '/catalog.json'
BINDINGS = BASE + '/bindings.json'
INDEX = '错题知识网络/个人知识点索引/index.sqlite3'
MAX_TEXT_CHARS = 2400
ALLOWED_VIEWS = {'direct', 'after_attempt'}
# Shared subject/object words alone cannot authorize a sibling theorem. These
# are generic vocabulary, not case identities or query-specific exceptions.
GENERIC_GRAMS = set(('函数 方程 分布 概率 矩阵 向量 积分 估计 参数 随机 变量 '
                     '性质 公式 定义 计算 求解 方法 问题 关系 比较 判断 条件 '
                     '形式 结构 表示 步骤 判定 等式 定理').split())
PRIVATE_OR_EXAMPLE = re.compile(
    r'learner|user[_ ]|personal[_ ]|PRIVATE_|SENTINEL|个人(?:概况|摘要|断点|作答|记录)|'
    r'用户|评分|掌握度|原话|实际答案|例题|例如|举例|本题|该题|本次作答|'
    r'(?:MATH[123]|GS|LA|PR)-\d|(?:^|[；。\s])例\s*\d', re.I)


class ReferenceError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in relative:
        raise ReferenceError('reference_source_path_invalid')
    current = Path(root)
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise ReferenceError('reference_hot_source_symlink_forbidden')
    return current.read_bytes()


def _native(root):
    with closing(sqlite3.connect((Path(root) / INDEX).as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        if not row:
            raise ReferenceError('reference_native_version_missing')
        # Deliberately never read payload, concept summaries, hints or utterances.
        sources = dict(db.execute('SELECT path,sha256 FROM sources WHERE path IN (?,?)',
                                  (CATALOG, BINDINGS)).fetchall())
    return json.loads(row[0]), sources


def require_reference_view(view):
    """Call before even opening a reference corpus, including on error paths."""
    if view not in ALLOWED_VIEWS:
        raise ReferenceError('reference_view_forbidden:' + str(view))


def _strings(value):
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return [x for x in value if x.strip()]
    return []


def _clean(values):
    return all(not PRIVATE_OR_EXAMPLE.search(x) for x in values)


def _complete_text_field(value):
    return isinstance(value, str) or (isinstance(value, list)
                                     and all(isinstance(x, str) for x in value))


def _grams(text):
    text = re.sub(r'\s+', '', str(text)).casefold()
    out = set(re.findall(r'[a-z][a-z0-9]{1,}', text))
    for run in re.findall(r'[\u3400-\u9fff]+', text):
        out.update(run[i:i + 2] for i in range(len(run) - 1)
                   if not set(run[i:i + 2]) & set('的与及或把从将按先再'))
    return out


def _scorer(documents):
    counts = Counter(g for d in documents for g in _grams(d['title']))
    size = len(documents)

    def score(query, value):
        return sum(math.log1p(size / (1 + counts[g])) for g in query & _grams(value))
    return score


def _source(path, sha256, collection, identity, fields):
    return {'path': path, 'sha256': sha256,
            'locator': {'collection': collection, 'id': identity, 'fields': fields}}


def _method_fragment(method, source, binding_source, role):
    # Complete condition list is indivisible; contaminated conditions discard
    # the whole fragment rather than silently weakening applicability.
    if not _complete_text_field(method.get('conditions')):
        return None
    conditions = _strings(method.get('conditions'))
    name = str(method.get('name', ''))
    if not name or not _clean([name, *conditions]):
        return None
    triggers = [x for x in _strings(method.get('triggers')) if _clean([x])]
    first = _strings(method.get('first_action'))
    first = first if _clean(first) else []
    aliases = [x for x in _strings(method.get('aliases')) if _clean([x])]
    fields = ['name', 'conditions']
    lines = ['候选教材方法：' + name]
    if aliases:
        lines.append('方法登记名称：' + '；'.join(aliases)); fields.append('aliases')
    if triggers:
        lines.append('原文触发描述：' + '；'.join(triggers)); fields.append('triggers')
    lines.append('方法条件原文（保留各条分支范围，不合并成共同条件）：')
    lines.extend('· ' + value for value in conditions)
    if first:
        lines.append('方法起步动作：' + '\n'.join(first)); fields.append('first_action')
    return {'kind': 'method', 'id': method['method_id'], 'binding_role': role,
            'title': name, 'text': '\n'.join(lines), 'conditions': conditions,
            'source_refs': [{**source, 'locator': {**source['locator'], 'fields': fields}}, binding_source]}


def _formula_fragment(record, source, method_ids):
    # No variants, exam_links, memory, derivation, examples or arbitrary nested
    # prose. Keep every formula and every condition together in this entry.
    if not all(_complete_text_field(record.get(key)) for key in ('conditions', 'formula_latex')):
        return None
    title = str(record.get('title', ''))
    formulas = _strings(record.get('formula_latex'))
    conditions = _strings(record.get('conditions'))
    if not title or not formulas or not _clean([title, *formulas, *conditions]):
        return None
    statement = _strings(record.get('statement_text'))
    statement = statement if _clean(statement) else []
    lines = ['候选公式参考：' + title, *statement, '公式：', *formulas, '本条公式的完整条件：']
    lines.extend('· ' + value for value in conditions)
    fields = ['title', 'formula_latex', 'conditions'] + (['statement_text'] if statement else [])
    return {'kind': 'formula', 'id': record['entry_id'], 'title': title,
            'text': '\n'.join(lines), 'conditions': conditions, 'formula_latex': formulas,
            'via_method_ids': sorted(method_ids),
            'source_refs': [{**source, 'locator': {**source['locator'], 'fields': fields}}]}


def export_references(repo_root, discovery_corpus_path_or_dict, destination=None, *,
                      max_text_chars=MAX_TEXT_CHARS):
    """Build explicitly from one native version; return and optionally save it.

    Callers own storage placement/registration. No backend activation or formal
    source writes occur. A maximum is a whole-fragment budget, never a slice.
    """
    if type(max_text_chars) is not int or not 200 <= max_text_chars <= MAX_TEXT_CHARS:
        raise ReferenceError('reference_text_budget_invalid')
    root = Path(repo_root).resolve()
    discovery = (discovery_corpus_path_or_dict if isinstance(discovery_corpus_path_or_dict, dict)
                 else json.loads(Path(discovery_corpus_path_or_dict).read_bytes()))
    if (discovery.get('schema') != 'math-memory-corpus-v1'
            or discovery.get('content_policy') != 'safe_discovery_metadata_only'
            or not isinstance(discovery.get('documents'), list)):
        raise ReferenceError('reference_discovery_schema_invalid')
    version, expected = _native(root)
    if discovery.get('source_version') != version:
        raise ReferenceError('reference_discovery_not_current')
    raw_cache = {}

    def reader(relative):
        if relative not in raw_cache:
            raw_cache[relative] = _read(root, relative)
        return raw_cache[relative]

    for path in (CATALOG, BINDINGS):
        if _sha(reader(path)) != expected.get(path):
            raise ReferenceError('reference_method_registry_not_current:' + path)
    catalog, bindings = (json.loads(reader(path)) for path in (CATALOG, BINDINGS))
    registry = FormulaRegistry(root, read_bytes=reader)
    if registry.manifest.get('library_mode') != 'practice_only':
        raise ReferenceError('reference_requires_active_formula_registry')
    methods = {x['method_id']: x for x in catalog.get('methods', [])}
    records = {}
    documents = sorted(discovery['documents'], key=lambda d: d['concept_key'])
    score = _scorer(documents)
    result = []
    for doc in documents:
        key, title = doc['concept_key'], doc['title']
        if not doc.get('discovery_eligible', True) or not _clean([title]):
            raise ReferenceError('reference_discovery_document_invalid:' + key)
        names = [x for x in _strings(doc.get('aliases')) if _clean([x])]
        query = _grams(' '.join([title, *names]))
        # Prefer the canonical operation over broad words introduced by aliases.
        focused_query = _grams(title) - GENERIC_GRAMS
        if not focused_query:
            focused_query = query - GENERIC_GRAMS or query
        prefix = '规范知识点：' + title
        if names:
            prefix += '\n登记名称：' + '；'.join(sorted(set(names)))
        prefix += '\n以下为检索候选参考；绑定不证明当前题适用，各片段条件分别核对。'
        if len(prefix) > max_text_chars:
            raise ReferenceError('reference_identity_exceeds_budget:' + key)
        candidates, omitted, formula_methods = [], [], {}
        bound = bindings.get('concept_bindings', {}).get(key, [])
        for item in sorted(bound, key=lambda x: (x.get('role', ''), x.get('method_id', ''))):
            mid, role = item.get('method_id'), item.get('role')
            if role not in {'primary', 'candidate'}:
                omitted.append({'kind': 'method', 'id': mid, 'reason': 'lower_priority_binding'})
                continue
            method = methods.get(mid)
            if not method:
                raise ReferenceError('reference_bound_method_missing:' + str(mid))
            method_source = _source(CATALOG, expected[CATALOG], 'methods', mid, [])
            binding_source = _source(BINDINGS, expected[BINDINGS], 'concept_bindings', key,
                                     ['method_id', 'role'])
            fragment = _method_fragment(method, method_source, binding_source, role)
            if fragment:
                relevance = score(query, ' '.join([method['name'], *_strings(method.get('aliases'))]))
                candidates.append((1, -relevance, 0 if role == 'primary' else 1, mid, fragment))
            else:
                omitted.append({'kind': 'method', 'id': mid, 'reason': 'non_reference_content'})
            # Explicit method-local links only: no global nearest-match join or
            # recursive expansion into all refinements/sibling branches.
            existing = [mid, *_strings(method.get('step_ids')), *_strings(method.get('conclusion_ids'))]
            for old_id in existing:
                for fid in registry.manifest.get('existing_to_entries', {}).get(old_id, []):
                    if fid in registry.index and registry.index[fid].get('practice_ready'):
                        formula_methods.setdefault(fid, set()).add(mid)
        for fid, mids in sorted(formula_methods.items()):
            if fid not in records:
                records[fid] = registry.get(fid, view='direct')
            record = records[fid]
            if (not formula_practice_ready(record) or record.get('source_binding_status') != 'verified'
                    or record.get('active_library') is False):
                omitted.append({'kind': 'formula', 'id': fid, 'reason': 'not_active_verified'})
                continue
            relevance = score(focused_query, record.get('title', ''))
            if relevance <= 0:
                omitted.append({'kind': 'formula', 'id': fid, 'reason': 'no_named_topic_overlap'})
                continue
            shard = registry.shards[registry.index[fid]['shard_id']]
            source = _source(shard['path'], shard['sha256'], 'entries', fid, [])
            fragment = _formula_fragment(record, source, mids)
            if fragment:
                candidates.append((0, -relevance, 0, fid, fragment))
            else:
                omitted.append({'kind': 'formula', 'id': fid, 'reason': 'non_reference_content'})
        selected, used, per_kind = [], len(prefix), Counter()
        # Precise formula bundles precede broader method descriptions. A named
        # concept gets at most three formulas and two methods, not every sibling.
        for _, _, _, identity, fragment in sorted(candidates, key=lambda x: x[:4]):
            kind = fragment['kind']
            if per_kind[kind] >= {'formula': 3, 'method': 2}[kind]:
                omitted.append({'kind': kind, 'id': identity, 'reason': 'fragment_limit'})
            elif used + 2 + len(fragment['text']) > max_text_chars:
                omitted.append({'kind': kind, 'id': identity, 'reason': 'whole_fragment_budget'})
            else:
                selected.append(fragment); per_kind[kind] += 1; used += 2 + len(fragment['text'])
        refs = {digest(ref): ref for fragment in selected for ref in fragment['source_refs']}
        text = '\n\n'.join([prefix, *[fragment['text'] for fragment in selected]])
        result.append({'id': key, 'concept_key': key, 'title': title, 'text': text,
                       # Public identity/scope fields copied from discovery,
                       # never inferred from the mathematical reference text.
                       'aliases': list(doc.get('aliases', [])),
                       'formal_ids': list(doc.get('formal_ids', [])),
                       'source_refs': sorted(refs.values(), key=canonical),
                       'fragments': selected, 'omitted': sorted(omitted, key=canonical),
                       'text_chars': len(text), 'content_policy': CONTENT_POLICY})
    dependencies = [{'path': path, 'sha256': _sha(raw)} for path, raw in sorted(raw_cache.items())]
    corpus = {'schema': SCHEMA, 'content_policy': CONTENT_POLICY, 'source_version': version,
              'compiler_version': COMPILER_VERSION,
              'compiler_sha256': _sha(Path(__file__).read_bytes()),
              'discovery_sha256': digest(discovery),
              'discovery_revision': discovery.get('retrieval_revision'),
              'formula_registry_version': registry.version, 'dependencies': dependencies,
              'max_text_chars': max_text_chars, 'documents': result,
              'learning_write_count': 0}
    corpus['version'] = digest(corpus)
    validate_references(root, corpus, discovery=discovery)
    if destination is not None:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_bytes(canonical(corpus) + b'\n')
        temporary.replace(path)
    return corpus


def validate_references(repo_root, corpus, *, discovery=None):
    """Fail closed on stale builds. Does not compile or repair anything."""
    if (corpus.get('schema') != SCHEMA or corpus.get('content_policy') != CONTENT_POLICY
            or corpus.get('version') != digest({k: v for k, v in corpus.items() if k != 'version'})):
        raise ReferenceError('reference_corpus_invalid')
    if (corpus.get('compiler_version') != COMPILER_VERSION
            or corpus.get('compiler_sha256') != _sha(Path(__file__).read_bytes())):
        raise ReferenceError('reference_compiler_changed')
    version, sources = _native(Path(repo_root).resolve())
    if version != corpus.get('source_version'):
        raise ReferenceError('reference_source_version_changed')
    if discovery is not None and digest(discovery) != corpus.get('discovery_sha256'):
        raise ReferenceError('reference_discovery_changed')
    dependencies = corpus.get('dependencies', [])
    by_path = {entry['path']: entry['sha256'] for entry in dependencies}
    if not {CATALOG, BINDINGS, MANIFEST} <= set(by_path):
        raise ReferenceError('reference_dependencies_incomplete')
    for path in (CATALOG, BINDINGS):
        if sources.get(path) != by_path[path]:
            raise ReferenceError('reference_native_binding_changed:' + path)
    for path, sha256 in by_path.items():
        if _sha(_read(repo_root, path)) != sha256:
            raise ReferenceError('reference_dependency_changed:' + path)
    return True


def load_references(repo_root, path, *, view, discovery=None):
    require_reference_view(view)  # Must precede Path(), exists(), and read_bytes().
    corpus = json.loads(Path(path).read_bytes())
    validate_references(repo_root, corpus, discovery=discovery)
    return corpus


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--discovery', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    corpus = export_references(args.repo, args.discovery, args.output)
    print(json.dumps({'schema': SCHEMA, 'version': corpus['version'],
                      'documents': len(corpus['documents']),
                      'text_chars': sum(d['text_chars'] for d in corpus['documents'])}))


if __name__ == '__main__':
    main()
