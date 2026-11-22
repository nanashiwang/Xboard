"""Synchronize registered fixed routes and independently verify test leases on the actual ingress."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import urllib.request

import stage1

STATE = Path('/etc/xboard-proxy-enrollment')
ROUTES = Path('/etc/nginx/snippets/xboard-px-registered.conf')
TRUST = Path('/etc/nginx/xboard-px-registered')
API = 'https://capybarago.uk/api/v1/proxy-agent/ingress'
VHOST = Path('/etc/nginx/sites-available/node.lumavia.fyi.conf')
SCRIPT = Path('/usr/local/lib/xboard-proxy-enrollment/ingress.py')


def exchange(token, payload=None):
    req = urllib.request.Request(API, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={'Authorization':'Bearer '+token, 'Content-Type':'application/json'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=15) as reply:
        if payload is None:
            return json.load(reply)


def install(token):
    old = VHOST.read_bytes()
    anchor = f'include {stage1.SNIPPET};'.encode()
    include = f'include {ROUTES};'.encode()
    if old.count(anchor) != 1:
        raise RuntimeError('expected existing residential ingress')
    exchange(token)
    if subprocess.run(['/usr/bin/python3','-c','from websockets.legacy.client import connect'], capture_output=True).returncode:
        stage1.run('apt-get','update','-qq')
        stage1.run('apt-get','install','-y','--no-install-recommends','python3-websockets')
    if not ROUTES.exists():
        stage1.write(ROUTES, b'')
    if include not in old:
        try:
            stage1.write(VHOST, old.replace(anchor, anchor+b'\n '+include))
            stage1.run('nginx','-t')
            stage1.run('systemctl','reload','nginx')
        except BaseException:
            stage1.write(VHOST, old)
            raise
    stage1.write(STATE/'ingress-token', token.encode(), 0o600)
    unit = Path('/etc/systemd/system/xboard-proxy-ingress')
    stage1.write(unit.with_suffix('.service'), f"""[Unit]
Description=Synchronize registered residential proxy routes and verify pending exits
After=network-online.target nginx.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {SCRIPT}
TimeoutStartSec=540
UMask=0077
""".encode())
    stage1.write(unit.with_suffix('.timer'), b"""[Unit]
Description=Poll for residential proxy registrations
[Timer]
OnBootSec=10
OnUnitInactiveSec=10
AccuracySec=2
[Install]
WantedBy=timers.target
""")
    stage1.run('systemctl','daemon-reload')
    stage1.run('systemctl','enable','--now','xboard-proxy-ingress.timer')
    stage1.run('systemctl','start','xboard-proxy-ingress.service')


def route_for(row):
    host = ipaddress.IPv4Address(row['address'])
    if type(row['id']) != int or row['id'] < 1 or not host.is_global or host.is_multicast:
        raise ValueError('invalid registered host')
    key = 'h' + str(row['id'])
    cert = row['cert'].encode('ascii')
    if not re.fullmatch(br'-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*', cert):
        raise ValueError('invalid certificate')
    # Immutable trust file. A bad pending certificate cannot overwrite an active route.
    dest = TRUST/(key+'.crt')
    if dest.exists() and dest.read_bytes() != cert:
        raise ValueError('certificate changed')
    with tempfile.NamedTemporaryFile() as f:
        f.write(cert); f.flush()
        stage1.run('openssl','verify','-verify_hostname',f'px-{key}.internal','-CAfile',f.name,f.name)
    stage1.write(dest, cert)
    return key, str(host)


def update_routes(rows):
    TRUST.mkdir(mode=0o755, exist_ok=True)
    expected = {}
    invalid = set()
    for row in rows:
        try:
            key, host = route_for(row)
            expected[key] = host
        except (ValueError, subprocess.CalledProcessError):
            invalid.add(row['id'])
    old = ROUTES.read_bytes()
    new = stage1.routes(expected, str(TRUST)).encode()
    if old != new:
        try:
            stage1.write(ROUTES, new)
            stage1.run('nginx','-t')
            stage1.run('systemctl','reload','nginx')
        except BaseException:
            stage1.write(ROUTES, old)
            raise
    return invalid


def proxy_check(host, port, scheme, credentials, expected):
    # curl config on stdin keeps disposable authentication out of process arguments.
    args = ['curl','--disable','--silent','--fail','--noproxy','','--max-time','12',
            '--proxy',f'{scheme}://{host}:{port}', '--config','-', '--write-out','\n%{http_connect}',
            'https://www.cloudflare.com/cdn-cgi/trace']
    cfg = 'proxy-user = '+json.dumps(credentials['username']+':'+credentials['password'])+'\n'
    p = subprocess.run(args, input=cfg, text=True, capture_output=True, timeout=15)
    if expected is None:
        return p.stdout.splitlines()[-1:] == ['407'] if scheme == 'http' else p.returncode == 97
    return p.returncode == 0 and ('ip='+expected) in p.stdout.splitlines()


def verify_port(host, route, row):
    port = row['port']
    if port not in stage1.PORTS:
        return 'route'
    return asyncio.run(verify_route(host, port, route, row))


async def verify_route(host, port, route, credentials):
    from websockets.legacy.client import connect
    from websockets.exceptions import WebSocketException
    async def tunnel(reader, writer):
        try:
            async with connect(f'wss://node.lumavia.fyi/residential/v1/{route}/{port}',
                               open_timeout=8, close_timeout=1) as ws:
                async def upload():
                    while chunk := await reader.read(32768):
                        await ws.send(chunk)
                async def download():
                    async for chunk in ws:
                        writer.write(chunk)
                        await writer.drain()
                tasks = [asyncio.create_task(upload()), asyncio.create_task(download())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks: task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except (OSError, TimeoutError, WebSocketException):
            pass
        finally:
            writer.close()

    async with await asyncio.start_server(tunnel, '127.0.0.1', 0) as server:
        local = server.sockets[0].getsockname()[1]
        for scheme in ['http','socks5h']:
            if not await asyncio.to_thread(proxy_check, host, port, scheme, credentials, host):
                return 'direct'
            if not await asyncio.to_thread(proxy_check, '127.0.0.1', local, scheme, credentials, host):
                return 'route'
            invalid = dict(credentials, password=secrets.token_hex(20))
            if not await asyncio.to_thread(proxy_check, '127.0.0.1', local, scheme, invalid, None):
                return 'auth'
    return None


def tick():
    token = (STATE/'ingress-token').read_text().strip()
    rows = exchange(token)['hosts']
    invalid = update_routes(rows)
    for row in rows:
        probe = row.get('probe')
        if not probe:
            continue
        if [p['port'] for p in probe['ports']] != list(stage1.PORTS):
            raise ValueError('unexpected test inventory')
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = ['route'] if row['id'] in invalid else list(pool.map(
                lambda port: verify_port(row['address'],'h'+str(row['id']),port), probe['ports']))
        error = next((r for r in results if r), None)
        exchange(token, {'id':row['id'],'probe':probe['id'],'passed':error is None,'error':error})


if __name__ == '__main__':
    tick()
