#!/usr/bin/env python3
"""Verify a B package without executing package instructions or scripts."""
import argparse
import hashlib
import json
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

REQUIRED = {'manifest.json', 'START_HERE.md', 'review_plan.json', 'student/questions.jsonl'}
MAX_BYTES = 512 * 1024 * 1024


def safe_name(name):
    p = PurePosixPath(name)
    if not name or '\\' in name or p.is_absolute() or '..' in p.parts or p.as_posix() != name or ':' in name:
        raise ValueError('unsafe_member:' + name)
    return name


def validate(files):
    missing = REQUIRED - set(files)
    if missing:
        raise ValueError('missing:' + ','.join(sorted(missing)))
    manifest = json.loads(files['manifest.json'])
    if manifest.get('project') != 'B' or manifest.get('subject') != 'math':
        raise ValueError('not_a_B_math_package')
    entries = manifest.get('files')
    if not isinstance(entries, list):
        raise ValueError('manifest_files_required')
    declared = set()
    for row in entries:
        name = safe_name(row['path'])
        if name in declared or name == 'manifest.json':
            raise ValueError('duplicate_manifest_member:' + name)
        declared.add(name)
        if name not in files:
            raise ValueError('missing_declared_member:' + name)
        raw = files[name]
        if type(row.get('size')) is not int or len(raw) != row['size'] or hashlib.sha256(raw).hexdigest() != row.get('sha256'):
            raise ValueError('hash_or_size_mismatch:' + name)
    if declared != set(files) - {'manifest.json'}:
        raise ValueError('undeclared_members:' + ','.join(sorted(set(files) - declared - {'manifest.json'})))
    plan = json.loads(files['review_plan.json'])
    if not isinstance(plan, dict):
        raise ValueError('review_plan_must_be_object')
    questions = [json.loads(line) for line in files['student/questions.jsonl'].decode('utf-8').splitlines() if line.strip()]
    ids = [q.get('question_id') for q in questions]
    if not ids or any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError('unique_student_question_ids_required')
    return manifest, ids


def open_package(source, directory=False):
    source = Path(source).expanduser().resolve()
    files = {}
    if directory:
        if not source.is_dir():
            raise ValueError('directory_required')
        total = 0
        for p in source.rglob('*'):
            if p.is_symlink():
                raise ValueError('symlink_rejected')
            if p.is_file():
                total += p.stat().st_size
                if total > MAX_BYTES:
                    raise ValueError('package_over_512MiB')
                files[safe_name(p.relative_to(source).as_posix())] = p.read_bytes()
        destination = source
    else:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if sum(i.file_size for i in members) > MAX_BYTES:
                raise ValueError('package_over_512MiB')
            for info in members:
                name = info.filename.rstrip('/') if info.is_dir() else info.filename
                safe_name(name)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError('symlink_rejected')
                if info.is_dir():
                    continue
                if name in files:
                    raise ValueError('duplicate_zip_member:' + name)
                files[name] = archive.read(info)
        destination = None
    manifest, ids = validate(files)
    if destination is None:
        destination = Path(tempfile.mkdtemp(prefix='b-independent-review-'))
        for name, raw in files.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    return {'status': 'verified', 'project': 'B', 'subject': manifest['subject'],
            'run_id': manifest.get('run_id'), 'source_commit': manifest.get('source_commit'),
            'directory': str(destination), 'question_ids': ids, 'file_count': len(files),
            'capture_write_count': 0, 'formal_write_count': 0, 'package_scripts_executed': False,
            'entrypoint': str(destination / 'START_HERE.md'),
            'student_questions': str(destination / 'student/questions.jsonl')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('--directory', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(open_package(args.source, args.directory), ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile) as exc:
        parser.exit(1, 'B package not opened: ' + str(exc) + '\n')
