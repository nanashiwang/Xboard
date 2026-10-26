#!/usr/bin/env python3
"""Explicit audit / restore of a missing original 41-route scope manifest only.

Never writes DB, approved identities, pins, source URL, guard state or visibility.
The audit fixes current evidence for human review; it does not prove historical
approval by itself. Restore requires the exact private audit ID and byte hash.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

SIBLING = Path(__file__).resolve().parent
PRIVATE_ROOT = Path('/root/Xboard/backups/upstream-20261022')
PLAN_ROOT = Path('/root/xboard-upstream-recovery')
ALLOCATION_BYTES_SHA = '552b6a820def4a1a8c9e7775691205c1dc8a87ed9eeeb7a77943daf02c605769'
HEX64 = re.compile(r'^[a-f0-9]{64}$')
ID32 = re.compile(r'^[a-f0-9]{32}$')
STAGE = 'startup'
REASONS = {'invalid_arguments', 'root_required', 'private_directory_invalid', 'private_file_invalid',
           'duplicate_json_key', 'invalid_json', 'scope_restore_busy', 'manifest_exists', 'scope_invalid',
           'allocation_hash_mismatch', 'snapshot_invalid', 'audit_hash_mismatch', 'audit_invalid',
           'audit_expired', 'approved_file_drift', 'snapshot_drift', 'restore_outcome_unknown'}


class ScopeError(Exception):
    pass


def fail(reason):
    raise ScopeError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def bytes_sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return bytes_sha(canonical(value))


def parse_json(value):
    def unique(items):
        result = {}
        for key, item in items:
            if key in result:
                fail('duplicate_json_key')
            result[key] = item
        return result
    try:
        return json.loads(value, object_pairs_hook=unique, parse_constant=lambda _: fail('invalid_json'))
    except (ValueError, TypeError):
        fail('invalid_json')


def private_directory(path, create=False, require_private=True):
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = path.lstat()
    mask = 0o077 if require_private else 0o022
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & mask:
        fail('private_directory_invalid')


def private_read(path, limit=20 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or not 0 < info.st_size <= limit):
            fail('private_file_invalid')
        with os.fdopen(fd, 'rb', closefd=False) as source:
            value = source.read(limit + 1)
        if len(value) > limit:
            fail('private_file_invalid')
        return value
    finally:
        os.close(fd)


def private_write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as output:
            output.write(value)
            output.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def root_lock():
    private_directory(PLAN_ROOT, create=True)
    fd = os.open(PLAN_ROOT / 'scope-restore.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            fail('private_file_invalid')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('scope_restore_busy')
        yield
    finally:
        os.close(fd)


def require_missing_manifest():
    # lstat distinguishes true ENOENT from permission/IO errors and sees dangling
    # symlinks. No existing entry can be interpreted as permission to overwrite.
    private_directory(PRIVATE_ROOT, require_private=False)
    try:
        (PRIVATE_ROOT / 'manifest.private').lstat()
    except FileNotFoundError:
        return
    fail('manifest_exists')


def load_inputs():
    global STAGE
    STAGE = 'approved_storage'
    approved_bytes = private_read(PRIVATE_ROOT / 'approved.private')
    approved = parse_json(approved_bytes)
    STAGE = 'allocation_scope'
    allocation_bytes = (SIBLING / 'allocation.json').read_bytes()
    if bytes_sha(allocation_bytes) != ALLOCATION_BYTES_SHA:
        fail('allocation_hash_mismatch')
    allocation = parse_json(allocation_bytes)
    if not isinstance(allocation, dict) or allocation.get('machine_id') != 21 or not isinstance(approved, list):
        fail('scope_invalid')
    rows = allocation.get('routes')
    if not isinstance(rows, list) or len(rows) != 41 or len(approved) != 41:
        fail('scope_invalid')
    scopes, approvals = {}, {}
    for values, target in ((rows, scopes), (approved, approvals)):
        for row in values:
            if not isinstance(row, dict) or not isinstance(row.get('key'), str) or row['key'] in target:
                fail('scope_invalid')
            target[row['key']] = row
    expected = {'U%02d' % n for n in range(1, 42)}
    if set(scopes) != expected or set(approvals) != expected:
        fail('scope_invalid')
    manifest_rows, source_names = [], set()
    for number in range(1, 42):
        key = 'U%02d' % number
        for row in (scopes[key], approvals[key]):
            if (type(row.get('backend_id')) is not int or row['backend_id'] != 357 + number * 2
                    or type(row.get('public_id')) is not int or row['public_id'] != 358 + number * 2):
                fail('scope_invalid')
        approval = approvals[key]
        if (not isinstance(approval.get('source_name'), str) or not approval['source_name']
                or not isinstance(approval.get('source_sha256'), str) or not HEX64.fullmatch(approval['source_sha256'])):
            fail('scope_invalid')
        if approval['source_name'] in source_names:
            fail('scope_invalid')
        source_names.add(approval['source_name'])
        manifest_rows.append({field: scopes[key][field] for field in ('key', 'backend_id', 'public_id')})
    return allocation, approved, approved_bytes, {'machine_id': 21, 'routes': manifest_rows}


def load_prepare():
    spec = importlib.util.spec_from_file_location('scope_prepare', SIBLING / 'prepare.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_snapshot(prepare, allocation, approved, snapshot):
    try:
        prepare.validate_scope(allocation, approved, snapshot)
        state_hashes = {}
        for row in snapshot['routes']:
            state = row['state']
            if not isinstance(state, dict) or set(state) != {'backend', 'public'} or digest(state) != row.get('state_sha256'):
                fail('snapshot_invalid')
            state_hashes[row['key']] = row['state_sha256']
        return state_hashes
    except ScopeError:
        raise
    except Exception:
        fail('snapshot_invalid')


def read_snapshot(prepare, allocation, approved, manifest):
    global STAGE
    STAGE = 'database_snapshot'
    snapshot = prepare.snapshot_database(allocation, canonical(manifest))
    return snapshot, validate_snapshot(prepare, allocation, approved, snapshot)


def audit(prepare=None, now=None):
    global STAGE
    prepare = prepare or load_prepare()
    with root_lock():
        STAGE = 'manifest_missing_check'
        require_missing_manifest()
        allocation, approved, approved_bytes, manifest = load_inputs()
        snapshot, hashes = read_snapshot(prepare, allocation, approved, manifest)
        require_missing_manifest()
        if private_read(PRIVATE_ROOT / 'approved.private') != approved_bytes:
            fail('approved_file_drift')
        plan_id = uuid.uuid4().hex
        prepared_at = int(time.time() if now is None else now)
        plan = {'schema': 1, 'kind': 'scope_restore_audit', 'plan_id': plan_id, 'prepared_at': prepared_at,
                'missing_before': True, 'approved_file_sha256': bytes_sha(approved_bytes),
                'allocation_file_sha256': ALLOCATION_BYTES_SHA, 'manifest_file_sha256': digest(manifest),
                'manifest': manifest, 'snapshot': snapshot}
        STAGE = 'audit_storage'
        directory = PLAN_ROOT / plan_id
        directory.mkdir(mode=0o700)
        body = canonical(plan)
        private_write(directory / 'scope-audit.private.json', body)
        sync_directory(directory)
        sync_directory(PLAN_ROOT)
        approvals = {row['key']: row for row in approved}
        report = {'status': 'scope_audited', 'schema': 1, 'plan_id': plan_id, 'plan_sha256': bytes_sha(body),
                  'approved_file_sha256': bytes_sha(approved_bytes), 'allocation_file_sha256': ALLOCATION_BYTES_SHA,
                  'manifest_file_sha256': digest(manifest), 'manifest_missing': True,
                  'database_mutated': False, 'public_key_baseline_mutated': False, 'source_baseline_mutated': False,
                  'routes': [{'key': key, 'source_name_sha256': bytes_sha(approvals[key]['source_name'].encode()),
                              'approved_source_sha256': approvals[key]['source_sha256'], 'state_sha256': hashes[key]}
                             for key in sorted(hashes)]}
        private_write(directory / 'scope-report.json', canonical(report))
        return report


def publish_manifest(body):
    """Atomic full-content publication without replacement, even under a race."""
    require_missing_manifest()
    temporary = PRIVATE_ROOT / ('.scope-manifest-' + uuid.uuid4().hex + '.tmp')
    target = PRIVATE_ROOT / 'manifest.private'
    linked = False
    try:
        private_write(temporary, body)
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError:
            fail('manifest_exists')
        linked = True
        sync_directory(PRIVATE_ROOT)
        if private_read(target) != body:
            fail('restore_outcome_unknown')
    except Exception:
        if linked:
            fail('restore_outcome_unknown')
        raise
    finally:
        try:
            if os.path.lexists(temporary):
                temporary.unlink()
        except Exception:
            if linked:
                fail('restore_outcome_unknown')
            raise
    return bytes_sha(body)


def restore(plan_id, plan_sha256, prepare=None, now=None):
    global STAGE
    if not isinstance(plan_id, str) or not ID32.fullmatch(plan_id) or not isinstance(plan_sha256, str) or not HEX64.fullmatch(plan_sha256):
        fail('invalid_arguments')
    prepare = prepare or load_prepare()
    with root_lock():
        STAGE = 'manifest_missing_check'
        require_missing_manifest()
        directory = PLAN_ROOT / plan_id
        private_directory(directory)
        STAGE = 'audit_plan_read'
        body = private_read(directory / 'scope-audit.private.json')
        if bytes_sha(body) != plan_sha256:
            fail('audit_hash_mismatch')
        plan = parse_json(body)
        fields = {'schema', 'kind', 'plan_id', 'prepared_at', 'missing_before', 'approved_file_sha256',
                  'allocation_file_sha256', 'manifest_file_sha256', 'manifest', 'snapshot'}
        timestamp = time.time() if now is None else now
        if (not isinstance(plan, dict) or set(plan) != fields or type(plan['schema']) is not int or plan['schema'] != 1
                or plan['kind'] != 'scope_restore_audit' or plan['plan_id'] != plan_id or plan['missing_before'] is not True
                or type(plan['prepared_at']) is not int):
            fail('audit_invalid')
        if not 0 <= timestamp - plan['prepared_at'] <= 7200:
            fail('audit_expired')
        allocation, approved, approved_bytes, manifest = load_inputs()
        if bytes_sha(approved_bytes) != plan['approved_file_sha256']:
            fail('approved_file_drift')
        if (plan['allocation_file_sha256'] != ALLOCATION_BYTES_SHA or plan['manifest'] != manifest
                or plan['manifest_file_sha256'] != digest(manifest)):
            fail('audit_invalid')
        original_hashes = validate_snapshot(prepare, allocation, approved, plan['snapshot'])
        _, current_hashes = read_snapshot(prepare, allocation, approved, manifest)
        STAGE = 'snapshot_compare'
        if current_hashes != original_hashes:
            fail('snapshot_drift')
        require_missing_manifest()
        if private_read(PRIVATE_ROOT / 'approved.private') != approved_bytes:
            fail('approved_file_drift')
        intent = {'schema': 1, 'operation': 'restore_scope', 'plan_id': plan_id, 'plan_sha256': plan_sha256,
                  'missing_before': True, 'at': int(timestamp), 'approved_file_sha256': bytes_sha(approved_bytes),
                  'allocation_file_sha256': ALLOCATION_BYTES_SHA, 'manifest_file_sha256': digest(manifest),
                  'snapshot_state_sha256': current_hashes, 'database_mutated': False,
                  'public_key_baseline_mutated': False, 'source_baseline_mutated': False}
        STAGE = 'restore_intent_storage'
        private_write(directory / 'scope-restore.intent.private.json', canonical(intent))
        sync_directory(directory)
        STAGE = 'manifest_create'
        manifest_hash = publish_manifest(canonical(manifest))
        STAGE = 'restore_receipt_storage'
        report = {'status': 'scope_restored', 'schema': 1, 'plan_id': plan_id, 'plan_sha256': plan_sha256,
                  'manifest_file_sha256': manifest_hash, 'manifest_created': True,
                  'database_mutated': False, 'public_key_baseline_mutated': False,
                  'source_baseline_mutated': False, 'route_count': 41}
        try:
            private_write(directory / 'scope-restore.receipt.private.json', canonical(dict(intent, result=report)))
            sync_directory(directory)
        except Exception:
            fail('restore_outcome_unknown')
        return report


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        fail('invalid_arguments')


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument('operation', choices=('audit', 'restore'))
    parser.add_argument('--plan-id')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        fail('root_required')
    os.umask(0o077)
    if args.operation == 'audit':
        if args.plan_id is not None or args.plan_sha256 is not None:
            fail('invalid_arguments')
        result = audit()
    else:
        result = restore(args.plan_id, args.plan_sha256)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


def safe_main(argv=None):
    try:
        return main(argv)
    except Exception as error:
        reason = str(error) if isinstance(error, ScopeError) and str(error) in REASONS else 'scope_restore_failed'
        print(json.dumps({'status': 'error', 'reason': reason, 'stage': STAGE}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(safe_main())
