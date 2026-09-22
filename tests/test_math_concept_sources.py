import hashlib
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('math_concept_sources', Path(__file__).parents[1] / '错题知识网络/scripts/math_concept_sources.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def put(root, name, data):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))
    return p


class MathConceptSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_reference_change_and_duplicate(self):
        tmp_path = self.root
        put(tmp_path, '错题知识网络/知识点库.md', '- 极限\n')
        p = put(tmp_path, '错题知识网络/知识树/a.md', '极限的定义')
        put(tmp_path, '错题知识网络/知识树/b.md', '极限的定义')
        a = m.collect_sources(tmp_path)
        r = next(r for r in a if r['labels'] == ['极限'] and r['metadata'].get('duplicate_paths'))
        assert r['text'] == ''
        assert hashlib.sha256((tmp_path / r['path']).read_bytes()).hexdigest() == r['sha256']
        old = r['metadata']['original_sha256']
        p.write_text('极限变更')
        b = m.collect_sources(tmp_path)
        assert any(r['metadata'].get('original_sha256') != old and r['metadata']['original_path'].endswith('a.md') for r in b)


    def test_accepted_pending_and_wrong_rejected(self):
        tmp_path = self.root
        events = [{'event_type': 'capture', 'event_id': 'pending'},
                  {'event_type': 'capture', 'event_id': 'closed'},
                  {'event_type': 'closeout', 'event_id': 'end', 'capture_results': [
                      {'capture_event_id': 'closed', 'formal_id': 'GS-001', 'outcome': 'wrong_rejected'}]}]
        put(tmp_path, str(m.ROLLBACK / '快速入库事件.jsonl'), '\n'.join(json.dumps(x) for x in events))
        rows = m.collect_sources(tmp_path)
        assert len(rows) == 1 and rows[0]['text'] == ''
        assert rows[0]['metadata']['terminal_outcomes'] == ['wrong_rejected']
        assert rows[0]['metadata']['status'] == 'archive_receipt_missing'
        inv = json.loads((tmp_path / m.CACHE / 'source_inventory.json').read_text())
        assert inv['excluded_or_pending'] == [{'capture_id': 'pending', 'status': 'pending_not_accepted'}]


    def test_unsafe_archive_rejected(self):
        tmp_path = self.root
        put(tmp_path, str(m.ROLLBACK / '快速入库事件.jsonl'), json.dumps({'event_type': 'closeout', 'event_id': 'end', 'capture_results': [{'capture_event_id': 'a', 'formal_id': 'GS-001', 'outcome': 'wrong_recorded'}]}))
        put(tmp_path, str(m.ROLLBACK / '原始会话归档回执.jsonl'), json.dumps({'capture_ids': ['a'], 'closeout_id': 'end', 'archive_volume': 'T9-Data', 'raw_archive_relpath': '03_数学/资料库/原始会话资料/../../../../bad', 'archive_status': 'verified', 'raw_archive_manifest_sha256': 'x'}))
        rows = m.collect_sources(tmp_path)
        assert rows[0]['metadata']['status'] == 'invalid_or_unavailable'
        assert rows[0]['text'] == ''


    def test_manifest_hash_and_assistant_exclusion(self):
        tmp_path = self.root
        # Substitute only the authorized archive root in this test, leaving containment active.
        archive = tmp_path / 'archive'
        original_inside = m._inside
        def inside(base, relative):
            return original_inside(archive if str(base) == '/Volumes/T9-Data' else base, relative)
        self.addCleanup(patch.stopall)
        patch.object(m, '_inside', inside).start()
        rel = '03_数学/资料库/原始会话资料/day/MATHPKG-test'
        conv = put(archive, rel + '/conversation.json', {'turns': [{'role': 'user', 'text': '我不认为极限存在。后一句。'}, {'role': 'assistant', 'text': 'SECRET COMPLETE ANSWER'}]})
        manifest = put(archive, rel + '/manifest.json', {'package_id': 'MATHPKG-test', 'files': {'conversation': {'path': 'packages/MATHPKG-test/conversation.json', 'sha256': m.digest(conv.read_bytes())}}})
        put(tmp_path, str(m.ROLLBACK / '快速入库事件.jsonl'), json.dumps({'event_type': 'closeout', 'event_id': 'end', 'capture_results': [{'capture_event_id': 'a', 'formal_id': 'GS-001', 'outcome': 'wrong_recorded'}]}))
        receipt = {'capture_ids': ['a'], 'closeout_id': 'end', 'archive_volume': 'T9-Data', 'raw_archive_relpath': rel, 'archive_status': 'verified', 'raw_archive_manifest_sha256': m.digest(manifest.read_bytes())}
        rp = put(tmp_path, str(m.ROLLBACK / '原始会话归档回执.jsonl'), json.dumps(receipt))
        rows = m.collect_sources(tmp_path)
        assert rows[0]['text'] == '我不认为极限存在。后一句。'
        assert 'SECRET' not in json.dumps(rows)
        conv.unlink(); manifest.unlink()
        receipt['refresh'] = True
        rp.write_text(json.dumps(receipt))
        assert m.collect_sources(tmp_path)[0]['metadata']['status'] == 'verified_cached_offline'
        receipt['raw_archive_manifest_sha256'] = 'bad'
        rp.write_text(json.dumps(receipt))
        assert m.collect_sources(tmp_path)[0]['metadata']['coverage'] == 'missing'

    def test_local_accepted_package_and_stable_cache(self):
        root = self.root
        put(root, '错题知识网络/错题卡/GS-001.md', '---\nid: GS-001\nknowledge:\n  - 极限\n---\n')
        put(root, '错题知识网络/assets/GS-001/a.png', 'binary bytes')
        conv = put(root, '数学一回滚复习系统/快速入库来源/P/conversation.json', {'turns': [
            {'role': 'user', 'text': '第一道我的做法。\n我不理解极限为何存在。'},
            {'role': 'assistant', 'text': 'SECRET ANSWER'}, {'role': 'user', 'text': '后来我改变了看法。'}]})
        manifest = put(root, '数学一回滚复习系统/快速入库来源/P/manifest.json', {'files': {'conversation': {
            'path': str(conv.relative_to(root)), 'sha256': m.digest(conv.read_bytes())}}})
        events = [{'event_type': 'capture', 'event_id': 'local', 'conversation_package': {
            'manifest_path': str(manifest.relative_to(root)), 'manifest_hash': m.digest(manifest.read_bytes())}},
            {'event_type': 'closeout', 'event_id': 'end', 'capture_results': [
                {'capture_event_id': 'local', 'formal_id': 'GS-001', 'outcome': 'wrong_recorded'}]}]
        put(root, str(m.ROLLBACK / '快速入库事件.jsonl'), '\n'.join(json.dumps(e) for e in events))
        first = m.collect_sources(root)
        row = next(r for r in first if r['source_kind'] == 'accepted_conversation_excerpt')
        assert row['labels'] == ['极限']
        assert row['text'] == '第一道我的做法。\n我不理解极限为何存在。'
        users = json.loads((root / row['metadata']['user_turn_cache']).read_text())
        assert len(users) == 2 and users[-1]['text'] == '后来我改变了看法。'
        assert 'SECRET' not in json.dumps(first, ensure_ascii=False)
        stamps = {r['path']: (root / r['path']).stat().st_mtime_ns for r in first}
        second = m.collect_sources(root)
        assert first == second
        assert stamps == {r['path']: (root / r['path']).stat().st_mtime_ns for r in second}


    def test_fast_cache_detects_add_delete_edit_and_projection_tamper(self):
        root = self.root
        p = put(root, '错题知识网络/知识树/a.md', 'initial')
        first = m.collect_sources(root)
        with patch.object(m, 'split_front_matter', side_effect=AssertionError('unexpected parse')):
            assert m.collect_sources(root) == first
        p.write_text('changed')
        changed = m.collect_sources(root)
        assert first != changed
        extra = put(root, '错题知识网络/知识树/b.md', 'new source')
        assert len(m.collect_sources(root)) == 2
        extra.unlink()
        assert len(m.collect_sources(root)) == 1
        projection = root / changed[0]['path']
        projection.write_text('tampered')
        repaired = m.collect_sources(root)
        assert hashlib.sha256(projection.read_bytes()).hexdigest() == repaired[0]['sha256']


if __name__ == "__main__":
    unittest.main()
