#!/usr/bin/env python3
"""Seal an explicitly bounded local rollout through the existing foreground writer."""
from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time

import math_session_io as session_io
from math_claude_session import ClaudeSessionIndex
import math_capture_context
import quick_intake as qi
from display_assets import atomic_write


def parser():
    p = argparse.ArgumentParser(description=__doc__, epilog=(
        'Boundaries are inclusive 1-based physical JSONL lines containing response_item/message; '
        'end must be a user message. No text matching, summaries, score writes or model calls. '
        'Artifacts JSON: {"artifacts":[{"role":"question_image","path":"/abs/a.png",'
        '"message_line":2,"block_index":1}],"missing_attachments":[{"message_line":2,'
        '"block_index":2,"reason":"original unavailable"}]}. Block indexes are zero-based. '
        'Each non-text block needs a mapping or missing declaration unless a local image path '
        'can be resolved. Unmapped local images use other_attachment. Text blocks are concatenated '
        'without inserted separators; block lengths retain the original boundaries. '
        'Repeat the identical command after failure; existing immutable stages and captures noop.'))
    session_arguments(p)
    p.add_argument('--date', required=True)
    p.add_argument('--attempt-id', default='auto', help='Stable existing ID, or auto from session and start line')
    p.add_argument('--formal-id', help='Known canonical GS/LA/PR ID; validated before staging')
    p.add_argument('--source-question-id', help='Exact ID printed on the source question; resolve before staging')
    p.add_argument('--source-locator', help='Stable source identity, required for a new question without a printed ID')
    p.add_argument('--start-line', type=int)
    p.add_argument('--start-message-id', help='Exact native Claude message UUID; stable across physical line changes')
    p.add_argument('--end-user-line', '--end-line', dest='end_user_line', default='auto',
                   type=inclusive_line,
                   help="Exact closing user-message line, or 'auto' for the last visible user message")
    p.add_argument('--end-assistant-line', type=int,
                   help='Include the displayed write-up after the closing user message; no later user turn may be crossed')
    p.add_argument('--repo', type=Path, help='Explicit repository root; retarget all writer paths (for isolated replay)')
    p.add_argument('--solution-line', type=solution_line,
                   help="Exact assistant line, or 'current' for the unique nonempty visible assistant message after the closing request")
    p.add_argument('--solution-message-id', help='Exact native UUID of an already displayed Claude write-up')
    p.add_argument('--artifacts-json', type=Path, help='Explicit attachment mappings/missing declarations; defaults to none')
    p.add_argument('--formula-display-evidence', type=Path,
                   help='Immutable current-question JSON from math_formula_display capture-evidence; no display or score action')
    p.add_argument('--formula-display-evidence-sha256', help='Expected SHA-256 returned by the formula evidence freezer')
    p.add_argument('--question-text', type=Path, help='Exact registered typed10 pure-text math-I surface')
    p.add_argument('--question-text-sha256')
    p.add_argument('--question-source-record-sha256', help='Pinned original question+teacher record hash, not the surface hash')
    p.add_argument('--review-source-run-id', help='Exact previously registered typed10 source; no directory scan')
    p.add_argument('--image-role', action='append', default=[], type=image_role,
                   help='Repeat LINE:BLOCK:ROLE for local/wrapped images; no mapping file needed')
    p.add_argument('--queue-id')
    p.add_argument('--item-id')
    p.add_argument('--score-event-id')
    p.add_argument('--score', type=int, choices=range(6), help='Validate an already recorded score; never create one')
    p.add_argument('--requested-action', choices=sorted(qi.ALLOWED_ACTIONS))
    p.add_argument('--recap-concept', action='append', dest='recap_concepts',
                   help='Legacy option; recap belongs to tutoring before capture. Never fetches references.')
    p.add_argument('--recap-view', choices=('protected', 'after_attempt', 'direct'), default='protected',
                   help='Existing answer permission for the optional recap; saving never unlocks direct view')
    p.add_argument('--recap-operation', help='Exact current operation/subquestion scope for the optional recap')
    return p


def session_arguments(p):
    p.add_argument('--provider', choices=('auto', 'codex', 'claude-code'), default='auto')
    p.add_argument('--rollout', type=Path, help='Exact native transcript path; never choose a latest log')
    p.add_argument('--session-id', help='Exact current session ID; omitted only with verified runtime context')
    p.add_argument('--session-context', type=Path, help='Per-session locator emitted by the Claude hooks')
    p.add_argument('--end-message-id', help='Exact closing Claude user-message UUID')


def fail(message):
    raise qi.QuickIntakeError(message)


def image_role(value):
    parts = value.split(':')
    roles = {'question_image', 'explanation_image', 'user_work_image', 'other_attachment'}
    if (len(parts) != 3 or not parts[0].isdigit() or int(parts[0]) < 1
            or not parts[1].isdigit() or parts[2] not in roles):
        raise argparse.ArgumentTypeError('expected LINE:BLOCK:question_image/explanation_image/user_work_image/other_attachment')
    return int(parts[0]), int(parts[1]), parts[2]


def attempt_for(session_id, start_line):
    identity = json.dumps([session_id, start_line], separators=(',', ':')).encode()
    return 'MATH-ATT-' + hashlib.sha256(identity).hexdigest()[:24]


def session_attempt(args, index, line):
    if args.provider == 'codex':
        return attempt_for(args.session_id, line)  # Preserve all existing identities.
    message = index.message(line)
    if message is None:
        fail('Question start must be a visible Claude message')
    identity = json.dumps(['claude-code', args.session_id, message['message_id']], separators=(',', ':')).encode()
    return 'MATH-ATT-' + hashlib.sha256(identity).hexdigest()[:24]


def visible_message(row):
    payload = row.get('payload', {})
    if (row.get('type') == 'response_item' and payload.get('type') == 'message'
            and payload.get('role') in ('user', 'assistant')
            and payload.get('phase') not in ('analysis', 'reasoning')
            and payload.get('channel') not in ('analysis', 'reasoning')
            and payload.get('recipient') in (None, 'all')):
        return payload
    return None


def embedded_image(block):
    """Freeze the bytes in the original typed block before consulting a live path."""
    source = block.get('source')
    if block.get('type') == 'image' and isinstance(source, dict) and source.get('type') == 'base64':
        mime, encoded = source.get('media_type'), source.get('data')
    elif block.get('type') in ('input_image', 'image', 'image_url', 'output_image'):
        url = block.get('image_url') or block.get('url')
        if isinstance(url, dict):
            url = url.get('url')
        if not isinstance(url, str) or not url.startswith('data:'):
            return None
        header, _, encoded = url.partition(',')
        if not header.endswith(';base64'):
            fail('Embedded image must use a base64 data URL')
        mime = header[5:-7]
    else:
        return None
    suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif'}.get(mime)
    if not suffix or not isinstance(encoded, str) or len(encoded) > 4 * ((qi.MAX_SOURCE_ARTIFACT_BYTES + 2) // 3):
        fail('Embedded image has an unsupported type or size')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        fail('Embedded image base64 is invalid')
    if not 0 < len(data) <= qi.MAX_SOURCE_ARTIFACT_BYTES:
        fail('Embedded image size is invalid')
    path = qi.ROOT / '.math_session_index' / 'attachments' / (hashlib.sha256(data).hexdigest() + suffix)
    if path.is_symlink() or (path.exists() and path.read_bytes() != data):
        fail('Cached image does not match its source bytes')
    if not path.exists():
        atomic_write(path, data)
    return path


def referenced_image(blocks, block_index, *, allow_missing=False):
    block = blocks[block_index]
    direct = local_image(block.get('image_url') or block.get('url') or block.get('path'))
    if direct:
        return direct
    if block.get('type') not in ('input_image', 'image', 'image_url'):
        return None
    # The app's original path belongs only to its immediately enclosed image block.
    if 0 < block_index < len(blocks) - 1:
        previous, following = blocks[block_index - 1], blocks[block_index + 1]
        opening = re.fullmatch(r'<image name=\[[^\]\n]+\] path="([^"\n]+)">', previous.get('text', ''))
        if opening and following.get('text', '') == '</image>':
            return local_image(opening.group(1), allow_missing=allow_missing)
    return None


def block_images(blocks, block_index):
    frozen = embedded_image(blocks[block_index])
    return frozen, referenced_image(blocks, block_index, allow_missing=frozen is not None)


def prepare(args):
    if args.repo is not None:
        configure_repo(args.repo)
    started = time.perf_counter()
    index = session_index(args)
    index, end = closing_boundary(args, index)
    if end is None:
        fail('No visible user message is available')
    if args.start_line is not None:
        start = args.start_line
    else:
        candidates = index.messages(100, end_line=end)
        if not candidates:
            fail('No recent boundary is available; supply the known --start-line')
        start = candidates[0]['line']
    try:
        rows, _ = index.read_range(start, end)
    except session_io.SessionIndexError as exc:
        fail(str(exc))
    messages = []
    for line, row in enumerate(rows, start):
        message = visible_message(row)
        if message is None:
            continue
        blocks = message.get('content', [])
        text = ''.join(b.get('text', '') for b in blocks
                       if b.get('type') in ('input_text', 'output_text', 'text'))
        images = []
        for i, block in enumerate(blocks):
            if block.get('type') in ('input_text', 'output_text', 'text'):
                continue
            frozen, path = block_images(blocks, i)
            if frozen and not same_image_bytes(path, frozen):
                path = frozen
            original_i = message.get('original_block_indexes', list(range(len(blocks))))[i]
            images.append({'block_index': original_i, 'path': str(path) if path else None,
                           'role_argument': f'{line}:{original_i}:ROLE'})
        if not text.strip() and not images:
            continue
        preview = text
        if message['role'] == 'user' and '\n## My request:\n' in text:
            preview = text.split('\n## My request:\n', 1)[1].lstrip()
        item = {'line': line, 'role': message['role'], 'preview': preview[:240], 'images': images}
        if item['preview'] != text:
            start_char = len(text) - len(preview)
            item.update(preview_truncated=True, preview_range=[start_char, start_char + len(item['preview'])],
                        full_text_chars=len(text))
        if message.get('message_id'):
            item['message_id'] = message['message_id']
        if message['role'] == 'user' or args.provider == 'claude-code':
            item['attempt_id'] = session_attempt(args, index, line)
        if message['role'] == 'assistant' and '卷面写法' in text:
            item['solution_candidate'] = True
            item['solution_preview'] = text[text.index('卷面写法'):][:500]
        messages.append(item)
    save_args = {'provider': args.provider, 'rollout': str(args.rollout), 'session_id': args.session_id,
                 'start_line': args.start_line, 'end_user_line': end}
    if args.provider == 'claude-code':
        save_args.update({'start_message_id': index.message(args.start_line)['message_id'] if args.start_line else None,
                          'end_message_id': index.message(end)['message_id']})
    return {'status': 'prepared', 'provider': args.provider, 'session_id': args.session_id, 'rollout': str(args.rollout),
            'save_args': save_args,
            'start_line': args.start_line, 'end_user_line': end, 'messages': messages,
            'boundary_selection_required': args.start_line is None,
            'history_window_limited': args.start_line is None,
            'elapsed_ms': round((time.perf_counter() - started) * 1000, 3),
            'formal_write_count': 0, 'capture_write_count': 0}


def inclusive_line(value):
    if value == 'auto':
        return value
    try:
        line = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive line number or 'auto'") from exc
    if line < 1:
        raise argparse.ArgumentTypeError("line number must be positive")
    return line


def solution_line(value):
    if value == 'current':
        return value
    line = inclusive_line(value)
    if line == 'auto':
        raise argparse.ArgumentTypeError("expected a positive line number or 'current'")
    return line


def current_solution_line(index, end_user_line):
    # Inspect typed messages in this turn, not keyword hits in reasoning/tool logs.
    latest = index.messages(1)
    if not latest or latest[-1]['line'] <= end_user_line:
        fail('No displayed write-up after the closing request')
    try:
        rows, _ = index.read_range(end_user_line, latest[-1]['line'])
    except session_io.SessionIndexError as exc:
        fail(str(exc))
    candidates = []
    for line, row in enumerate(rows[1:], end_user_line + 1):
        message = visible_message(row)
        if message is None:
            continue
        if message['role'] == 'user':
            fail('Cannot cross another user turn after the closing request')
        if any(block.get('type') in ('input_text', 'output_text', 'text')
               and isinstance(block.get('text'), str) and block['text'].strip()
               for block in message.get('content', [])):
            candidates.append(line)
    if len(candidates) != 1:
        fail('Expected exactly one displayed write-up after the closing request; use an explicit solution-line for multiple messages')
    return candidates[0]


def session_index(args):
    context = None
    supplied_context = getattr(args, 'session_context', None)
    context_file = supplied_context or os.environ.get('MATH_CAPTURE_CONTEXT')
    if not context_file and getattr(args, 'provider', 'auto') == 'claude-code' and args.session_id:
        candidate = math_capture_context.context_path(args.session_id)
        if candidate.is_file():
            context_file = candidate
    if context_file:
        value = json.loads(Path(context_file).read_text())
        if value.get('schema_version') != 'math-capture-session-v1' or value.get('provider') != 'claude-code':
            fail('Invalid Claude session context')
        if args.session_id and value.get('session_id') != args.session_id:
            if supplied_context:
                fail('Session context does not belong to the requested session')
        elif getattr(args, 'provider', 'auto') != 'codex':
            context = value
    provider = getattr(args, 'provider', 'auto')
    if provider == 'auto':
        if context:
            provider = 'claude-code'
        elif args.rollout:
            provider = detect_provider(args.rollout)
        else:
            provider = 'codex'
    args.provider = provider
    if context:
        args.session_id = args.session_id or context['session_id']
        if args.rollout and Path(args.rollout).resolve() != Path(context['transcript_path']).resolve():
            fail('Explicit transcript conflicts with the current Claude session context')
        args.rollout = Path(context['transcript_path'])
    if not args.session_id and provider == 'codex':
        args.session_id = os.environ.get('CODEX_THREAD_ID') or os.environ.get('CODEX_SESSION_ID')
    if not args.session_id:
        fail('Current session identity is unavailable; supply --session-id or the hook --session-context')
    args._session_context = context
    if provider == 'claude-code':
        if not args.rollout:
            fail('Claude transcript locator unavailable; use the hook --session-context or exact --rollout')
        try:
            index = ClaudeSessionIndex(args.rollout, args.session_id)
            for id_field, line_field in [('start_message_id', 'start_line'), ('end_message_id', 'end_user_line'),
                                          ('solution_message_id', 'solution_line')]:
                uid = getattr(args, id_field, None)
                if uid:
                    line = index.line_for_id(uid)
                    supplied = getattr(args, line_field, None)
                    if supplied not in (None, 'auto', line):
                        fail(f'{id_field} disagrees with its physical line; prepare again with the same UUID')
                    setattr(args, line_field, line)
            return index
        except session_io.SessionIndexError as exc:
            fail(str(exc))
    if any(getattr(args, key, None) for key in ('start_message_id', 'end_message_id', 'solution_message_id')):
        fail('Native message UUID arguments require --provider claude-code')
    if not args.rollout:
        args.rollout = locate_rollout(args.session_id)
    try:
        return session_io.open_session(
            Path(args.rollout), qi.ROOT / '.math_session_index', args.session_id,
        )
    except session_io.SessionIndexError as exc:
        fail(str(exc))


def detect_provider(path):
    with Path(path).open() as source:
        for _, line in zip(range(32), source):
            row = json.loads(line)
            if row.get('type') == 'session_meta':
                return 'codex'
            if row.get('sessionId'):
                return 'claude-code'
    fail('Transcript format is unknown; supply --provider explicitly')


def closing_boundary(args, index):
    end = getattr(args, 'end_user_line', 'auto')
    if end not in (None, 'auto'):
        message = index.message(end)
        if not message or message['role'] != 'user' or not message.get('visible', True):
            fail('Closing boundary must be a visible user message')
        return index, end
    if args.provider == 'codex':
        return index, index.latest_visible_user_line()
    context = getattr(args, '_session_context', None) or {}
    prompt_id = context.get('prompt_id')
    if not prompt_id:
        fail('Claude auto end requires the current UserPromptSubmit hook prompt_id; supply an exact --end-message-id otherwise')
    deadline = time.monotonic() + 2.0
    while True:
        try:
            end = index.prompt_line(prompt_id)
            if end is not None:
                return index, end
            if time.monotonic() >= deadline:
                fail('Current Claude user message is not persisted yet; retry the same prompt after transcript flush')
            time.sleep(0.1)
            # Revalidate UUID-to-line bindings as well if Claude rewrote the file.
            index = session_index(args)
        except session_io.SessionIndexError as exc:
            fail(str(exc))


def locate_rollout(session_id, codex_home=None):
    home = Path(codex_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser().resolve()
    databases = sorted((p for p in home.glob('state_*.sqlite')
                        if re.fullmatch(r'state_\d+\.sqlite', p.name)),
                       key=lambda p: int(p.stem.split('_')[1]), reverse=True)
    for database in databases:
        try:
            with contextlib.closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
                row = conn.execute('SELECT rollout_path FROM threads WHERE id=?', (session_id,)).fetchone()
        except sqlite3.Error:
            continue
        if row:
            path = session_io.current_codex_path(row[0], home, from_app_state=True)
            if path.is_absolute() and path.is_file():
                return path
            fail('Current session log is unavailable; supply the exact --rollout path')
    fail('Session ID not found in app state; supply the exact --rollout path')


def local_image(value, *, allow_missing=False):
    if isinstance(value, dict):
        value = value.get('url') or value.get('path')
    if not isinstance(value, str) or value.startswith('data:'):
        return None
    if value.startswith('file://'):
        value = value[7:]
    p = session_io.current_codex_path(value, os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    if (p.is_absolute() and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'}
            and (allow_missing or p.is_file())):
        return p
    return None


def same_image_bytes(path, frozen):
    try:
        return (path is not None and path.is_absolute() and not path.is_symlink() and path.is_file()
                and path.stat().st_size == frozen.stat().st_size and path.read_bytes() == frozen.read_bytes())
    except OSError:
        return False


def extract(args, index=None):
    index = index or session_index(args)
    if args.end_user_line == 'auto':
        index, args.end_user_line = closing_boundary(args, index)
        if args.end_user_line is None:
            fail('No visible user message is available for --end-user-line auto')
    if args.solution_line == 'current':
        selected = current_solution_line(index, args.end_user_line)
        if args.end_assistant_line not in (None, selected):
            fail('end-assistant-line conflicts with the current displayed write-up')
        args.solution_line = selected
        args.end_assistant_line = selected
    finish = getattr(args, 'end_assistant_line', None) or args.end_user_line
    if not 1 <= args.start_line <= args.end_user_line <= finish <= index.line_count:
        fail('Invalid inclusive JSONL line boundaries')
    try:
        rows, raw_slice = index.read_range(args.start_line, finish)
    except session_io.SessionIndexError as exc:
        fail(str(exc))
    def message(row):
        payload = row.get('payload', {})
        return payload if row.get('type') == 'response_item' and payload.get('type') == 'message' and payload.get('role') in ('user', 'assistant') and payload.get('phase') not in ('analysis', 'reasoning') and payload.get('channel') not in ('analysis', 'reasoning') else None
    if not message(rows[0]):
        fail('start-line must point to an exact user/assistant message')
    end = message(rows[args.end_user_line - args.start_line])
    if not end or end['role'] != 'user':
        fail('end-user-line must point to an exact user message')
    if finish > args.end_user_line:
        tail = message(rows[-1])
        if not tail or tail['role'] != 'assistant' or tail.get('recipient') not in (None, 'all'):
            fail('end-assistant-line must point to an exact visible assistant message')
        start = args.end_user_line - args.start_line + 1
        if any((m := message(row)) and m['role'] == 'user' for row in rows[start:]):
            fail('Cannot cross another user turn after the closing request')
    specification = json.loads(args.artifacts_json.read_text()) if args.artifacts_json else {}
    if not isinstance(specification, dict) or set(specification) - {'artifacts', 'missing_attachments'}:
        fail('Invalid artifacts JSON object')
    mappings, missing_map = {}, {}
    for field, destination in [('artifacts', mappings), ('missing_attachments', missing_map)]:
        for item in specification.get(field, []):
            key = (item.get('message_line'), item.get('block_index'))
            if key in destination or not all(type(v) is int for v in key):
                fail('Attachment requires unique integer message_line and block_index')
            if field == 'artifacts' and set(item) != {'message_line', 'block_index', 'role', 'path'}:
                fail('Artifact fields must be role, path, message_line, block_index')
            if field == 'missing_attachments' and (set(item) != {'message_line', 'block_index', 'reason'} or not isinstance(item['reason'], str) or not item['reason'].strip()):
                fail('Missing attachment requires a nonempty reason')
            destination[key] = item
    if mappings.keys() & missing_map.keys():
        fail('Attachment cannot be both present and missing')
    image_roles = {}
    for line, block, role in getattr(args, 'image_role', []):
        key = (line, block)
        if key in image_roles or key in mappings or key in missing_map:
            fail('Image role is duplicated or conflicts with artifacts JSON')
        image_roles[key] = role
    used_roles = set()
    turns, provenance, artifacts, missing, used = [], [], [], [], set()
    solution = None
    seen_paths = set()
    def add_artifact(role, path):
        path = Path(path).expanduser()
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            fail('Artifact path must be an existing absolute regular file')
        resolved = str(path.resolve())
        if resolved not in seen_paths:
            artifacts.append({'role': role, 'path': resolved})
            seen_paths.add(resolved)
    def default_role(path):
        if path.parent.name == args.formal_id and path.stem.startswith('question_'):
            return 'question_image'
        if path.suffix.lower() == '.svg':
            return 'explanation_image'
        return 'other_attachment'
    for line_no in range(args.start_line, finish + 1):
        m = message(rows[line_no - args.start_line])
        if not m:
            continue
        # Tool-call assistant messages are not conversation, even if they contain text.
        if m.get('recipient') not in (None, 'all'):
            if line_no in (args.start_line, args.end_user_line, args.solution_line):
                fail('Boundary/solution cannot refer to a tool-call message')
            continue
        blocks = m.get('content')
        if not isinstance(blocks, list):
            fail('Message content must be a list of typed blocks')
        images = {i: block_images(blocks, i)
                  for i, b in enumerate(blocks) if isinstance(b, dict)
                  and b.get('type') not in ('input_text', 'output_text', 'text')}
        # A Markdown reference to the very same wrapper must not add a later disk revision.
        embedded_paths = {ref.resolve() for frozen, ref in images.values() if frozen and ref}
        texts, lengths = [], []
        for index, block in enumerate(blocks):
            original_index = m.get('original_block_indexes', list(range(len(blocks))))[index]
            key = (line_no, original_index)
            if not isinstance(block, dict):
                fail('Invalid message block')
            is_text = block.get('type') in ('input_text', 'output_text', 'text')
            if is_text:
                text = block.get('text')
                if not isinstance(text, str):
                    fail('Text block lacks exact text')
                texts.append(text)
                lengths.append(len(text))
                # Only references within this exact selected message are considered.
                for ref in re.findall(r'!\[[^\]]*\]\(<?([^\n)]+?)>?\)', text):
                    path = local_image(ref, allow_missing=True)
                    if path and path.resolve() in embedded_paths:
                        continue
                    if path and path.is_file():
                        add_artifact(mappings.get(key, {}).get('role', default_role(path)), path)
                    elif key not in mappings and key not in missing_map:
                        fail(f'Unresolved image reference at line {line_no}, block {index}; provide artifacts JSON')
            if key in mappings:
                item = mappings[key]
                frozen = images.get(index, (None, None))[0]
                if frozen and not same_image_bytes(Path(item['path']).expanduser(), frozen):
                    fail(f'Attachment mapping disagrees with the embedded image at line {line_no}, block {original_index}')
                add_artifact(item['role'], frozen or item['path'])
                used.add(key)
            elif key in missing_map:
                if images.get(index, (None, None))[0]:
                    fail(f'Embedded image exists at line {line_no}, block {original_index}')
                missing.append(f'attachment:{line_no}:{index}: {missing_map[key]["reason"]}')
                used.add(key)
            elif not is_text:
                frozen, reference = images[index]
                path = frozen or reference
                if path:
                    add_artifact(image_roles.get(key, default_role(reference or path)), path)
                    if key in image_roles:
                        used_roles.add(key)
                else:
                    fail(f'Unresolved non-text block at line {line_no}, block {index}; provide mapping or missing reason')
        text = ''.join(texts)
        turns.append({'role': m['role'], 'text': text})
        boundary = {'line': line_no, 'text_block_lengths': lengths,
                    'block_types': m.get('original_block_types', [b.get('type') for b in blocks])}
        if args.provider == 'claude-code':
            boundary.update({'message_id': m['message_id'], 'parent_message_id': m['parent_message_id'],
                             'block_indexes': m['original_block_indexes']})
        provenance.append(boundary)
        if line_no == args.solution_line:
            if m['role'] != 'assistant':
                fail('solution-line must be an included assistant message')
            solution = text
    if used != mappings.keys() | missing_map.keys():
        fail('Attachment mapping points outside selected conversation blocks')
    if used_roles != image_roles.keys():
        fail('Image role must refer to a resolved image inside the selected conversation')
    if args.solution_line is not None and solution is None:
        fail('solution-line must be inside the exact selected conversation')
    return turns, provenance, artifacts, missing, solution, hashlib.sha256(raw_slice).hexdigest()


def invoke(command, payload, directory):
    path = directory / (command + '.json')
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        getattr(qi, 'cmd_' + command.replace('-', '_'))(argparse.Namespace(payload_file=str(path)))
    return json.loads(out.getvalue())


def configure_repo(root):
    root = root.expanduser().resolve(strict=True)
    if not root.is_dir():
        fail('--repo must be an existing repository directory')
    old_root = qi.REPO_ROOT
    for name, value in list(vars(qi).items()):
        if isinstance(value, Path) and value.is_relative_to(old_root):
            setattr(qi, name, root / value.relative_to(old_root))


def resolve_identity(args):
    """Keep a sealed attempt's binding; resolve a fresh printed ID through the current index."""
    question_id = args.source_question_id
    formal_id = args.formal_id
    if question_id is not None:
        question_id = qi.require_text(question_id, 'source-question-id', max_length=200)
        qi.reject_local_absolute_paths(question_id, 'source-question-id')
        # A new-source package may already have been sealed under this exact
        # attempt before the printed ID gained a formal alias. Resume its
        # original locator; stage/record still verify all bytes and hashes.
        original_locator = args.source_locator or f'{args.provider}:{args.session_id}:math:new_source:{question_id}:{args.attempt_id}'
        day = qi.validate_date(args.date)
        package_id = qi.conversation_package_id(day, args.attempt_id, original_locator)
        manifest_path = qi.SOURCE_STAGING_ROOT / day / package_id / 'manifest.json'
        if manifest_path.is_file():
            document = qi.read_json_document(manifest_path)
            source = document.get('source_identity') or {}
            if (document.get('package_id') == package_id and document.get('source_locator') == original_locator
                    and source.get('session_id') == args.session_id and source.get('capture_identity') == args.attempt_id
                    and source.get('question_id') == question_id):
                saved_formal = source.get('formal_id')
                if formal_id and formal_id != saved_formal:
                    fail('Existing attempt must keep its original capture target')
                if saved_formal is not None:
                    return {'kind': 'formal_card', 'formal_id': saved_formal}, original_locator, question_id
                return {'kind': 'new_source', 'source_locator': original_locator}, original_locator, question_id
        matches = lookup_source_identity(question_id)
        formal_ids = sorted({row['formal_id'] for row in matches})
        if len(formal_ids) > 1:
            fail('Source question ID matches multiple formal cards: ' + ', '.join(formal_ids))
        if formal_ids:
            if formal_id and formal_id != formal_ids[0]:
                fail('Source question ID conflicts with supplied formal-id')
            formal_id = formal_ids[0]
    if not formal_id and not question_id and not args.source_locator:
        fail('Supply formal-id, source-question-id, or a stable source-locator')
    locator = args.source_locator or f'{getattr(args, "provider", "codex")}:{args.session_id}:math:{formal_id or "new_source:" + question_id}:{args.attempt_id}'
    qi.reject_local_absolute_paths(locator, 'source-locator')
    target = ({'kind': 'formal_card', 'formal_id': formal_id} if formal_id else
              {'kind': 'new_source', 'source_locator': locator})
    qi.normalize_target(target, None)
    return target, locator, question_id


def _stamp(path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino]


def lookup_source_identity(question_id):
    index_path = qi.REPO_ROOT / '错题知识网络/个人知识点索引/index.sqlite3'
    if not index_path.is_file():
        fail('Source identity index unavailable; rebuild is disabled on the quick capture path')
    try:
        connection = sqlite3.connect(index_path.resolve().as_uri() + '?mode=ro', uri=True)
        with connection:
            connection.execute('BEGIN')
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_identities'"
            ).fetchone()
            if table is None:
                fail('Source identity index unavailable: source_identities is missing; rebuild is disabled on the quick capture path')
            meta = {}
            for key, value in connection.execute(
                "SELECT key,value FROM meta WHERE key IN ('schema','version','directories','store_stamps')"
            ):
                meta[key] = json.loads(value)
            required = {'schema', 'version', 'directories', 'store_stamps'}
            if not required.issubset(meta):
                fail('Source identity index metadata is incomplete; rebuild is disabled on the quick capture path')
            if meta['schema'] != 'math-concept-index-v1':
                fail('Source identity index schema is outdated; rebuild is disabled on the quick capture path')
            if not isinstance(meta['directories'], dict) or not isinstance(meta['store_stamps'], dict):
                fail('Source identity index freshness metadata is invalid; rebuild is disabled on the quick capture path')
            # source_identities is built solely from the front matter of formal
            # cards. Directory stamps catch additions/renames; existing file
            # stamps also catch an in-place edit introducing a duplicate ID.
            card_dir = qi.CARDS_DIR.relative_to(qi.REPO_ROOT).as_posix()
            if card_dir not in meta['directories']:
                fail('Source identity card directory stamp is missing')
            prefix = card_dir + '/'
            watched = {path: stamp for path, stamp in meta['directories'].items()
                       if path == card_dir or path.startswith(prefix)}
            for path, stamp in connection.execute(
                    'SELECT path,stamp FROM sources WHERE path GLOB ?', (prefix + '*.md',)):
                watched[path] = json.loads(stamp)
            observed = {path: _stamp(qi.REPO_ROOT / path) for path in watched}
            changed = [
                path for path, stamp in watched.items() if observed[path] != stamp
            ]
            if changed:
                preview = ', '.join(changed[:3])
                suffix = '' if len(changed) <= 3 else f' (+{len(changed) - 3} more)'
                fail(f'Source identity index is stale: {preview}{suffix}; rebuild is disabled on the quick capture path')
            rows = connection.execute(
                'SELECT source_id,formal_id,card_path FROM source_identities WHERE source_id=? ORDER BY formal_id,card_path',
                (question_id,),
            ).fetchall()
            if any(_stamp(qi.REPO_ROOT / path) != stamp for path, stamp in observed.items()):
                fail('Source identity inputs changed during lookup; retry after the index is rebuilt')
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        fail(f'Source identity index cannot be read ({exc}); rebuild is disabled on the quick capture path')
    finally:
        if 'connection' in locals():
            connection.close()
    result = []
    for source_id, card_id, card_path in rows:
        if source_id != question_id or not qi.CARD_ID_PATTERN.fullmatch(str(card_id)):
            fail('Source identity index returned an invalid exact-match row')
        relative = Path(str(card_path))
        if relative.is_absolute() or '..' in relative.parts:
            fail('Source identity index returned an invalid card path')
        canonical = (qi.REPO_ROOT / relative).resolve()
        card_root = qi.CARDS_DIR.resolve()
        if (
            not canonical.is_file()
            or card_root not in canonical.parents
            or canonical.stem.split('_', 1)[0] != str(card_id)
        ):
            fail('Source identity index returned a card path inconsistent with its formal ID')
        result.append({'formal_id': str(card_id), 'card_path': str(relative)})
    return result


def registered_question_text_attachment(args, question_id, locator):
    path = getattr(args, 'question_text', None)
    values = [getattr(args, key, None) for key in ('question_text_sha256', 'question_source_record_sha256', 'review_source_run_id')]
    if path is None and not any(x is not None for x in values):
        return None, None
    if path is None or any(x is None for x in values) or args.queue_id is None or args.item_id is None:
        fail('question-text requires exact surface/source hashes, review-source-run-id and queue/item')
    if not isinstance(question_id, str) or not re.fullmatch(r'MATH1-\d{4}-[A-Za-z0-9-]+', question_id):
        fail('question-text is only supported for an exact registered mathematics-I question')
    import math_review
    try:
        source = math_review.read_source(qi.REPO_ROOT, args.review_source_run_id)
        rows = [r for r in source.get('questions', []) if r.get('queue_item_id') == args.item_id]
        if len(rows) != 1:
            fail('question-text registered queue item not found')
        row = rows[0]
        if args.formal_id is not None and row.get('capture_formal_id') != args.formal_id:
            aliases = {r['formal_id'] for r in lookup_source_identity(question_id)}
            if aliases != {args.formal_id}:
                fail('question-text formal target lacks an exact registered or indexed alias')
        binding = {'schema': 'math-registered-question-text-binding-v1', 'run_id': args.review_source_run_id,
                   'registered_source_sha256': source.get('source_record_sha256'),
                   'question_id': question_id, 'queue_id': args.queue_id, 'item_id': args.item_id,
                   'source_record_sha256': args.question_source_record_sha256,
                   'question_sha256': args.question_text_sha256, 'question_file': row.get('question_file')}
        identity = {'question_text_binding': binding, 'question_id': question_id, 'formal_id': args.formal_id,
                    'queue_id': args.queue_id, 'item_id': args.item_id, 'source_locator': locator}
        expected, _ = qi.registered_question_text(identity)
        path = Path(path)
        if path.is_symlink() or path.resolve(strict=True) != expected.resolve(strict=True):
            fail('question-text path is not the exact registered surface')
        return {'role': 'question_text', 'path': str(expected)}, binding
    except (OSError, ValueError, TypeError, KeyError) as exc:
        fail('question-text binding rejected: ' + str(exc))


def formula_display_attachment(args, question_id, locator):
    path = getattr(args, 'formula_display_evidence', None)
    expected = getattr(args, 'formula_display_evidence_sha256', None)
    if path is None:
        if expected is not None:
            fail('formula-display-evidence-sha256 requires the evidence file')
        return None, None
    if expected is not None and not re.fullmatch(r'[0-9a-f]{64}', expected):
        fail('Invalid formula-display-evidence-sha256')
    reader = qi.formula_display_evidence_reader()
    path = Path(path)
    if path.is_symlink():
        fail('Formula display evidence cannot be a symlink')
    try:
        actual = path.resolve(strict=True)
        frozen = (qi.REPO_ROOT / reader.BASE / 'frozen').resolve()
        if actual.parent != frozen or not actual.is_file() or actual.stat().st_size > reader.MAX_BYTES:
            fail('Formula display evidence must be a sealed file in the current repository')
        value, sha = reader.validate_bundle_bytes(actual.read_bytes(),
            session_ref=args.session_id,
            question_ids=[x for x in (args.formal_id, question_id) if x],
            attempt_id=args.attempt_id, start_line=args.start_line,
            queue_id=args.queue_id, item_id=args.item_id, source_locator=locator,
            expected_sha256=expected)
        if actual.name != value['context_key'] + '.json':
            fail('Formula display evidence filename does not match its sealed context')
    except (OSError, ValueError, TypeError, KeyError) as exc:
        fail('Formula display evidence rejected: ' + str(exc))
    source = {'schema': value['schema'], 'artifact_sha256': sha,
              'bundle_sha256': value['bundle_sha256'], 'context_key': value['context_key'],
              'display_session_id': value['session_id'], 'question_id': value['question_id'],
              'counts': value['counts'], 'confirmation_scope': value['confirmation_scope']}
    return {'role': 'other_attachment', 'path': str(actual)}, source


def capture(args):
    if args.repo is not None:
        configure_repo(args.repo)
    started = time.perf_counter()
    index = session_index(args)
    if args.start_line is None:
        fail('Supply the exact --start-line or --start-message-id for this question')
    if args.attempt_id == 'auto':
        args.attempt_id = session_attempt(args, index, args.start_line)
    target, locator, question_id = resolve_identity(args)
    args.formal_id = target.get('formal_id')
    turns, provenance, artifacts, missing, solution, slice_hash = extract(args, index)
    question_text_artifact, question_text_binding = registered_question_text_attachment(args, question_id, locator)
    if question_text_artifact is not None:
        artifacts.append(question_text_artifact)
    display_artifact, display_source = formula_display_attachment(args, question_id, locator)
    if display_artifact is not None:
        artifacts.append(display_artifact)
    qi.validate_date(args.date)
    score = qi.score_reference(args.score_event_id)
    if args.score is not None and score is None:
        fail('--score requires an existing --score-event-id')
    if (args.queue_id is None) != (args.item_id is None):
        fail('queue-id and item-id must be supplied together')
    if score:
        expected = {'attempt_id': args.attempt_id, 'study_date': args.date, 'formal_id': args.formal_id}
        expected.update({k: v for k, v in [('queue_id', args.queue_id), ('queue_item_id', args.item_id), ('score', args.score)] if v is not None})
        if any(score[k] != v for k, v in expected.items()):
            fail('Requested identity/queue/item/score conflicts with recorded score')
    qi.normalize_target(target, score)  # Reject identity errors before any stage write.
    if not qi.ATTEMPT_ID_PATTERN.fullmatch(args.attempt_id):
        fail('Invalid attempt-id')
    prepare_ms = (time.perf_counter() - started) * 1000
    with tempfile.TemporaryDirectory(prefix='capture-current-math-') as temp:
        directory = Path(temp)
        if solution is not None:
            if any(a['role'] == 'solution_text' for a in artifacts):
                fail('solution-line and explicit solution_text cannot both be supplied')
            solution_path = directory / 'solution.txt'
            solution_path.write_bytes(solution.encode('utf-8'))
            artifacts.append({'role': 'solution_text', 'path': str(solution_path)})
        stage_payload = {
            'schema_version': qi.SOURCE_STAGE_SCHEMA_V2, 'package_key': args.attempt_id,
            'study_date': args.date, 'timezone': 'Asia/Shanghai',
            'source': {'source_locator': locator,
                       'session_id': args.session_id, 'formal_id': args.formal_id,
                       'capture_identity': args.attempt_id, 'queue_id': args.queue_id,
                       'item_id': args.item_id, 'score_event_id': args.score_event_id,
                       'rollout_slice_sha256': slice_hash, 'message_boundaries': provenance},
            'conversation': turns, 'artifacts': artifacts, 'missing_fields': missing,
        }
        if question_id is not None:
            stage_payload['source']['question_id'] = question_id
        if display_source is not None:
            stage_payload['source']['formula_display_evidence'] = display_source
        if question_text_binding is not None:
            stage_payload['source']['question_text_binding'] = question_text_binding
        if args.provider == 'claude-code':
            stage_payload['source'].update({'provider': 'claude-code',
                'start_message_id': provenance[0]['message_id'],
                'end_message_id': next(p['message_id'] for p in provenance if p['line'] == args.end_user_line)})
        stage_start = time.perf_counter()
        stage = invoke('stage-source', stage_payload, directory)
        stage_ms = (time.perf_counter() - stage_start) * 1000
        record_start = time.perf_counter()
        record = invoke('record', {
            'schema_version': qi.CAPTURE_SCHEMA_V3, 'attempt_id': args.attempt_id,
            'study_date': args.date, 'target': target, 'score_event_id': args.score_event_id,
            'requested_action': args.requested_action or ('record_wrong' if target['kind'] == 'new_source' else 'record_recurrence'), 'thread_ref': args.session_id,
            'conversation_package': {k: stage[k] for k in ('manifest_path', 'manifest_hash', 'package_sha256')},
        }, directory)
        record_ms = (time.perf_counter() - record_start) * 1000
    capture_id = record.get('capture_event_id') or record.get('event_id')
    # The Capture is already committed. A disposable pending-memory projection
    # must never turn its failure into an instruction to replay the writer.
    projection_started = time.perf_counter()
    try:
        scripts = Path(__file__).resolve().parents[2] / '错题知识网络/scripts'
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import math_memory_pending
        pending_projection = math_memory_pending.refresh_capture(qi.REPO_ROOT, capture_id)
    except Exception as exc:
        pending_projection = {'status': 'pending', 'reason': type(exc).__name__,
            'capture_id': capture_id, 'capture_committed': True,
            'recovery': 'math_memory_pending.py --repo REPO refresh --capture-id CAPTURE_ID',
            'replay_capture': False}
    projection_ms = (time.perf_counter() - projection_started) * 1000
    pending_projection['elapsed_ms'] = round(projection_ms, 3)
    result = {'stage_status': stage['status'], 'record_status': record['status'],
            'capture_event_id': record.get('capture_event_id') or record.get('event_id'),
            'attempt_id': args.attempt_id,
            'package_id': stage['package_id'], 'manifest_path': stage['manifest_path'],
            'target_kind': target['kind'], 'formal_id': args.formal_id, 'source_question_id': question_id,
            'manifest_hash': stage['manifest_hash'], 'package_sha256': stage['package_sha256'],
            'rollout_slice_sha256': slice_hash, 'turn_count': len(turns),
            'pending_projection': pending_projection,
            'elapsed_ms': {k: round(v, 3) for k, v in [('prepare', prepare_ms), ('stage', stage_ms),
                ('record', record_ms), ('total', (time.perf_counter() - started) * 1000)]},
            'formal_write_count': 0, 'score_write_count': 0, 'model_call_count': 0}
    if getattr(args, 'recap_concepts', None):
        result['recap'] = {'schema': 'math-recap-v1', 'status': 'reuse_teaching_context',
                           'basic_formulas': [], 'secondary_conclusions': [], 'solution_methods': [],
                           'capture_committed': True, 'replay_capture': False, 'learning_write_count': 0}
    return result


def main():
    try:
        if len(sys.argv) > 1 and sys.argv[1] == 'prepare':
            p = argparse.ArgumentParser(description='Read current-task boundaries, image paths and write-up candidates once')
            session_arguments(p)
            p.add_argument('--start-line', type=int)
            p.add_argument('--start-message-id')
            p.add_argument('--end-user-line', type=inclusive_line, default='auto')
            p.add_argument('--repo', type=Path)
            print(json.dumps(prepare(p.parse_args(sys.argv[2:])), ensure_ascii=False))
            return 0
        if len(sys.argv) > 1 and sys.argv[1] == 'messages':
            p = argparse.ArgumentParser(description='Locate exact current-task message lines without ad-hoc extraction code')
            session_arguments(p)
            p.add_argument('--limit', type=int, default=10)
            args = p.parse_args(sys.argv[2:])
            try:
                index = session_index(args)
            except session_io.SessionIndexError as exc:
                fail(str(exc))
            print(json.dumps(index.messages(args.limit), ensure_ascii=False))
            return 0
        print(json.dumps(capture(parser().parse_args()), ensure_ascii=False, sort_keys=True))
    except (qi.QuickIntakeError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc),
                          'recovery': 'Fix the input or retry the identical command; no existing package is overwritten.'}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
