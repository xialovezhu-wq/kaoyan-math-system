"""Public reproduction uses only a disposable mathematical example and its own ledger."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CAPTURE = Path(__file__).resolve().parents[1] / '数学一回滚复习系统/scripts/capture_current_math.py'

class PromptCaptureTest(unittest.TestCase):
    def test_recap_precedes_receipt_and_repeated_capture_is_a_noop(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cards = root / '错题知识网络/错题卡'
            cards.mkdir(parents=True)
            (cards / 'GS-99991_fixture.md').write_text('---\nid: GS-99991\n---\nSynthetic example.\n')
            turns = [('user', '驻点一定是极值吗？'), ('assistant', '比较两条过原点的直线。'),
                     ('user', '看过提示后，我改为不一定。请保存并回顾。'),
                     ('assistant', '可微函数在内点取得局部极值，梯度必为零。逆命题不成立。')]
            log = root / 'fixture.jsonl'
            records = [{'type': 'session_meta', 'payload': {'id': 'synthetic-session'}}]
            for role, text in turns:
                records.append({'type': 'response_item', 'payload': {'type': 'message', 'role': role,
                                'content': [{'type': 'input_text' if role == 'user' else 'output_text', 'text': text}]}})
            log.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in records))
            args = [sys.executable, str(CAPTURE), '--repo', str(root), '--provider', 'codex', '--rollout', str(log),
                    '--session-id', 'synthetic-session', '--start-line', '2', '--end-user-line', '4',
                    '--end-assistant-line', '5', '--formal-id', 'GS-99991', '--attempt-id', 'prompt-fixture',
                    '--date', '2026-11-18', '--recap-concept', 'fixture']
            first = json.loads(subprocess.check_output(args))
            second = json.loads(subprocess.check_output(args))
            self.assertEqual(('recorded', 'noop'), (first['record_status'], second['record_status']))
            self.assertEqual(first['package_id'], second['package_id'])
            self.assertEqual('reuse_teaching_context', first['recap']['status'])
            manifest = json.loads((root / first['manifest_path']).read_bytes())
            saved = json.loads((root / manifest['files']['conversation']['path']).read_bytes())
            self.assertEqual(turns, [(row['role'], row['text']) for row in saved['turns']])
            self.assertEqual((0, 0), (first['formal_write_count'], first['score_write_count']))

if __name__ == '__main__':
    unittest.main()
