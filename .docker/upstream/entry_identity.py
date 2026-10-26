#!/usr/bin/env python3
"""Bounded, certificate-only identity checks from the real dual-stack ingress.

The panel sends its approved mappings over a dedicated forced-command SSH key.
No subscription password, authentication bytes, observed key, or arbitrary command
crosses this interface. Missing/invalid responses fail every requested identity.
"""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

import guard

MAX_BYTES = 65536
HOST = '143.203.200.5'
REMOTE_ROOT = Path('/etc/xboard-upstream-identity')
ALLOCATION = Path(__file__).with_name('allocation.json')


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def decode(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('identity_message_too_large')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_identity_field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


def request_rows(request, allocation):
    if (not isinstance(request, dict) or set(request) != {'schema', 'nonce', 'mappings'}
            or type(request['schema']) is not int or request['schema'] != 1
            or not isinstance(request['nonce'], str) or not re.fullmatch('[a-f0-9]{64}', request['nonce'])
            or not isinstance(request['mappings'], list) or not 1 <= len(request['mappings']) <= 28):
        raise ValueError('invalid_identity_request')
    scope = {r['key']: r for r in allocation['routes'] if r['upstream_type'] == 'anytls'}
    seen = set()
    approved = []
    for row in request['mappings']:
        if (not isinstance(row, dict) or set(row) != {'key', 'ip', 'port', 'sni', 'pin'}
                or not isinstance(row['key'], str) or row['key'] not in scope or row['key'] in seen):
            raise ValueError('invalid_identity_scope')
        guard.validate_identity(row)
        # The worker cannot be used to contact loopback or private infrastructure.
        if not ipaddress.ip_address(row['ip']).is_global:
            raise ValueError('non_public_identity_target')
        seen.add(row['key'])
        approved.append(guard.route_result(scope[row['key']]))
    return approved


def serve(request, allocation, probe=None):
    approved = request_rows(request, allocation)
    checks = guard.evaluate_identity(approved, allocation, request['mappings'], probe)
    return {'schema': 1, 'nonce': request['nonce'],
            'request_sha256': hashlib.sha256(encode(request)).hexdigest(),
            'checked_at': int(time.time()), 'identity_checks': checks}


def ssh_exchange(request):
    args = ['ssh', '-F', '/dev/null', '-T', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'GlobalKnownHostsFile=/dev/null',
            '-o', 'UserKnownHostsFile=' + str(REMOTE_ROOT / 'known_hosts'),
            '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
            '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes', '-o', 'LogLevel=ERROR',
            '-i', str(REMOTE_ROOT / 'id_ed25519'), 'xboard-identity@' + HOST]
    # Worker stdout is bounded by its fixed scope; no stderr is exposed.
    result = subprocess.run(args, input=encode(request), capture_output=True, timeout=40,
                            env={k: v for k, v in os.environ.items() if k not in ('SSH_AUTH_SOCK', 'SSH_AGENT_PID')})
    if result.returncode != 0 or result.stderr or len(result.stdout) > MAX_BYTES:
        raise ValueError('identity_transport_failed')
    return decode(result.stdout)


def validate_response(response, request, expected, started):
    if (not isinstance(response, dict) or set(response) != {'schema', 'nonce', 'request_sha256', 'checked_at', 'identity_checks'}
            or type(response['schema']) is not int or response['schema'] != 1
            or response['nonce'] != request['nonce']
            or response['request_sha256'] != hashlib.sha256(encode(request)).hexdigest()
            or type(response['checked_at']) is not int
            or not started - 10 <= response['checked_at'] <= time.time() + 10
            or not isinstance(response['identity_checks'], list)
            or len(response['identity_checks']) != len(expected)):
        raise ValueError('invalid_identity_response')
    scope = {r['key']: r for r in expected}
    seen = set()
    for row in response['identity_checks']:
        if (not isinstance(row, dict) or set(row) not in ({'key', 'backend_id', 'public_id'}, {'key', 'backend_id', 'public_id', 'reason'})
                or not isinstance(row.get('key'), str) or row['key'] not in scope or row['key'] in seen
                or any(type(row[k]) is not int or row[k] != scope[row['key']][k] for k in ('backend_id', 'public_id'))
                or ('reason' in row and (not isinstance(row['reason'], str) or row['reason'] not in guard.GUARD_WITHDRAW_REASONS
                                        or not row['reason'].startswith('runtime_')))):
            raise ValueError('invalid_identity_result')
        seen.add(row['key'])
    return {row['key']: row for row in response['identity_checks']}


def evaluate_identity(approved, allocation, mappings, probe=None, exchange=None):
    # Reuse the local scope/mapping validation before sending any destinations.
    checks = guard.evaluate_identity(approved, allocation, mappings, lambda _: None)
    valid = [row for row in checks if 'reason' not in row]
    if not valid:
        return checks
    identities = {row['key']: row for row in mappings if isinstance(row, dict) and isinstance(row.get('key'), str)}
    request = {'schema': 1, 'nonce': secrets.token_hex(32),
               'mappings': [{k: identities[row['key']][k] for k in ('key', 'ip', 'port', 'sni', 'pin')} for row in valid]}
    started = time.time()
    try:
        request_rows(request, allocation)
        response = (exchange or ssh_exchange)(request)
        results = validate_response(response, request, valid, started)
    except Exception:
        results = {row['key']: guard.route_result(row, 'runtime_identity_check_failed') for row in valid}
    return [results.get(row['key'], row) for row in checks]


def main():
    # This is the only operation permitted by the dedicated SSH authorized key.
    request = decode(sys.stdin.buffer.read(MAX_BYTES + 1))
    allocation = decode(ALLOCATION.read_bytes())
    answer = serve(request, allocation)
    sys.stdout.buffer.write(encode(answer) + b'\n')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('{"error":"identity_worker_failed"}')
        raise SystemExit(2)
