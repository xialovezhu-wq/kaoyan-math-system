"""Card-level profile evidence must not manufacture point learning events."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'错题知识网络/scripts'))
import math_concept_index as index
import math_learning_profiles as profiles


class ProfileCardEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        adapter = patch.dict(sys.modules, {'math_concept_sources': types.SimpleNamespace(collect_sources=lambda root: [])})
        adapter.start()
        self.addCleanup(adapter.stop)
        self.key = index.concept_key('局部条件检查')
        self.card = self.root/'错题知识网络/错题卡/GS-001_card.md'
        self.card.parent.mkdir(parents=True)

    def build(self, history='[]'):
        self.card.write_text(f'''---
id: GS-001
knowledge:
- 局部条件检查
wrong_point: 2026-09-01 候选断点 SECRET_POINT：原卡未确认用户本人存在此错误。
wrong_history: {history}
mastery_history: []
evidence_origin: pending_user_confirmation
---
## 题目
题面内容不可进入个人证据。
## 个人错因与证据边界
SECRET_SECTION：只存在助手提出的候选机制，用户独立表现未记录。
''')
        index.build_index(self.root)

    def profile(self):
        with closing(sqlite3.connect((self.root/index.INDEX).as_uri()+'?mode=ro', uri=True)) as conn:
            return json.loads(conn.execute('SELECT payload FROM concepts WHERE key=?', (self.key,)).fetchone()[0])['learning_profile']

    def test_card_only_evidence_is_visible_without_becoming_a_dated_or_point_event(self):
        self.build()
        profile = self.profile()
        self.assertEqual('evidence_digest_only', profile['status'])
        self.assertEqual(0, profile['timeline_count'])
        self.assertEqual(0, profile['explicit_observation_count'])
        self.assertIsNone(profile['first_date'])
        self.assertIsNone(profile['latest_date'])
        self.assertNotIn('SECRET_POINT', profile['short_summary'])
        self.assertIn('历史摘要不足', profile['short_summary'])
        page = (self.root/profile['page']).read_text()
        self.assertIn('## 关联题卡级证据', page)
        self.assertIn('SECRET_POINT', page)
        self.assertIn('SECRET_SECTION', page)
        self.assertIn('pending_user_confirmation', page)
        self.assertIn(hashlib.sha256(self.card.read_bytes()).hexdigest(), page)
        self.assertNotIn('### 2026-09-01', page)
        protected = profiles.canonical(profiles.resolve(self.root, ['局部条件检查'], view='protected'))
        self.assertNotIn('SECRET_POINT', protected)
        self.assertNotIn('SECRET_SECTION', protected)
        direct = profiles.resolve(self.root, ['局部条件检查'], view='direct')
        self.assertNotIn('SECRET_POINT', profiles.canonical(direct))
        for ref in profile['source_refs']:
            self.assertEqual(ref['sha256'], hashlib.sha256((self.root/ref['path']).read_bytes()).hexdigest())

    def test_full_timeline_and_card_evidence_remain_separate_from_teaching_digest(self):
        self.build('''
- 2026-09-02：ACTUAL_TIMELINE 条件核对记录。''')
        profile = self.profile()
        self.assertEqual(1, profile['timeline_count'])
        self.assertEqual(0, profile['explicit_observation_count'])
        self.assertEqual('2026-09-02', profile['first_date'])
        self.assertNotIn('ACTUAL_TIMELINE', profile['short_summary'])
        self.assertNotIn('SECRET_POINT', profile['short_summary'])
        page = (self.root/profile['page']).read_text()
        self.assertIn('SECRET_POINT', page)
        self.assertIn('SECRET_SECTION', page)
        self.assertLess(page.index('## 关联题卡级证据'), page.index('ACTUAL_TIMELINE'))

    def test_accepted_semantics_take_precedence_and_use_model_neutral_status(self):
        self.build()
        row = {'concept_key': self.key, 'overview': '已有语义概况。',
               'short_summary': 'ACCEPTED_SUMMARY 仅记录已核实的证据边界。',
               'progress': [], 'next_check': '依据本轮真实作答检查条件。',
               'source_refs': [{'path': str(self.card.relative_to(self.root)),
                                'sha256': hashlib.sha256(self.card.read_bytes()).hexdigest()}]}
        prepared = profiles.prepare_updates(self.root, {'schema': profiles.SCHEMA, 'updates': [row]})
        result = profiles.accept_maintenance(self.root, prepared, '依据原卡证据更新摘要')
        profiles.finish_maintenance(self.root, result, refresh_only=True)
        profile = self.profile()
        self.assertEqual('semantic_current', profile['status'])
        self.assertEqual(row['short_summary'], profile['short_summary'])
        self.assertEqual(0, profile['timeline_count'])
        self.assertIsNone(profile['first_date'])
        page = (self.root/profile['page']).read_text()
        self.assertIn('概况状态：已接受语义成稿', page)
        self.assertNotIn('GPT-6', page)
        self.assertIn('SECRET_POINT', page)

    def test_declared_math_alias_with_analytic_expression_is_not_an_evidence_field(self):
        alias_path = self.root / index.ALIASES
        alias_path.parent.mkdir(parents=True, exist_ok=True)
        alias_path.write_text(json.dumps({'aliases': {
            '局部条件的解析式': ['局部条件检查']
        }}, ensure_ascii=False))
        self.build()
        protected = profiles.resolve(self.root, ['局部条件的解析式'], view='protected')
        self.assertEqual('available', protected['status'])
        self.assertEqual('局部条件检查', protected['records'][0]['concept_name'])
        self.assertNotIn('SECRET_POINT', profiles.canonical(protected))
        self.assertNotIn('SECRET_SECTION', profiles.canonical(protected))


if __name__ == '__main__':
    unittest.main()
