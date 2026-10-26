#!/usr/bin/env python3
"""Narrow the fixed probe JSON mode to 0600 without changing its bytes or service."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import urllib.parse
import uuid

AGENT = Path('/etc/xboard-extension-probe/agent.json')
PLAN_ROOT = Path('/root/xboard-upstream-recovery')
SERVICE = 'xboard-extension-probe.service'
STAGE = 'startup'
REASONS = {'root_required', 'invalid_arguments', 'service_inspection_failed', 'service_not_static_root',
           'service_not_loaded',
           'service_identity_changed', 'private_storage_invalid', 'operation_busy', 'agent_file_invalid',
           'agent_json_invalid', 'agent_contract_invalid', 'agent_changed', 'permission_change_outcome_unknown'}


class SecureProbeError(Exception):
    pass


def fail(reason):
    raise SecureProbeError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail('agent_json_invalid')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: fail('agent_json_invalid'))
    except (ValueError, TypeError):
        fail('agent_json_invalid')


def root_owned(info):
    return info.st_uid == 0


def private_directory(path, create=False):
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or not root_owned(info) or info.st_mode & 0o077:
        fail('private_storage_invalid')


def private_write(path, body):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as target:
            target.write(body)
            target.flush()
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
def operation_lock():
    private_directory(PLAN_ROOT, create=True)
    fd = os.open(PLAN_ROOT / 'scope-restore.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not root_owned(info) or stat.S_IMODE(info.st_mode) != 0o600:
            fail('private_storage_invalid')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('operation_busy')
        yield
    finally:
        os.close(fd)


def service_identity():
    try:
        result = subprocess.run(['systemctl', 'show', SERVICE, '--property=LoadState,User,Group,DynamicUser', '--no-pager'],
                                capture_output=True, timeout=5)
        if result.returncode or len(result.stdout) > 4096:
            fail('service_inspection_failed')
        values = {}
        for line in result.stdout.decode('utf-8').splitlines():
            key, value = line.split('=', 1)
            if key not in ('LoadState', 'User', 'Group', 'DynamicUser') or key in values:
                fail('service_inspection_failed')
            values[key] = value
        if set(values) != {'LoadState', 'User', 'Group', 'DynamicUser'}:
            fail('service_inspection_failed')
        if values['LoadState'] != 'loaded':
            fail('service_not_loaded')
        if values['User'] not in ('', 'root') or values['DynamicUser'] != 'no':
            fail('service_not_static_root')
        # Group is recorded and bound, but a static UID 0 can read its own 0600
        # file regardless of the configured primary group.
        return {'unit_loaded': True, 'user_is_root_or_empty': True, 'group_is_root_or_empty': values['Group'] in ('', 'root'),
                'dynamic_user_is_no': True, 'identity_sha256': sha(canonical(values))}
    except SecureProbeError:
        raise
    except Exception:
        fail('service_inspection_failed')


def identity(info):
    return {'device': info.st_dev, 'inode': info.st_ino, 'uid': info.st_uid, 'gid': info.st_gid}


def read_fd(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    with os.fdopen(fd, 'rb', closefd=False) as source:
        body = source.read(65537)
    if not 0 < len(body) <= 65536:
        fail('agent_file_invalid')
    return body


def validate_content(body):
    settings = parse_json(body)
    if (not isinstance(settings, dict) or set(settings) != {'panel_url', 'token'}
            or not isinstance(settings['token'], str) or len(settings['token']) != 64
            or not isinstance(settings['panel_url'], str)):
        fail('agent_contract_invalid')
    url = settings['panel_url']
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = (parsed.scheme == 'https' and parsed.hostname in ('taige.us', 'board.taige.us')
                 and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment
                 and parsed.path in ('', '/') and parsed.port in (None, 443)
                 and not any(ord(c) < 33 or ord(c) == 127 for c in url))
    except Exception:
        valid = False
    if not valid:
        fail('agent_contract_invalid')


def verify_unchanged(fd, original, body, expected_mode):
    current = os.fstat(fd)
    located = AGENT.lstat()
    if (not stat.S_ISREG(current.st_mode) or not stat.S_ISREG(located.st_mode) or not root_owned(current)
            or identity(current) != identity(original) or identity(located) != identity(original)
            or stat.S_IMODE(current.st_mode) != expected_mode or stat.S_IMODE(located.st_mode) != expected_mode
            or current.st_mtime_ns != original.st_mtime_ns or current.st_size != original.st_size):
        fail('agent_changed')
    if read_fd(fd) != body:
        fail('agent_changed')
    final = os.fstat(fd)
    if (identity(AGENT.lstat()) != identity(original) or final.st_size != original.st_size
            or final.st_mtime_ns != original.st_mtime_ns or stat.S_IMODE(final.st_mode) != expected_mode):
        fail('agent_changed')


def secure():
    global STAGE
    with operation_lock():
        STAGE = 'service_identity'
        service = service_identity()
        STAGE = 'fixed_agent_file'
        initial = AGENT.lstat()
        if not stat.S_ISREG(initial.st_mode) or not root_owned(initial) or not 0 < initial.st_size <= 65536:
            fail('agent_file_invalid')
        fd = os.open(AGENT, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        attempted = False
        try:
            original = os.fstat(fd)
            if not stat.S_ISREG(original.st_mode) or not root_owned(original) or identity(original) != identity(initial):
                fail('agent_file_invalid')
            body = read_fd(fd)
            validate_content(body)
            old_mode = stat.S_IMODE(original.st_mode)
            verify_unchanged(fd, original, body, old_mode)
            content_sha = sha(body)
            if old_mode == 0o600:
                return {'status': 'already_private', 'mode_class': 'private_0600', 'content_sha256': content_sha,
                        'permissions_changed': False, 'content_unchanged': True, 'inode_unchanged': True,
                        'owner_unchanged': True, 'service_static_root': True, 'service_restarted': False}
            metadata_id = uuid.uuid4().hex
            directory = PLAN_ROOT / metadata_id
            directory.mkdir(mode=0o700)
            record = {'schema': 1, 'operation': 'secure_probe_config', 'metadata_id': metadata_id,
                      'at': int(time.time()), 'old_mode': old_mode, 'content_sha256': content_sha,
                      'file_identity': identity(original), 'size': original.st_size,
                      'mtime_ns': original.st_mtime_ns, 'service_criteria': service}
            STAGE = 'private_metadata_storage'
            private_write(directory / 'probe-permission.private.json', canonical(record))
            sync_directory(directory)
            sync_directory(PLAN_ROOT)
            STAGE = 'pre_chmod_recheck'
            verify_unchanged(fd, original, body, old_mode)
            if service_identity() != service:
                fail('service_identity_changed')
            # Recheck once more after the bounded service query; no pathname
            # chmod can follow a replacement or symlink.
            verify_unchanged(fd, original, body, old_mode)
            STAGE = 'chmod_fixed_descriptor'
            attempted = True
            os.fchmod(fd, 0o600)
            os.fsync(fd)
            STAGE = 'post_chmod_recheck'
            verify_unchanged(fd, original, body, 0o600)
            result = {'status': 'secured', 'metadata_id': metadata_id, 'mode_class': 'private_0600',
                      'content_sha256': content_sha, 'permissions_changed': True, 'content_unchanged': True,
                      'inode_unchanged': True, 'owner_unchanged': True, 'service_static_root': True,
                      'service_restarted': False}
            STAGE = 'private_receipt_storage'
            private_write(directory / 'probe-permission-receipt.private.json', canonical(result))
            sync_directory(directory)
            return result
        except Exception:
            if attempted:
                fail('permission_change_outcome_unknown')
            raise
        finally:
            os.close(fd)


def main(argv=None):
    if (sys.argv[1:] if argv is None else argv):
        fail('invalid_arguments')
    if os.geteuid() != 0:
        fail('root_required')
    os.umask(0o077)
    result = secure()
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


def safe_main(argv=None):
    try:
        return main(argv)
    except Exception as error:
        reason = str(error) if isinstance(error, SecureProbeError) and str(error) in REASONS else 'secure_probe_config_failed'
        print(json.dumps({'status': 'error', 'reason': reason, 'stage': STAGE}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(safe_main())
