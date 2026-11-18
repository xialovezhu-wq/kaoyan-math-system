"""Read one identity-bound Claude Code transcript without synthesizing dialogue."""
from __future__ import annotations

import json
from pathlib import Path

from math_session_io import SessionIndexError


def visible_message(row):
    role = row.get('type')
    if (role not in ('user', 'assistant') or row.get('isSidechain')
            or row.get('isMeta') or row.get('isCompactSummary')):
        return None
    message = row.get('message')
    if not isinstance(message, dict) or message.get('role') != role:
        raise SessionIndexError('Claude message role does not match its transcript record')
    content = message.get('content')
    if isinstance(content, str):
        content = [{'type': 'text', 'text': content}]
    if not isinstance(content, list) or any(not isinstance(b, dict) for b in content):
        raise SessionIndexError('Claude message content must be text or typed blocks')
    blocks, positions = [], []
    for i, block in enumerate(content):
        if block.get('type') in ('thinking', 'redacted_thinking', 'tool_use', 'tool_result'):
            continue
        blocks.append(block)
        positions.append(i)
    if not any(b.get('type') != 'text' or str(b.get('text', '')).strip() for b in blocks):
        return None
    return {'type': 'message', 'role': role, 'content': blocks,
            'message_id': row['uuid'], 'parent_message_id': row.get('parentUuid'),
            'original_block_indexes': positions,
            'original_block_types': [b.get('type') for b in content]}


class ClaudeSessionIndex:
    """Exact UUID/line lookup; branch selection follows native parent pointers.

    Read only the selected session. Claude files can be rewritten on resume, so
    UUIDs, rather than cached physical offsets, are the durable message anchors.
    The original complete JSONL bytes remain the source of the slice digest.
    """

    def __init__(self, rollout, session_id):
        path = Path(rollout).expanduser()
        if path.is_symlink() or not path.is_file():
            raise SessionIndexError('Claude transcript must be an existing regular non-symlink file')
        self.rollout = path.resolve(strict=True)
        self.session_id = session_id
        before = self.rollout.stat()
        raw = self.rollout.read_bytes()
        after = self.rollout.stat()
        if ((before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
                or after.st_size < len(raw)):
            raise SessionIndexError('Claude transcript changed while reading')
        # An unfinished final line is not a persisted message yet.
        complete = raw[:raw.rfind(b'\n') + 1]
        self.raw_lines = complete.splitlines(keepends=True)
        self.rows, self.by_id, self.visible = [], {}, {}
        sessions = set()
        for line, encoded in enumerate(self.raw_lines, 1):
            try:
                row = json.loads(encoded)
            except (ValueError, UnicodeDecodeError) as exc:
                raise SessionIndexError(f'Invalid Claude JSONL at line {line}') from exc
            if not isinstance(row, dict):
                raise SessionIndexError(f'Invalid Claude record at line {line}')
            self.rows.append(row)
            if row.get('sessionId'):
                sessions.add(row['sessionId'])
            uid = row.get('uuid')
            if not uid:
                if row.get('type') in ('user', 'assistant'):
                    raise SessionIndexError('Claude conversation message is missing its native UUID')
                continue
            if not isinstance(uid, str) or uid in self.by_id:
                raise SessionIndexError('Claude message UUID is invalid or duplicated')
            self.by_id[uid] = line
            if row.get('type') in ('user', 'assistant') and row.get('sessionId') != session_id:
                raise SessionIndexError('Claude message session identity mismatch')
            message = visible_message(row)
            if message is not None:
                self.visible[line] = message
        if sessions != {session_id}:
            raise SessionIndexError('Claude transcript session identity must match exactly')
        self.line_count = len(self.rows)

    def line_for_id(self, message_id):
        line = self.by_id.get(message_id)
        if line not in self.visible:
            raise SessionIndexError('Claude message UUID is missing or is not visible conversation')
        return line

    def prompt_line(self, prompt_id):
        matches = [line for line, message in self.visible.items()
                   if message['role'] == 'user' and self.rows[line - 1].get('promptId') == prompt_id]
        if len(matches) > 1:
            raise SessionIndexError('Current Claude prompt matches multiple visible messages; supply its exact UUID')
        return matches[0] if matches else None

    def _lineage(self, end_line, start_line=None):
        if end_line not in self.visible:
            raise SessionIndexError('Claude boundary is not visible conversation')
        uid = self.rows[end_line - 1]['uuid']
        selected = set()
        while uid is not None:
            line = self.by_id.get(uid)
            if line is None:
                break
            if line in selected:
                raise SessionIndexError('Claude parent chain contains a cycle')
            row = self.rows[line - 1]
            if row.get('isSidechain'):
                raise SessionIndexError('Claude boundary crosses a sidechain')
            selected.add(line)
            if line == start_line:
                return selected
            # Compaction summaries stay excluded; reconnect to retained originals.
            uid = (row.get('logicalParentUuid') if row.get('subtype') == 'compact_boundary'
                   else row.get('parentUuid'))
        if start_line is not None:
            raise SessionIndexError('Claude start/end are not on one retained message chain; original context is missing or on another branch')
        return selected

    def message(self, line_no):
        message = self.visible.get(line_no)
        if message is None:
            return None
        text = ''.join(b.get('text', '') for b in message['content'] if b.get('type') == 'text')
        return {'line': line_no, 'role': message['role'], 'visible': True,
                'recipient': None, 'preview': text[:90], 'message_id': message['message_id'],
                'blocks': message['original_block_types']}

    def latest_visible_user_line(self):
        return next((line for line in reversed(self.visible)
                     if self.visible[line]['role'] == 'user'), None)

    def messages(self, limit=10, end_line=None):
        selected = self._lineage(end_line) if end_line is not None else set(self.visible)
        lines = [line for line in self.visible if line in selected and (end_line is None or line <= end_line)]
        return [self.message(line) for line in lines[-max(1, min(limit, 100)):]]

    def read_range(self, start_line, end_line):
        if start_line not in self.visible or start_line > end_line:
            raise SessionIndexError('Claude start boundary is not a visible message before the end')
        selected = self._lineage(end_line, start_line)
        rows = []
        for line in range(start_line, end_line + 1):
            message = self.visible.get(line) if line in selected else None
            rows.append({'type': 'response_item', 'payload': message} if message else {})
        return rows, b''.join(self.raw_lines[start_line - 1:end_line])
