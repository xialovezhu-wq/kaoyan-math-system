"""Teaching choices survive intake, remain source-backed, and reach the bounded reader."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'错题知识网络/scripts'))
import math_concept_index as index
import math_learning_profiles as profiles
import math_enhancement_input as enhancement


class TeachingPreferenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        adapter = patch.dict(sys.modules, {'math_concept_sources': types.SimpleNamespace(collect_sources=lambda root: [])})
        adapter.start()
        self.addCleanup(adapter.stop)
        self.card = self.write('错题知识网络/错题卡/LA-001_card.md',
            '---\nid: LA-001\nknowledge:\n- 矩阵求逆\nwrong_point: 块内乘法未完成。\n---\n原题\n')
        self.evidence = self.write('evidence/conversation.json', json.dumps({'turns': [
            {'role': 'user', 'sequence': 1, 'text': '我更熟悉分块求逆，先按这个方法讲。'},
            {'role': 'assistant', 'sequence': 2, 'text': '你偏爱循环交换技巧。'},
        ]}, ensure_ascii=False))
        self.key = index.concept_key('矩阵求逆')
        index.build_index(self.root)

    def write(self, rel, text):
        path = self.root/rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def ref(self, path):
        return {'path': str(path.relative_to(self.root)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def payload(self):
        return {'schema': profiles.SCHEMA, 'updates': [{
            'concept_key': self.key, 'overview': '分块入口熟悉，块内计算还待检查。',
            'short_summary': '保留已知分块路线，只检查当前块乘法。',
            'progress': [], 'next_check': '只写一个输出块。',
            'source_refs': [self.ref(self.card)],
            'teaching_preferences': [{
                'basis': 'explicit_preference', 'scope': '分块结构矩阵求逆',
                'approach': '先按熟悉的分块乘回单位矩阵。', 'avoid': '不要无必要换成循环交换。',
                'source_refs': [{**self.ref(self.evidence), 'role': 'user',
                    'quote': '我更熟悉分块求逆，先按这个方法讲。', 'sequence': 1, 'locator': '用户第1轮'}]
            }]}]}

    def install(self, payload=None):
        payload = payload or self.payload()
        path = self.root/profiles.SEMANTIC/(self.key+'.json')
        if path.exists():
            payload['updates'][0].update(supersedes_content_sha256=json.loads(path.read_text())['content_sha256'],
                                         revision_reason='新的有据教学选择')
        prepared = profiles.prepare_updates(self.root, payload)
        accepted = profiles.accept_maintenance(self.root, prepared, '测试教学偏好维护')
        profiles.finish_maintenance(self.root, accepted, refresh_only=True)
        return prepared

    def test_preference_reaches_reader_without_leaking_quote_or_protected_hints(self):
        before = self.card.read_bytes()
        prepared = self.install()
        self.assertIn(self.ref(self.evidence), prepared['updates'][0]['source_refs'])
        for view in ['after_attempt', 'direct']:
            value = profiles.resolve(self.root, ['矩阵求逆'], view=view, max_bytes=4500)
            self.assertEqual('available', value['status'])
            self.assertFalse(value['truncated'])
            preference = value['records'][0]['teaching_preferences'][0]
            self.assertEqual('explicit_preference', preference['basis'])
            self.assertEqual('先按熟悉的分块乘回单位矩阵。', preference['approach'])
            self.assertNotIn('source_refs', preference)
            self.assertLessEqual(len(profiles.canonical(value).encode()), 4500)
        protected = profiles.resolve(self.root, ['矩阵求逆'], view='protected')
        self.assertNotIn('teaching_preferences', protected['records'][0])
        self.assertNotIn('分块', profiles.canonical(protected))
        page = (self.root/profiles.PAGES/(self.key+'.md')).read_text()
        self.assertIn('我更熟悉分块求逆，先按这个方法讲。', page)
        self.assertEqual(before, self.card.read_bytes())

    def test_later_legacy_update_does_not_erase_existing_preference(self):
        self.install()
        payload = self.payload()
        payload['updates'][0].pop('teaching_preferences')
        payload['updates'][0]['short_summary'] = '新增断点但没有新的讲法选择。'
        prepared = self.install(payload)
        self.assertEqual(self.payload()['updates'][0]['teaching_preferences'], prepared['updates'][0]['teaching_preferences'])
        current = profiles.resolve(self.root, ['矩阵求逆'], view='direct')['records'][0]
        self.assertEqual('explicit_preference', current['teaching_preferences'][0]['basis'])

    def test_protected_identity_does_not_disclose_method_bearing_card_filename(self):
        self.install()
        protected = profiles.resolve(self.root, ['矩阵求逆'], formal_id='LA-001', view='protected')
        self.assertEqual('LA-001', protected['identity']['formal_id'])
        self.assertNotIn('card_path', protected['identity'])
        after = profiles.resolve(self.root, ['矩阵求逆'], formal_id='LA-001', view='after_attempt')
        self.assertEqual(str(self.card.relative_to(self.root)), after['identity']['card_path'])

    def test_protected_query_does_not_include_method_bearing_scope_notes(self):
        self.write(str(index.ALIASES), json.dumps({'aliases': {}, 'scope_notes': {'矩阵求逆': '先交换列再按稀疏块展开。'}}, ensure_ascii=False))
        index.build_index(self.root)
        protected = profiles.resolve(self.root, ['矩阵求逆'], view='protected')
        self.assertEqual({}, protected['scope_notes'])
        after = profiles.resolve(self.root, ['矩阵求逆'], view='after_attempt')
        self.assertEqual('先交换列再按稀疏块展开。', after['scope_notes']['矩阵求逆'])

    def test_removal_requires_explicit_revision_reason_and_can_be_done(self):
        self.install()
        payload = self.payload()
        payload['updates'][0]['teaching_preferences'] = []
        with self.assertRaisesRegex(ValueError, 'revision_reason_required'):
            profiles.prepare_updates(self.root, payload)
        payload['updates'][0]['teaching_preferences_revision_reason'] = '用户在维护请求中明确撤回该偏好。'
        self.install(payload)
        self.assertNotIn('teaching_preferences', profiles.resolve(self.root, ['矩阵求逆'], view='direct')['records'][0])

    def test_assistant_text_and_wrong_user_sequence_are_not_preference_evidence(self):
        for edit in [dict(quote='你偏爱循环交换技巧。', sequence=2), dict(sequence=3), dict(role='assistant')]:
            payload = self.payload()
            payload['updates'][0]['teaching_preferences'][0]['source_refs'][0].update(edit)
            with self.subTest(edit=edit), self.assertRaisesRegex(ValueError, 'user_quote'):
                profiles.prepare_updates(self.root, payload)

    def test_quote_is_verified_after_json_decoding_and_source_drift_is_rejected(self):
        raw = json.loads(self.evidence.read_text())
        raw['turns'][0]['text'] += '\n请保持原符号。'
        self.evidence.write_text(json.dumps(raw, ensure_ascii=True))
        payload = self.payload()
        pref = payload['updates'][0]['teaching_preferences'][0]
        pref['source_refs'][0].update(self.ref(self.evidence), quote='先按这个方法讲。\n请保持原符号。')
        prepared = profiles.prepare_updates(self.root, payload)
        self.evidence.write_text(self.evidence.read_text()+'\n')
        with self.assertRaisesRegex(ValueError, 'profile_source_changed'):
            profiles.accept_maintenance(self.root, prepared, '不得接受漂移原话')

    def test_preference_budget_is_rejected_instead_of_silently_cutting_conditions(self):
        payload = self.payload()
        payload['updates'][0]['teaching_preferences'][0]['scope'] = '适用条件'*400
        with self.assertRaisesRegex(ValueError, 'teaching_budget'):
            profiles.prepare_updates(self.root, payload)

    def test_effective_support_and_familiar_route_keep_their_evidence_type(self):
        for basis in ['observed_helpful', 'familiar_route']:
            with self.subTest(basis=basis):
                payload = self.payload()
                payload['updates'][0]['teaching_preferences'][0]['basis'] = basis
                prepared = profiles.prepare_updates(self.root, payload)
                self.assertEqual(basis, prepared['updates'][0]['teaching_preferences'][0]['basis'])
        payload = self.payload()
        payload['updates'][0]['teaching_preferences'][0]['basis'] = 'assistant_assumed_preference'
        with self.assertRaisesRegex(ValueError, 'evidence_basis'):
            profiles.prepare_updates(self.root, payload)

    def test_changed_teaching_choice_invalidates_cached_read(self):
        self.install()
        old = profiles.resolve(self.root, ['矩阵求逆'], view='direct')
        payload = self.payload()
        payload['updates'][0]['teaching_preferences'][0]['approach'] = '先展示块位置，再只做一个乘回。'
        payload['updates'][0]['teaching_preferences_revision_reason'] = '同一证据进一步细化解释顺序。'
        self.install(payload)
        new = profiles.resolve(self.root, ['矩阵求逆'], view='direct', known_version=old['version'])
        self.assertEqual('available', new['status'])
        self.assertNotEqual(old['version'], new['version'])
        self.assertEqual('先展示块位置，再只做一个乘回。', new['records'][0]['teaching_preferences'][0]['approach'])

    def test_web_return_maps_nested_preference_sources_without_changing_quote(self):
        payload = self.payload()
        refs = enhancement.collect_references(payload, 'profile_updates.json')
        mapping = {(item['ref']['path'], item['ref']['sha256']): 'cache/'+str(i)+'.json' for i, item in enumerate(refs)}
        mapped = enhancement.replace_profile_refs(payload, mapping)
        preference = mapped['updates'][0]['teaching_preferences'][0]
        original = payload['updates'][0]['teaching_preferences'][0]['source_refs'][0]
        self.assertEqual(mapping[(original['path'], original['sha256'])], preference['source_refs'][0]['path'])
        self.assertEqual(original['quote'], preference['source_refs'][0]['quote'])
        self.assertEqual('user', preference['source_refs'][0]['role'])

    def test_web_return_verifies_decoded_user_quote_in_immutable_hash_cache(self):
        ref = self.payload()['updates'][0]['teaching_preferences'][0]['source_refs'][0]
        decoded = json.loads(self.evidence.read_text())
        cache = self.write('evidence/hashed-cache.json', json.dumps(decoded, ensure_ascii=True))
        enhancement.verify_quote(ref, cache)
        with self.assertRaises(enhancement.EnhancementInputError):
            enhancement.verify_quote({**ref, 'quote': '你偏爱循环交换技巧。', 'sequence': 2}, cache)

    def test_same_source_numeric_observation_order_is_not_question_lexicographic_order(self):
        rows = [{'question_ref': 'question-'+str(i), 'outcome': 'wrong', 'error_detail': '先前错误'+str(i)} for i in range(40)]
        rows[-1].update(outcome='corrected_after_hint', error_detail='最后的提示后实际修复')
        source = {'path': 'evidence/observations.json', 'sha256': 'a'*64}
        records = {'review': {'record_id': 'review', 'kind': 'concept_review', 'formal_id': None,
            'summary': {'study_date': '2026-10-01', 'observations': rows}, 'source_refs': [source]}}
        concepts = {self.key: {'key': self.key, 'label': '矩阵求逆', 'formal_ids': []}}
        def read(path, kind):
            return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        profiles.enrich_index(self.root, concepts, records, {}, {(self.key, 'review')}, read)
        result = concepts[self.key]['learning_profile']
        from math_memory_lifecycle import observation_hash
        self.assertIn(observation_hash(rows[-1]), result['short_summary'])
        self.assertIn('outcome=corrected_after_hint', result['short_summary'])
        self.assertIn('hint_dependency=assisted', result['short_summary'])
        self.assertNotIn('最后的提示后实际修复', result['short_summary'])
        self.assertIn('最后的提示后实际修复', (self.root / result['page']).read_text())
        self.assertNotIn('先前错误9', result['short_summary'])

    def test_generated_page_metadata_only_change_is_rehashed_during_build(self):
        original = index._stamp
        calls = {}
        def stamp(path):
            value = original(path)
            if str(profiles.PAGES) in str(path) and str(path).endswith('.md'):
                calls[path] = calls.get(path, 0) + 1
                if calls[path] >= 2:
                    value = list(value)
                    value[2] += 1
            return value
        with patch.object(index, '_stamp', side_effect=stamp):
            result = index.build_index(self.root)
        self.assertIn(result['status'], ['ready', 'noop'])
        self.assertTrue(calls)

    def test_generated_page_byte_change_still_rejects_snapshot(self):
        original = index._stamp
        calls = {}
        def stamp(path):
            value = original(path)
            if str(profiles.PAGES) in str(path) and str(path).endswith('.md'):
                calls[path] = calls.get(path, 0) + 1
                if calls[path] == 2:
                    path.write_text(path.read_text()+'并发更改内容')
                    value = original(path)
            return value
        with patch.object(index, '_stamp', side_effect=stamp):
            with self.assertRaisesRegex(RuntimeError, 'source_changed_during_build'):
                index.build_index(self.root)


if __name__ == '__main__':
    unittest.main()
