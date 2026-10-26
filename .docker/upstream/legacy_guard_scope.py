#!/usr/bin/env python3
"""Inspect or restore only the existing metadata guard's container scope file.

Never executes/replaces guard code, starts services, updates pins, or mutates DB.
Reviewed code comes from git revision 41373eb; a different installed byte hash is
not accepted as equivalent by heuristic source inspection.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import uuid

SIBLING = Path(__file__).resolve().parent
PRIVATE_ROOT = Path('/root/Xboard/backups/upstream-20261022')
PLAN_ROOT = Path('/root/xboard-upstream-recovery')
REPOSITORY = Path('/root/Xboard')
REVIEWED = {'guard.py': '56197b13cf36c01135abecd6870deb34b3ddabfdeaaef830814b79926e974bd5',
            'guard-apply.php': '4b8e66a8f137c2bcc7b61f91bb2b3416bd239bad5b2e4c909c0fc6321ea7729a'}
REVIEWED_REVISION = '41373ebd943832b05d0fb67c5144f0490ce5ff5f'
STAGE = 'startup'


class ScopeRepairError(Exception):
    def __init__(self, reason, installed=None, container=None):
        self.reason = reason
        self.installed = installed
        self.container = container
        super().__init__(reason)


def fail(reason, installed=None, container=None):
    raise ScopeRepairError(reason, installed, container)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def installed_code():
    rows = []
    for name, expected in REVIEWED.items():
        path = PRIVATE_ROOT / name
        info = path.lstat()
        signature = code_signature(info)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            current = os.fstat(fd)
            if code_signature(current) != signature:
                fail('installed_guard_changed')
            with os.fdopen(fd, 'rb', closefd=False) as source:
                body = source.read(1048577)
            after = os.fstat(fd)
            if len(body) != info.st_size or code_signature(after) != signature or code_signature(path.lstat()) != signature:
                fail('installed_guard_changed')
        finally:
            os.close(fd)
        checksum = sha(body)
        rows.append({'file': name, 'sha256': checksum, 'matches_reviewed_metadata_only': checksum == expected})
    return rows


def code_signature(info):
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or not 0 < info.st_size <= 1048576:
        fail('installed_guard_file_invalid')
    return tuple(getattr(info, key) for key in ('st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def container_scope(action, manifest_bytes):
    program = (SIBLING / 'legacy-guard-scope.php').read_text()
    import base64
    if program.count('__ACTION__') != 1 or program.count('__MANIFEST_BASE64__') != 1:
        fail('container_helper_invalid')
    program = program.replace('__ACTION__', action).replace('__MANIFEST_BASE64__', base64.b64encode(manifest_bytes).decode())
    result = subprocess.run(['docker', 'compose', 'exec', '-T', 'xboard', 'php'], cwd=REPOSITORY,
                            input=program.encode(), capture_output=True, timeout=30)
    if len(result.stdout) > 4096:
        fail('container_reply_invalid')
    try:
        value = json.loads(result.stdout)
    except Exception:
        fail('container_reply_invalid')
    if not isinstance(value, dict):
        fail('container_reply_invalid')
    if result.returncode:
        reason = value.get('reason')
        if reason not in {'container_scope_invalid', 'container_parent_invalid', 'container_manifest_conflict',
                          'container_manifest_permissions', 'container_commit_unknown', 'container_io_failed'}:
            reason = 'container_operation_failed'
        fail(reason)
    expected = {'status', 'manifest_sha256', 'target_exists', 'target_matches', 'target_private', 'parent_safe',
                'parent_creatable', 'directories', 'directories_created', 'manifest_created'}
    if set(value) != expected or value['status'] not in ('inspected', 'restored', 'already_matches') or value['manifest_sha256'] != sha(manifest_bytes):
        fail('container_reply_invalid')
    if any(type(value[key]) is not bool for key in expected - {'status', 'manifest_sha256', 'directories', 'directories_created'}):
        fail('container_reply_invalid')
    directories = value['directories']
    if not isinstance(directories, dict) or set(directories) != {'anchor', 'backups', 'scope'}:
        fail('container_reply_invalid')
    for metadata in directories.values():
        fields = {'classification', 'exists', 'directory', 'is_symlink', 'owner_class', 'mode', 'realpath_matches'}
        if (not isinstance(metadata, dict) or set(metadata) != fields
                or metadata['classification'] not in ('missing', 'unreadable', 'present', 'parent_unavailable')
                or metadata['owner_class'] not in ('root', 'nonroot', 'unknown')
                or (metadata['mode'] is not None and (not isinstance(metadata['mode'], str) or not re.fullmatch('[0-7]{4}', metadata['mode'])))
                or any(type(metadata[key]) is not bool for key in ('exists', 'directory', 'is_symlink', 'realpath_matches'))):
            fail('container_reply_invalid')
    created = value['directories_created']
    if (not isinstance(created, list) or any(item not in ('backups', 'scope') for item in created)
            or len(created) != len(set(created))):
        fail('container_reply_invalid')
    if action == 'inspect' and (value['status'] != 'inspected' or value['manifest_created'] or created):
        fail('container_reply_invalid')
    if action == 'restore' and (value['status'] not in ('restored', 'already_matches') or not all(value[k] for k in ('target_exists','target_matches','target_private','parent_safe'))):
        fail('container_reply_invalid')
    return value


def run(action, scope=None, prepare=None, container=None):
    global STAGE
    if action not in ('inspect', 'restore'):
        fail('invalid_arguments')
    scope = scope or load('legacy_scope_contract', SIBLING / 'scope_restore.py')
    prepare = prepare or load('legacy_prepare_snapshot', SIBLING / 'prepare.py')
    container = container or container_scope
    with scope.root_lock():
        STAGE = 'installed_metadata_guard'
        installed = installed_code()
        exact = all(row['matches_reviewed_metadata_only'] for row in installed)
        if action == 'restore' and not exact:
            fail('installed_guard_not_reviewed_metadata_only', installed)
        STAGE = 'host_scope_inputs'
        allocation, approved, approved_bytes, minimal = scope.load_inputs()
        manifest_bytes = scope.private_read(PRIVATE_ROOT / 'manifest.private')
        if manifest_bytes != scope.canonical(minimal):
            fail('host_manifest_not_exact_minimal_scope')
        STAGE = 'database_ownership_snapshot'
        snapshot = prepare.snapshot_database(allocation, manifest_bytes)
        state_hashes = scope.validate_snapshot(prepare, allocation, approved, snapshot)
        STAGE = 'container_scope_inspection'
        before = container('inspect', manifest_bytes)
        report = {'status': 'legacy_guard_scope_inspected', 'reviewed_git_revision': REVIEWED_REVISION, 'installed': installed,
                  'metadata_only_exact': exact, 'route_count': 41, 'manifest_sha256': sha(manifest_bytes),
                  'approved_file_sha256': sha(approved_bytes), 'allocation_file_sha256': scope.ALLOCATION_BYTES_SHA,
                  'container': before, 'database_mutated': False, 'guard_code_mutated': False,
                  'public_key_baseline_mutated': False, 'source_baseline_mutated': False, 'guard_executed': False}
        if action == 'inspect':
            return report
        if not before['parent_safe'] and not before['parent_creatable']:
            fail('container_parent_invalid', container=before)
        if before['target_exists'] and not before['target_matches']:
            fail('container_manifest_conflict')
        if before['target_exists'] and not before['target_private']:
            fail('container_manifest_permissions')
        if before['target_exists']:
            report['status'] = 'legacy_guard_scope_already_matches'
            return report
        metadata_id = uuid.uuid4().hex
        directory = PLAN_ROOT / metadata_id
        directory.mkdir(mode=0o700)
        STAGE = 'private_repair_intent'
        intent = {'schema': 1, 'operation': 'restore_legacy_guard_scope', 'metadata_id': metadata_id,
                  'at': int(time.time()), 'approved_file_sha256': sha(approved_bytes),
                  'allocation_file_sha256': scope.ALLOCATION_BYTES_SHA, 'manifest_sha256': sha(manifest_bytes),
                  'installed': installed, 'state_sha256': state_hashes, 'target_missing_before': True,
                  'container_directories_before': before['directories']}
        scope.private_write(directory / 'legacy-guard-scope-intent.private.json', scope.canonical(intent))
        scope.sync_directory(directory)
        scope.sync_directory(PLAN_ROOT)
        STAGE = 'pre_restore_recheck'
        if (scope.private_read(PRIVATE_ROOT/'approved.private') != approved_bytes
                or scope.private_read(PRIVATE_ROOT/'manifest.private') != manifest_bytes or installed_code() != installed):
            fail('repair_input_changed')
        current_snapshot = prepare.snapshot_database(allocation, manifest_bytes)
        if scope.validate_snapshot(prepare, allocation, approved, current_snapshot) != state_hashes:
            fail('database_state_changed')
        if (scope.private_read(PRIVATE_ROOT/'approved.private') != approved_bytes
                or scope.private_read(PRIVATE_ROOT/'manifest.private') != manifest_bytes or installed_code() != installed):
            fail('repair_input_changed')
        STAGE = 'container_scope_restore'
        try:
            after = container('restore', manifest_bytes)
            STAGE = 'container_scope_readback'
            checked = container('inspect', manifest_bytes)
            if not all(checked[key] for key in ('target_exists', 'target_matches', 'target_private', 'parent_safe')):
                fail('container_commit_unknown')
            report.update(status='legacy_guard_scope_restored', metadata_id=metadata_id, container=after)
            STAGE = 'private_repair_receipt'
            scope.private_write(directory / 'legacy-guard-scope-receipt.private.json', scope.canonical(report))
            scope.sync_directory(directory)
            return report
        except Exception:
            # A timeout, connection loss or unknown result after dispatch must
            # not be retried or automatically undone. Keep the private intent.
            fail('container_commit_unknown')


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args not in (['inspect'], ['restore']):
        fail('invalid_arguments')
    if os.geteuid() != 0:
        fail('root_required')
    os.umask(0o077)
    print(json.dumps(run(args[0]), sort_keys=True), flush=True)
    return 0


def safe_main(argv=None):
    try:
        return main(argv)
    except Exception as error:
        reason = error.reason if isinstance(error, ScopeRepairError) else 'legacy_guard_scope_failed'
        report = {'status': 'error', 'reason': reason, 'stage': STAGE}
        if isinstance(error, ScopeRepairError) and error.installed is not None:
            report.update(installed=error.installed, metadata_only_exact=False)
        if isinstance(error, ScopeRepairError) and error.container is not None:
            report['container'] = error.container
        print(json.dumps(report, sort_keys=True), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(safe_main())
