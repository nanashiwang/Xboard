#!/usr/bin/env python3
"""Explicitly accept U01 source.server metadata only; never update a pin or DB.

No endpoint, credential, source URL, scope, or replacement config CLI input.
A successful acceptance invalidates the old prepare plan: prepare again.
"""
import argparse
import copy
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

SIBLING = Path(__file__).resolve().parent
PRIVATE_ROOT = Path('/root/Xboard/backups/upstream-20261022')
PLAN_ROOT = Path('/root/xboard-upstream-recovery')
ALLOCATION_BYTES_SHA = '552b6a820def4a1a8c9e7775691205c1dc8a87ed9eeeb7a77943daf02c605769'
ID32 = re.compile(r'^[a-f0-9]{32}$')
HEX64 = re.compile(r'^[a-f0-9]{64}$')
KEYS = {'U%02d' % n for n in range(1, 42)}
STAGE = 'arguments'

class AcceptanceError(Exception):
    pass

def fail(reason):
    raise AcceptanceError(reason)

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()

def bytes_sha(value):
    return hashlib.sha256(value).hexdigest()

def digest(value):
    return bytes_sha(canonical(value))

def parse_json(value):
    def pairs(items):
        result = {}
        for key, child in items:
            if key in result:
                fail('duplicate_json_key')
            result[key] = child
        return result
    return json.loads(value, object_pairs_hook=pairs, parse_constant=lambda _: fail('invalid_json_number'))

def private_directory(path, create=False, strict=True):
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & (0o077 if strict else 0o022):
        fail('private_directory_invalid')

def private_read(path, limit=20 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or not 0 < info.st_size <= limit:
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
def lock(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            fail('lock_invalid')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('acceptance_busy')
        yield
    finally:
        os.close(fd)

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def rows_by_key(value):
    if not isinstance(value, list):
        fail('scope_invalid')
    result = {}
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get('key'), str) or row['key'] not in KEYS or row['key'] in result:
            fail('scope_invalid')
        result[row['key']] = row
    if set(result) != KEYS:
        fail('scope_invalid')
    return result

def validate_scope(allocation, approved, manifest):
    if not isinstance(allocation, dict) or not isinstance(manifest, dict) or allocation.get('machine_id') != 21 or manifest.get('machine_id') != 21:
        fail('scope_invalid')
    scopes, approvals, mapping = rows_by_key(allocation.get('routes')), rows_by_key(approved), rows_by_key(manifest.get('routes'))
    names = set()
    for n in range(1, 42):
        key = 'U%02d' % n
        for group in (scopes, approvals, mapping):
            row = group[key]
            if type(row.get('backend_id')) is not int or row['backend_id'] != 357 + 2 * n or type(row.get('public_id')) is not int or row['public_id'] != 358 + 2 * n:
                fail('scope_invalid')
        old = approvals[key]
        if not isinstance(old.get('source_name'), str) or not old['source_name'] or old['source_name'] in names or not isinstance(old.get('source_sha256'), str) or not HEX64.fullmatch(old['source_sha256']):
            fail('scope_invalid')
        names.add(old['source_name'])
    if scopes['U01'].get('upstream_type') != 'anytls':
        fail('scope_invalid')
    return scopes, approvals

def snapshot_hashes(prepare, allocation, approved, snapshot):
    try:
        prepare.validate_scope(allocation, approved, snapshot)
        rows = rows_by_key(snapshot['routes'])
        result = {}
        for key, row in rows.items():
            state = row.get('state')
            if not isinstance(state, dict) or set(state) != {'backend', 'public'} or digest(state) != row.get('state_sha256'):
                fail('snapshot_invalid')
            # Cross-check the raw state with the attested mapping/ownership, not
            # only the snapshot's human-readable summary fields.
            if any(state['backend'].get(k) != row['backend'].get(k) for k in ('id', 'machine_id')) or any(state['public'].get(k) != row['public'].get(k) for k in ('id', 'parent_id')):
                fail('snapshot_invalid')
            result[key] = row['state_sha256']
        return result
    except AcceptanceError:
        raise
    except Exception:
        fail('snapshot_invalid')

def exact_address_proof(prepare, guard, source, expected_new_sha, old, original_state):
    if not isinstance(source, dict) or guard.fingerprint(source) != expected_new_sha or source.get('name') != old['source_name'] or source.get('type') != 'anytls':
        fail('source_fingerprint_mismatch')
    if expected_new_sha == old['source_sha256']:
        fail('source_address_unchanged')
    try:
        settings = prepare.settings_for({'backend': original_state['backend']}, 'anytls')
        prepare.source_target(source, settings)
        if len(settings['tls']['certificate_public_key_sha256']) != 1 or not prepare.global_unicast(settings['server']):
            fail('source_contract_invalid')
    except AcceptanceError:
        raise
    except Exception:
        fail('source_contract_invalid')
    original = dict(source, server=settings['server'])
    if source.get('server') == original['server'] or guard.fingerprint(original) != old['source_sha256']:
        fail('not_exact_server_only_change')
    return {'old_source_sha256': old['source_sha256'], 'new_source_sha256': expected_new_sha, 'changed_fields': ['server']}

def validate_usage(usage, now):
    if (not isinstance(usage, dict) or any(type(usage.get(field)) is not int or usage[field] < 0
            for field in ('expire', 'total', 'upload', 'download')) or
            usage['expire'] <= now + 300 or usage['total'] <= usage['upload'] + usage['download']):
        fail('source_quota_or_expiry')

def atomic_approved_replace(path, expected, replacement):
    temporary = path.parent / ('.source-address-U01-' + uuid.uuid4().hex + '.tmp')
    published = False
    try:
        private_write(temporary, replacement)
        # Last comparison immediately before the one atomic approved-file write.
        if private_read(path) != expected:
            fail('approved_file_drift')
        os.replace(temporary, path)
        published = True
        sync_directory(path.parent)
        if private_read(path) != replacement:
            fail('accept_outcome_unknown')
    except Exception:
        if published:
            fail('accept_outcome_unknown')
        raise
    finally:
        if os.path.lexists(temporary):
            try:
                temporary.unlink()
            except Exception:
                fail('accept_outcome_unknown' if published else 'temporary_cleanup_failed')

class Driver:
    def __init__(self, private_root=PRIVATE_ROOT, plan_root=PLAN_ROOT, sibling=SIBLING, prepare=None, guard=None,
                 fetch=None, snapshot=None, clock=time.time):
        self.private_root, self.plan_root, self.sibling = private_root, plan_root, sibling
        self.prepare = prepare or load_module('accept_address_prepare', sibling / 'prepare.py')
        self.guard = guard or load_module('accept_address_guard', sibling / 'guard.py')
        self.fetch = fetch or self.fetch_live
        self.snapshot = snapshot or self.prepare.snapshot_database
        self.clock = clock

    def fetch_live(self):
        private_read(self.private_root / 'source-url.secret')
        return self.guard.fetch_subscription(self.private_root)

    def run(self, plan_id, plan_sha, key, expected_source_sha):
        if not isinstance(plan_id, str) or not ID32.fullmatch(plan_id) or not isinstance(plan_sha, str) or not HEX64.fullmatch(plan_sha) or key != 'U01' or not isinstance(expected_source_sha, str) or not HEX64.fullmatch(expected_source_sha):
            fail('arguments_invalid')
        private_directory(self.private_root, strict=False)
        private_directory(self.plan_root)
        directory = self.plan_root / plan_id
        private_directory(directory)
        with lock(self.plan_root / 'scope-restore.lock'):
            with lock(directory / 'maintenance.lock'):
                return self.locked(directory, plan_id, plan_sha, expected_source_sha)

    def locked(self, directory, plan_id, plan_sha, expected_source_sha):
        global STAGE
        STAGE = 'prepare_plan'
        body = private_read(directory / 'plan.private.json')
        if bytes_sha(body) != plan_sha:
            fail('plan_hash_mismatch')
        plan = parse_json(body)
        now = self.clock()
        if not isinstance(plan, dict) or plan.get('schema') != 1 or plan.get('plan_id') != plan_id or type(plan.get('prepared_at')) is not int or not math.isfinite(now) or not 0 <= now - plan['prepared_at'] <= 7200:
            fail('plan_invalid_or_expired')
        planned = rows_by_key(plan.get('routes'))
        operation = directory / 'source-address-U01'
        private_directory(operation, create=True)
        if os.path.lexists(operation / 'intent.private.json') and not os.path.lexists(operation / 'receipt.private.json'):
            fail('previous_outcome_unknown')
        if os.path.lexists(operation / 'receipt.private.json'):
            fail('acceptance_already_recorded')
        if any(operation.iterdir()):
            fail('incomplete_previous_preparation')
        STAGE = 'fixed_scope_inputs'
        allocation_bytes = (self.sibling / 'allocation.json').read_bytes()
        allocation = parse_json(allocation_bytes)
        if bytes_sha(allocation_bytes) != ALLOCATION_BYTES_SHA or digest(allocation) != plan.get('allocation_sha256'):
            fail('allocation_drift')
        approved_bytes = private_read(self.private_root / 'approved.private')
        manifest_bytes = private_read(self.private_root / 'manifest.private')
        if bytes_sha(approved_bytes) != plan.get('approved_file_sha256'):
            fail('approved_file_drift')
        if bytes_sha(manifest_bytes) != plan.get('manifest_file_sha256'):
            fail('manifest_drift')
        approved, manifest = parse_json(approved_bytes), parse_json(manifest_bytes)
        scopes, approvals = validate_scope(allocation, approved, manifest)
        for key in KEYS:
            if planned[key].get('approved') != approvals[key]:
                fail('approved_row_drift')
        baseline = {'machine_id': 21, 'routes': [planned[key]['snapshot'] for key in sorted(KEYS)]}
        original_hashes = snapshot_hashes(self.prepare, allocation, approved, baseline)
        original_state = planned['U01']['snapshot']['state']
        STAGE = 'current_database_state'
        actual = self.snapshot(allocation, manifest_bytes)
        if snapshot_hashes(self.prepare, allocation, approved, actual) != original_hashes:
            fail('database_state_drift')
        STAGE = 'fresh_source'
        try:
            proxies, usage = self.fetch()
        except Exception:
            fail('source_fetch_failed')
        validate_usage(usage, self.clock())
        if not isinstance(proxies, list):
            fail('source_invalid')
        matches = [row for row in proxies if isinstance(row, dict) and row.get('name') == approvals['U01']['source_name']]
        if len(matches) != 1:
            fail('source_missing_or_ambiguous')
        source = matches[0]
        if digest(planned['U01'].get('source')) != expected_source_sha or digest(source) != expected_source_sha:
            fail('source_fingerprint_mismatch')
        proof = exact_address_proof(self.prepare, self.guard, source, expected_source_sha, approvals['U01'], original_state)
        # Keep row order and every unrelated value/field, including unknown
        # historical metadata. Only U01.source_sha256 is eligible for mutation.
        updated = copy.deepcopy(approved)
        target = next(row for row in updated if row['key'] == 'U01')
        target['source_sha256'] = expected_source_sha
        restored = copy.deepcopy(updated)
        next(row for row in restored if row['key'] == 'U01')['source_sha256'] = approvals['U01']['source_sha256']
        if restored != approved:
            fail('unexpected_field_change')
        replacement = canonical(updated)
        request = {'schema': 1, 'operation': 'accept_source_address', 'key': 'U01', 'plan_id': plan_id,
                   'plan_sha256': plan_sha, 'expected_new_source_sha256': expected_source_sha,
                   'approved_file_sha256': bytes_sha(approved_bytes), 'new_approved_file_sha256': bytes_sha(replacement),
                   'manifest_file_sha256': bytes_sha(manifest_bytes), 'allocation_file_sha256': ALLOCATION_BYTES_SHA,
                   'snapshot_state_sha256': original_hashes, **proof}
        STAGE = 'private_backups'
        backup = operation / 'backup'
        private_directory(backup, create=True)
        private_write(backup / 'approved.private', approved_bytes)
        private_write(backup / 'manifest.private', manifest_bytes)
        private_write(operation / 'request.private.json', canonical(request))
        sync_directory(backup)
        sync_directory(operation)
        STAGE = 'final_state_and_input_check'
        final = self.snapshot(allocation, manifest_bytes)
        if snapshot_hashes(self.prepare, allocation, approved, final) != original_hashes:
            fail('database_state_drift')
        if private_read(directory / 'plan.private.json') != body:
            fail('plan_hash_mismatch')
        if private_read(self.private_root / 'manifest.private') != manifest_bytes:
            fail('manifest_drift')
        if private_read(self.private_root / 'approved.private') != approved_bytes:
            fail('approved_file_drift')
        final_time = self.clock()
        if type(final_time) not in (int, float) or not math.isfinite(final_time) or not 0 <= final_time - plan['prepared_at'] <= 7200:
            fail('plan_invalid_or_expired')
        validate_usage(usage, final_time)
        STAGE = 'intent_storage'
        private_write(operation / 'intent.private.json', canonical({'schema': 1, 'request_sha256': digest(request), 'at': self.clock()}))
        sync_directory(operation)
        result = {'status': 'source_address_accepted', 'schema': 1, 'key': 'U01', 'changed_fields': ['source_sha256'],
                  'proved_source_change_fields': ['server'], 'plan_id': plan_id, 'plan_sha256': plan_sha,
                  'old_source_sha256': proof['old_source_sha256'], 'new_source_sha256': expected_source_sha,
                  'old_approved_file_sha256': bytes_sha(approved_bytes), 'new_approved_file_sha256': bytes_sha(replacement),
                  'source_baseline_mutated': True, 'public_key_baseline_mutated': False, 'database_mutated': False,
                  'prepare_plan_invalidated': True, 'requires_reprepare': True}
        try:
            STAGE = 'atomic_approved_update'
            atomic_approved_replace(self.private_root / 'approved.private', approved_bytes, replacement)
            STAGE = 'receipt_storage'
            private_write(operation / 'receipt.private.json', canonical({'schema': 1, 'request_sha256': digest(request), 'result': result, 'at': self.clock()}))
            sync_directory(operation)
        except Exception:
            fail('accept_outcome_unknown')
        return result

class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        fail('arguments_invalid')

def main(argv=None):
    global STAGE
    parser = SafeParser(description=__doc__)
    parser.add_argument('--plan-id', required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--key', required=True, choices=('U01',))
    parser.add_argument('--expected-source-sha256', required=True)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        fail('root_required')
    os.umask(0o077)
    report = Driver().run(args.plan_id, args.plan_sha256, args.key, args.expected_source_sha256)
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0

def safe_main(argv=None):
    try:
        return main(argv)
    except AcceptanceError as error:
        print(json.dumps({'status': 'rejected', 'reason': str(error), 'stage': STAGE}), flush=True)
        return 1
    except Exception:
        print(json.dumps({'status': 'rejected', 'reason': 'source_acceptance_failed', 'stage': STAGE}), flush=True)
        return 1

if __name__ == '__main__':
    raise SystemExit(safe_main())
