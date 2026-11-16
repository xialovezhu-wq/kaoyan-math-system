"""Isolated regressions for atomic observation projection and the final byte budget."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '错题知识网络/scripts'))
import math_concept_index as index
import math_learning_profiles as profiles
import math_teaching_context as teaching


OLD = '我把任意实方阵都当成可正交对角化。'
FIX = '实矩阵可正交对角化当且仅当实对称；必须核对对称性。'
FILLER = '这是同条记录的一段完整中间过程。' * 35
LABEL = '实矩阵正交对角化'


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        space = tempfile.TemporaryDirectory()
        self.addCleanup(space.cleanup)
        self.root = Path(space.name)
        self.source = self.root / 'synthetic-evidence.json'

    def project(self, observations):
        key = index.concept_key(LABEL)
        records = {}
        for i, rows in enumerate(observations):
            rid = f'synthetic-observation-{i}'
            records[rid] = {'record_id': rid, 'formal_id': f'SYN-{i}',
                'kind': 'formal_concept_observation',
                'summary': {'study_date': f'2026-01-0{i+1}', 'observations': rows}}
        self.source.write_text(profiles.canonical(records))
        before = self.source.read_bytes()
        ref = {'path': self.source.name, 'sha256': hashlib.sha256(before).hexdigest()}
        for rec in records.values():
            rec['source_refs'] = [ref]
        concepts = {key: {'label': LABEL, 'formal_ids': []}}

        def read(path, kind):
            return {'path': str(path.relative_to(self.root)),
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

        hot = profiles.enrich_index(self.root, concepts, records, {},
                                    [(key, rid) for rid in records], read)
        self.assertEqual(before, self.source.read_bytes())
        return ({view: json.loads(x) for _, view, x in hot},
                (self.root / concepts[key]['learning_profile']['page']).read_text())

    def assert_status_only(self, hot, outcome, hint, value):
        for view in ('after_attempt', 'direct'):
            row = hot[view]
            self.assertEqual('evidence_digest_only', row['status'])
            text = row['short_summary']
            self.assertIn('历史摘要不足', text)
            self.assertIn('synthetic-observation-', text)
            self.assertIn('证据版本 ' + profiles.digest(value), text)
            self.assertIn('outcome=' + outcome, text)
            self.assertIn('hint_dependency=' + hint, text)
            self.assertNotIn(OLD, profiles.canonical(row))
            self.assertNotIn(FIX, profiles.canonical(row))
        self.assertNotIn('short_summary', hot['protected'])
        self.assertNotIn('synthetic-observation-', profiles.canonical(hot['protected']))

    def test_long_prose_in_both_orders_does_not_lose_status_or_original(self):
        for text in (OLD + FILLER + FIX, FIX + FILLER + OLD):
            with self.subTest(starts=text[:8]):
                value = {'error_detail': text, 'outcome': 'corrected_after_hint'}
                hot, full = self.project([[value]])
                self.assert_status_only(hot, 'corrected_after_hint', 'assisted', value)
                self.assertIn(text, full)

    def test_adjacent_observation_does_not_supply_unverified_correction(self):
        wrong = {'error_detail': OLD, 'outcome': 'wrong', 'hint_evidence': []}
        fixed = {'error_detail': '原例只涉及实二维矩阵。',
                 'correction_text': FIX, 'outcome': 'corrected_after_hint'}
        for rows in ([[wrong, fixed]], [[wrong], [fixed]], [[fixed], [wrong]]):
            with self.subTest(rows=len(rows), last=rows[-1][-1]['outcome']):
                hot, full = self.project(rows)
                latest = rows[-1][-1]
                self.assert_status_only(hot, latest['outcome'],
                                        'assisted' if latest is fixed else 'none_recorded', latest)
                self.assertIn(OLD, full)
                self.assertIn(FIX, full)

    def test_missing_hint_evidence_does_not_infer_independence(self):
        value = {'error_detail': OLD, 'outcome': 'unresolved'}
        hot, full = self.project([[value]])
        self.assert_status_only(hot, 'unresolved', 'unknown', value)
        self.assertNotIn(FIX, full)


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        space = tempfile.TemporaryDirectory()
        self.addCleanup(space.cleanup)
        self.root = Path(space.name)
        self.key = index.concept_key(LABEL)
        card = self.root / index.BASE / '错题卡' / 'LA-001_fixture.md'
        card.parent.mkdir(parents=True)
        card.write_text(f'---\nid: LA-001\nknowledge:\n- {LABEL}\n---\n')
        index.build_index(self.root)

    def insert(self, view, body):
        row = {'concept_key': self.key, 'concept_name': LABEL, 'status': 'evidence_digest_only'}
        if view == 'protected':
            row['timeline_count'] = 10 ** (len(body) - 1) if body else 0
        else:
            row['short_summary'] = body
        with closing(sqlite3.connect(self.root / index.INDEX)) as conn, conn:
            conn.execute('UPDATE teaching_profiles SET payload=? WHERE key=? AND view=?',
                         (profiles.canonical(row), self.key, view))

    def test_final_serialized_native_byte_boundary_includes_counts(self):
        for view in ('after_attempt', 'direct'):
            with self.subTest(view=view):
                def resolve(body, budget=4500):
                    self.insert(view, body)
                    return profiles.resolve(self.root, [self.key], view, budget)
                initial = resolve('')
                self.assertEqual((1, 1, False), (initial['total'], initial['returned'], initial['truncated']))
                delta = 4500 - len(profiles.canonical(initial).encode())
                body = '界' * (delta // 3) + 'a' * (delta % 3)
                exact = resolve(body)
                self.assertEqual(4500, len(profiles.canonical(exact).encode()))
                self.assertEqual(body, exact['records'][0]['short_summary'])
                overflow = resolve(body + 'a')
                self.assertLessEqual(len(profiles.canonical(overflow).encode()), 4500)
                if overflow['records']:
                    self.assertEqual(body + 'a', overflow['records'][0]['short_summary'])
                else:
                    self.assertEqual(('budget_too_small', 1, 0, True),
                        (overflow['status'], overflow['total'], overflow['returned'], overflow['truncated']))
                for read_view in ('protected', view):
                    result = teaching.resolve_teaching_concepts(
                        self.root, [self.key], read_view, 4500, teaching_turn=True)
                    self.assertLessEqual(len(profiles.canonical(result).encode()), 4500)
                    if read_view == 'protected':
                        self.assertNotIn('short_summary', profiles.canonical(result))

    def test_empty_result_final_envelope(self):
        for view in ('protected', 'after_attempt', 'direct'):
            with self.subTest(view=view):
                result = profiles.resolve(self.root, ['不存在的合成知识点'], view, 4500)
                self.assertEqual(('unknown_concept', 0, 0, False),
                    (result['status'], result['total'], result['returned'], result['truncated']))
                self.assertLessEqual(len(profiles.canonical(result).encode()), 4500)

    def test_pre_upgrade_cache_cannot_supply_unreviewed_prefix(self):
        self.insert('after_attempt', OLD)
        with closing(sqlite3.connect(self.root / index.INDEX)) as conn, conn:
            conn.execute("UPDATE meta SET value='15' WHERE key='implementation'")
        prior = profiles.resolve(self.root, [self.key], 'after_attempt', 4500)
        self.assertNotIn(OLD, profiles.canonical(prior))
        self.assertIn('历史摘要版本较旧', prior['records'][0]['short_summary'])
        rebuild = index.build_index(self.root)
        self.assertEqual('full', rebuild['projection_mode'])
        self.assertEqual('noop', index.build_index(self.root)['status'])
