"""One-shot installer run on a registered exit or the existing stage-one ingress."""
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import pwd
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile

import manage
import stage1

API = 'https://capybarago.uk/api/v1/proxy-agent'
STATE = Path('/etc/xboard-proxy-enrollment')
SCRIPTS = Path('/usr/local/lib/xboard-proxy-enrollment')
UNITS = Path('/etc/systemd/system')
GOST = ('https://github.com/go-gost/gost/releases/download/v3.3.3/gost_3.3.3_linux_amd64.tar.gz',
        'f4c1255dc892a7014c0ad6e5f1c3573108f7bea4403f04f21873406ab58aa666')
SING = ('https://github.com/SagerNet/sing-box/releases/download/v1.12.10/sing-box-1.12.10-linux-amd64.tar.gz',
        '4b4dc09818bebaeb88c14e7e499984f0f77361e962ce19b20037703d6b307608')


def run(*args):
    subprocess.run(args, check=True)


def store(path, data, mode=0o600, gid=0):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        f.write(data)
        os.fchmod(f.fileno(), mode)
        os.fchown(f.fileno(), 0, gid)
    os.replace(f.name, path)


def api(route, token, body):
    req = urllib.request.Request(API + '/' + route, data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as r:
        return r.read(1024 * 1024)


def binary(spec, member, dest):
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / 'binary.tgz'
        run('curl', '--proto', '=https', '--proto-redir', '=https', '-fsSL', '--retry', '3', spec[0], '-o', str(archive))
        if hashlib.sha256(archive.read_bytes()).hexdigest() != spec[1]:
            raise ValueError('download checksum mismatch')
        with tarfile.open(archive) as tar:
            info = tar.getmember(member)
            if not info.isfile() or info.size > 200_000_000:
                raise ValueError('unexpected binary archive')
            store(dest, tar.extractfile(info).read(), 0o755)


def dependencies(packages):
    missing = [pkg for cmd, pkg in packages if not shutil.which(cmd)]
    if missing:
        run('apt-get', 'update', '-qq')
        run('apt-get', 'install', '-y', '--no-install-recommends', *missing)


def service_user(name):
    try:
        return pwd.getpwnam(name)
    except KeyError:
        run('useradd', '--system', '--user-group', '--no-create-home', '--shell', '/usr/sbin/nologin', name)
        return pwd.getpwnam(name)


def install_exit(args, code):
    host = str(ipaddress.IPv4Address(args.address))
    local = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr']))
    if not any(a['local'] == host for nic in local for a in nic.get('addr_info', [])):
        raise ValueError('registered IPv4 must be assigned to this machine')
    identity = STATE / 'identity.json'
    if not identity.exists():
        if any(p.exists() for p in (manage.ROOT, manage.UNIT, manage.BINARY, stage1.DIRECTORY)):
            raise ValueError('existing proxy deployment requires operator inspection')
        for user in (manage.USER, manage.AUTH_USER, stage1.USER):
            try:
                pwd.getpwnam(user)
            except KeyError:
                continue
            raise ValueError('service account already exists')
        for port in stage1.PORTS:
            for addr, n in ((host, port), ('127.0.0.1', port+1000), (host, port+3000)):
                with socket.socket() as check:
                    check.bind((addr, n))
        store(identity, json.dumps({'id': args.id, 'address': host, 'token': secrets.token_hex(32)}).encode())
    config = json.loads(identity.read_text())
    if (config['id'], config['address']) != (args.id, host):
        raise ValueError('machine already belongs to a different registration')
    if not (STATE / 'claimed').exists():
        try:
            api('claim', code, {'id': args.id, 'digest': hashlib.sha256(config['token'].encode()).hexdigest()})
        except urllib.error.HTTPError as e:
            if e.code != 409:
                raise
            # Resume if the claim succeeded but its response was lost.
            api('sync', config['token'], {'reports': []})
        store(STATE / 'claimed', b'1')
    dependencies([('nft', 'nftables'), ('openssl', 'openssl'), ('curl', 'curl'), ('ss', 'iproute2')])
    manage.BINARY.parent.mkdir(exist_ok=True, parents=True, mode=0o755)
    manage.BINARY.parent.chmod(0o755)
    if not manage.BINARY.exists():
        binary(GOST, 'gost', manage.BINARY)
    if hashlib.sha256(manage.BINARY.read_bytes()).hexdigest() != manage.BINARY_SHA256:
        raise ValueError('GOST checksum mismatch')
    core = Path('/usr/bin/sing-box')
    if not core.is_file():
        core = manage.BINARY.parent / 'sing-box'
        if not core.is_file():
            binary(SING, 'sing-box-1.12.10-linux-amd64/sing-box', core)
    user = service_user(manage.USER)
    auth = service_user(manage.AUTH_USER)
    manage.ROOT.mkdir(exist_ok=True)
    manage.ROOT.chmod(0o750)
    os.chown(manage.ROOT, 0, user.pw_gid)
    rows = [{'port': p} for p in stage1.PORTS]
    store(manage.ROOT/'config.json', json.dumps(manage.config_for(host, rows)).encode(), 0o640, user.pw_gid)
    store(manage.ROOT/'guard.nft', manage.guard_config(manage.HOSTS | {host}, user, auth).encode(), 0o644)
    store(manage.ROOT/'agent.json', json.dumps(dict(config, url=API+'/sync', enrolled=True)).encode())
    # The guard remains installed while any leased authentication service can run.
    store(manage.UNIT, f'''[Unit]
Description=Residential proxy forwarding and per-port bandwidth limits
After=network-online.target
[Service]
User={manage.USER}
ExecStartPre=-+/usr/sbin/nft delete table inet xboard_proxy_guard
ExecStartPre=+/usr/sbin/nft -f {manage.ROOT}/guard.nft
ExecStart={manage.BINARY} -C {manage.ROOT}/config.json
Restart=on-failure
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
[Install]
WantedBy=multi-user.target
'''.encode(), 0o644)
    store(UNITS/'xboard-proxy-agent.service', f'''[Unit]
Description=Residential port lease agent
After=network-online.target xboard-proxy-endpoints.service
Requires=xboard-proxy-endpoints.service
[Service]
ExecStart=/usr/bin/python3 {SCRIPTS}/agent.py
ExecStopPost=/usr/bin/python3 {SCRIPTS}/agent.py --revoke
Restart=always
RestartSec=5
UMask=0077
[Install]
WantedBy=multi-user.target
'''.encode(), 0o644)
    store(UNITS/'xboard-proxy-port@.service', f'''[Unit]
Description=Residential lease for port %i
BindsTo=xboard-proxy-agent.service xboard-proxy-endpoints.service
After=xboard-proxy-agent.service xboard-proxy-endpoints.service
[Service]
User={manage.AUTH_USER}
Group={manage.USER}
ExecStart={core} run -c {manage.ROOT}/port-%i.json
ProtectSystem=strict
ProtectHome=yes
NoNewPrivileges=yes
RestrictAddressFamilies=AF_INET AF_UNIX AF_NETLINK
CapabilityBoundingSet=
'''.encode(), 0o644)
    run('nft', '--check', '-f', str(manage.ROOT/'guard.nft'))
    key = 'h' + str(args.id)
    stage1.HOSTS[key] = host
    stage1.install_exit(key)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', manage.SERVICE, 'xboard-proxy-agent.service')
    if shutil.which('ufw') and 'Status: active' in subprocess.check_output(['ufw','status'], text=True):
        run('ufw', 'allow', 'proto', 'tcp', 'to', host, 'port', '20001:20010')
    print('安装完成。请在「家宽订阅与容量」中选择「验收并上架」。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='role', required=True)
    exit_args = sub.add_parser('exit')
    exit_args.add_argument('id', type=int)
    exit_args.add_argument('address')
    sub.add_parser('ingress')
    args = parser.parse_args()
    if os.geteuid() or sys.platform != 'linux' or not Path('/run/systemd/system').is_dir():
        raise SystemExit('requires Linux systemd and root')
    if args.role == 'exit' and platform.machine() != 'x86_64':
        raise SystemExit('currently supports Linux x86_64')
    token = sys.stdin.readline().strip()
    if len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
        raise SystemExit('invalid installation credential')
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE/'installer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        SCRIPTS.mkdir(mode=0o755, exist_ok=True, parents=True)
        with zipfile.ZipFile(sys.argv[0]) as archive:
            for name in ['agent.py', 'stage1.py', 'ingress.py']:
                store(SCRIPTS/name, archive.read(name), 0o644)
        if args.role == 'exit':
            install_exit(args, token)
        else:
            import ingress
            ingress.install(token)


if __name__ == '__main__':
    main()
