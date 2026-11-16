"""Optional objective exam-frequency projection; never a learning observation.

The cold builder authenticates the local registry. Hot readers use only its
aggregate projection and source stamps, never paper text or answer material.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re

BASE = Path('真题数据库')
FILES = tuple(BASE / name for name in ('metadata.json', 'frequency.json', 'concept-links.json'))
SCHEMA = 'math-exam-context-v1'
ANNOUNCEMENT_SCHEMA = 'math-exam-announcement-v1'
RECORD_BRIEF_SCHEMA = 'math-exam-frequency-brief-v1'
PRIMARY_WINDOWS = ('math1_2005_2025', 'math1_2016_2025')
TIERS = {'高频', '中频', '低频', '样本不足', '未见命中'}
POLICY = '客观真题统计，不是个人错误、学习次数或掌握度；低频不等于不考。'
REVIEWED_EMPTY_MAPPINGS = {
    'general_operation': (
        'not_separately_counted', '通用操作，未单独统计考频',
        '须结合当前题的具体对象使用；没有单独统计不表示未被考查。'),
    'non_knowledge_object': (
        'not_applicable', '非知识点对象，考频不适用',
        '本项承担导航、来源或流程作用，不生成数学考点次数或个人学习表现。'),
    'unresolved_scope': (
        'scope_unresolved', '范围尚未核定',
        '须先核清具体对象或跨范围条件，现不提供该点考次。'),
}
WINDOW_LABELS = {
    'math1_2005_2025': '数学一 2005—2025',
    'math1_2016_2025': '数学一近十年 2016—2025',
    'math1_2009_2025': '数学一 2009—2025（三卷同范围对照）',
    'math1_1987_2004': '数学一早期 1987—2004',
    'math2_2009_2025': '数学二 2009—2025（跨卷参考）',
    'math3_2009_2025': '数学三 2009—2025（跨卷参考）',
}
_COVERAGE_FIELDS = {
    'status', 'coverage_status', 'source_status', 'available_year_count',
    'available_paper_count', 'paper_count', 'question_count', 'topic_count',
    'mapped_question_count', 'unmapped_question_count', 'missing_years',
    'available_years', 'year_range', 'years', 'expected_year_count',
    'annotated_question_count', 'reviewed_question_count', 'source_tag_question_count',
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _coverage(value):
    """Retain coverage counts/ranges, never arbitrary paper or solution fields."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        normalized = {'数学一': 'math1', '数学二': 'math2', '数学三': 'math3'}.get(key, key)
        if re.fullmatch(r'math[123](?:_\d{4}_\d{4})?', normalized) and isinstance(item, dict):
            result[normalized] = _coverage(item)
        elif key in _COVERAGE_FIELDS:
            if isinstance(item, (str, int, float, bool)) or item is None:
                result[key] = item
            elif isinstance(item, list) and all(type(x) is int for x in item):
                result[key] = list(item)
    return result


def _frequency_policy(value):
    if not isinstance(value, dict):
        return {}
    result = {key: value[key] for key in (
        'metric', 'primary_window', 'recent_window', 'cross_paper_policy',
        'annotation_limit', 'priority_rule', 'threshold_summary')
        if isinstance(value.get(key), str)}
    if type(value.get('minimum_years')) is int and value['minimum_years'] > 0:
        result['minimum_years'] = value['minimum_years']
    if type(value.get('labels_are_local_not_official')) is bool:
        result['labels_are_local_not_official'] = value['labels_are_local_not_official']
    rules = value.get('tier_rules')
    if isinstance(rules, dict):
        result['tier_rules'] = {k: rules[k] for k in ('high', 'medium', 'low', 'unobserved')
                                if isinstance(rules.get(k), str)}
        if not result.get('threshold_summary'):
            names = {'high': '高频', 'medium': '中频', 'low': '低频', 'unobserved': '未见命中'}
            result['threshold_summary'] = '；'.join(names[k] + '：' + text
                                                     for k, text in result['tier_rules'].items())
    return result


def load_registry(root, read_source):
    """An absent or unfinished import never blocks existing personal evidence."""
    root = Path(root)
    present = [(root / relative).is_file() for relative in FILES]
    if not any(present):
        return None
    refs, bodies = [], {}
    issue = None
    for relative, exists in zip(FILES, present):
        if not exists:
            continue
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            issue = 'unsafe_registry_path'
            continue
        try:
            source = read_source(path, 'external')
            refs.append({'path': str(relative), 'sha256': source['sha256']})
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != source['sha256']:
                raise RuntimeError('source_changed_during_build: ' + str(relative))
            bodies[relative.name] = json.loads(raw)
        except (OSError, ValueError, KeyError):
            issue = 'invalid_registry_data'
    version = 'MATH-EXAM-' + hashlib.sha256(_canonical(refs).encode()).hexdigest()
    result = {'status': 'unavailable', 'source_version': version, 'source_refs': refs,
              'reason': issue or 'registry_incomplete'}
    if issue or not all(present) or len(bodies) != len(FILES):
        return result
    metadata, frequency, links = (bodies[path.name] for path in FILES)
    if (not all(isinstance(x, dict) for x in (metadata, frequency, links))
            or frequency.get('schema') != 'math-exam-frequency-v1'
            or links.get('schema') != 'math-exam-concept-links-v1'
            or not isinstance(frequency.get('topics'), dict)
            or not isinstance(links.get('concepts'), dict)):
        return {**result, 'reason': 'registry_schema_invalid'}
    versions = [body.get('source_version') for body in (metadata, frequency, links)]
    if any(not isinstance(v, str) or not v for v in versions) or len(set(versions)) != 1:
        return {**result, 'reason': 'registry_version_mismatch'}
    return {**result, 'status': 'ready', 'reason': None,
            'declared_source_version': versions[0],
            'coverage': _coverage(frequency.get('coverage') or metadata.get('coverage')),
            'frequency_policy': _frequency_policy(frequency.get('policy')),
            'topics': frequency['topics'], 'concepts': links['concepts']}


def _window_issue(key, value):
    """Validate observed years, never substitute the available-paper inventory."""
    if not isinstance(value, dict):
        return 'window_missing_or_invalid'
    counts = {field: value.get(field) for field in
              ('question_count', 'year_count', 'available_year_count')}
    tier = value.get('frequency_tier', value.get('tier'))
    if (any(type(v) is not int or v < 0 for v in counts.values())
            or counts['year_count'] > counts['available_year_count']
            or counts['year_count'] > counts['question_count'] or tier not in TIERS):
        return 'counts_or_tier_invalid'
    if counts['available_year_count'] == 0 and tier != '样本不足':
        return 'empty_sample_has_frequency_tier'
    if counts['question_count'] == 0 and tier not in {'样本不足', '未见命中'}:
        return 'zero_questions_has_frequency_tier'
    if bool(counts['question_count']) != bool(counts['year_count']):
        return 'questions_and_year_count_inconsistent'
    match = re.fullmatch(r'math[123]_(\d{4})_(\d{4})', key)
    if not match:
        return 'window_scope_unknown'
    start, end = map(int, match.groups())
    if counts['available_year_count'] > end - start + 1:
        return 'available_year_count_exceeds_window'
    year_range = value.get('year_range', [start, end])
    if (not isinstance(year_range, list) or len(year_range) != 2
            or any(type(year) is not int for year in year_range) or year_range != [start, end]):
        return 'year_range_disagrees_with_window'
    years = value.get('years')
    if not isinstance(years, list):
        return 'observed_years_missing'
    if (any(type(year) is not int or not start <= year <= end for year in years)
            or len(set(years)) != len(years)):
        return 'observed_years_invalid'
    if len(years) != counts['year_count']:
        return 'observed_years_count_mismatch'
    available = value.get('available_years')
    if available is not None:
        if (not isinstance(available, list)
                or any(type(year) is not int or not start <= year <= end for year in available)
                or len(set(available)) != len(available)
                or len(available) != counts['available_year_count']):
            return 'available_years_invalid'
        if not set(years) <= set(available):
            return 'observed_years_outside_available_papers'
    missing = value.get('missing_years')
    if missing is not None:
        if (not isinstance(missing, list)
                or any(type(year) is not int or not start <= year <= end for year in missing)
                or len(set(missing)) != len(missing)
                or set(years) & set(missing)
                or (available is not None and set(available) & set(missing))):
            return 'missing_years_invalid'
    if not isinstance(value.get('count_scope'), str) or not value['count_scope'].strip():
        return 'count_scope_missing'
    return None


def _window(key, value):
    if _window_issue(key, value):
        return None
    counts = {field: value[field] for field in
              ('question_count', 'year_count', 'available_year_count')}
    tier = value.get('frequency_tier', value.get('tier'))
    result = {**counts, 'frequency_tier': tier,
              'scope': WINDOW_LABELS.get(key, key), 'years': sorted(value['years'])}
    for field in ('year_range', 'missing_years', 'available_years'):
        item = value.get(field)
        if isinstance(item, list) and all(type(x) is int for x in item):
            result[field] = list(item)
    for field in ('count_scope', 'coverage_status'):
        if isinstance(value.get(field), str):
            result[field] = value[field]
    return result


def project(registry, concept_key, *, compact=False):
    if registry is None:
        return None
    result = {'schema': SCHEMA, 'status': registry['status'],
              'source_version': registry['source_version'], 'policy': POLICY}
    if registry['status'] != 'ready':
        return {**result, 'reason': registry['reason']}
    result['declared_source_version'] = registry['declared_source_version']
    result['coverage'] = copy.deepcopy(registry['coverage'])
    result['frequency_policy'] = copy.deepcopy(registry['frequency_policy'])
    mapping = registry['concepts'].get(concept_key)
    if not isinstance(mapping, dict):
        return {**result, 'status': 'not_mapped', 'reason': 'no_reviewed_concept_mapping'}
    ids = mapping.get('topic_ids', [])
    relation = mapping.get('relation')
    mapping_status = mapping.get('mapping_status')
    if mapping_status is not None and not isinstance(mapping_status, str):
        return {**result, 'status': 'unavailable', 'reason': 'concept_mapping_invalid'}
    if ids == [] and mapping_status in REVIEWED_EMPTY_MAPPINGS:
        reason = mapping.get('not_mappable_reason')
        basis = mapping.get('mapping_basis')
        if not all(isinstance(text, str) and text.strip() for text in (reason, basis)):
            return {**result, 'status': 'unavailable', 'reason': 'reviewed_empty_mapping_reason_required'}
        status, label, note = REVIEWED_EMPTY_MAPPINGS[mapping_status]
        # Corpus totals and tier definitions could be misread as this empty
        # mapping's own statistics. Keep its reviewed scope and provenance only.
        result.pop('coverage', None)
        result.pop('frequency_policy', None)
        return {**result, 'status': status, 'status_label': label,
                'mapping_status': mapping_status, 'mapping_basis': basis,
                'not_mappable_reason': reason, 'reason': reason, 'scope_note': note,
                'policy': '已审核映射范围；本项不生成题目频次、个人错误或掌握度。'}
    if (not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids)
            or relation not in ('exact', 'broader_topic')
            or mapping_status in REVIEWED_EMPTY_MAPPINGS
            or (mapping_status == 'conditional_multi_topic' and relation != 'broader_topic')):
        return {**result, 'status': 'unavailable', 'reason': 'concept_mapping_invalid'}
    result.update(relation=relation,
                  mapping_basis=str(mapping.get('mapping_basis', '未记录')),
                  frequency_scope=('mapped_topic' if relation == 'exact' else 'parent_topic_not_subpoint'),
                  scope_note=('仅统计映射主题，不推断本人的学习表现。' if relation == 'exact' else
                              '父主题统计，不代表当前细点自身考次。'))
    if isinstance(mapping_status, str) and mapping_status:
        result['mapping_status'] = mapping_status
    if mapping_status == 'conditional_multi_topic':
        result['scope_note'] = ('按当前题的对象与条件分别使用各父主题；这些范围的考次不能相加或合并为当前细点自身考次。')
    topics, invalid, unready_topics = [], [], []
    for topic_id in dict.fromkeys(ids):
        raw = registry['topics'].get(topic_id)
        if not isinstance(raw, dict) or not isinstance(raw.get('name'), str):
            invalid.append(topic_id)
            unready_topics.append({'topic_id': topic_id, 'reason': 'topic_missing_or_invalid'})
            continue
        windows = raw.get('windows', {})
        if not isinstance(windows, dict):
            invalid.append(topic_id)
            unready_topics.append({'topic_id': topic_id, 'name': raw['name'], 'reason': 'topic_windows_invalid'})
            continue
        valid = {key: projected for key, value in windows.items()
                 if key in WINDOW_LABELS and (projected := _window(key, value)) is not None}
        declared_windows = {key for key in windows if key in WINDOW_LABELS}
        issues = {key: issue for key in declared_windows | set(PRIMARY_WINDOWS)
                  if (issue := _window_issue(key, windows.get(key)))}
        if declared_windows != set(valid) or any(k not in valid for k in PRIMARY_WINDOWS):
            invalid.append(topic_id)
        basis = raw.get('annotation_basis', raw.get('source_role', 'unknown'))
        topic = {'topic_id': topic_id, 'name': raw['name'],
                       'subject': str(raw.get('subject', '')),
                       'annotation_basis': basis if basis in ('source-tag', 'reviewed', 'source-tag-and-reviewed') else 'unknown',
                       'windows': valid}
        if issues:
            topic['unready_windows'] = issues
        topics.append(topic)
    result['topics'] = topics
    if unready_topics:
        result['unready_topics'] = unready_topics
    if invalid:
        result['status'] = 'partial' if topics else 'unavailable'
        result['reason'] = 'some_topic_statistics_unavailable'
    return compact_context(result) if compact else result


def compact_context(value):
    """Prioritize the Math I study range; defer cross-paper and early statistics."""
    result = copy.deepcopy(value)
    policy = result.get('frequency_policy', {})
    if policy:
        result['frequency_policy'] = {k: policy[k] for k in (
            'metric', 'threshold_summary', 'minimum_years', 'labels_are_local_not_official',
            'annotation_limit', 'priority_rule') if k in policy}
    for topic in result.get('topics', []):
        windows = topic['windows']
        extra = [key for key in windows if key not in PRIMARY_WINDOWS]
        topic['windows'] = {key: windows[key] for key in PRIMARY_WINDOWS if key in windows}
        for window in topic['windows'].values():
            # Observed years are the teaching payload. The inventory of every
            # available paper is provenance and must not be read as hit years.
            window.pop('available_years', None)
        if extra:
            topic['additional_window_ids'] = extra
    return result


def defer_context(value):
    """Defer verbose metadata, preserving the complete short announcement."""
    if value.get('status') not in ('ready', 'partial'):
        return copy.deepcopy(value)
    result = {'schema': SCHEMA, 'status': 'detail_deferred',
              'source_version': value['source_version'],
              'frequency_scope': value.get('frequency_scope'),
              'detail_lookup': 'same_concept_with_larger_max_bytes',
              'reason': 'verbose_exam_metadata_omitted;announcement_preserved',
              'announcement': announcement(value)}
    for field in ('mapping_status', 'relation', 'scope_note'):
        if field in value:
            result[field] = value[field]
    return result


def stale(value):
    return {'schema': SCHEMA, 'status': 'stale',
            'source_version': value.get('source_version') if value else None,
            'reason': 'exam_sources_changed;refresh_required', 'policy': POLICY}


def announcement(value, view='direct'):
    """Answer-safe compact frequency data after the caller's source guards.

    Each topic/window remains independent. ``years`` is the complete observed
    year list, ``question_count`` follows the source's deduplicated count_scope.
    Missing/invalid years never fall back to available_years or a guessed list.
    """
    if view == 'protected' or value is None:
        return None
    if view not in ('after_attempt', 'direct'):
        raise ValueError('invalid_exam_announcement_view')
    result = {'schema': ANNOUNCEMENT_SCHEMA, 'status': 'not_ready',
              'source_version': value.get('source_version')}
    for field in ('mapping_status', 'relation', 'frequency_scope', 'scope_note'):
        if field in value:
            result[field] = value[field]
    empty_statuses = {row[0] for row in REVIEWED_EMPTY_MAPPINGS.values()}
    status = value.get('status')
    if status in empty_statuses:
        return {**result, 'status': status, 'status_label': value['status_label'],
                'reason': value.get('not_mappable_reason', value.get('reason'))}
    if status not in ('ready', 'partial', 'detail_deferred'):
        labels = {'stale': '真题来源已变化，考频暂未就绪',
                  'not_mapped': '本点尚无已审核考频映射',
                  'unavailable': '本点考频资料暂未就绪'}
        return {**result, 'status_label': labels.get(status, '本点考频暂未就绪'),
                'reason': value.get('reason', 'exam_context_not_ready')}
    data = value.get('announcement') if status == 'detail_deferred' else value
    if not isinstance(data, dict):
        return {**result, 'status_label': '短考频播报暂未就绪', 'reason': 'announcement_missing'}
    topics, unready = [], copy.deepcopy(data.get('unready_topics', []))
    if status == 'detail_deferred':
        unready.extend(copy.deepcopy(data.get('unready', [])))
    for topic in data.get('topics', []):
        topic_id, name = topic.get('topic_id'), topic.get('name')
        if not isinstance(topic_id, str) or not isinstance(name, str) or not name:
            unready.append({'topic_id': topic_id, 'reason': 'topic_missing_or_invalid'})
            continue
        windows = {}
        for key in PRIMARY_WINDOWS:
            raw = topic.get('windows', {}).get(key)
            issue = _window_issue(key, raw)
            if issue:
                previous_gap = next((gap for gap in unready if gap.get('topic_id') == topic_id
                                     and gap.get('window_id') == key), {})
                issue = topic.get('unready_windows', {}).get(key, previous_gap.get('reason', issue))
                gap = {'topic_id': topic_id, 'name': name, 'window_id': key, 'reason': issue}
                if gap not in unready:
                    unready.append(gap)
                continue
            validated = _window(key, raw)
            windows[key] = {field: validated[field] for field in
                            ('scope', 'years', 'question_count', 'year_count',
                             'available_year_count', 'frequency_tier', 'count_scope')}
            for field in ('coverage_status', 'missing_years'):
                if validated.get(field):
                    windows[key][field] = copy.deepcopy(validated[field])
        if windows:
            topics.append({'topic_id': topic_id, 'name': name, 'windows': windows})
    result['topics'] = topics
    if unready:
        result['unready'] = unready
    result['status'] = 'partial' if topics and unready else 'ready' if topics else 'not_ready'
    if not topics:
        result['status_label'] = '考频年份或统计范围尚未核齐'
    return result


def announcement_lines(value):
    """Render counts and scope; observed years remain in data for verification."""
    if not value:
        return []
    if value.get('schema') != ANNOUNCEMENT_SCHEMA:
        value = announcement(value)
    if not value:
        return []
    status = value.get('status')
    if status not in ('ready', 'partial'):
        line = value.get('status_label', '考频暂未就绪') + '。'
        if value.get('reason') and status in {row[0] for row in REVIEWED_EMPTY_MAPPINGS.values()}:
            line += '原因：' + value['reason']
        return [line]
    parent = value.get('frequency_scope') == 'parent_topic_not_subpoint'
    lines = [value['scope_note']] if value.get('scope_note') else []
    for topic in value.get('topics', []):
        for key in PRIMARY_WINDOWS:
            window = topic['windows'].get(key)
            if not window:
                continue
            scope = {'math1_2005_2025': '数学一主统计范围',
                     'math1_2016_2025': '数学一近十年'}.get(key, window['scope'])
            lines.append(('父主题' if parent else '主题') + '“' + topic['name'] + '”：'
                         + scope + '，' + window['frequency_tier'] + '，考查'
                         + str(window['question_count']) + '次（同卷同题去重）。')
    for gap in value.get('unready', []):
        scope = WINDOW_LABELS.get(gap.get('window_id'), '该主题统计')
        lines.append('“' + str(gap.get('name', gap.get('topic_id', '当前主题'))) + '”的'
                     + scope + '未就绪：真实出现年份或计数范围未通过校验，不据此报零次。')
    return lines


def brief_for_records(records, view='direct', *, include_lines=False):
    """Deduplicate 1–3 guarded concept records without merging topic counts.

    ``topics`` owns each consistent topic/window statistic exactly once;
    ``contexts`` retains each concept's relationship and coverage boundaries.
    Conflicting topic values or source versions are withheld, never selected by
    record order. Rendering is optional so years are not repeated in the payload.
    """
    if view == 'protected':
        return None
    if view not in ('direct', 'after_attempt'):
        raise ValueError('invalid_exam_announcement_view')
    if not isinstance(records, (list, tuple)) or len(records) > 3:
        raise ValueError('exam_brief_requires_at_most_three_records')
    contexts, candidates, gap_rows, conflicts, duplicate_keys = {}, {}, {}, [], set()
    empty_statuses = {row[0] for row in REVIEWED_EMPTY_MAPPINGS.values()}

    def gap(value, concept_key):
        identity = _canonical(value)
        item = gap_rows.setdefault(identity, {**copy.deepcopy(value), 'concept_keys': []})
        if concept_key not in item['concept_keys']:
            item['concept_keys'].append(concept_key)

    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get('concept_key'), str)
                or not record['concept_key']):
            raise ValueError('exam_brief_concept_identity_required')
        key = record['concept_key']
        name = record.get('concept_name')
        name = name if isinstance(name, str) and name else key
        brief = announcement(record.get('exam_context'), view=view)
        brief = brief or {'status': 'not_ready', 'reason': 'exam_context_missing',
                          'status_label': '本点考频资料暂未就绪'}
        topics = brief.get('topics', [])
        gaps = brief.get('unready', [])
        topic_ids = list(dict.fromkeys([topic['topic_id'] for topic in topics]
                                      + [item['topic_id'] for item in gaps if item.get('topic_id')]))
        context = {'concept_key': key, 'concept_name': name,
                   'status': brief['status'], 'topic_ids': topic_ids,
                   'relation': brief.get('relation') or {
                       'mapped_topic': 'exact', 'parent_topic_not_subpoint': 'broader_topic',
                   }.get(brief.get('frequency_scope')),
                   'source_version': brief.get('source_version')}
        for field in ('mapping_status', 'frequency_scope', 'scope_note', 'reason', 'status_label'):
            if field in brief:
                context[field] = copy.deepcopy(brief[field])
        if key in contexts and contexts[key] != context:
            duplicate_keys.add(key)
        else:
            contexts.setdefault(key, context)
        for item in gaps:
            gap(item, key)
        for topic in topics:
            candidates.setdefault(topic['topic_id'], []).append({
                'concept_key': key, 'source_version': brief.get('source_version'),
                'topic': copy.deepcopy(topic)})
    for key in sorted(duplicate_keys):
        contexts[key] = {'concept_key': key, 'status': 'not_ready', 'topic_ids': [],
                         'relation': None, 'reason': 'concept_context_conflict',
                         'status_label': '同一概念的考频范围记录不一致'}
        conflicts.append({'concept_key': key, 'reason': 'concept_context_conflict'})
    topics, topic_conflicts, source_versions = [], set(), set()
    for topic_id, values in candidates.items():
        values = [item for item in values if item['concept_key'] not in duplicate_keys]
        if not values:
            continue
        keys = list(dict.fromkeys(item['concept_key'] for item in values))
        versions = {item['source_version'] if isinstance(item['source_version'], str) else None
                    for item in values}
        signatures = {_canonical(item['topic']) for item in values}
        reason = ('source_version_missing' if any(not isinstance(v, str) or not v for v in versions) else
                  'topic_source_version_conflict' if len(versions) != 1 else
                  'topic_statistics_conflict' if len(signatures) != 1 else None)
        if reason:
            topic_conflicts.add(topic_id)
            names = {item['topic']['name'] for item in values}
            conflicts.append({'topic_id': topic_id, 'concept_keys': keys, 'reason': reason,
                              **({'name': next(iter(names))} if len(names) == 1 else {})})
            continue
        source_versions.update(versions)
        topics.append({**values[0]['topic'], 'concept_keys': keys})
    # Separate sources cannot form one current statistical brief, even if the
    # differing versions happen to contribute disjoint topic IDs.
    if len(source_versions) > 1:
        topic_conflicts.update(topic['topic_id'] for topic in topics)
        conflicts.append({'reason': 'mixed_exam_source_versions',
                          'source_versions': sorted(source_versions),
                          'topic_ids': [topic['topic_id'] for topic in topics]})
        topics = []
    available = {topic['topic_id'] for topic in topics}
    for key, context in contexts.items():
        if key in duplicate_keys or context['status'] in empty_statuses:
            continue
        ids = context['topic_ids']
        usable = [topic_id for topic_id in ids if topic_id in available]
        if set(ids) & topic_conflicts:
            context['status'] = 'partial' if usable else 'not_ready'
            context['reason'] = 'referenced_topic_statistics_conflict'
        if ids and len(usable) != len(ids):
            context['available_topic_ids'] = usable
            if not usable:
                context['status'] = 'not_ready'
        if context['status'] == 'not_ready' and not ids and context.get('reason'):
            gap({'reason': context['reason']}, key)
    problem = bool(conflicts or gap_rows or any(value['status'] in ('not_ready', 'partial')
                                               for value in contexts.values()))
    status = ('partial' if problem else 'ready') if topics else (
        'not_ready' if problem or not contexts else 'no_independent_statistics')
    if not source_versions:
        source_versions = {context['source_version'] for context in contexts.values()
                           if isinstance(context.get('source_version'), str) and context['source_version']}
    result = {'schema': RECORD_BRIEF_SCHEMA, 'status': status,
              'source_version': next(iter(source_versions)) if len(source_versions) == 1 else None,
              'contexts': list(contexts.values()), 'topics': topics,
              'display_policy': '讲题默认只报考频等级、去重考查次数及必要统计范围；不列具体年份或出现年份数。父主题必须标明，不能当作细点考次。',
              'count_policy': '相同主题和窗口的完整统计一致时只报一次；不同主题题次不能相加。'}
    if gap_rows:
        result['unready'] = list(gap_rows.values())
    if conflicts:
        result['conflicts'] = conflicts
    if include_lines:
        result['lines'] = brief_lines(result)
    return result


def brief_lines(value):
    """Render shared topic statistics once while preserving concept boundaries."""
    if not value:
        return []
    if value.get('schema') != RECORD_BRIEF_SCHEMA:
        raise ValueError('exam_record_brief_schema_required')
    contexts = {item['concept_key']: item for item in value.get('contexts', [])}
    lines, notes = [], {}
    for context in contexts.values():
        name = context.get('concept_name', context['concept_key'])
        if context.get('scope_note') and context.get('topic_ids'):
            notes.setdefault(context['scope_note'], []).append(name)
        elif context.get('status_label'):
            line = '“' + name + '”：' + context['status_label'] + '。'
            if context.get('status') in {row[0] for row in REVIEWED_EMPTY_MAPPINGS.values()} and context.get('reason'):
                line += '原因：' + context['reason']
            lines.append(line)
    lines += ['“' + '、'.join(names) + '”的范围：' + note for note, names in notes.items()]
    for topic in value.get('topics', []):
        associated = [contexts[key] for key in topic.get('concept_keys', []) if key in contexts]
        scope = ('parent_topic_not_subpoint' if associated and all(item.get('relation') == 'broader_topic'
                                                                  for item in associated) else 'mapped_topic')
        lines += announcement_lines({'schema': ANNOUNCEMENT_SCHEMA, 'status': 'ready',
                                     'frequency_scope': scope, 'topics': [topic]})
    for conflict in value.get('conflicts', []):
        if conflict['reason'] == 'mixed_exam_source_versions':
            lines.append('当前记录的真题来源版本不一致，考频数值暂未就绪。')
        elif conflict.get('topic_id'):
            lines.append('主题“' + conflict.get('name', conflict['topic_id']) + '”的统计或来源不一致，暂缓播报；不择一、不相加。')
    for item in value.get('unready', []):
        if item.get('window_id'):
            lines.append('“' + str(item.get('name', item.get('topic_id'))) + '”的'
                         + WINDOW_LABELS.get(item['window_id'], item['window_id'])
                         + '数据未核齐，不据此报零次。')
    return lines or ['当前没有可播报的知识点考频记录。']


def page_lines(value):
    if not value:
        return []
    lines = ['', '## 真题考频与复习优先级', '', value.get('policy', POLICY),
             '统计版本：`' + value['source_version'] + '`。', '']
    if value.get('status') in {row[0] for row in REVIEWED_EMPTY_MAPPINGS.values()}:
        return lines + [value['status_label'] + '。', '',
                        '审核理由：' + value['not_mappable_reason'], '',
                        '映射依据：' + value['mapping_basis'], '', value['scope_note'], '']
    if value.get('status') == 'detail_deferred':
        return lines + announcement_lines(announcement(value)) + ['']
    if value.get('status') not in ('ready', 'partial'):
        return lines + ['客观真题统计当前状态：' + value['status'] + '；不据此判为零考次。', '']
    lines += [value['scope_note'], '']
    policy = value.get('frequency_policy', {})
    for field in ('metric', 'threshold_summary', 'annotation_limit', 'priority_rule'):
        if policy.get(field):
            lines += [policy[field] + '。', '']
    if policy.get('minimum_years'):
        lines += ['有效样本最低为 ' + str(policy['minimum_years']) + ' 个已收录年份；不足时标记样本不足。', '']
    if policy.get('labels_are_local_not_official'):
        lines += ['高、中、低频是本地统计标签，不是官方权重。', '']
    for topic in value.get('topics', []):
        basis = {'source-tag': '来源标签统计，未冒称逐题独立复核',
                 'reviewed': '已审核考点映射',
                 'source-tag-and-reviewed': '来源标签与人工审核标注混合，不代表所有题均已逐题审核',
                 'unknown': '标注依据未明确'}.get(topic['annotation_basis'])
        lines += ['### ' + topic['name'], '', basis + '。', '']
        for key in PRIMARY_WINDOWS + tuple(k for k in topic['windows'] if k not in PRIMARY_WINDOWS):
            window = topic['windows'].get(key)
            if window:
                lines.append('- ' + window['scope'] + '：' + window['frequency_tier'] + '；'
                             + str(window['question_count']) + ' 题，涉及 '
                             + str(window['year_count']) + '/' + str(window['available_year_count'])
                             + ' 个已收录年份；出现年份：'
                             + ('、'.join(str(year) for year in window['years']) or '本窗口未见命中') + '。')
        lines += ['']
    if value.get('status') == 'partial':
        lines += ['部分映射或统计窗口尚未就绪，缺项不按零次解释。', '']
    if value.get('coverage'):
        lines += ['收录范围与缺项：`' + _canonical(value['coverage']) + '`。', '']
    return lines
