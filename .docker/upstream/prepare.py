#!/usr/bin/env python3
"""Prepare PRIVATE identity candidates; never trust, apply, enable or withdraw them.

stdout contains only IDs, digest commitments, booleans and fixed error classes.
Certificate discovery deliberately sends no proxy authentication/application data.
Even identical observations on two networks are not independent provider identity.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import subprocess
import sys
import time
import uuid

PRIVATE_ROOT = Path('/root/Xboard/backups/upstream-20261022')
PLAN_ROOT = Path('/root/xboard-upstream-recovery')
SIBLING = Path(__file__).resolve().parent
TCP_TYPES = {'anytls', 'trojan'}
FIELDS = ('key', 'ip', 'port', 'sni', 'pin')
MAX_DNS = 8


class ContractError(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def private_file(path):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise ContractError()
    return path.read_bytes()


def load_guard(path):
    spec = importlib.util.spec_from_file_location('prepare_guard', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unique(rows):
    if not isinstance(rows, list):
        raise ContractError()
    by_key = {}
    for row in rows:
        if not isinstance(row, dict) or not re.fullmatch(r'U(?:0[1-9]|[1-3][0-9]|4[01])', row.get('key', '')):
            raise ContractError()
        if row['key'] in by_key:
            raise ContractError()
        by_key[row['key']] = row
    return by_key


def validate_scope(allocation, approved, snapshot):
    if allocation.get('machine_id') != 21 or snapshot.get('machine_id') != 21:
        raise ContractError()
    scopes, approved_rows, current = unique(allocation.get('routes')), unique(approved), unique(snapshot.get('routes'))
    keys = {'U%02d' % n for n in range(1, 42)}
    if set(scopes) != keys or set(approved_rows) != keys or set(current) != keys:
        raise ContractError()
    ids = []
    for key, row in scopes.items():
        old = approved_rows[key]
        snap = current[key]
        if any(type(row.get(k)) is not int or row[k] != old.get(k) for k in ('backend_id', 'public_id')):
            raise ContractError()
        ids.extend([row['backend_id'], row['public_id']])
        if snap['backend'].get('id') != row['backend_id'] or snap['public'].get('id') != row['public_id']:
            raise ContractError()
        if snap['backend'].get('machine_id') != 21 or snap['public'].get('parent_id') != row['backend_id']:
            raise ContractError()
        if ('upstream-extension-backend' not in snap['backend'].get('tags', [])
                or 'upstream-extension-public' not in snap['public'].get('tags', [])):
            raise ContractError()
        if (not isinstance(old.get('source_name'), str) or not old['source_name']
                or not re.fullmatch(r'[a-f0-9]{64}', old.get('source_sha256', ''))):
            raise ContractError()
        if row.get('upstream_type') not in ('anytls', 'trojan', 'vless', 'hysteria2'):
            raise ContractError()
    if len(set(ids)) != 82 or set(ids) & set(allocation.get('ordinary_owned_ids', [])):
        raise ContractError()
    return scopes, approved_rows, current


def snapshot_database(allocation):
    encoded = base64.b64encode(canonical(allocation)).decode()
    program = (SIBLING / 'snapshot.php').read_text()
    if program.count('__ALLOCATION_BASE64__') != 1:
        raise ContractError()
    program = program.replace('__ALLOCATION_BASE64__', encoded)
    result = subprocess.run(['docker', 'compose', 'exec', '-T', 'xboard', 'php'],
                            cwd='/root/Xboard', input=program.encode(), capture_output=True, timeout=60)
    if result.returncode or len(result.stdout) > 5 * 1024 * 1024:
        raise ContractError()
    data = json.loads(result.stdout)
    if 'error' in data:
        raise ContractError()
    return data


def settings_for(row, protocol):
    entries = row['backend']['custom_outbounds']
    if isinstance(entries, str):
        entries = json.loads(entries)
    if not isinstance(entries, list) or len(entries) != 1 or entries[0].get('protocol') != protocol:
        raise ContractError()
    settings = entries[0]['settings']
    if isinstance(settings, str):
        settings = json.loads(settings)
    if not isinstance(settings, dict) or settings.get('type', protocol) != protocol:
        raise ContractError()
    return settings


def hostname(value):
    if not isinstance(value, str) or not value or len(value) > 253 or any(ord(c) < 33 for c in value):
        raise ContractError()
    return value


def source_target(source, settings):
    host = hostname(source['server'])
    port = source['port']
    sni = hostname(source.get('sni') or source.get('servername') or host)
    tls = settings.get('tls')
    if (type(port) is not int or not 1 <= port <= 65535 or settings.get('server_port') != port
            or not isinstance(tls, dict) or tls.get('enabled') is not True or tls.get('insecure', False) is not False
            or tls.get('server_name') != sni or settings.get('password') != source.get('password')
            or not isinstance(source.get('password'), str) or not source['password']):
        raise ContractError()
    # Do not silently reinterpret transport differences as an address rotation.
    network = source.get('network', 'tcp')
    if network == 'tcp':
        if source.get('ws-opts') or settings.get('transport'):
            raise ContractError()
    elif network == 'ws' and source.get('type') == 'trojan':
        opts = source.get('ws-opts', {})
        if not isinstance(opts, dict) or set(opts) - {'path', 'headers'}:
            raise ContractError()
        transport = {'type': 'ws', 'path': opts.get('path', '/')}
        if 'headers' in opts:
            transport['headers'] = opts['headers']
        if settings.get('transport') != transport:
            raise ContractError()
    else:
        raise ContractError()
    pins = tls.get('certificate_public_key_sha256')
    if not isinstance(pins, list) or not pins:
        raise ContractError()
    for pin in pins:
        value = base64.b64decode(pin, validate=True)
        if len(value) != 32 or base64.b64encode(value).decode() != pin:
            raise ContractError()
    current_ip = str(ipaddress.ip_address(settings['server']))
    return host, port, sni, pins, current_ip


DNS_PROGRAM = """import socket,json,sys
data=json.load(sys.stdin)
try:
 result=sorted({row[4][0] for row in socket.getaddrinfo(data['host'],data['port'],type=socket.SOCK_STREAM)})
 print(json.dumps(result))
except Exception:
 raise SystemExit(1)
"""


def resolve(host, port):
    result = subprocess.run([sys.executable, '-c', DNS_PROGRAM], input=canonical({'host': host, 'port': port}),
                            capture_output=True, timeout=6)
    if result.returncode:
        raise ContractError()
    values = json.loads(result.stdout)
    if not isinstance(values, list):
        raise ContractError()
    addresses = sorted({str(ipaddress.ip_address(item)) for item in values})
    if any(not ipaddress.ip_address(item).is_global for item in addresses):
        raise ContractError()
    return addresses[:MAX_DNS], len(addresses) > MAX_DNS


def certificate_data(certificate, remaining):
    public_key = subprocess.run(['openssl', 'x509', '-inform', 'DER', '-pubkey', '-noout'],
                                input=certificate, capture_output=True, check=True, timeout=remaining()).stdout
    spki = subprocess.run(['openssl', 'pkey', '-pubin', '-outform', 'DER'], input=public_key,
                          capture_output=True, check=True, timeout=remaining()).stdout
    dates = subprocess.run(['openssl', 'x509', '-inform', 'DER', '-dates', '-noout'], input=certificate,
                           capture_output=True, check=True, timeout=remaining()).stdout.decode('ascii')
    periods = dict(line.split('=', 1) for line in dates.strip().splitlines())
    if not spki or set(periods) != {'notBefore', 'notAfter'}:
        raise ContractError()
    start, end = (ssl.cert_time_to_seconds(periods[key]) for key in ['notBefore', 'notAfter'])
    return base64.b64encode(hashlib.sha256(spki).digest()).decode(), start, end


def observe(ip, port, sni, timeout=6):
    deadline = time.monotonic() + timeout
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError()
        return value
    try:
        address = ipaddress.ip_address(ip)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(remaining())
            connection.connect((str(address), port))
            with context.wrap_socket(connection, server_hostname=sni, do_handshake_on_connect=False) as tls:
                tls.settimeout(remaining())
                tls.do_handshake()
                certificate = tls.getpeercert(binary_form=True)
        pin, before, after = certificate_data(certificate, remaining)
        return {'pin': pin, 'not_before': before, 'not_after': after, 'certificate_time_valid': before <= time.time() <= after}
    except (TimeoutError, socket.timeout, subprocess.TimeoutExpired):
        return {'reason': 'identity_timeout'}
    except ssl.SSLError:
        return {'reason': 'tls_failed'}
    except FileNotFoundError:
        return {'reason': 'identity_tool_unavailable'}
    except (subprocess.CalledProcessError, ContractError, ValueError):
        return {'reason': 'certificate_invalid'}
    except OSError:
        return {'reason': 'tcp_unreachable'}
    except Exception:
        return {'reason': 'identity_discovery_failed'}


def prepare_rows(allocation, approved, snapshot, proxies, usage, now=None, resolver=resolve, observer=observe):
    now = time.time() if now is None else now
    scopes, approved_rows, current = validate_scope(allocation, approved, snapshot)
    names = {}
    for item in proxies:
        if isinstance(item, dict):
            names.setdefault(item.get('name'), []).append(item)
    quota_ok = (usage.get('expire', 0) > now + 300 and usage.get('total', 0) > usage.get('upload', 0) + usage.get('download', 0))

    def prepare(key):
        scope, old, snap = scopes[key], approved_rows[key], current[key]
        matches = names.get(old['source_name'], [])
        report = {'key': key, 'backend_id': scope['backend_id'], 'public_id': scope['public_id'],
                  'protocol': scope['upstream_type'], 'source_name_sha256': hashlib.sha256(old['source_name'].encode()).hexdigest(),
                  'source_matches_approved': len(matches) == 1 and digest(matches[0]) == old['source_sha256'],
                  'source_match_count': len(matches), 'quota_and_expiry_ok': quota_ok,
                  'current_show': snap['public'].get('show'), 'current_enabled': snap['backend'].get('enabled'),
                  'old_fields_sha256': digest(snap), 'candidates': []}
        if 'state_sha256' in snap:
            report['state_sha256'] = snap['state_sha256']
        private = {'key': key, 'approved': old, 'snapshot': snap, 'source': matches[0] if len(matches) == 1 else None,
                   'old_fields_sha256': report['old_fields_sha256'], 'candidates': []}
        if not report['source_matches_approved']:
            report['reason'] = 'source_changed_or_ambiguous'
            return private, report
        if matches[0].get('type') != scope['upstream_type']:
            report['reason'] = 'source_protocol_scope_mismatch'
            return private, report
        if not quota_ok:
            report['reason'] = 'quota_or_expiry_rejected'
            return private, report
        if scope['upstream_type'] not in TCP_TYPES:
            report['reason'] = 'outside_tcp_identity_discovery'
            return private, report
        try:
            settings = settings_for(snap, scope['upstream_type'])
            host, port, sni, pins, current_ip = source_target(matches[0], settings)
            if not ipaddress.ip_address(current_ip).is_global:
                raise ContractError()
        except Exception:
            report['reason'] = 'current_source_contract_mismatch'
            return private, report
        try:
            addresses, truncated = resolver(host, port)
            report['dns_candidate_truncated'] = truncated
        except Exception:
            addresses = []
            report['dns_reason'] = 'dns_resolution_failed'
        # Always inspect the existing approved endpoint, even if DNS fails.
        endpoints = sorted(set(addresses) | {current_ip})
        for ip in endpoints:
            observation = observer(ip, port, sni)
            entry = {'current_endpoint': ip == current_ip, 'source_dns_endpoint': ip in addresses}
            if 'reason' in observation:
                entry['reason'] = observation['reason']
                report['candidates'].append(entry)
                continue
            identity = {'key': key, 'ip': ip, 'port': port, 'sni': sni, 'pin': observation['pin']}
            commitment = digest(identity)
            entry.update(candidate_digest=commitment, old_pin_matches=identity['pin'] in pins,
                         certificate_time_valid=observation['certificate_time_valid'], reason='observed_not_approved')
            private['candidates'].append({'identity': identity, 'candidate_digest': commitment, **observation,
                                          'old_pin_matches': entry['old_pin_matches'],
                                          'current_endpoint': entry['current_endpoint'], 'source_dns_endpoint': entry['source_dns_endpoint']})
            report['candidates'].append(entry)
        return private, report

    with ThreadPoolExecutor(max_workers=6) as executor:
        pairs = list(executor.map(prepare, sorted(scopes)))
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


def save_plan(root, plan):
    if root.exists():
        st = root.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
            raise ContractError()
    else:
        root.mkdir(mode=0o700)
    plan_id = uuid.uuid4().hex
    directory = root / plan_id
    directory.mkdir(mode=0o700)
    plan = dict(plan, plan_id=plan_id)
    body = canonical(plan)
    with os.fdopen(os.open(directory / 'plan.private.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
        output.write(body)
    return plan_id, hashlib.sha256(body).hexdigest(), directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allocation', type=Path, default=SIBLING / 'allocation.json')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ContractError()
    os.umask(0o077)
    allocation = json.loads(args.allocation.read_text())
    approved_bytes = private_file(PRIVATE_ROOT / 'approved.private')
    approved = json.loads(approved_bytes)
    private_file(PRIVATE_ROOT / 'source-url.secret')  # Validate storage before fetch.
    guard = load_guard(SIBLING / 'guard.py')
    snapshot = snapshot_database(allocation)
    validate_scope(allocation, approved, snapshot)
    proxies, usage = guard.fetch_subscription(PRIVATE_ROOT)
    private, report_rows = prepare_rows(allocation, approved, snapshot, proxies, usage)
    plan = {'schema': 1, 'prepared_at': int(time.time()), 'allocation_sha256': digest(allocation),
            'approved_file_sha256': hashlib.sha256(approved_bytes).hexdigest(), 'usage': usage, 'routes': private,
            'trust_status': 'candidate_observations_only_not_approved', 'production_mutated': False}
    plan_id, plan_hash, directory = save_plan(PLAN_ROOT, plan)
    report = {'status': 'prepared', 'schema': 1, 'plan_id': plan_id, 'plan_sha256': plan_hash,
              'production_mutated': False, 'trust_status': 'candidate_observations_only_not_approved', 'routes': report_rows}
    (directory / 'report.json').write_bytes(canonical(report))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'error', 'reason': 'prepare_failed', 'error_type': type(error).__name__}), flush=True)
        raise SystemExit(1)
