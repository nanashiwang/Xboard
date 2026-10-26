#!/usr/bin/env python3
"""Explicit bounded maintenance. No identity discovery or trust-baseline writes."""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

SIBLING = Path(__file__).resolve().parent
ALLOCATION_BYTES_SHA = '552b6a820def4a1a8c9e7775691205c1dc8a87ed9eeeb7a77943daf02c605769'
PLAN_ROOT = Path('/root/xboard-upstream-recovery')
PRIVATE_ROOT = Path('/root/Xboard/backups/upstream-20261022')
DATABASE = Path('/root/Xboard/.docker/.data/database.sqlite')
REPOSITORY = Path('/root/Xboard')
ACTIONS = ('withdraw', 'apply_hidden', 'publish', 'rollback')
HEX64 = re.compile(r'^[a-f0-9]{64}$')
KEY = re.compile(r'^U(?:0[1-9]|[1-3][0-9]|4[01])$')


class MaintenanceError(Exception):
    pass


def fail(reason):
    raise MaintenanceError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def parse_json(value):
    def pairs(items):
        result = {}
        for key, child in items:
            if key in result:
                fail('duplicate_json_key')
            result[key] = child
        return result
    return json.loads(value, object_pairs_hook=pairs, parse_constant=lambda _: fail('invalid_number'))


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def bytes_sha(value):
    return hashlib.sha256(value).hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def private_directory(path, create=False):
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        fail('private_directory_invalid')


def private_read(path, limit=20 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > limit:
            fail('private_file_invalid')
        with os.fdopen(fd, 'rb', closefd=False) as source:
            result = source.read(limit + 1)
        if len(result) > limit:
            fail('private_file_invalid')
        return result
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


@contextmanager
def exclusive_plan(path):
    fd = os.open(path / 'maintenance.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            fail('lock_invalid')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('maintenance_busy')
        yield
    finally:
        os.close(fd)


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        fail('unexpected_fields')


def unique(rows):
    if not isinstance(rows, list):
        fail('scope_invalid')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not KEY.fullmatch(row.get('key', '')) or row['key'] in result:
            fail('scope_invalid')
        result[row['key']] = row
    return result


def validate_scope(allocation, approved, manifest):
    scopes, approvals, mappings = unique(allocation.get('routes')), unique(approved), unique(manifest.get('routes'))
    expected = {'U%02d' % n for n in range(1, 42)}
    if allocation.get('machine_id') != 21 or manifest.get('machine_id') != 21 or any(set(x) != expected for x in (scopes, approvals, mappings)):
        fail('scope_invalid')
    for n in range(1, 42):
        key = 'U%02d' % n
        for rows in (scopes, approvals, mappings):
            if type(rows[key].get('backend_id')) is not int or type(rows[key].get('public_id')) is not int or rows[key]['backend_id'] != 357 + n * 2 or rows[key]['public_id'] != 358 + n * 2:
                fail('scope_invalid')
    return scopes, approvals


def selection_value(value):
    if not isinstance(value, dict) or not value or len(value) > 41:
        fail('selection_invalid')
    for key, commitment in value.items():
        if not KEY.fullmatch(key) or (commitment is not None and (not isinstance(commitment, str) or not HEX64.fullmatch(commitment))):
            fail('selection_invalid')
    return dict(sorted(value.items()))


def execution_plan_id(rows):
    fields = ('key', 'backend_id', 'public_id', 'original_state_sha256', 'candidate_digest')
    bound = [{field: row[field] for field in fields} for row in sorted(rows, key=lambda row: row['key'])]
    return digest({'schema': 1, 'machine_id': 21, 'routes': bound})


def outbound_settings(state):
    entries = json.loads(state['backend']['custom_outbounds'])
    if not isinstance(entries, list) or len(entries) != 1:
        fail('outbound_shape_invalid')
    settings = entries[0]['settings']
    return json.loads(settings) if isinstance(settings, str) else settings


def selected_rows(plan, selection, scopes, approvals, operation, now):
    candidates = unique(plan.get('routes'))
    if set(candidates) != set(scopes):
        fail('plan_scope_invalid')
    result = []
    for key, commitment in selection.items():
        row, scope = candidates[key], scopes[key]
        if row.get('approved') != approvals[key]:
            fail('approved_row_drift')
        snap = row.get('snapshot', {})
        state = snap.get('state')
        if not isinstance(state, dict) or snap.get('state_sha256') != digest(state):
            fail('snapshot_digest_mismatch')
        if state['backend'].get('id') != scope['backend_id'] or state['public'].get('id') != scope['public_id'] or state['backend'].get('machine_id') != 21 or state['public'].get('parent_id') != scope['backend_id']:
            fail('snapshot_scope_invalid')
        identity = None
        if commitment is not None:
            matches = [c for c in row.get('candidates', []) if c.get('candidate_digest') == commitment]
            if len(matches) != 1:
                fail('candidate_not_unique')
            candidate = matches[0]
            identity = candidate.get('identity')
            exact(identity, ('key', 'ip', 'port', 'sni', 'pin'))
            if digest(identity) != commitment or identity['key'] != key:
                fail('candidate_digest_mismatch')
            address = ipaddress.ip_address(identity['ip'])
            if not address.is_global or address.is_multicast or address.is_reserved:
                fail('candidate_address_invalid')
            settings = outbound_settings(state)
            tls = settings.get('tls', {})
            if type(identity['port']) is not int or settings.get('server_port') != identity['port'] or tls.get('server_name') != identity['sni'] or tls.get('enabled') is not True or tls.get('insecure') is not False:
                fail('candidate_contract_invalid')
            if operation != 'rollback':
                if candidate.get('certificate_time_valid') is not True or type(candidate.get('not_before')) not in (int, float) or type(candidate.get('not_after')) not in (int, float) or not math.isfinite(candidate['not_before']) or not math.isfinite(candidate['not_after']) or not candidate['not_before'] <= now <= candidate['not_after']:
                    fail('candidate_certificate_expired')
            if scope['upstream_type'] == 'vless':
                if 'certificate_public_key_sha256' in tls:
                    fail('ca_boundary_changed')
                # Observation pin is evidence, not a new CA pin policy.
                identity = dict(identity, pin=None)
            else:
                pin = identity.get('pin')
                try:
                    valid = isinstance(pin, str) and base64.b64encode(base64.b64decode(pin, validate=True)).decode() == pin and len(base64.b64decode(pin)) == 32
                except Exception:
                    valid = False
                if not valid:
                    fail('pin_invalid')
                old_pins = tls.get('certificate_public_key_sha256')
                if not isinstance(old_pins, list) or len(old_pins) != 1:
                    fail('pin_shape_invalid')
                old_matches = pin == old_pins[0]
                if candidate.get('old_pin_matches') is not old_matches:
                    fail('candidate_role_mismatch')
                if not old_matches and candidate.get('source_dns_endpoint') is not True:
                    fail('new_pin_requires_source_endpoint')
        elif operation in ('apply_hidden', 'publish'):
            fail('no_approved_candidate')
        result.append({'key': key, 'backend_id': scope['backend_id'], 'public_id': scope['public_id'],
                       'original_state': state, 'original_state_sha256': digest(state),
                       'identity': identity, 'candidate_digest': digest(identity), 'expected_sha256': digest(state)})
    return result


def verify_source(plan, selection, proxies, usage, now):
    if usage.get('expire', 0) <= now + 300 or usage.get('total', 0) <= usage.get('upload', 0) + usage.get('download', 0):
        fail('source_quota_or_expiry')
    source_rows = unique(plan['routes'])
    names = {}
    for proxy in proxies:
        if isinstance(proxy, dict):
            names.setdefault(proxy.get('name'), []).append(proxy)
    for key in selection:
        row = source_rows[key]
        source = row.get('source')
        observed = row.get('observed_source_sha', digest(source))
        if not isinstance(source, dict) or observed != digest(source):
            fail('prepared_source_invalid')
        matches = names.get(row['approved']['source_name'], [])
        if len(matches) != 1 or digest(matches[0]) != observed:
            fail('source_fingerprint_changed')


class DockerBackend:
    def __init__(self, sibling=SIBLING, private_root=PRIVATE_ROOT):
        self.sibling = sibling
        self.private_root = private_root
        self.manifest_bytes = None
        self.container = None
        self.directory = None

    def run(self, command, body=None, timeout=60):
        try:
            result = subprocess.run(command, cwd=REPOSITORY, input=body, capture_output=True, timeout=timeout)
        except Exception:
            fail('container_execution_uncertain')
        if result.returncode or len(result.stdout) > 20 * 1024 * 1024:
            fail('container_execution_failed')
        return result.stdout

    def __enter__(self):
        # A container rebuild may remove storage/app. The durable host file is
        # mandatory; validate it before transferring a private copy anywhere.
        private_directory(self.private_root)
        try:
            self.manifest_bytes = private_read(self.private_root / 'manifest.private')
        except FileNotFoundError:
            fail('host_manifest_missing')
        allocation_bytes = (self.sibling / 'allocation.json').read_bytes()
        if bytes_sha(allocation_bytes) != ALLOCATION_BYTES_SHA:
            fail('allocation_drift')
        validate_scope(parse_json(allocation_bytes), parse_json(private_read(self.private_root / 'approved.private')),
                       parse_json(self.manifest_bytes))
        try:
            self.container = self.run(['docker', 'compose', 'ps', '-q', 'xboard']).decode().strip()
            if not re.fullmatch(r'[a-f0-9]{12,64}', self.container):
                fail('container_identity_invalid')
            directory = self.run(['docker', 'compose', 'exec', '-T', 'xboard', 'mktemp', '-d', '/tmp/xboard-upstream-maintain.XXXXXX']).decode().strip()
            if not re.fullmatch(r'/tmp/xboard-upstream-maintain\.[A-Za-z0-9]{6,16}', directory):
                fail('container_directory_invalid')
            self.directory = directory
            self.run(['docker', 'compose', 'exec', '-T', 'xboard', 'chmod', '700', self.directory])
            for name in ('recovery.php', 'allocation.json'):
                self.run(['docker', 'cp', str(self.sibling / name), self.container + ':' + self.directory + '/' + name])
            # No private data in argv or a publicly printed subprocess result.
            program = '$f=fopen($argv[1],"x");if(!$f||!chmod($argv[1],0600)){exit(1);}$n=stream_copy_to_stream(STDIN,$f,20971521);if($n===false||$n>20971520||!fflush($f)){exit(1);}fclose($f);'
            self.run(['docker', 'compose', 'exec', '-T', 'xboard', 'php', '-r', program,
                      self.directory + '/manifest.private'], self.manifest_bytes)
            return self
        except Exception:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, *exc):
        if self.directory:
            try:
                self.run(['docker', 'compose', 'exec', '-T', 'xboard', 'rm', '-f',
                          self.directory + '/manifest.private', self.directory + '/recovery.php', self.directory + '/allocation.json'])
                self.run(['docker', 'compose', 'exec', '-T', 'xboard', 'rmdir', self.directory])
            except Exception:
                # Never hide the original mutation/setup exception. After a
                # successful action, surface cleanup failure without replaying it.
                if not exc or exc[0] is None:
                    fail('private_temp_cleanup_failed')
            finally:
                self.manifest_bytes = None

    def manifest(self):
        if self.manifest_bytes is None:
            fail('host_manifest_unloaded')
        return self.manifest_bytes

    def snapshot(self, keys):
        raw = self.run(['docker', 'compose', 'exec', '-T', 'xboard', 'php', self.directory + '/recovery.php', '--private-snapshot'], canonical({'schema': 1, 'keys': keys}))
        data = json.loads(raw)
        if data.get('schema') != 1 or data.get('private') is not True or data.get('machine_id') != 21:
            fail('snapshot_failed')
        return data['routes']

    def mutate(self, request):
        raw = self.run(['docker', 'compose', 'exec', '-T', 'xboard', 'php', self.directory + '/recovery.php'], canonical(request))
        return json.loads(raw)


def current_hashes(backend, rows):
    snapshots = unique(backend.snapshot([r['key'] for r in rows]))
    if set(snapshots) != {r['key'] for r in rows}:
        fail('snapshot_scope_invalid')
    result = {}
    for row in rows:
        found = snapshots[row['key']]
        if found.get('backend_id') != row['backend_id'] or found.get('public_id') != row['public_id'] or found.get('state_sha256') != digest(found.get('state')):
            fail('snapshot_digest_mismatch')
        result[row['key']] = found['state_sha256']
    return result


def safe_response(response, action, execution, rows):
    exact(response, ('schema', 'action', 'plan_id', 'routes'))
    if response['schema'] != 1 or response['action'] != action or response['plan_id'] != execution:
        fail('action_response_invalid')
    found = unique(response['routes'])
    if set(found) != {r['key'] for r in rows}:
        fail('action_response_invalid')
    for row in rows:
        answer = found[row['key']]
        exact(answer, ('key', 'backend_id', 'public_id', 'state_sha256'))
        if answer['backend_id'] != row['backend_id'] or answer['public_id'] != row['public_id'] or not isinstance(answer['state_sha256'], str) or not HEX64.fullmatch(answer['state_sha256']):
            fail('action_response_invalid')
    return {key: row['state_sha256'] for key, row in found.items()}


class Driver:
    def __init__(self, backend, plan_root=PLAN_ROOT, private_root=PRIVATE_ROOT, sibling=SIBLING,
                 database=DATABASE, fetch=None, backup=None, clock=time.time):
        self.backend, self.plan_root, self.private_root, self.sibling = backend, plan_root, private_root, sibling
        self.database, self.clock = database, clock
        self.fetch = fetch or self.fetch_live
        self.backup = backup or self.backup_live

    def fetch_live(self):
        private_read(self.private_root / 'source-url.secret')
        guard = load_module('maintenance_metadata_guard', self.sibling / 'guard.py')
        return guard.fetch_subscription(self.private_root)

    def backup_live(self, directory):
        path = self.sibling / 'backup-database.py'
        if not path.exists():
            path = self.sibling.parent / 'production/backup-database.py'
        helper = load_module('maintenance_online_backup', path)
        path = helper.backup_database(self.database, directory)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            fail('backup_permissions_invalid')
        checksum = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                checksum.update(chunk)
        return {'database_file': path.name, 'database_sha256': checksum.hexdigest()}

    def run(self, plan_id, plan_sha, selection, operation):
        if not re.fullmatch(r'[a-f0-9]{32}', plan_id) or not HEX64.fullmatch(plan_sha) or operation not in ACTIONS:
            fail('arguments_invalid')
        selection = selection_value(selection)
        private_directory(self.plan_root)
        directory = self.plan_root / plan_id
        private_directory(directory)
        with exclusive_plan(directory):
            return self.locked(directory, plan_id, plan_sha, selection, operation)

    def locked(self, directory, plan_id, plan_sha, selection, operation):
        body = private_read(directory / 'plan.private.json')
        if bytes_sha(body) != plan_sha:
            fail('plan_bytes_mismatch')
        plan = parse_json(body)
        now = self.clock()
        if plan.get('schema') != 1 or plan.get('plan_id') != plan_id or type(plan.get('prepared_at')) is not int:
            fail('plan_schema_invalid')
        if operation != 'rollback' and (plan['prepared_at'] > now + 60 or now - plan['prepared_at'] > 7200):
            fail('plan_expired')
        allocation_bytes = (self.sibling / 'allocation.json').read_bytes()
        allocation = json.loads(allocation_bytes)
        if bytes_sha(allocation_bytes) != ALLOCATION_BYTES_SHA or digest(allocation) != plan.get('allocation_sha256'):
            fail('allocation_drift')
        approved_bytes = private_read(self.private_root / 'approved.private')
        if bytes_sha(approved_bytes) != plan.get('approved_file_sha256'):
            fail('approved_file_drift')
        approved = json.loads(approved_bytes)
        manifest_bytes = self.backend.manifest()
        if bytes_sha(manifest_bytes) != plan.get('manifest_file_sha256'):
            fail('manifest_file_drift')
        scopes, approvals = validate_scope(allocation, approved, json.loads(manifest_bytes))
        rows = selected_rows(plan, selection, scopes, approvals, operation, now)
        execution = execution_plan_id(rows)
        execution_dir = directory / ('maintenance-' + execution)
        private_directory(execution_dir, create=True)
        receipts = []
        for action in ACTIONS:
            intent = execution_dir / ('intent-' + action + '.private.json')
            receipt = execution_dir / ('receipt-' + action + '.private.json')
            if intent.exists() and not receipt.exists():
                fail('previous_outcome_unknown')
            if receipt.exists():
                saved = json.loads(private_read(receipt))
                exact(saved, ('schema', 'prepare_plan_id', 'prepare_plan_sha256', 'selection_sha256', 'response', 'at'))
                if saved['schema'] != 1 or saved['prepare_plan_id'] != plan_id or saved['prepare_plan_sha256'] != plan_sha or saved['selection_sha256'] != digest(selection):
                    fail('receipt_binding_mismatch')
                hashes = safe_response(saved['response'], action, execution, rows)
                receipts.append((action, saved, hashes))
        stages = [r[0] for r in receipts]
        if stages not in ([], ['withdraw'], ['withdraw', 'apply_hidden'], ['withdraw', 'apply_hidden', 'publish'],
                          ['withdraw', 'rollback'], ['withdraw', 'apply_hidden', 'rollback'], ['withdraw', 'apply_hidden', 'publish', 'rollback']):
            fail('receipt_phase_invalid')
        current = current_hashes(self.backend, rows)
        if receipts:
            last, _, expected = receipts[-1]
            if current != expected:
                fail('current_state_drift')
            if last == operation:
                return {'status': 'already_applied', 'operation': operation, 'prepare_plan_id': plan_id,
                        'execution_plan_id': execution, 'routes': receipts[-1][1]['response']['routes']}
            allowed = {'withdraw': ('apply_hidden', 'rollback'), 'apply_hidden': ('publish', 'rollback'), 'publish': ('rollback',), 'rollback': ()}
            if operation not in allowed[last]:
                fail('operation_phase_invalid')
        else:
            if operation != 'withdraw':
                fail('withdraw_required')
            expected = {row['key']: row['original_state_sha256'] for row in rows}
            if current != expected:
                fail('current_state_drift')
        if operation != 'rollback':
            try:
                proxies, usage = self.fetch()
                verify_source(plan, selection, proxies, usage, now)
            except MaintenanceError:
                raise
            except Exception:
                fail('source_fetch_failed')
        if not receipts:
            backup_record = execution_dir / 'backup.private.json'
            if backup_record.exists():
                fail('incomplete_previous_backup')
            backups = execution_dir / 'backup'
            private_directory(backups, create=True)
            # Must finish the consistent online DB snapshot before any mutation.
            try:
                backup_result = self.backup(backups)
            except Exception:
                fail('backup_failed')
            private_write(backups / 'approved.private', approved_bytes)
            pin_path = self.private_root / 'pinned.private'
            if pin_path.exists():
                private_write(backups / 'pinned.private', private_read(pin_path))
            private_write(backups / 'manifest.private', manifest_bytes)
            private_write(backups / 'original-fields.private.json', canonical([{'key': r['key'], 'state': r['original_state']} for r in rows]))
            private_write(backup_record, canonical({'schema': 1, 'prepare_plan_id': plan_id, 'execution_plan_id': execution, 'at': now, **backup_result}))
        for row in rows:
            row['expected_sha256'] = expected[row['key']]
        request = {'schema': 1, 'action': operation, 'plan_id': execution, 'routes': rows}
        private_write(execution_dir / ('request-' + operation + '.private.json'), canonical(request))
        private_write(execution_dir / ('intent-' + operation + '.private.json'), canonical({'schema': 1, 'request_sha256': digest(request), 'at': now}))
        try:
            response = self.backend.mutate(request)
            after = safe_response(response, operation, execution, rows)
            if current_hashes(self.backend, rows) != after:
                fail('post_action_state_mismatch')
            saved = {'schema': 1, 'prepare_plan_id': plan_id, 'prepare_plan_sha256': plan_sha,
                     'selection_sha256': digest(selection), 'response': response, 'at': self.clock()}
            private_write(execution_dir / ('receipt-' + operation + '.private.json'), canonical(saved))
        except Exception:
            # Intent without receipt permanently blocks autonomous replay. A root
            # operator must inspect the private state; never infer no commit.
            fail('action_outcome_unknown')
        return {'status': 'applied', 'operation': operation, 'prepare_plan_id': plan_id,
                'execution_plan_id': execution, 'routes': response['routes']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-id', required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--selection-json', required=True)
    parser.add_argument('--operation', required=True, choices=ACTIONS)
    args = parser.parse_args()
    if os.geteuid() != 0:
        fail('root_required')
    os.umask(0o077)
    selection = parse_json(args.selection_json)
    with DockerBackend() as backend:
        answer = Driver(backend).run(args.plan_id, args.plan_sha256, selection, args.operation)
    print(json.dumps(answer, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except MaintenanceError as error:
        print(json.dumps({'status': 'rejected', 'reason': str(error)}), flush=True)
        raise SystemExit(1)
    except Exception:
        print(json.dumps({'status': 'rejected', 'reason': 'maintenance_failed'}), flush=True)
        raise SystemExit(1)
