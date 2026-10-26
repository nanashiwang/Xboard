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
QUIC_TOOL_NAME = 'quic-observer-linux-amd64'
QUIC_FAILURES = {'invalid_input', 'identity_timeout', 'tls_failed', 'quic_unreachable',
                 'quic_handshake_failed', 'certificate_invalid'}
FIELDS = ('key', 'ip', 'port', 'sni', 'pin')
MAX_DNS = 8
STAGE = 'startup'
DIAGNOSTICS = {}


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


def snapshot_database(allocation, manifest):
    global STAGE, DIAGNOSTICS
    encoded = base64.b64encode(canonical(allocation)).decode()
    program = (SIBLING / 'snapshot.php').read_text()
    if program.count('__ALLOCATION_BASE64__') != 1:
        raise ContractError()
    program = program.replace('__ALLOCATION_BASE64__', encoded)
    if program.count('__MANIFEST_BASE64__') != 1:
        raise ContractError()
    program = program.replace('__MANIFEST_BASE64__', base64.b64encode(manifest).decode())
    result = subprocess.run(['docker', 'compose', 'exec', '-T', 'xboard', 'php'],
                            cwd='/root/Xboard', input=program.encode(), capture_output=True, timeout=60)
    if len(result.stdout) > 5 * 1024 * 1024:
        raise ContractError()
    data = json.loads(result.stdout)
    if 'error' in data:
        details = data.get('diagnostics', {})
        for key in ('manifest_exists', 'manifest_readable', 'manifest_object', 'machine_matches', 'routes_array'):
            if type(details.get(key)) is bool:
                DIAGNOSTICS[key] = details[key]
        if type(details.get('route_count')) is int and 0 <= details['route_count'] <= 1000:
            DIAGNOSTICS['route_count'] = details['route_count']
        if data.get('stage') in {'bootstrap', 'manifest', 'mapping', 'read_fields'}:
            STAGE = 'database_snapshot_' + data['stage']
        raise ContractError()
    if result.returncode:
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


def quic_alpn(source, settings):
    # This helper cannot model obfuscation or port hopping. Such a change needs
    # separate review; never reinterpret it as a certificate/address rotation.
    if (any(source.get(key) for key in ('obfs', 'obfs-password', 'ports', 'hop-interval'))
            or any(settings.get(key) for key in ('obfs', 'server_ports', 'hop_interval', 'transport'))
            or source.get('network') not in (None, 'udp')):
        raise ContractError()
    source_alpn = source.get('alpn') or ['h3']
    current_alpn = settings['tls'].get('alpn') or ['h3']
    if (not isinstance(source_alpn, list) or not 1 <= len(source_alpn) <= 8
            or source_alpn != current_alpn
            or any(not isinstance(value, str) or not 1 <= len(value) <= 255
                   or any(ord(c) < 33 or ord(c) > 126 for c in value) for value in source_alpn)):
        raise ContractError()
    return source_alpn


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
    if source.get('type') == 'hysteria2':
        quic_alpn(source, settings)
    elif network == 'tcp':
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
    try:
        current_ip = str(ipaddress.ip_address(settings['server']))
    except ValueError:
        if source.get('type') != 'hysteria2' or settings['server'] != host:
            raise ContractError()
        current_ip = None
    return host, port, sni, pins, current_ip


def source_target_ca(source, settings):
    """Preserve the CA VLESS transport/identity contract; discover addresses only."""
    host = hostname(source['server'])
    port = source['port']
    sni = hostname(source.get('sni') or source.get('servername') or host)
    tls = settings.get('tls')
    if (type(port) is not int or not 1 <= port <= 65535 or settings.get('server_port') != port
            or not isinstance(tls, dict) or tls.get('enabled') is not True
            or tls.get('insecure', False) is not False or tls.get('server_name') != sni
            or 'certificate_public_key_sha256' in tls or source.get('tls') is not True
            or source.get('skip-cert-verify', False) is not False
            or settings.get('uuid') != source.get('uuid') or not isinstance(source.get('uuid'), str)
            or (settings.get('flow') or '') != (source.get('flow') or '')
            or source.get('alterId', 0) != 0 or source.get('cipher', 'auto') != 'auto'
            or any(source.get(key) for key in ('reality-opts', 'ech-opts'))
            or any(tls.get(key) for key in ('reality', 'ech', 'certificate', 'certificate_path',
                    'client_certificate', 'client_certificate_path', 'client_key', 'client_key_path'))):
        raise ContractError()
    uuid.UUID(source['uuid'])
    alpn = source.get('alpn') or []
    if (not isinstance(alpn, list) or len(alpn) > 8 or alpn != (tls.get('alpn') or [])
            or any(not isinstance(value, str) or not 1 <= len(value) <= 255
                   or any(ord(c) < 33 or ord(c) > 126 for c in value) for value in alpn)):
        raise ContractError()
    network = source.get('network', 'tcp')
    if network == 'tcp':
        if source.get('ws-opts') or settings.get('transport'):
            raise ContractError()
    elif network == 'ws':
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
    current_server = hostname(settings['server'])
    try:
        current_ip = str(ipaddress.ip_address(current_server))
    except ValueError:
        if current_server != host:
            raise ContractError()
        current_ip = None
    return host, port, sni, [], current_ip, alpn


DNS_PROGRAM = """import socket,json,sys
data=json.load(sys.stdin)
try:
 result=sorted({row[4][0] for row in socket.getaddrinfo(data['host'],data['port'],type=socket.SOCK_STREAM)})
 print(json.dumps(result))
except Exception:
 raise SystemExit(1)
"""


def global_unicast(value):
    address = ipaddress.ip_address(value)
    return address.is_global and not address.is_multicast and not address.is_reserved


def resolve(host, port):
    result = subprocess.run([sys.executable, '-c', DNS_PROGRAM], input=canonical({'host': host, 'port': port}),
                            capture_output=True, timeout=6)
    if result.returncode:
        raise ContractError()
    values = json.loads(result.stdout)
    if not isinstance(values, list):
        raise ContractError()
    addresses = sorted({str(ipaddress.ip_address(item)) for item in values})
    if any(not global_unicast(item) for item in addresses):
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


def observe_ca(ip, port, sni, alpn=None, timeout=6):
    """CA validation must succeed before any SPKI observation becomes a candidate."""
    deadline = time.monotonic() + timeout
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError()
        return value
    try:
        address = ipaddress.ip_address(ip)
        context = ssl.create_default_context()
        # No insecure mode, custom trust roots, or arbitrary context is accepted
        # from a source entry. Dial a fixed IP and verify the original TLS name.
        if alpn:
            context.set_alpn_protocols(alpn)
        with socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(remaining())
            connection.connect((str(address), port))
            with context.wrap_socket(connection, server_hostname=sni, do_handshake_on_connect=False) as tls:
                tls.settimeout(remaining())
                tls.do_handshake()
                certificate = tls.getpeercert(binary_form=True)
        pin, before, after = certificate_data(certificate, remaining)
        return {'pin': pin, 'not_before': before, 'not_after': after,
                'certificate_time_valid': before <= time.time() <= after, 'ca_validated': True}
    except (TimeoutError, socket.timeout, subprocess.TimeoutExpired):
        return {'reason': 'identity_timeout'}
    except ssl.SSLCertVerificationError:
        return {'reason': 'ca_validation_failed'}
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


def verify_quic_tool(expected_sha256):
    """Only run the fixed sibling built by the trusted checkout workflow.

    The hash comes from that build, never workflow_dispatch or the subscription.
    The private directory prevents another user replacing a verified executable.
    """
    if not isinstance(expected_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_sha256):
        raise ContractError()
    directory = SIBLING.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid()
            or directory.st_mode & 0o077):
        raise ContractError()
    path = SIBLING / QUIC_TOOL_NAME
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as file:
        info = os.fstat(file.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700 or not 0 < info.st_size <= 16 * 1024 * 1024):
            raise ContractError()
        if hashlib.sha256(file.read()).hexdigest() != expected_sha256:
            raise ContractError()
    return path


def observe_quic(tool, ip, port, sni, alpn, timeout=8):
    """Capture private helper stdout; expose only a validated observation/class."""
    try:
        result = subprocess.run([str(tool)], input=canonical({'ip': ip, 'port': port, 'sni': sni, 'alpn': alpn}),
                                capture_output=True, timeout=timeout)
        if len(result.stdout) > 4096:
            raise ContractError()
        def unique_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ContractError()
                value[key] = item
            return value
        observed = json.loads(result.stdout, object_pairs_hook=unique_object)
        if not isinstance(observed, dict):
            raise ContractError()
        if 'reason' in observed:
            if (set(observed) != {'reason'} or observed['reason'] not in QUIC_FAILURES
                    or result.returncode != (2 if observed['reason'] == 'invalid_input' else 1)):
                raise ContractError()
            return observed
        if result.returncode != 0 or set(observed) != {'pin', 'not_before', 'not_after', 'certificate_time_valid'}:
            raise ContractError()
        pin = observed['pin']
        decoded = base64.b64decode(pin, validate=True)
        start, end = observed['not_before'], observed['not_after']
        if (len(decoded) != 32 or base64.b64encode(decoded).decode() != pin
                or type(start) is not int or type(end) is not int or end < start
                or type(observed['certificate_time_valid']) is not bool):
            raise ContractError()
        # The receiving process also checks time; a helper flag can never turn
        # an already expired / not-yet-valid observation into a valid candidate.
        observed['certificate_time_valid'] = observed['certificate_time_valid'] and start <= time.time() <= end
        return observed
    except subprocess.TimeoutExpired:
        return {'reason': 'identity_timeout'}
    except OSError:
        return {'reason': 'identity_tool_unavailable'}
    except Exception:
        return {'reason': 'identity_observer_invalid_output'}


def prepare_rows(allocation, approved, snapshot, proxies, usage, now=None, resolver=resolve, observer=observe,
                 quic_observer=None, ca_observer=observe_ca):
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
                  'approved_source_sha256': old['source_sha256'],
                  'observed_source_sha256': digest(matches[0]) if len(matches) == 1 else None,
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
        if scope['upstream_type'] not in TCP_TYPES | {'hysteria2', 'vless'}:
            report['reason'] = 'outside_tcp_identity_discovery'
            return private, report
        if scope['upstream_type'] == 'hysteria2' and quic_observer is None:
            report['reason'] = 'identity_tool_unavailable'
            return private, report
        try:
            settings = settings_for(snap, scope['upstream_type'])
            if scope['upstream_type'] == 'vless':
                host, port, sni, pins, current_ip, alpn = source_target_ca(matches[0], settings)
            else:
                host, port, sni, pins, current_ip = source_target(matches[0], settings)
            if current_ip is not None and not global_unicast(current_ip):
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
        endpoints = sorted(set(addresses) | ({current_ip} if current_ip is not None else set()))
        for ip in endpoints:
            if scope['upstream_type'] == 'hysteria2':
                observation = quic_observer(ip, port, sni, quic_alpn(matches[0], settings))
            elif scope['upstream_type'] == 'vless':
                observation = ca_observer(ip, port, sni, alpn)
                if 'reason' not in observation and observation.get('ca_validated') is not True:
                    observation = {'reason': 'ca_validation_failed'}
            else:
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
            if scope['upstream_type'] == 'vless':
                entry['ca_validated'] = True
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
    global STAGE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allocation', type=Path, default=SIBLING / 'allocation.json')
    parser.add_argument('--quic-observer-sha256', required=True,
                        help='SHA256 of the fixed sibling executable from the trusted workflow build')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ContractError()
    os.umask(0o077)
    STAGE = 'allocation'
    allocation = json.loads(args.allocation.read_text())
    STAGE = 'approved_storage'
    approved_bytes = private_file(PRIVATE_ROOT / 'approved.private')
    approved = json.loads(approved_bytes)
    STAGE = 'source_url_storage'
    private_file(PRIVATE_ROOT / 'source-url.secret')  # Validate storage before fetch.
    STAGE = 'guard_module'
    guard = load_guard(SIBLING / 'guard.py')
    STAGE = 'database_snapshot'
    STAGE = 'manifest_storage'
    manifest_bytes = private_file(PRIVATE_ROOT / 'manifest.private')
    STAGE = 'database_snapshot'
    snapshot = snapshot_database(allocation, manifest_bytes)
    STAGE = 'scope_validation'
    validate_scope(allocation, approved, snapshot)
    STAGE = 'source_fetch'
    proxies, usage = guard.fetch_subscription(PRIVATE_ROOT)
    STAGE = 'quic_observer_verification'
    quic_tool = verify_quic_tool(args.quic_observer_sha256)
    STAGE = 'candidate_discovery'
    private, report_rows = prepare_rows(allocation, approved, snapshot, proxies, usage,
        quic_observer=lambda ip, port, sni, alpn: observe_quic(quic_tool, ip, port, sni, alpn))
    plan = {'schema': 1, 'prepared_at': int(time.time()), 'allocation_sha256': digest(allocation),
            'manifest_file_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'approved_file_sha256': hashlib.sha256(approved_bytes).hexdigest(), 'usage': usage, 'routes': private,
            'trust_status': 'candidate_observations_only_not_approved', 'production_mutated': False,
            'tools': {'quic_observer_sha256': args.quic_observer_sha256}}
    STAGE = 'private_plan_storage'
    plan_id, plan_hash, directory = save_plan(PLAN_ROOT, plan)
    report = {'status': 'prepared', 'schema': 1, 'plan_id': plan_id, 'plan_sha256': plan_hash,
              'production_mutated': False, 'trust_status': 'candidate_observations_only_not_approved', 'routes': report_rows,
              'tools': {'quic_observer_sha256': args.quic_observer_sha256}}
    (directory / 'report.json').write_bytes(canonical(report))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'error', 'reason': 'prepare_failed', 'stage': STAGE,
                          'error_type': type(error).__name__, 'diagnostics': DIAGNOSTICS}), flush=True)
        raise SystemExit(1)
