"""Install a fixed, separately managed ten-port proxy service. Never print credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import socket
import subprocess
import time

HOSTS = {'216.36.108.173', '192.204.56.29'}
PORTS = range(20001, 20011)
BINARY_SHA256 = 'a60f87707d679d154fad93d05313284baf3dea71fdb9ec18afecaac35db946dd'
ROOT = Path('/etc/xboard-proxy-endpoints')
PRIVATE = Path('/root/xboard-proxy-endpoints')
BINARY = Path('/usr/local/lib/xboard-proxy-endpoints/gost')
UNIT = Path('/etc/systemd/system/xboard-proxy-endpoints.service')
SERVICE = UNIT.name
USER = 'xboard-proxy'
AUTH_USER = 'xboard-proxy-auth'
AUTH_SERVICE = 'xboard-proxy-auth.service'
AUTH_UNIT = UNIT.with_name(AUTH_SERVICE)
BLOCKED = ['0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
           '169.254.0.0/16', '172.16.0.0/12', '192.168.0.0/16', '224.0.0.0/4',
           '240.0.0.0/4', '::1', 'fc00::/7', 'fe80::/10', 'localhost', '*.localhost']


def run(args, check=True):
    r = subprocess.run(args, text=True, capture_output=True, timeout=45)
    if check and r.returncode:
        raise RuntimeError('command_failed:' + args[0])
    return r


def save(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.new')
    with temp.open('x') as out:
        out.write(data)
    temp.chmod(mode)
    os.replace(temp, path)


def config_for(host, credentials, rate=12500000, blocked=True):
    """Raw TCP forwarding only: never use GOST auto/TLS routes for public authentication."""
    config = {'services': [], 'limiters': [], 'log': {'level': 'fatal'}}
    for row in credentials:
        name = 'endpoint-' + str(row['port'])
        config['services'].append({'name': name, 'addr': f"{host}:{row['port']}", 'limiter': name,
            'handler': {'type': 'tcp'}, 'listener': {'type': 'tcp'},
            'forwarder': {'nodes': [{'name': name, 'addr': f"127.0.0.1:{row['port'] + 1000}"}]},
            'metadata': {'limiter.scope': 'service'}})
        config['limiters'].append({'name': name, 'limits': [f'$ {rate}B {rate}B']})
    return config


def auth_config(credentials):
    return {'log': {'level': 'fatal'},
            'inbounds': [{'type': 'mixed', 'tag': 'endpoint-' + str(row['port']),
                          'listen': '127.0.0.1', 'listen_port': row['port'] + 1000,
                          'users': [{'username': row['username'], 'password': row['password']}]}
                         for row in credentials],
            'outbounds': [{'type': 'direct', 'tag': 'direct'}],
            'route': {'rules': [{'ip_is_private': True, 'action': 'reject'},
                                {'ip_cidr': [ip + '/32' for ip in sorted(HOSTS)], 'action': 'reject'},
                                {'network': 'udp', 'action': 'reject'}], 'final': 'direct'}}


def baseline():
    result = {}
    for name in ['xboard-node', 'sing-box', 'nginx']:
        result[name] = run(['systemctl', 'show', name, '-p', 'MainPID', '-p', 'ActiveState']).stdout.strip()
    for path in ['/etc/sing-box/config.json', '/etc/xboard-node/config.yml', '/etc/xboard-node/config.yaml',
                 '/etc/wireguard/wg-vpn-stage1.conf', '/etc/wireguard/wg-xboard.conf']:
        if Path(path).is_file():
            result[path] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return result


def status():
    manifest = PRIVATE / 'endpoints.json'
    return {'service': run(['systemctl', 'is-active', SERVICE], False).stdout.strip(),
            'auth_service': run(['systemctl', 'is-active', AUTH_SERVICE], False).stdout.strip(),
            'enabled': run(['systemctl', 'is-enabled', SERVICE], False).stdout.strip(),
            'ports': [r['port'] for r in json.loads(manifest.read_text())['endpoints']] if manifest.exists() else [],
            'binary_sha256': hashlib.sha256(BINARY.read_bytes()).hexdigest() if BINARY.exists() else None}


def install(host, source):
    if host not in HOSTS or os.geteuid() != 0:
        raise RuntimeError('unexpected_target_or_user')
    addresses = run(['ip', '-j', 'address']).stdout
    if not any(a.get('local') == host for i in json.loads(addresses) for a in i.get('addr_info', [])):
        raise RuntimeError('target_ip_not_local')
    if hashlib.sha256(source.read_bytes()).hexdigest() != BINARY_SHA256:
        raise RuntimeError('binary_digest_mismatch')
    if AUTH_UNIT.exists() or UNIT.exists() or ROOT.exists() or PRIVATE.exists() or BINARY.exists():
        raise RuntimeError('existing_installation_use_status_or_reviewed_update')
    for port in PORTS:
        for addr, number in [(host, port), ('127.0.0.1', port + 1000)]:
            with socket.socket() as probe:
                probe.bind((addr, number))
    before = baseline()
    PRIVATE.mkdir(mode=0o700)
    save(PRIVATE / 'baseline.json', json.dumps(before, indent=2))
    save(PRIVATE / 'nft.before.txt', run(['nft', 'list', 'ruleset']).stdout)
    save(PRIVATE / 'ufw.before.txt', run(['ufw', 'status'], False).stdout)
    for username in [USER, AUTH_USER]:
        try:
            pwd.getpwnam(username)
            raise RuntimeError('service_user_already_exists')
        except KeyError:
            run(['useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', username])
    user = pwd.getpwnam(USER)
    auth_user = pwd.getpwnam(AUTH_USER)
    ROOT.mkdir(mode=0o750)
    ROOT.chmod(0o750)
    os.chown(ROOT, 0, user.pw_gid)
    rows = [{'host': host, 'port': port, 'username': 'cp_' + secrets.token_hex(6),
             'password': secrets.token_urlsafe(24), 'protocols': ['socks5', 'http'],
             'speed_limit_mbps_per_direction': 100, 'quota_bytes': None, 'assigned_to': None}
            for port in PORTS]
    save(PRIVATE / 'endpoints.json', json.dumps({'host': host, 'version': '3.3.3', 'endpoints': rows}, indent=2))
    save(ROOT / 'config.json', json.dumps(config_for(host, rows), indent=2), 0o640)
    os.chown(ROOT / 'config.json', 0, user.pw_gid)
    save(ROOT / 'auth.json', json.dumps(auth_config(rows), indent=2), 0o640)
    os.chown(ROOT / 'auth.json', 0, user.pw_gid)
    run(['/usr/bin/sing-box', 'check', '-c', str(ROOT / 'auth.json')])
    BINARY.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
    BINARY.parent.chmod(0o755)
    shutil.copyfile(source, BINARY)
    BINARY.chmod(0o755)
    # OUTPUT-only guard applies to this service UID. It also blocks DNS rebinding to private destinations.
    cidrs = ', '.join(BLOCKED[:9] + [ip + '/32' for ip in sorted(HOSTS)])
    guard = (f'table inet xboard_proxy_guard {{\n chain output {{\n'
             f' type filter hook output priority -5; policy accept;\n'
             f' meta skuid {{ {user.pw_uid}, {auth_user.pw_uid} }} ct state established,related accept\n'
             f' meta skuid {user.pw_uid} ip daddr 127.0.0.1 tcp dport 21001-21010 accept\n'
             f' meta skuid {user.pw_uid} reject\n'
             f' meta skuid {auth_user.pw_uid} ip daddr 127.0.0.53 udp dport 53 accept\n'
             f' meta skuid {auth_user.pw_uid} ip daddr 127.0.0.53 tcp dport 53 accept\n'
             f' meta skuid {auth_user.pw_uid} ip daddr {{ {cidrs} }} reject\n'
             f' meta skuid {auth_user.pw_uid} meta nfproto ipv6 reject\n'
             ' }\n}\n')
    save(ROOT / 'guard.nft', guard, 0o644)
    unit = f'''[Unit]
Description=Xboard independent HTTP and SOCKS5 endpoints
After=network-online.target xboard-proxy-auth.service
Wants=network-online.target
Requires=xboard-proxy-auth.service

[Service]
Type=simple
User={USER}
Group={USER}
ExecStartPre=-+/usr/sbin/nft delete table inet xboard_proxy_guard
ExecStartPre=+/usr/sbin/nft -f {ROOT}/guard.nft
ExecStart={BINARY} -C {ROOT}/config.json
ExecStopPost=-+/usr/sbin/nft delete table inet xboard_proxy_guard
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_UNIX
CapabilityBoundingSet=
LockPersonality=yes
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
'''
    save(UNIT, unit, 0o644)
    auth_unit = unit.replace('Description=Xboard independent HTTP and SOCKS5 endpoints', 'Description=Xboard isolated mixed protocol authentication').replace('After=network-online.target xboard-proxy-auth.service', 'After=network-online.target').replace('Requires=xboard-proxy-auth.service\n', '').replace('User=' + USER, 'User=' + AUTH_USER)
    auth_unit = '\n'.join(line for line in auth_unit.splitlines() if not line.startswith(('ExecStartPre=', 'ExecStopPost='))) + '\n'
    auth_unit = auth_unit.replace(f'ExecStart={BINARY} -C {ROOT}/config.json', f'ExecStart=/usr/bin/sing-box run -c {ROOT}/auth.json')
    auth_unit = auth_unit.replace('RestrictAddressFamilies=AF_INET AF_UNIX',
                                  'RestrictAddressFamilies=AF_INET AF_UNIX AF_NETLINK')
    save(AUTH_UNIT, auth_unit, 0o644)
    opened_ufw = False
    try:
        run(['nft', '--check', '-f', str(ROOT / 'guard.nft')])
        run(['systemd-analyze', 'verify', str(UNIT), str(AUTH_UNIT)])
        run(['runuser', '-u', USER, '--', 'test', '-x', str(BINARY)])
        run(['runuser', '-u', AUTH_USER, '-g', USER, '--', 'test', '-r', str(ROOT / 'auth.json')])
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', '--now', SERVICE])
        time.sleep(2)
        if run(['systemctl', 'is-active', SERVICE], False).stdout.strip() != 'active':
            raise RuntimeError('new_service_not_active')
        if run(['systemctl', 'is-active', AUTH_SERVICE], False).stdout.strip() != 'active':
            raise RuntimeError('authentication_service_not_active')
        for port in PORTS:
            with socket.create_connection(('127.0.0.1', port + 1000), timeout=3):
                pass
            with socket.create_connection((host, port), timeout=3):
                pass
        if 'Status: active' in (PRIVATE / 'ufw.before.txt').read_text():
            run(['ufw', 'allow', 'proto', 'tcp', 'to', host, 'port', '20001:20010', 'comment', 'xboard-proxy-endpoints'])
            opened_ufw = True
        save(PRIVATE / 'firewall.json', json.dumps({'ufw_rule_added': opened_ufw, 'host': host}))
        if baseline() != before:
            raise RuntimeError('existing_service_or_config_changed')
    except Exception:
        run(['systemctl', 'disable', '--now', SERVICE, AUTH_SERVICE], False)
        if opened_ufw:
            run(['ufw', 'delete', 'allow', 'proto', 'tcp', 'to', host, 'port', '20001:20010'], False)
        raise
    return {**status(), 'existing_services_unchanged': True, 'credentials_file': str(PRIVATE / 'endpoints.json')}


def stop():
    run(['systemctl', 'disable', '--now', SERVICE, AUTH_SERVICE])
    path = PRIVATE / 'firewall.json'
    if path.exists():
        firewall = json.loads(path.read_text())
        if firewall['ufw_rule_added']:
            run(['ufw', 'delete', 'allow', 'proto', 'tcp', 'to', firewall['host'], 'port', '20001:20010'])
            firewall['ufw_rule_added'] = False
            save(path, json.dumps(firewall))
    return status()


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'status', 'stop'])
    parser.add_argument('--host', choices=sorted(HOSTS))
    parser.add_argument('--binary', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'install':
            if not args.host or not args.binary:
                parser.error('install requires --host and --binary')
            result = install(args.host, args.binary)
        else:
            result = status() if args.action == 'status' else stop()
        print(json.dumps(result))
    except Exception as exc:
        # Avoid command stdout/stderr or configuration content in deployment logs.
        print(json.dumps({'error': str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__}))
        raise SystemExit(1)
