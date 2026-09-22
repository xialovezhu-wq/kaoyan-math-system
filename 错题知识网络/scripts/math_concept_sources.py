"""Build-only source collection. No formal writes and no source reads on query paths."""
from __future__ import annotations
import hashlib
import sys
import json
import re
import shutil
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrongnet import split_front_matter

CACHE = Path('错题知识网络/个人知识点索引/source_cache')
ROLLBACK = Path('数学一回滚复习系统')
DOMAINS = ('错题知识网络/知识树', '错题知识网络/方法论库',
           '错题知识网络/学习记录', '数学一回滚复习系统/学习记录',
           'kaoyan_math_project_v2', '高数讲义', '线代讲义', '概率讲义', '概率论讲义', '资料库', '错题知识网络/assets')
SOURCE_WATCH_PATHS = DOMAINS + ('错题知识网络/知识点库.md', '错题知识网络/错题卡',
    '数学一回滚复习系统/快速入库事件.jsonl', '数学一回滚复习系统/原始会话归档回执.jsonl',
    '数学一回滚复习系统/快速入库来源')
TEXT_EXT = {'.md', '.txt', '.json', '.jsonl', '.html', '.csv'}
BINARY_EXT = {'.pdf', '.docx', '.png', '.jpg', '.jpeg', '.webp', '.xlsx'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _write(path, data):
    data = data.encode('utf-8') if isinstance(data, str) else data
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def _user_reference(conversation, cache, outcomes):
    turns = conversation.get('turns', [])
    users = []
    for i, turn in enumerate(turns):
        if turn.get('role') == 'user' and isinstance(turn.get('text'), str):
            raw = turn['text']
            users.append({'sequence': turn.get('sequence', i + 1), 'role': 'user', 'text': raw,
                          'raw_text_sha256': digest(raw.encode()), 'character_range': [0, len(raw)],
                          'previous_role': turns[i-1].get('role') if i else None,
                          'next_role': turns[i+1].get('role') if i+1 < len(turns) else None})
    payload = json.dumps(users, ensure_ascii=False, sort_keys=True)
    sha = digest(payload.encode())
    _write(cache / (sha + '.users.json'), payload)
    chosen = [u for u in users if u['text'].strip()]
    # A complete first substantive user turn, never a synthetic concatenation.
    first = chosen[0] if chosen else None
    meta = {'user_turn_cache': (CACHE / (sha + '.users.json')).as_posix(),
            'user_turn_cache_sha256': sha, 'user_turn_count': len(users),
            'user_turn_provenance': [{k:v for k,v in u.items() if k != 'text'} for u in users],
            'selected_user_sequence': first['sequence'] if first else None,
            'selection': 'first_complete_user_turn', 'role': 'raw_unadjudicated_not_new_wrong_cause'}
    return (first['text'] if first and 'wrong_rejected' not in outcomes else ''), meta


def _json(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()] if path.exists() else []


def _inside(base, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('unsafe source path')
    target = base / rel
    if not target.resolve().is_relative_to(base.resolve()):
        raise ValueError('source escapes allowed domain')
    return target


def _input_stamps(root):
    """Build-only recursive local stat inventory, including additions and removals."""
    paths = set()
    for relative in SOURCE_WATCH_PATHS:
        base = root / relative
        if base.is_dir():
            paths.update(p for p in base.rglob('*') if p.is_file())
        else:
            paths.add(base)
    paths.add(root / '.codex-artifacts/math-concept-personal-20260908/source-inventory.json')
    paths.add(Path(__file__).resolve())
    paths.add(Path(__file__).resolve().with_name('wrongnet.py'))
    result = {}
    for path in sorted(paths):
        if path.is_relative_to(root / CACHE):
            continue
        try:
            st = path.stat()
            result[str(path)] = [st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino]
        except OSError:
            result[str(path)] = None
    return result


def _fast_sources(root, cache, stamps):
    try:
        state = _json(cache / 'collection_state.json', {})
    except (OSError, ValueError):
        return None
    if state.get('input_stamps') != stamps:
        return None
    inventory_path = cache / 'source_inventory.json'
    try:
        raw = inventory_path.read_bytes()
        if digest(raw) != state.get('inventory_sha256'):
            return None
        inventory = json.loads(raw)
        for row in inventory['sources']:
            path = _inside(root, row['path'])
            if not path.is_relative_to(cache) or digest(path.read_bytes()) != row['sha256']:
                return None
        return inventory['sources']
    except (OSError, ValueError, KeyError):
        return None


def collect_sources(repo_root):
    """Return safe, hash-addressed projections; write a coverage inventory beside them."""
    root = Path(repo_root).resolve()
    cache = root / CACHE
    cache.mkdir(parents=True, exist_ok=True)
    input_stamps = _input_stamps(root)
    fast = _fast_sources(root, cache, input_stamps)
    if fast is not None:
        return fast
    state_path = cache / 'stat_cache.json'
    old = _json(state_path, {})
    state, output, coverage = {}, [], []

    def read(path, expected=None, immutable=False):
        key = str(path)
        prior = old.get(key, {})
        try:
            st = path.stat()
        except OSError:
            if immutable and expected and prior.get('sha256') == expected:
                blob = cache / (expected + '.blob')
                if blob.exists() and digest(blob.read_bytes()) == expected:
                    state[key] = prior
                    return blob.read_bytes(), 'verified_cached_offline'
            return None, 'missing'
        signature = [st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino]
        sha = prior.get('sha256')
        blob = cache / (str(sha) + '.blob')
        if prior.get('stat') == signature and blob.exists():
            data = blob.read_bytes()
            if digest(data) != sha:
                data = path.read_bytes()
        elif prior.get('stat') == signature and path.suffix not in TEXT_EXT and not immutable:
            state[key] = prior
            return b'', 'verified_stat_cached:' + sha
        else:
            data = path.read_bytes()
        sha = digest(data)
        if expected and sha != expected:
            return None, 'hash_mismatch'
        # Immutable raw cache remains private build input, never a query source.
        if immutable or path.suffix in TEXT_EXT:
            _write(cache / (sha + '.blob'), data)
        state[key] = {'stat': signature, 'sha256': sha}
        return data, 'verified'

    labels = set()
    registry = root / '错题知识网络/知识点库.md'
    if registry.exists():
        labels.update(re.findall(r'^- (.+)$', registry.read_text(), re.M))
    formal_labels = {}
    for card in sorted((root / '错题知识网络/错题卡').glob('*.md')):
        data = card.read_text(encoding='utf-8')
        front, _ = split_front_matter(data)
        values = front.get('knowledge', [])
        values = values if isinstance(values, list) else [values]
        values = [str(value) for value in values if value]
        if front.get('id'):
            formal_labels[str(front['id'])] = values
        labels.update(values)

    def emit(identity, kind, text, metadata, ids=(), search_text=''):
        ls = sorted({label for label in labels if label and label in search_text} |
                    {label for fid in ids for label in formal_labels.get(fid, [])})
        payload = json.dumps({'source_kind': kind, 'labels': ls, 'formal_ids': sorted(set(ids)),
                              'text': text, 'metadata': metadata}, ensure_ascii=False, sort_keys=True)
        name = digest(identity.encode()) + '.json'
        output.append({'path': (CACHE / name).as_posix(), 'sha256': digest(payload.encode()),
                       'source_kind': kind, 'labels': ls, 'formal_ids': sorted(set(ids)),
                       'text': text, 'metadata': metadata})

    candidates = {registry} if registry.exists() else set()
    for domain in DOMAINS:
        base = root / domain
        if base.exists():
            candidates.update(p for p in base.rglob('*') if p.is_file() and p.suffix.lower() in TEXT_EXT | BINARY_EXT)
    # Scout paths supplement explicit domains, while discovery above admits future files.
    scout = _json(root / '.codex-artifacts/math-concept-personal-20260908/source-inventory.json', {})
    for row in scout.get('sources', []):
        p = Path(row['path'])
        if row.get('sourceKind') in {'reference_material', 'learning_record', 'source_pdf', 'knowledge_registry'} and p.is_relative_to(root):
            candidates.add(p)
    dedup = {}
    for path in sorted(candidates):
        if not path.resolve().is_relative_to(root):
            continue
        data, status = read(path)
        meta = {'original_path': path.relative_to(root).as_posix(), 'status': 'verified' if status.startswith('verified_stat_cached:') else status,
                'personal_evidence': False, 'role': 'reference_only_not_mastery'}
        if data is None:
            meta['coverage'] = 'missing'
            emit(str(path), 'general_learning_material', '', meta)
            continue
        sha = status.split(':', 1)[1] if status.startswith('verified_stat_cached:') else digest(data)
        meta.update(original_sha256=sha, size=path.stat().st_size, coverage='full_bytes', image_semantic_reviewed=False)
        body = data.decode('utf-8', errors='replace') if path.suffix in TEXT_EXT else ''
        if path.suffix.lower() == '.pdf':
            extracted = cache / (sha + '.pdftext.json')
            if extracted.exists():
                pdf = _json(extracted, {})
            else:
                try:
                    import fitz
                    with fitz.open(path) as doc:
                        pages = [page.get_text() for page in doc]
                    pdf = {'text': '\n'.join(pages), 'pages': len(pages), 'pages_with_text': sum(bool(t.strip()) for t in pages)}
                    _write(extracted, json.dumps(pdf, ensure_ascii=False))
                except (ImportError, RuntimeError, ValueError) as exc:
                    pdf = {'text': '', 'error': str(exc)}
                    if shutil.which('pdftotext'):
                        result = subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True)
                        if result.returncode == 0:
                            pages = result.stdout.split('\f')
                            if pages and not pages[-1].strip():
                                pages.pop()
                            pdf = {'text': result.stdout, 'pages': len(pages), 'pages_with_text': sum(bool(t.strip()) for t in pages), 'extractor': 'pdftotext', 'ocr_performed': False}
                            _write(extracted, json.dumps(pdf, ensure_ascii=False))
            body = pdf.get('text', '')
            meta['pdf_coverage'] = {k: v for k, v in pdf.items() if k != 'text'}
        meta['text_status'] = 'parsed_full' if body.strip() else 'text_unavailable_no_ocr'
        if body.strip():
            if path.suffix == '.json':
                try:
                    body = json.dumps(json.loads(body), ensure_ascii=False, indent=2)
                except ValueError:
                    pass
            text_sha = digest(body.encode())
            text_path = CACHE / (text_sha + '.reference.txt')
            _write(root / text_path, body)
            material_lines = body.splitlines()
            meta['reference_text_path'] = text_path.as_posix()
            meta['reference_text_sha256'] = text_sha
            meta['reference_line_count'] = len(material_lines)
            meta['concept_locations'] = {label: [i+1 for i,line in enumerate(material_lines) if label in line][:8]
                                         for label in sorted(labels) if label and label in body}

        asset_ids = re.findall(r'(?<![A-Z0-9])(?:GS|LA|PR)-\d+', meta['original_path']) if '/assets/' in meta['original_path'] else []
        if sha in dedup:
            dedup[sha]['formal_ids'] = sorted(set(dedup[sha]['formal_ids']) | set(asset_ids))
            dedup[sha]['labels'] = sorted(set(dedup[sha]['labels']) | {label for fid in asset_ids for label in formal_labels.get(fid, [])})
            dedup[sha]['metadata'].setdefault('duplicate_paths', []).append(meta['original_path'])
            continue
        asset_ids = re.findall(r'(?<![A-Z0-9])(?:GS|LA|PR)-\d+', meta['original_path']) if '/assets/' in meta['original_path'] else []
        emit(str(path), 'general_learning_material', '', meta, asset_ids, search_text=body)
        dedup[sha] = output[-1]

    events = _lines(root / ROLLBACK / '快速入库事件.jsonl')
    accepted, captures = {}, {}
    for event in events:
        if event.get('event_type') == 'capture':
            captures[event['event_id']] = event
        if event.get('event_type') == 'closeout':
            for result in event.get('capture_results', []):
                accepted[result['capture_event_id']] = dict(result, closeout_id=event['event_id'])
    receipts = _lines(root / ROLLBACK / '原始会话归档回执.jsonl')
    covered = set()
    for receipt in receipts:
        cids = receipt.get('capture_ids') or [receipt.get('capture_event_id')]
        cids = [cid for cid in cids if cid]
        if not cids or not all(cid in accepted and accepted[cid]['closeout_id'] == receipt.get('closeout_id') for cid in cids):
            coverage.append({'receipt_id': receipt.get('receipt_id'), 'status': 'not_accepted'})
            continue
        covered.update(cids)
        outcomes = sorted({accepted[cid]['outcome'] for cid in cids})
        ids = [accepted[cid].get('formal_id') for cid in cids if accepted[cid].get('formal_id')]
        meta = {'capture_ids': cids, 'receipt_id': receipt.get('receipt_id'), 'terminal_outcomes': outcomes,
                'closeout_id': receipt.get('closeout_id'), 'personal_evidence': False,
                'role': 'raw_unadjudicated_not_new_wrong_cause', 'conversation_complete': False}
        text = ''
        try:
            rel = receipt.get('raw_archive_relpath', '')
            if not rel.startswith('03_数学/资料库/原始会话资料/') or receipt.get('archive_volume') != 'T9-Data':
                raise ValueError('archive outside mathematical receipt scope')
            archive = _inside(Path('/Volumes/T9-Data'), rel)
            meta['original_path'] = str(archive)
            expected = receipt.get('raw_archive_manifest_sha256')
            if receipt.get('archive_status') != 'verified' or not expected:
                raise ValueError('unverified receipt')
            raw, status = read(archive / 'manifest.json', expected, True)
            meta.update(status=status, original_sha256=expected)
            if raw is None:
                meta['coverage'] = status
            else:
                manifest = json.loads(raw)
                entries = list(manifest.get('files', {}).values()) + manifest.get('artifacts', [])
                legacy = 'payload_files' in manifest
                if legacy:
                    entries = manifest['payload_files']
                checks = []
                conversation = None
                for entry in entries:
                    original = entry.get('original_path') or entry.get('path', '')
                    if legacy:
                        target = _inside(archive, entry['archive_path'])
                    else:
                        local = _inside(root, original)
                        # Archives retain attachment paths below package root.
                        subpath = original.split(str(manifest.get('package_id')) + '/', 1)[-1]
                        archived = _inside(archive, subpath)
                        target = local if local.exists() else archived
                    if not entry.get('sha256'):
                        raise ValueError('manifest file lacks SHA256')
                    content, checked = read(target, entry['sha256'], True)
                    checks.append({'path': str(target), 'sha256': entry.get('sha256'), 'status': checked,
                                   'text_status': 'available' if target.suffix in TEXT_EXT else 'text_unavailable_no_ocr'})
                    if target.name == 'conversation.json' and content is not None:
                        conversation = json.loads(content)
                meta['files'] = checks
                meta['coverage'] = 'full_bytes' if all(x['status'].startswith('verified') for x in checks) else 'partial'
                meta['conversation_complete'] = conversation is not None
                if conversation is None:
                    meta['conversation_status'] = 'legacy_conversation_missing' if legacy else 'conversation_unavailable'
                else:
                    text, user_meta = _user_reference(conversation, cache, outcomes)
                    meta.update(user_meta)
        except (ValueError, OSError, KeyError) as exc:
            meta.update(status='invalid_or_unavailable', coverage='partial', error=str(exc))
        emit('capture:' + '|'.join(cids), 'accepted_conversation_excerpt' if text else 'accepted_capture_reference', text, meta, ids)
    for cid, result in accepted.items():
        if cid not in covered:
            meta = {'capture_ids': [cid], 'status': 'archive_receipt_missing', 'coverage': 'missing',
                    'terminal_outcomes': [result['outcome']], 'personal_evidence': False}
            text = ''
            package = captures.get(cid, {}).get('conversation_package')
            if package:
                try:
                    manifest_path = _inside(root, package['manifest_path'])
                    expected = package.get('manifest_hash')
                    if not expected:
                        raise ValueError('local package lacks manifest hash')
                    raw, status = read(manifest_path, expected, True)
                    meta.update(status=status, original_path=package['manifest_path'], original_sha256=expected,
                                archive_status='not_yet_archived')
                    if raw is not None:
                        manifest = json.loads(raw)
                        if package.get('package_sha256') and manifest.get('canonical_sha256') != package['package_sha256']:
                            raise ValueError('local package canonical hash mismatch')
                        checks, conversation = [], None
                        for entry in list(manifest.get('files', {}).values()) + manifest.get('artifacts', []):
                            if not entry.get('sha256'):
                                raise ValueError('local file lacks SHA256')
                            target = _inside(root, entry['path'])
                            content, checked = read(target, entry['sha256'], True)
                            checks.append({'path': entry['path'], 'sha256': entry['sha256'], 'status': checked})
                            if target.name == 'conversation.json' and content is not None:
                                conversation = json.loads(content)
                        meta.update(files=checks, coverage='full_bytes' if checks and all(x['status'].startswith('verified') for x in checks) else 'partial',
                                    conversation_complete=conversation is not None)
                        if conversation is not None:
                            text, user_meta = _user_reference(conversation, cache, [result['outcome']])
                            meta.update(user_meta)
                except (ValueError, KeyError, OSError) as exc:
                    meta.update(status='invalid_or_unavailable', coverage='partial', error=str(exc))
            emit('capture:' + cid, 'accepted_conversation_excerpt' if text else 'accepted_capture_reference', text, meta,
                 [result['formal_id']] if result.get('formal_id') else [])
    for cid in captures.keys() - accepted.keys():
        coverage.append({'capture_id': cid, 'status': 'pending_not_accepted'})
    # Re-serialize after duplicate-path provenance was merged.
    for row in output:
        payload = json.dumps({k: row[k] for k in ('source_kind', 'labels', 'formal_ids', 'text', 'metadata')}, ensure_ascii=False, sort_keys=True)
        _write(root / row['path'], payload)
        row['sha256'] = digest(payload.encode())
        row['record_id'] = Path(row['path']).stem
        row['source_refs'] = []
        meta = row['metadata']
        if row['source_kind'] == 'general_learning_material' and meta.get('original_sha256'):
            row['source_refs'].append({'path': meta['original_path'], 'sha256': meta['original_sha256']})
            for duplicate in meta.get('duplicate_paths', []):
                row['source_refs'].append({'path': duplicate, 'sha256': meta['original_sha256']})
    _write(state_path, json.dumps(state, ensure_ascii=False, sort_keys=True))
    _write(cache / 'source_inventory.json', json.dumps({'sources': output, 'excluded_or_pending': coverage, 'summary': {'source_records': len(output), 'full_byte_scanned': sum(r['metadata'].get('coverage') == 'full_bytes' for r in output), 'text_parsed': sum(r['metadata'].get('text_status') == 'parsed_full' or r['metadata'].get('conversation_complete', False) for r in output), 'image_semantic_reviewed': False}}, ensure_ascii=False, sort_keys=True))
    if _input_stamps(root) == input_stamps:
        _write(cache / 'collection_state.json', json.dumps({'input_stamps': input_stamps,
            'inventory_sha256': digest((cache / 'source_inventory.json').read_bytes())}, sort_keys=True))
    return output
