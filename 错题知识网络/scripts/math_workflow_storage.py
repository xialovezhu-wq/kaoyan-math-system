#!/usr/bin/env python3
"""T9 work directories and verified relocation of disposable math workflow files.

Formal records and referenced evidence are not disposable. Callers decide the
completed workflow scope and pass any still-referenced members through --keep.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import math_runtime_paths

REPO = Path(__file__).resolve().parents[2]
T9 = Path('/Volumes/Study-Archive')
WORK_ROOT = T9 / '03_数学/资料库/网页加工中间文件'
RECEIPTS = REPO / '数学一回滚复习系统/中间文件归档回执'
REGISTRY_MODULE = math_runtime_paths.storage_map_root(REPO) / 'cold_storage.py'


@lru_cache(maxsize=1)
def cold_registry():
    """Load the shared, fail-closed volume guard and live file locator writer."""
    spec = importlib.util.spec_from_file_location('_math_cold_storage', REGISTRY_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError('cold_storage_registry_unavailable')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ensure_cold_output(path: Path) -> Path:
    return cold_registry().ensure_output_path(path, subject='math')


def register_cold_artifact(path: Path, *, purpose: str, aliases=()) -> dict:
    return cold_registry().register_tree(path, subject='math', purpose=purpose, aliases=aliases)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def validate_t9() -> None:
    spec = importlib.util.spec_from_file_location('_math_storage_volume', REPO / '数学一回滚复习系统/scripts/archive_conversation_package.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.validate_volume(T9)


def ensure_workspace(path: Path) -> Path:
    path = ensure_cold_output(path)
    if not path.is_relative_to(WORK_ROOT.resolve()):
        raise ValueError('workspace_must_be_on_verified_T9_work_root')
    validate_t9()  # Never create a fake /Volumes mount directory when the disk is absent.
    path.mkdir(parents=True, exist_ok=True)
    return path


def transport_base() -> Path:
    return ensure_workspace(WORK_ROOT / '传输缓存')


def relocate(source: Path, destination: Path, *, keep: list[str], remove_local: bool) -> dict:
    source = source.expanduser().absolute()
    if any(p.is_symlink() for p in (source, *source.parents)) or not source.exists():
        raise ValueError('source_missing_or_symlink')
    destination = ensure_workspace(destination)
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('source_destination_overlap')
    single_file = source.is_file()
    root = source.parent if single_file else source
    paths = [source] if single_file else sorted(p for p in source.rglob('*') if p.is_file())
    if not single_file and any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('source_tree_contains_symlink')
    rows = [{'path': str(p.relative_to(root)), 'sha256': sha(p), 'size': p.stat().st_size} for p in paths]
    manifest_path = destination / 'T9-transfer-manifest.json'
    if any(row['path'] == manifest_path.name for row in rows):
        raise ValueError('reserved_transfer_manifest_name')
    manifest = {'schema': 'math-workflow-transfer-v1', 'source': str(source), 'files': rows}
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text())
        if prior.get('source') != str(source):
            raise ValueError('archive_destination_owned_by_another_source')
        old = {row['path']: row for row in prior['files']}
        if any(old.get(row['path']) != row for row in rows):
            raise ValueError('source_changed_since_archive')
        manifest = prior  # Resume cleanup of a subset without forgetting already copied members.
    for row in manifest['files']:
        target = destination / row['path']
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('archive_contains_symlink')
        if target.exists():
            if target.stat().st_size != row['size'] or sha(target) != row['sha256']:
                raise ValueError('archive_existing_bytes_conflict:' + row['path'])
            continue
        src = root / row['path']
        if not src.is_file() or src.stat().st_size != row['size'] or sha(src) != row['sha256']:
            raise ValueError('source_changed_before_copy:' + row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.copy-', dir=target.parent)
        os.close(fd)
        try:
            shutil.copyfile(src, temporary)
            if sha(Path(temporary)) != row['sha256']:
                raise ValueError('copy_hash_mismatch:' + row['path'])
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    raw = canonical(manifest)
    if not manifest_path.exists():
        with manifest_path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    if manifest_path.read_bytes() != raw:
        raise ValueError('archive_manifest_readback_failed')
    # Reopen the completed destination before removing any original byte.
    for row in manifest['files']:
        target = destination / row['path']
        if target.stat().st_size != row['size'] or sha(target) != row['sha256']:
            raise ValueError('archive_readback_failed:' + row['path'])
    keep_set = set(keep)
    if not keep_set <= {row['path'] for row in manifest['files']}:
        raise ValueError('keep_member_not_in_archive')
    receipt = {'schema': 'math-workflow-transfer-receipt-v1', 'source': str(source),
               't9_relative_path': str(destination.relative_to(T9)), 'manifest_sha256': hashlib.sha256(raw).hexdigest(),
               'file_count': len(manifest['files']), 'bytes': sum(row['size'] for row in manifest['files']),
               'retained_formal_members': sorted(keep_set), 'archive_verified': True}
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    receipt_path = RECEIPTS / (hashlib.sha256(canonical(receipt)).hexdigest() + '.json')
    if receipt_path.exists():
        if receipt_path.read_bytes() != canonical(receipt):
            raise ValueError('transfer_receipt_conflict')
    else:
        receipt_path.write_bytes(canonical(receipt))
    if receipt_path.read_bytes() != canonical(receipt):
        raise ValueError('transfer_receipt_readback_failed')
    # Persist and read back the shared locator before any source is removed.
    registration = register_cold_artifact(
        destination / source.name if single_file else destination,
        purpose='math_workflow_archive', aliases=(source,))
    if single_file:
        register_cold_artifact(manifest_path, purpose='math_workflow_archive_manifest')
    removed = 0
    if remove_local:
        validate_t9()
        for row in manifest['files']:
            src = root / row['path']
            if row['path'] in keep_set or not src.exists():
                continue
            if src.is_symlink() or src.stat().st_size != row['size'] or sha(src) != row['sha256']:
                raise ValueError('source_changed_before_cleanup:' + row['path'])
            src.unlink()
            removed += row['size']
        if not single_file:
            for directory in sorted((p for p in source.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                if not any(directory.iterdir()):
                    directory.rmdir()
            if not any(source.iterdir()):
                source.rmdir()
    return {**receipt, 'receipt_path': str(receipt_path), 'storage_registration': registration,
            'local_bytes_removed_this_run': removed,
            'cleanup_requested': remove_local}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--batch-id', required=True)
    init.add_argument('--date', required=True)
    archive = sub.add_parser('archive')
    archive.add_argument('--source', type=Path, required=True)
    archive.add_argument('--destination', type=Path, required=True)
    archive.add_argument('--keep', action='append', default=[])
    archive.add_argument('--remove-local', action='store_true')
    args = parser.parse_args()
    if args.command == 'init':
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', args.batch_id) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.date):
            raise ValueError('invalid_work_directory_identity')
        root = ensure_workspace(WORK_ROOT / args.date / args.batch_id)
        temp = ensure_workspace(root / 'tmp')
        result = {'workspace': str(root), 'temp_directory': str(temp), 'formal_write_count': 0}
    else:
        result = relocate(args.source, args.destination, keep=args.keep, remove_local=args.remove_local)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
