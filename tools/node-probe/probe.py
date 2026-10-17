#!/usr/bin/env python3
"""Xboard scoped node probe. No TUN, direct fallback or third-party Python packages."""
import concurrent.futures
import contextlib
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlencode
import uuid

VERSION = '1.0.0'
STOP = threading.Event()


def clean_env():
    return {k: v for k, v in os.environ.items() if k.lower() not in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')}


def runtime_config(outbound, port):
    if outbound.get('type') in ('direct', 'selector', 'urltest', 'block') or outbound.get('detour'):
        raise ValueError('unsupported outbound')
    if outbound.get('tls', {}).get('insecure'):
        raise ValueError('insecure TLS')
    return {'log': {'disabled': True}, 'dns': {'servers': [{'type': 'local', 'tag': 'local'}]},
            'inbounds': [{'type': 'socks', 'listen': '127.0.0.1', 'listen_port': port}],
            'outbounds': [{**outbound, 'tag': 'node'}],
            'route': {'final': 'node', 'default_domain_resolver': 'local'}}


def error_code(code):
    return {5: 'dns', 6: 'dns', 7: 'connect', 28: 'timeout', 35: 'tls', 60: 'tls', 97: 'proxy', 18: 'incomplete', 63: 'incomplete'}.get(code, 'unknown')


def curl_check(port, target, folder, size=0):
    kind = target['id']
    body = Path(folder) / (kind + '.body')
    url = target['url']
    if urlsplit(url).scheme != 'https':
        raise ValueError('HTTPS required')
    args = ['curl', '--silent', '--show-error', '--proxy', f'socks5h://127.0.0.1:{port}', '--noproxy', '',
            '--proto', '=https', '--connect-timeout', '5', '--max-time', '15' if size else '8',
            '--max-filesize', str(max(size, 65536)), '--output', str(body), '--write-out', '%{json}']
    if kind == 'upload':
        payload = Path(folder) / 'payload'
        payload.write_bytes(os.urandom(size))
        args += ['--request', 'POST', '--header', 'Content-Type: application/octet-stream', '--data-binary', '@' + str(payload)]
    if kind == 'download':
        url += ('&' if '?' in url else '?') + urlencode({'bytes': size, 'nonce': str(uuid.uuid4())})
    args.append(url)
    try:
        result = subprocess.run(args, capture_output=True, timeout=18, env=clean_env())
        metrics = json.loads(result.stdout or '{}')
        status = int(metrics.get('http_code', 0))
        count = int(metrics.get('size_upload' if kind == 'upload' else 'size_download', 0))
        code = error_code(result.returncode) if result.returncode else None
        if not code and status != target.get('status', 200): code = 'http'
        if not code and size and count != size: code = 'incomplete'
        if not code and kind == 'download' and (not body.exists() or body.stat().st_size != size): code = 'incomplete'
        ms = min(60000, round(float(metrics.get('time_total', 0)) * 1000, 2))
        check = {'id': kind, 'status': status, 'ms': ms, 'bytes': min(count, 4194304), 'error': code}
        exit_ip = None
        if kind == 'cloudflare' and not code and body.exists():
            for line in body.read_text(errors='replace').splitlines():
                if line.startswith('ip='):
                    try: exit_ip = str(ipaddress.ip_address(line[3:]))
                    except ValueError: pass
        if kind == 'cloudflare' and not code and not exit_ip: check['error'] = 'incomplete'
        return check, exit_ip
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return {'id': kind, 'status': 0, 'ms': 18000, 'bytes': 0, 'error': 'unknown'}, None


@contextlib.contextmanager
def core(outbound, folder):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    config = Path(folder) / 'core.json'
    config.write_text(json.dumps(runtime_config(outbound, port)))
    config.chmod(0o600)
    checked = subprocess.run(['sing-box', 'check', '-c', str(config)], capture_output=True, timeout=10, env=clean_env())
    if checked.returncode: raise ValueError('core_config')
    process = subprocess.Popen(['sing-box', 'run', '-c', str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env())
    try:
        ready = False
        for _ in range(50):
            if process.poll() is not None: break
            try:
                with socket.create_connection(('127.0.0.1', port), .1): ready = True
                break
            except OSError: time.sleep(.05)
        if not ready: raise ValueError('core_config')
        yield port
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def measure(node, config, transfer):
    sample = {'sample_id': str(uuid.uuid4()), 'server_id': node['id'], 'checks': []}
    if node.get('error'):
        sample['error'] = node['error']
    else:
        try:
            with tempfile.TemporaryDirectory(prefix='xboard-probe-') as folder, core(node['outbound'], folder) as port:
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(lambda t: curl_check(port, t, folder), config['targets']))
                sample['checks'] = [c for c, _ in results]
                sample['exit_ip'] = next((ip for _, ip in results if ip), None)
                if transfer:
                    for kind in ('upload', 'download'):
                        c, _ = curl_check(port, {'id': kind, 'url': config[kind + '_url'], 'status': 200}, folder, config['transfer_bytes'])
                        sample['checks'].append(c)
        except FileNotFoundError:
            sample.update(error='core_unavailable', checks=[])
        except (OSError, ValueError, subprocess.SubprocessError):
            sample.update(error='core_config', checks=[])
    sample['checked_at'] = int(time.time())
    return sample


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Agent:
    def __init__(self, settings, state_dir):
        self.url = settings['panel_url'].rstrip('/')
        parsed = urlsplit(self.url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('panel_url must be an HTTPS origin')
        if parsed.path not in ('', '/') or len(settings['token']) != 64: raise ValueError('invalid config')
        self.token = settings['token']
        self.state_path = Path(state_dir) / 'transfers.json'
        try: self.transfers = json.loads(self.state_path.read_text())
        except (OSError, ValueError): self.transfers = {}
        # Explicit empty proxy handler prevents inheriting a machine-wide proxy for reporting.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def post(self, path, data):
        request = urllib.request.Request(self.url + '/api/v2/probe/' + path, data=json.dumps(data).encode(),
                                         headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json', 'Accept': 'application/json'})
        with self.http.open(request, timeout=20) as response:
            return json.loads(response.read(2 * 1024 * 1024))['data']

    def cycle(self):
        config = self.post('config', {'agent_version': VERSION})
        if config['version'] != 1 or not 1 <= len(config['nodes']) <= 50: raise ValueError('config version or scope')
        if not 60 <= config['interval_seconds'] <= 3600 or not 1800 <= config['transfer_interval_seconds'] <= 86400: raise ValueError('cadence')
        if not 65536 <= config['transfer_bytes'] <= 1048576: raise ValueError('transfer budget')
        now = time.time()
        jobs = []
        for node in config['nodes']:
            key = str(node['id'])
            due = not node.get('error') and now - self.transfers.get(key, 0) >= config['transfer_interval_seconds']
            if due: self.transfers[key] = now  # Also back off failed transfer attempts, across restarts.
            jobs.append((node, due))
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.transfers))
        tmp.replace(self.state_path)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(measure, node, config, due) for node, due in jobs]
            for future in concurrent.futures.as_completed(futures):
                sample = future.result()
                try:
                    self.post('report', sample)
                    print(json.dumps({'node': sample['server_id'], 'checked_at': sample['checked_at'], 'error': sample.get('error'),
                                      'checks': [{k: c[k] for k in ('id', 'status', 'ms', 'bytes', 'error')} for c in sample['checks']],
                                      'exit_ip': sample.get('exit_ip')}), flush=True)
                except (OSError, ValueError):
                    # Do not print credentials, URLs, raw exception/remote response or core stderr.
                    print(json.dumps({'node': sample['server_id'], 'error': 'report_failed'}), flush=True)
        return config['interval_seconds']


def main():
    os.umask(0o077)
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, lambda *_: STOP.set())
    state = Path(os.getenv('PROBE_STATE', '/state'))
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'agent.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        agent = Agent(json.loads(Path(os.getenv('PROBE_CONFIG', '/config/agent.json')).read_text()), state)
        while not STOP.is_set():
            try: interval = agent.cycle()
            except (OSError, ValueError, KeyError, urllib.error.HTTPError):
                print(json.dumps({'error': 'panel_unavailable_or_config_invalid'}), flush=True)
                interval = 60
            STOP.wait(interval)


if __name__ == '__main__': main()
