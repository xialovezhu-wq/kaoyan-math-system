"""A textbook route must reach teaching without becoming a personal result."""
import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '错题知识网络/scripts'))
import math_concept_index as index
import math_learning_profiles as profiles
import math_problem_methods as methods
import study_personalization_math as published


class ProblemMethodsTests(unittest.TestCase):
    def setUp(self):
        # The caller chooses a verified cold output root for all fixture files.
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('MATH_METHOD_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        adapter = patch.dict(sys.modules, {'math_concept_sources': types.SimpleNamespace(collect_sources=lambda root: [])})
        adapter.start()
        self.addCleanup(adapter.stop)
        self.card = self.write('错题知识网络/错题卡/LA-001_结构计算.md', '''---
id: LA-001
knowledge:
- 行列式计算
wrong_point: 原卡只记录过启动犹豫，未归因为某一种方法错误。
wrong_history: []
mastery_history: []
---
## 题目
固定题面，维护方法不修改此卡。
''')
        self.pdf = self.write('线代讲义/fixture.pdf', 'verified textbook fixture')
        self.key = index.concept_key('行列式计算')
        self.method = {
            'method_id': 'LA-DET-TRIANGLE', 'name': '化为基本行列式', 'subject': 'linear_algebra',
            'aliases': ['具体型行列式入口'], 'triggers': ['已给出全部矩阵元素'],
            'first_action': '比较各行列结构，选出能通过合法初等变换制造零的位置。',
            'conditions': ['只把一行的倍数加到另一行不会改变行列式。', '交换两行必须变号；提取行因子必须保留外因子。'],
            'steps': ['先标出重复或比例结构。', '制造零并化为三角形。', '乘对角元并恢复外因子和符号。'],
            'branches': ['若同阶结构重复出现，另检查递推法的适用性。'],
            'pitfalls': ['不能把行列式整体加法误用成矩阵加法。'],
            'source_refs': [{'path': str(self.pdf.relative_to(self.root)),
                             'sha256': hashlib.sha256(self.pdf.read_bytes()).hexdigest(),
                             'pdf_pages': [8, 9], 'section': '行列式计算方法'}]}
        self.binding = {'method_id': self.method['method_id'],
                        'applicability': '元素已知且存在可消元结构。',
                        'specific_hint': '先检查当前题的重复行列结构。'}
        self.catalog = {'schema': methods.CATALOG_SCHEMA, 'methods': [self.method]}
        self.bindings = {'schema': methods.BINDINGS_SCHEMA,
                         'concept_bindings': {self.key: [self.binding]}, 'formal_bindings': {}}
        self.install()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def install(self):
        self.write(methods.CATALOG, json.dumps(self.catalog, ensure_ascii=False))
        self.write(methods.BINDINGS, json.dumps(self.bindings, ensure_ascii=False))
        index.build_index(self.root)

    def query(self, **kwargs):
        return profiles.resolve(self.root, ['行列式计算'], 'after_attempt', **kwargs)

    def test_shared_index_lookup_preserves_method_content_and_later_file_drift_checks(self):
        with closing(sqlite3.connect(profiles._read_only_uri(self.root/index.INDEX), uri=True)) as conn:
            conn.execute('BEGIN')
            row = conn.execute('SELECT payload FROM teaching_profiles WHERE key=? AND view=?',
                               (self.key, 'after_attempt')).fetchone()
            projected = json.loads(row[0])['problem_solving']
            expected = methods.checked_projection(self.root, conn, projected)
            reads = []
            conn.set_trace_callback(reads.append)
            lookup = profiles._source_lookup(conn)
            first = methods.checked_projection(self.root, conn, projected, source_lookup=lookup)
            second = methods.checked_projection(self.root, conn, projected, source_lookup=lookup)
            self.assertEqual(expected, first)
            self.assertEqual(first, second)
            selects = [s for s in reads if s.startswith('SELECT stamp,sha256')]
            self.assertEqual(len(selects), len(set(selects)))
            self.pdf.write_text(self.pdf.read_text()+'\nSource changed within this request.\n')
            changed = methods.checked_projection(self.root, conn, projected, source_lookup=lookup)
            self.assertEqual('stale', changed['status'])
            self.assertEqual('stale', changed['routes'][0]['status'])

    def test_default_budget_keeps_complete_method_and_full_history_keeps_original_evidence(self):
        before = self.card.read_bytes()
        value = self.query()
        self.assertEqual('available', value['status'])
        self.assertLessEqual(len(profiles.canonical(value).encode()), 12000)
        row = value['records'][0]
        self.assertIn('历史摘要不足', row['short_summary'])
        self.assertNotIn('原卡只记录过启动犹豫', row['short_summary'])
        self.assertEqual('evidence_digest_only', row['status'])
        route = row['problem_solving']['routes'][0]
        self.assertEqual(self.method['conditions'], route['conditions'])
        self.assertEqual(self.method['steps'], route['steps'])
        self.assertEqual(self.method['source_refs'], route['source_refs'])
        self.assertNotIn('_source_paths', row['problem_solving'])
        self.assertEqual(before, self.card.read_bytes())
        page = (self.root / profiles.PAGES / (self.key + '.md')).read_text()
        self.assertIn('做题路线与来源', page)
        self.assertLess(page.index('[!summary] 当前个人概况'), page.index('做题路线与来源'))
        self.assertIn(self.method['first_action'], page)
        self.assertIn('原卡只记录过启动犹豫', page)

    def test_protected_and_published_protected_never_leak_method(self):
        value = profiles.resolve(self.root, ['行列式计算'], 'protected', formal_id='LA-001')
        self.assertNotIn('problem_solving', profiles.canonical(value))
        self.assertNotIn('制造零', profiles.canonical(value))
        destination = self.root / 'snapshot'
        exported = published.export_snapshot(self.root, destination)
        result = published.query_snapshot(Path(exported['manifest_path']), ['行列式计算'], [], view='protected', max_bytes=9000)
        self.assertNotIn('problem_solving', profiles.canonical(result))

    def test_exact_formal_binding_precedes_concept_candidates(self):
        self.bindings['formal_bindings']['LA-001'] = [{**self.binding, 'role': 'primary', 'specific_hint': '本题先消去第一列。'}]
        self.install()
        value = self.query(formal_id='LA-001')
        self.assertEqual('exact_formal_card', value['problem_solving']['binding_scope'])
        self.assertEqual('本题先消去第一列。', value['problem_solving']['routes'][0]['specific_hint'])
        self.assertNotIn('problem_solving', value['records'][0])
        protected = profiles.resolve(self.root, ['行列式计算'], 'protected', formal_id='LA-001')
        self.assertNotIn('本题先消', profiles.canonical(protected))

    def add_choice_technique(self):
        technique = copy.deepcopy(self.method)
        technique.update(method_id='LA-DET-SPECIAL', name='选填技巧：合法特例排除', aliases=[],
            triggers=['单选题给出关于所有方阵的候选命题'],
            first_action='逐项核对量词和前提，再用满足全部题设的对角阵检验错误选项。',
            conditions=['特例必须满足全部题设；一个反例能否定全称命题，有限正例不能证明它。'],
            steps=['构造满足题设的简单矩阵。', '代入各候选并记录被反驳的选项。',
                   '只有合法排除后剩唯一候选才结束，否则继续正解。'],
            branches=[], pitfalls=['只排除部分选项不等于已经解出。'])
        self.catalog['methods'].append(technique)
        self.bindings['concept_bindings'][self.key].append({
            'method_id': technique['method_id'], 'role': 'candidate',
            'applicability': '当前题为全称命题单选且能构造合法特例时检查。',
            'specific_hint': '反例前提和唯一性都需要核对。'})
        return technique

    def test_exact_formal_route_keeps_uncovered_current_concept_technique(self):
        self.bindings['concept_bindings'][self.key][0]['role'] = 'primary'
        technique = self.add_choice_technique()
        self.bindings['formal_bindings']['LA-001'] = [{**self.binding, 'role': 'primary'}]
        self.install()
        for view in ('after_attempt', 'direct'):
            with self.subTest(view=view):
                value = profiles.resolve(self.root, ['行列式计算'], view, 9000, formal_id='LA-001')
                self.assertEqual(self.method['method_id'], value['problem_solving']['primary_method_id'])
                self.assertEqual('current_concept_route_requires_condition_check',
                                 value['problem_solving']['selection_status'])
                routes = value['records'][0]['problem_solving']['routes']
                choice = next(r for r in routes if r['method_id'] == technique['method_id'])
                self.assertEqual(technique['conditions'], choice['conditions'])
                self.assertEqual(technique['first_action'], choice['first_action'])
                self.assertIn(technique['method_id'], [r['method_id'] for r in
                    value['records'][0]['exam_brief']['candidates']])
                self.assertLessEqual(len(profiles.canonical(value).encode()), 9000)
        protected = profiles.resolve(self.root, ['行列式计算'], 'protected', 9000, formal_id='LA-001')
        self.assertNotIn('problem_solving', profiles.canonical(protected))
        self.assertNotIn('合法特例', profiles.canonical(protected))
        exported = published.export_snapshot(self.root, self.root/'snapshot')
        snapshot = published.query_snapshot(Path(exported['manifest_path']), ['行列式计算'], [],
                                           view='protected', max_bytes=9000)
        self.assertNotIn('合法特例', profiles.canonical(snapshot))
        self.assertNotIn(technique['method_id'], profiles.canonical(snapshot))

    def test_broad_current_concept_keeps_technique_outside_formal_routes(self):
        alternate = copy.deepcopy(self.method)
        alternate.update(method_id='LA-DET-RECUR', name='递推法', aliases=[])
        self.catalog['methods'].append(alternate)
        second = {**self.binding, 'method_id': alternate['method_id'], 'role': 'candidate'}
        self.bindings['concept_bindings'][self.key].append(second)
        technique = self.add_choice_technique()
        self.bindings['formal_bindings']['LA-001'] = [
            {**self.binding, 'role': 'primary'}, {**second, 'role': 'alternative'}]
        self.install()
        value = self.query(formal_id='LA-001', max_bytes=12000)
        self.assertEqual('broad_concept_keeps_formal_context', value['problem_solving']['selection_basis'])
        self.assertEqual(self.method['method_id'], value['problem_solving']['primary_method_id'])
        routes = value['records'][0]['problem_solving']['routes']
        choice = next(r for r in routes if r['method_id'] == technique['method_id'])
        self.assertEqual(technique['steps'], choice['steps'])
        self.assertEqual(technique['conditions'], choice['conditions'])

    def test_unmatched_personal_alias_is_explicitly_source_based(self):
        value = profiles.resolve(self.root, ['具体型行列式入口'], 'direct')
        self.assertEqual('source_based', value['status'])
        self.assertEqual(['具体型行列式入口'], value['unknown'])
        self.assertEqual('not_resolved', value['records'][0]['personal_history_status'])
        self.assertNotIn('short_summary', value['records'][0])
        protected = profiles.resolve(self.root, ['具体型行列式入口'], 'protected')
        self.assertEqual('unknown_concept', protected['status'])
        self.assertEqual([], protected['records'])

    def test_method_and_pdf_drift_invalidate_known_version_without_hot_pdf_read(self):
        old = self.query()
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('hot reads must not open sources')), \
             patch.object(Path, 'read_text', side_effect=AssertionError('hot reads must not open sources')):
            value = self.query(known_version=old['version'])
            self.assertEqual('unchanged', value['status'])
        self.pdf.write_text('changed textbook bytes')
        value = self.query(known_version=old['version'])
        self.assertNotEqual('unchanged', value['status'])
        self.assertEqual('stale', value['method_status'])
        self.assertEqual('stale', value['records'][0]['problem_solving']['status'])
        self.assertNotIn('steps', value['records'][0]['problem_solving']['routes'][0])
        index.build_index(self.root)
        rebuilt = self.query()
        self.assertEqual('stale', rebuilt['method_status'])
        self.assertNotIn('steps', rebuilt['records'][0]['problem_solving']['routes'][0])

    def test_catalog_edit_invalidates_in_place_and_rebuild_changes_version(self):
        old = self.query()
        path = self.root / methods.CATALOG
        before = path.parent.stat().st_mtime_ns
        self.catalog['methods'][0]['first_action'] = '重新核对这一题的各行结构。'
        path.write_text(json.dumps(self.catalog, ensure_ascii=False))
        self.assertEqual(before, path.parent.stat().st_mtime_ns)
        stale = self.query(known_version=old['version'])
        self.assertEqual('stale', stale['method_status'])
        index.build_index(self.root)
        current = self.query(known_version=old['version'])
        self.assertEqual('available', current['status'])
        self.assertNotEqual(old['version'], current['version'])

    def test_multiple_candidates_never_silently_choose_first_and_budget_never_cuts_conditions(self):
        second = copy.deepcopy(self.method)
        second.update(method_id='LA-DET-RECUR', name='递推法', first_action='观察低阶情形并按一行展开。')
        second['aliases'] = []
        self.catalog['methods'].append(second)
        self.bindings['concept_bindings'][self.key].append({**self.binding, 'method_id': second['method_id']})
        self.install()
        value = self.query(max_bytes=9000)
        method = value['records'][0]['problem_solving']
        self.assertIsNone(method['primary_method_id'])
        self.assertEqual('needs_discrimination', method['selection_status'])
        self.assertEqual(2, len(method['routes']))
        smaller = self.query(max_bytes=3100)
        if smaller['status'] == 'available':
            for route in smaller['records'][0]['problem_solving']['routes']:
                self.assertEqual(self.method['conditions'], route['conditions'])
                self.assertIn('detail_status', route)
        else:
            self.assertEqual('budget_too_small', smaller['status'])
            self.assertEqual([], smaller['records'])
        tiny = self.query(max_bytes=900)
        self.assertEqual('budget_too_small', tiny['status'])
        self.assertEqual([], tiny['records'])

    def test_invalid_binding_and_missing_hash_fail_closed(self):
        self.catalog['methods'][0]['source_refs'][0].pop('sha256')
        with self.assertRaisesRegex(ValueError, 'source_hash_required'):
            self.install()

    def test_changed_card_source_only_invalidates_its_route_after_refresh(self):
        card_method = copy.deepcopy(self.method)
        card_method.update(method_id='CARD-ROUTE', name='原卡操作线索')
        card_method['source_refs'] = [{
            'path': str(self.card.relative_to(self.root)),
            'sha256': hashlib.sha256(self.card.read_bytes()).hexdigest(),
            'section': '原卡解题方法', 'pdf_pages': []}]
        self.catalog['methods'].append(card_method)
        self.bindings['concept_bindings'][self.key].append({**self.binding, 'method_id': 'CARD-ROUTE'})
        self.install()
        current = self.query(max_bytes=9000)['records'][0]['problem_solving']['routes']
        self.assertEqual('verified_formal_card_method', current[1]['source_status'])
        self.card.write_text(self.card.read_text() + '\n原卡合法补充。\n')
        index.build_index(self.root)
        value = self.query(max_bytes=9000)
        self.assertEqual('partial', value['method_status'])
        routes = value['records'][0]['problem_solving']['routes']
        self.assertEqual(self.method['steps'], routes[0]['steps'])
        self.assertEqual('stale', routes[1]['status'])
        self.assertNotIn('steps', routes[1])

    def test_changed_formal_binding_loses_exact_choice_but_keeps_verified_textbook(self):
        self.bindings['formal_bindings']['LA-001'] = [{**self.binding, 'role': 'primary',
            'card_sha256': hashlib.sha256(self.card.read_bytes()).hexdigest(), 'specific_hint': '旧版本该题的第一步。'}]
        self.install()
        self.card.write_text(self.card.read_text() + '\n题面局部修订。\n')
        index.build_index(self.root)
        value = self.query(formal_id='LA-001', max_bytes=9000)['problem_solving']
        self.assertEqual('available', value['status'])
        self.assertIsNone(value['primary_method_id'])
        self.assertEqual('card_changed_requires_discrimination', value['selection_status'])
        route = value['routes'][0]
        self.assertEqual('', route['specific_hint'])
        self.assertEqual(self.method['steps'], route['steps'])

    def test_formal_source_hold_blocks_broad_method_fallback_but_not_independent_concept(self):
        self.bindings['formal_exclusions'] = {'LA-001': {'status': 'source_hold', 'reason': '缺少完整原题，禁止生成方法。'}}
        self.install()
        held = self.query(formal_id='LA-001')
        self.assertEqual('source_hold', held['problem_solving']['status'])
        self.assertEqual('source_hold', held['method_status'])
        self.assertEqual([], held['problem_solving']['routes'])
        self.assertNotIn('problem_solving', held['records'][0])
        independent = self.query()
        self.assertEqual('available', independent['records'][0]['problem_solving']['status'])

    def test_stale_personal_semantics_do_not_hide_verified_method(self):
        payload = {'schema': profiles.SCHEMA, 'updates': [{
            'concept_key': self.key, 'overview': '只依赖已有原卡证据。',
            'short_summary': '原卡有启动犹豫，独立解法尚未验证。', 'progress': [],
            'next_check': '依据本轮真实第一动作检查。',
            'source_refs': [{'path': str(self.card.relative_to(self.root)),
                             'sha256': hashlib.sha256(self.card.read_bytes()).hexdigest()}]}]}
        prepared = profiles.prepare_updates(self.root, payload)
        profiles.accept_maintenance(self.root, prepared, 'test fixture maintenance')
        index.build_index(self.root)
        self.assertEqual('semantic_current', self.query()['records'][0]['status'])
        self.card.write_text(self.card.read_text().replace('启动犹豫', '已给出第一步但尚未完成计算'))
        index.build_index(self.root)
        row = self.query()['records'][0]
        self.assertEqual('semantic_stale', row['status'])
        self.assertEqual('available', row['problem_solving']['status'])
        self.assertEqual(self.method['steps'], row['problem_solving']['routes'][0]['steps'])

    def multi_part_probability_fixture(self):
        self.write('错题知识网络/错题卡/PR-100_多问概率题.md', '''---
id: PR-100
knowledge:
- 边缘密度
- 条件密度与固定点条件
- 联合密度综合入口
wrong_point: 仅记录过分母条件需要检查，不能归为所有小问都不会。
wrong_history: []
mastery_history: []
---
## 题目
先求边缘密度，再求固定点的条件密度。
''')
        marginal = copy.deepcopy(self.method)
        marginal.update(method_id='PR-M42', name='边缘密度', subject='probability', aliases=[],
            triggers=['已给联合密度，目标只含一个随机变量'],
            first_action='固定目标变量，由支撑域确定被积变量的合法范围。',
            conditions=['积分范围必须来自联合密度支撑域。'],
            steps=['写出固定目标变量时的切片范围。', '对另一变量积分。'], branches=[], pitfalls=[])
        conditional = copy.deepcopy(marginal)
        conditional.update(method_id='PR-M43', name='条件密度',
            triggers=['条件给出另一个变量的固定取值'],
            first_action='先确认固定点位于条件变量的合法范围且边缘密度严格为正。',
            conditions=['条件变量的边缘密度在固定点严格为正。', '目标变量的区间由固定点切片决定。'],
            steps=['代入固定点确定切片。', '计算该固定点处的边缘密度。', '用联合密度除以该非零边缘密度。'])
        self.catalog['methods'] += [marginal, conditional]
        first = {'method_id': 'PR-M42', 'applicability': '目标为边缘密度时使用。',
                 'specific_hint': '检查切片后再积分。', 'role': 'primary'}
        second = {'method_id': 'PR-M43', 'applicability': '当前小问给出固定条件点时使用。',
                  'specific_hint': '当前断点先查分母合法性。', 'role': 'primary'}
        self.bindings['concept_bindings'][index.concept_key('边缘密度')] = [first]
        self.bindings['concept_bindings'][index.concept_key('条件密度与固定点条件')] = [second]
        self.bindings['concept_bindings'][index.concept_key('联合密度综合入口')] = [
            {**first, 'role': 'candidate'}, {**second, 'role': 'candidate'}]
        self.bindings['formal_bindings']['PR-100'] = [first, {**second, 'role': 'alternative',
            'specific_hint': '本题第二小问固定条件点，先核其边缘密度。'}]
        self.install()
        return marginal, conditional

    def test_current_subquestion_overrides_whole_card_primary_with_full_steps(self):
        marginal, conditional = self.multi_part_probability_fixture()
        value = profiles.resolve(self.root, ['条件密度与固定点条件'], 'after_attempt', 9000, formal_id='PR-100')
        method = value['problem_solving']
        self.assertEqual('PR-M43', method['primary_method_id'])
        self.assertEqual('current_concept_route_requires_condition_check', method['selection_status'])
        route = method['routes'][0]
        self.assertEqual(conditional['conditions'], route['conditions'])
        self.assertEqual(conditional['steps'], route['steps'])
        self.assertEqual('本题第二小问固定条件点，先核其边缘密度。', route['specific_hint'])
        self.assertEqual('当前断点先查分母合法性。', route['current_concept_hint'])
        alternate = next(r for r in method['routes'] if r['method_id'] == 'PR-M42')
        self.assertEqual(marginal['first_action'], alternate['first_action'])
        self.assertIn('detail_status', alternate)
        self.assertNotIn('problem_solving', value['records'][0])
        broad = profiles.resolve(self.root, ['联合密度综合入口'], 'after_attempt', 9000, formal_id='PR-100')
        self.assertEqual('PR-M42', broad['problem_solving']['primary_method_id'])
        default = profiles.resolve(self.root, [], 'after_attempt', 9000, formal_id='PR-100')
        self.assertEqual('PR-M42', default['problem_solving']['primary_method_id'])

    def test_first_explicit_point_remains_primary_with_auxiliary_point_under_9000(self):
        _, conditional = self.multi_part_probability_fixture()
        value = profiles.resolve(self.root, ['条件密度与固定点条件', '边缘密度'], 'after_attempt', 9000, formal_id='PR-100')
        self.assertEqual('PR-M43', value['problem_solving']['primary_method_id'])
        self.assertEqual(conditional['steps'], value['problem_solving']['routes'][0]['steps'])
        self.assertEqual(conditional['conditions'], value['problem_solving']['routes'][0]['conditions'])
        self.assertEqual(2, value['returned'])
        self.assertFalse(value['truncated'])
        self.assertLessEqual(len(profiles.canonical(value).encode()), 9000)
        self.assertTrue(all('short_summary' in row for row in value['records']))

    def test_unmatched_current_point_keeps_its_candidates_without_forcing_card_primary(self):
        self.multi_part_probability_fixture()
        value = profiles.resolve(self.root, ['行列式计算'], 'after_attempt', 9000, formal_id='PR-100')
        self.assertIsNone(value['problem_solving']['primary_method_id'])
        self.assertEqual('needs_discrimination', value['problem_solving']['selection_status'])
        self.assertEqual('LA-DET-TRIANGLE', value['records'][0]['problem_solving']['routes'][0]['method_id'])
        unknown = profiles.resolve(self.root, ['未解析的当前断点'], 'after_attempt', 9000, formal_id='PR-100')
        self.assertIsNone(unknown['problem_solving']['primary_method_id'])
        self.assertEqual('needs_discrimination', unknown['problem_solving']['selection_status'])

    def test_administrative_concept_exclusion_is_explicit_and_preserves_node(self):
        admin = self.write('错题知识网络/wiki/concepts/method_card_registry.md', '''---
title: method_card_registry
---
方法注册表行政说明，不是一道题的做题对象。
''')
        key = index.concept_key('method_card_registry')
        self.bindings['concept_exclusions'] = {key: {
            'status': 'non_problem_concept', 'reason': '此节点是方法卡注册表元数据，没有数学对象或操作目标。'}}
        self.bindings['coverage'] = {'notes': '行政统计不是教材方法', 'method_id': 'not-a-route'}
        before = admin.read_bytes()
        self.install()
        value = profiles.resolve(self.root, ['method_card_registry'], 'after_attempt', 4500)
        row = value['records'][0]
        self.assertEqual('non_problem_concept', row['problem_solving']['status'])
        self.assertEqual([], row['problem_solving']['routes'])
        self.assertEqual('evidence_digest_only', row['status'])
        self.assertNotIn('not-a-route', profiles.canonical(value))
        self.assertEqual(before, admin.read_bytes())
        with sqlite3.connect(self.root / index.INDEX) as conn:
            concept = json.loads(conn.execute('SELECT payload FROM concepts WHERE key=?', (key,)).fetchone()[0])
        self.assertEqual([], concept['formal_ids'])
        page = (self.root / profiles.PAGES / (key + '.md')).read_text()
        self.assertIn(self.bindings['concept_exclusions'][key]['reason'], page)
        self.assertNotIn('操作流程：', page)
        protected = profiles.resolve(self.root, ['method_card_registry'], 'protected', 4500)
        self.assertNotIn('problem_solving', profiles.canonical(protected))
        self.assertNotIn('没有数学对象', profiles.canonical(protected))

    def test_concept_exclusion_must_not_conflict_and_unmatched_math_stays_gap(self):
        self.bindings['concept_exclusions'] = {self.key: {'status': 'source_hold', 'reason': '待核教材来源。'}}
        with self.assertRaisesRegex(ValueError, 'concept_exclusion_conflicts_with_binding'):
            self.install()
        self.bindings['concept_exclusions'] = {}
        self.write('错题知识网络/wiki/concepts/矩阵多项式核空间.md', '''---
title: 矩阵多项式核空间
---
现有数学节点，尚无已核教材方法绑定。
''')
        self.install()
        value = profiles.resolve(self.root, ['矩阵多项式核空间'], 'after_attempt', 4500)
        self.assertEqual('available', value['status'])
        self.assertNotIn('problem_solving', value['records'][0])
        self.assertNotIn('non_problem_concept', profiles.canonical(value))
        key = index.concept_key('矩阵多项式核空间')
        self.bindings['concept_exclusions'][key] = {'status': 'source_hold', 'reason': '所需原始定理页尚未核验，暂不生成方法。'}
        self.install()
        held = profiles.resolve(self.root, ['矩阵多项式核空间'], 'direct', 4500)
        self.assertEqual('source_hold', held['records'][0]['problem_solving']['status'])
        self.assertEqual([], held['records'][0]['problem_solving']['routes'])

    def test_derived_reference_has_distinct_source_status_and_explicit_role(self):
        reference = self.write('错题知识网络/wiki/maps/行列式结构.md', '既有知识锚点原文，不替代未上传原书。')
        ref = {'path': str(reference.relative_to(self.root)),
               'sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
               'section': '仅核读此派生锚点；未核读其所引原书。',
               'source_role': 'derived_reference', 'pdf_pages': []}
        self.catalog['methods'][0]['source_refs'] = [ref]
        self.install()
        method = self.query()['records'][0]['problem_solving']
        self.assertEqual('verified_derived_references', method['source'])
        self.assertEqual('verified_derived_reference', method['routes'][0]['source_status'])
        self.assertNotEqual('verified_textbook', method['routes'][0]['source_status'])
        self.catalog['methods'][0]['source_refs'][0].pop('source_role')
        with self.assertRaisesRegex(ValueError, 'source_kind_unsupported'):
            self.install()

    def test_textbook_plus_derived_is_explicit_and_arbitrary_markdown_is_rejected(self):
        reference = self.write('错题知识网络/知识树/行列式.md', '已读知识树锚点。')
        ref = {'path': str(reference.relative_to(self.root)),
               'sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
               'section': '派生知识树原文边界。', 'source_role': 'derived_reference'}
        self.catalog['methods'][0]['source_refs'].append(ref)
        self.install()
        route = self.query()['records'][0]['problem_solving']['routes'][0]
        self.assertEqual('verified_textbook_with_derived_reference', route['source_status'])
        arbitrary = self.write('notes/unvetted.md', '不能因为有来源角色就允许任意markdown。')
        ref.update(path=str(arbitrary.relative_to(self.root)), sha256=hashlib.sha256(arbitrary.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError, 'source_kind_unsupported'):
            self.install()

    def snapshot_reference(self, source, role):
        original = source.read_bytes()
        sha = hashlib.sha256(original).hexdigest()
        snapshot = self.root / methods.SOURCE_CACHE / (sha + '.md')
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(original)
        self.assertEqual(original, snapshot.read_bytes())
        return {'path': str(snapshot.relative_to(self.root)), 'source_role': role,
                'sha256': sha, 'original_path': str(source.relative_to(self.root)),
                'original_sha256': sha, 'section': '本轮实际读取的原始版本快照；不声明后来版本。'}, snapshot

    def test_formal_card_snapshot_survives_new_learning_but_exact_binding_loses_choice(self):
        ref, snapshot = self.snapshot_reference(self.card, 'formal_card_snapshot')
        self.catalog['methods'][0]['source_refs'] = [ref]
        self.bindings['formal_bindings']['LA-001'] = [{**self.binding, 'role': 'primary',
            'card_sha256': ref['original_sha256'], 'specific_hint': '旧卡版本的专属启动提示。'}]
        self.install()
        before = snapshot.read_bytes()
        self.card.write_text(self.card.read_text() + '\n## 学习记录\n本次新增真实学习记录。\n')
        index.build_index(self.root)
        generic = self.query()['records'][0]['problem_solving']
        self.assertEqual('available', generic['status'])
        self.assertEqual('verified_formal_card_method', generic['routes'][0]['source_status'])
        self.assertEqual(before, snapshot.read_bytes())
        exact = self.query(formal_id='LA-001', max_bytes=9000)['problem_solving']
        self.assertIsNone(exact['primary_method_id'])
        self.assertEqual('', exact['routes'][0]['specific_hint'])
        self.assertEqual('card_changed_candidate_only', exact['routes'][0]['binding_status'])

    def test_derived_snapshot_survives_backlink_change_but_snapshot_tampering_is_stale(self):
        original = self.write('错题知识网络/wiki/maps/参考锚点.md', '本轮实际读取的参考锚点。')
        ref, snapshot = self.snapshot_reference(original, 'derived_reference_snapshot')
        self.catalog['methods'][0]['source_refs'] = [ref]
        self.install()
        original.write_text(original.read_text() + '\n新增加的反向链接。\n')
        index.build_index(self.root)
        current = self.query()
        route = current['records'][0]['problem_solving']['routes'][0]
        self.assertEqual('verified_derived_reference', route['source_status'])
        self.assertEqual(ref['original_path'], route['source_refs'][0]['original_path'])
        snapshot.write_text('快照被意外修改。')
        stale = self.query(known_version=current['version'])
        self.assertNotEqual('unchanged', stale['status'])
        self.assertEqual('stale', stale['method_status'])
        self.assertNotIn('steps', stale['records'][0]['problem_solving']['routes'][0])
        index.build_index(self.root)
        self.assertEqual('stale', self.query()['method_status'])

    def test_snapshot_original_kind_hash_and_content_address_are_required(self):
        ref, _ = self.snapshot_reference(self.card, 'formal_card_snapshot')
        self.catalog['methods'][0]['source_refs'] = [ref]
        self.install()
        for field, value, error in [
                ('original_path', 'notes/unvetted.md', 'original_kind_invalid'),
                ('original_sha256', '0' * 64, 'original_hash_mismatch'),
                ('path', str(methods.SOURCE_CACHE / 'arbitrary-name.md'), 'content_address_required')]:
            with self.subTest(field=field):
                old = ref[field]
                ref[field] = value
                with self.assertRaisesRegex(ValueError, error):
                    self.install()
                ref[field] = old

    def test_method_snapshot_export_has_matching_raw_evidence_mapping(self):
        ref, snapshot = self.snapshot_reference(self.card, 'formal_card_snapshot')
        self.catalog['methods'][0]['source_refs'] = [ref]
        self.install()
        original_bytes = snapshot.read_bytes()
        self.card.write_text(self.card.read_text() + '\n后续学习追加不改变方法来源快照。\n')
        index.build_index(self.root)
        exported = published.export_snapshot(self.root, self.root / 'published')
        manifest = json.loads(Path(exported['manifest_path']).read_text())
        mapping = next(row for row in manifest['source_mappings'] if row['original_reference'] == ref['path'])
        self.assertEqual(ref['sha256'], mapping['expected_sha256'])
        evidence = next(row for row in exported['files'] if row.get('original_reference') == ref['path'])
        self.assertEqual(original_bytes, Path(evidence['source_path']).read_bytes())
        self.assertEqual(mapping['publish_path'], evidence['publish_path'])


if __name__ == '__main__':
    unittest.main()
