#!/usr/bin/env python3
"""Claude hooks: register the exact current math session, never learning data."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile


REPO = Path(__file__).resolve().parents[2]


def context_root():
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'math-capture-context'


def context_path(session_id):
    if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', session_id):
        raise ValueError('Invalid capture session ID')
    return context_root() / f'{session_id}.json'


def register(event, *, repo=REPO, directory=None, env_file=None):
    if event.get('hook_event_name') not in ('SessionStart', 'UserPromptSubmit') or event.get('agent_id'):
        return {}
    cwd = Path(event.get('cwd', '')).expanduser().resolve()
    if not cwd.is_relative_to(Path(repo).resolve()):
        return {}
    sid = event.get('session_id')
    target = context_path(sid)
    if directory is not None:
        target = Path(directory) / target.name
    transcript = Path(event.get('transcript_path', ''))
    if not transcript.is_absolute() or transcript.suffix != '.jsonl':
        raise ValueError('Claude hook did not supply an absolute JSONL transcript path')
    value = {'schema_version': 'math-capture-session-v1', 'provider': 'claude-code',
             'session_id': sid, 'transcript_path': str(transcript), 'cwd': str(cwd)}
    if event['hook_event_name'] == 'UserPromptSubmit':
        if isinstance(event.get('prompt_id'), str) and event['prompt_id']:
            value['prompt_id'] = event['prompt_id']
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as out:
        temporary = Path(out.name)
        json.dump(value, out, ensure_ascii=False, sort_keys=True)
        out.write('\n')
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    if event['hook_event_name'] == 'SessionStart' and env_file:
        with Path(env_file).open('a') as out:
            out.write('\nexport MATH_CAPTURE_CONTEXT=' + shlex.quote(str(target)) + '\n')
    # This is only a locator; it neither triggers saving nor changes teaching.
    context = ('数学快速保存的当前会话定位（仅在用户要求保存时使用）：'
               f'--provider claude-code --session-id {sid} --session-context {shlex.quote(str(target))}。'
               '调用 capture_current_math.py prepare，再按本题起止消息 UUID 保存；沿用共用 Skill，'
               '不要因 Claude 日志格式改走人工拼接会话。')
    return {'hookSpecificOutput': {'hookEventName': event['hook_event_name'], 'additionalContext': context}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, default=REPO)
    args = p.parse_args()
    try:
        result = register(json.load(sys.stdin), repo=args.repo, env_file=os.environ.get('CLAUDE_ENV_FILE'))
        if result:
            print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, TypeError) as exc:
        print(f'Math capture session locator unavailable: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
