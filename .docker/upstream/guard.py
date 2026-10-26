#!/usr/bin/env python3
"""Withdraw only approved extension routes when their upstream is no longer usable.

Private state and URL live outside Git. This guard never trusts new credentials,
changes package membership, or re-enables a withdrawn route without acceptance.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path('/root/Xboard/backups/upstream-20261022')
ALLOCATION = Path(__file__).with_name('allocation.json')


def fingerprint(node):
    return hashlib.sha256(json.dumps(node, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def evaluate(approved, proxies, usage, now):
    names = {}
    for node in proxies:
        names.setdefault(node.get('name'), []).append(node)
    reason = None
    if usage.get('expire', 0) <= now + 300:
        reason = 'expired_or_near_expiry'
    elif usage.get('total', 0) <= usage.get('upload', 0) + usage.get('download', 0):
        reason = 'quota_exhausted'
    disabled = []
    for row in approved:
        matches = names.get(row['source_name'], [])
        why = reason
        if not why and len(matches) != 1:
            why = 'missing_or_ambiguous_source'
        if not why and fingerprint(matches[0]) != row['source_sha256']:
            why = 'source_changed_requires_acceptance'
        if why:
            disabled.append({'key': row['key'], 'backend_id': row['backend_id'],
                             'public_id': row['public_id'], 'reason': why})
    return disabled


def route_result(row, reason=None):
    result = {k: row[k] for k in ('key', 'backend_id', 'public_id')}
    if reason:
        result['reason'] = reason
    return result


def validate_identity(mapping):
    """Accept only the existing, manually approved endpoint/pin format."""
    if not isinstance(mapping, dict):
        raise ValueError('invalid_identity_mapping')
    if not isinstance(mapping.get('ip'), str):
        raise ValueError('invalid_ip')
    ipaddress.ip_address(mapping['ip'])  # No DNS rotation or subscription endpoint.
    if type(mapping['port']) is not int or not 1 <= mapping['port'] <= 65535:
        raise ValueError('invalid_port')
    sni = mapping['sni']
    if not isinstance(sni, str) or not sni or len(sni) > 253 or any(c.isspace() or ord(c) < 32 for c in sni):
        raise ValueError('invalid_sni')
    pin = mapping['pin']
    if not isinstance(pin, str):
        raise ValueError('invalid_pin')
    digest = base64.b64decode(pin, validate=True)
    if len(digest) != 32 or base64.b64encode(digest).decode('ascii') != pin:
        raise ValueError('invalid_pin')


def probe_identity(mapping, timeout=5):
    """Collect a leaf certificate, then authenticate its SPKI against the old pin.

    CERT_NONE is confined to certificate collection: no AnyTLS authentication or
    application bytes are sent, and only an exact approved SPKI match succeeds.
    """
    try:
        validate_identity(mapping)
    except (KeyError, TypeError, ValueError):
        return 'runtime_identity_mapping_invalid'
    deadline = time.monotonic() + timeout

    def remaining():
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise TimeoutError()
        return budget

    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        address = ipaddress.ip_address(mapping['ip'])
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(remaining())
            connection.connect((str(address), mapping['port']))
            with context.wrap_socket(connection, server_hostname=mapping['sni'],
                                     do_handshake_on_connect=False) as tls:
                tls.settimeout(remaining())
                tls.do_handshake()
                certificate = tls.getpeercert(binary_form=True)
        # Pass certificate bytes over stdin, never endpoints/pins/credentials in
        # command arguments. Hash SPKI DER, not the whole certificate DER.
        public_key = subprocess.run(
            ['openssl', 'x509', '-inform', 'DER', '-pubkey', '-noout'],
            input=certificate, capture_output=True, check=True, timeout=remaining()).stdout
        spki = subprocess.run(
            ['openssl', 'pkey', '-pubin', '-outform', 'DER'],
            input=public_key, capture_output=True, check=True, timeout=remaining()).stdout
        if not spki:
            return 'runtime_certificate_invalid'
        observed = base64.b64encode(hashlib.sha256(spki).digest()).decode('ascii')
        return None if observed == mapping['pin'] else 'runtime_public_key_mismatch'
    except (TimeoutError, socket.timeout, subprocess.TimeoutExpired):
        return 'runtime_identity_timeout'
    except ssl.SSLError:
        return 'runtime_tls_failed'
    except FileNotFoundError:
        return 'runtime_identity_tool_unavailable'
    except subprocess.CalledProcessError:
        return 'runtime_certificate_invalid'
    except OSError:
        return 'runtime_tcp_unreachable'
    except Exception:
        # Never expose OpenSSL stderr or exception messages containing identities.
        return 'runtime_identity_check_failed'


def evaluate_identity(approved, allocation, mappings, probe=None):
    """Check approved AnyTLS routes only; unknown maps cannot add destinations."""
    probe = probe or probe_identity
    scopes = {}
    if isinstance(allocation, dict) and isinstance(allocation.get('routes'), list):
        for row in allocation['routes']:
            if isinstance(row, dict) and isinstance(row.get('key'), str):
                scopes.setdefault(row['key'], []).append(row)
    identities = {}
    if isinstance(mappings, list):
        for row in mappings:
            if isinstance(row, dict) and isinstance(row.get('key'), str):
                identities.setdefault(row['key'], []).append(row)

    def check(row):
        scope = scopes.get(row['key'], [])
        if len(scope) != 1 or any(scope[0].get(k) != row[k] for k in ('backend_id', 'public_id')):
            return route_result(row, 'runtime_identity_scope_invalid')
        protocol = scope[0].get('upstream_type')
        if protocol in ('vless', 'trojan', 'hysteria2'):
            return None  # Outside this TCP AnyTLS check; existing guards remain.
        if protocol != 'anytls':
            return route_result(row, 'runtime_identity_scope_invalid')
        candidates = identities.get(row['key'], [])
        if len(candidates) != 1:
            return route_result(row, 'runtime_identity_mapping_invalid')
        try:
            validate_identity(candidates[0])
        except (KeyError, TypeError, ValueError):
            return route_result(row, 'runtime_identity_mapping_invalid')
        try:
            reason = probe(candidates[0])
        except Exception:
            reason = 'runtime_identity_check_failed'
        return route_result(row, reason)

    # 28 deployed AnyTLS endpoints: at most four waves of five-second probes.
    with ThreadPoolExecutor(max_workers=8) as executor:
        return [result for result in executor.map(check, approved) if result is not None]


def read_json_or_none(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def apply(withdraw, root=ROOT):
    request = root / 'guard.request.json'
    request.write_text(json.dumps(withdraw))
    request.chmod(0o600)
    container = subprocess.check_output(['docker', 'compose', 'ps', '-q', 'xboard'],
                                        cwd='/root/Xboard', text=True, timeout=10,
                                        stderr=subprocess.PIPE).strip()
    if not container:
        raise RuntimeError('application_not_running')
    target = '/www/storage/app/backups/upstream-20261022/guard.request.json'
    subprocess.run(['docker', 'cp', str(request), container + ':' + target], check=True,
                   capture_output=True, timeout=30)
    script = (root / 'guard-apply.php').read_text()
    result = subprocess.run(['docker', 'compose', 'exec', '-T', 'xboard', 'php'],
                            cwd='/root/Xboard', input=script, text=True,
                            capture_output=True, timeout=60)
    answer = json.loads(result.stdout)
    if result.returncode or 'error' in answer:
        raise RuntimeError('withdrawal_failed')
    return answer


def fetch_subscription(root):
    import yaml
    url = (root / 'source-url.secret').read_text().strip()
    if not url.startswith('https://'):
        raise ValueError('https_required')
    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={'User-Agent': 'ClashMeta/1.19.32'})
    with opener.open(req, timeout=25) as response:
        raw = response.read(5 * 1024 * 1024 + 1)
        header = response.headers.get('subscription-userinfo', '')
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError('response_too_large')
    data = yaml.safe_load(raw)
    if not isinstance(data, dict) or not isinstance(data.get('proxies'), list):
        raise ValueError('invalid_subscription')
    usage = {}
    for item in header.split(';'):
        key, _, value = item.strip().partition('=')
        if value.isdigit():
            usage[key] = int(value)
    if not all(k in usage for k in ('expire', 'total', 'upload', 'download')):
        raise ValueError('missing_quota_metadata')
    return data['proxies'], usage


def check(approved, previous, allocation, mappings, now, fetch, probe=None):
    try:
        proxies, usage = fetch()
        withdraw = evaluate(approved, proxies, usage, now)
        state = {'checked_at': now, 'last_success_at': now, 'usage': usage,
                 'withdraw': withdraw, 'fetch_ok': True}
    except Exception as error:
        # Do not print URLs, headers, authentication, or exception messages.
        state = {k: previous[k] for k in ('last_success_at', 'usage') if k in previous}
        state.update(checked_at=now, fetch_ok=False, error_type=type(error).__name__)
        stale = now - previous.get('last_success_at', 0) > 86400
        expiring = previous.get('usage', {}).get('expire', 0) <= now + 300
        withdraw = [dict(key=r['key'], backend_id=r['backend_id'], public_id=r['public_id'],
                         reason='metadata_stale' if stale else 'known_expiry')
                    for r in approved] if stale or expiring else []
        state['withdraw'] = withdraw
    # Deliberately outside the fetch try/except: metadata grace cannot hide a
    # runtime pin rejection, and a successful fetch is not an identity success.
    checks = evaluate_identity(approved, allocation, mappings, probe)
    state['identity_checks'] = checks
    state['identity_ok'] = bool(checks) and all('reason' not in item for item in checks)
    already = {row['key'] for row in withdraw}
    withdraw.extend(row for row in checks if 'reason' in row and row['key'] not in already)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--allocation', type=Path, default=ALLOCATION)
    parser.add_argument('--identity-map', type=Path, help='Existing approved pinned.private; never generated here')
    parser.add_argument('--check-identity', action='store_true', help='Read-only: no subscription, state writes or withdrawal')
    parser.add_argument('--key', action='append', help='Limit read-only checks to approved U keys (repeatable)')
    args = parser.parse_args(argv)
    if args.key and not args.check_identity:
        parser.error('--key requires --check-identity')
    os.umask(0o077)
    approved = json.loads((args.root / 'approved.private').read_text())
    if not isinstance(approved, list) or not approved:
        raise ValueError('invalid_approved_routes')
    for row in approved:
        if not isinstance(row, dict) or not isinstance(row.get('key'), str) or not re.fullmatch(r'U\d{2}', row['key']):
            raise ValueError('invalid_approved_key')
        if any(type(row.get(field)) is not int or row[field] <= 0 for field in ('backend_id', 'public_id')):
            raise ValueError('invalid_approved_ids')
    for field in ('key', 'backend_id', 'public_id'):
        if len({row[field] for row in approved}) != len(approved):
            raise ValueError('ambiguous_approved_routes')
    allocation = read_json_or_none(args.allocation)
    mappings = read_json_or_none(args.identity_map or args.root / 'pinned.private')
    now = int(time.time())
    if args.check_identity:
        if args.key:
            if not set(args.key) <= {row['key'] for row in approved}:
                raise ValueError('unapproved_key')
            approved = [row for row in approved if row['key'] in args.key]
        checks = evaluate_identity(approved, allocation, mappings)
        ok = bool(checks) and all('reason' not in item for item in checks)
        print(json.dumps({'checked_at': now, 'identity_ok': ok, 'identity_checks': checks}))
        return 0 if ok else 1
    previous = read_json_or_none(args.root / 'guard-state.json')
    if not isinstance(previous, dict):
        previous = {}
    state = check(approved, previous, allocation, mappings, now,
                  lambda: fetch_subscription(args.root))
    withdraw = state['withdraw']
    if withdraw:
        state['apply'] = apply(withdraw, args.root)
    temporary = args.root / 'guard-state.next'
    temporary.write_text(json.dumps(state, indent=2))
    temporary.replace(args.root / 'guard-state.json')
    print(json.dumps({'fetch_ok': state['fetch_ok'], 'withdraw_count': len(withdraw),
                      'identity_ok': state['identity_ok'], 'checked_at': now}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'error_type': type(error).__name__}))
        raise SystemExit(2)
