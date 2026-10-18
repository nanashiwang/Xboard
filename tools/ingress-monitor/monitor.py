#!/usr/bin/env python3
"""Read-only Linux ingress collector. No proxy node, routing or firewall changes."""
import concurrent.futures
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlsplit

STOP = threading.Event()


def command(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=6, env={**os.environ, 'LC_ALL': 'C'})


def counters(interface):
    cpu = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    folder = Path('/sys/class/net') / interface / 'statistics'
    return (time.monotonic(), sum(cpu), cpu[3] + cpu[4],
            int((folder / 'rx_bytes').read_text()), int((folder / 'tx_bytes').read_text()))


def rates(before, after):
    seconds = max(.01, after[0] - before[0]); total = after[1] - before[1]
    return (round(max(0, min(100, 100 * (1 - (after[2] - before[2]) / total))), 2) if total > 0 else 0,
            {'in_speed': max(0, after[3] - before[3]) / seconds, 'out_speed': max(0, after[4] - before[4]) / seconds})


def ping_peer(ip):
    result = {'ip': str(ipaddress.ip_address(ip)), 'loss_percent': None, 'rtt_ms': None}
    try:
        r = command(['ping', '-n', '-c', '3', '-i', '0.2', '-W', '1', '-w', '4', result['ip']])
        loss = re.search(r'([\d.]+)% packet loss', r.stdout)
        rtt = re.search(r'=\s*[\d.]+/([\d.]+)/', r.stdout)
        if loss: result['loss_percent'] = float(loss[1])
        if rtt: result['rtt_ms'] = float(rtt[1])
    except (OSError, ValueError, subprocess.SubprocessError):
        pass  # Missing tool or insufficient permission is unknown, not 100% packet loss.
    return result


def tunnel_status(interface, ips):
    def active(name):
        try: return command(['systemctl', 'is-active', '--quiet', name]).returncode == 0
        except (OSError, subprocess.SubprocessError): return False
    handshakes = {}
    try:
        allowed = command(['wg', 'show', interface, 'allowed-ips'])
        latest = command(['wg', 'show', interface, 'latest-handshakes'])
        if allowed.returncode == 0 and latest.returncode == 0:
            keys = dict(line.split() for line in latest.stdout.splitlines())
            for line in allowed.stdout.splitlines():
                key, networks = line.split(None, 1)
                for net in networks.split(','):
                    network = ipaddress.ip_network(net.strip())
                    if network.prefixlen == network.max_prefixlen:
                        handshakes[str(network.network_address)] = int(keys.get(key, 0))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        peers = list(executor.map(ping_peer, ips))
    for peer in peers: peer['handshake_at'] = handshakes.get(peer['ip'])
    return {'nginx': active('nginx'), 'wireguard': active('wg-quick@' + interface), 'peers': peers}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def validate(settings):
    url = urlsplit(settings['panel_url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        raise ValueError('HTTPS panel origin required')
    for key in ('network_interface', 'wireguard_interface'):
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,30}', settings[key]): raise ValueError('invalid interface')
    if not 1 <= len(settings['peers']) <= 50: raise ValueError('peer scope')
    for ip in settings['peers']: ipaddress.ip_address(ip)
    if not isinstance(settings['machine_id'], int) or settings['machine_id'] < 1 or len(settings['token']) != 32: raise ValueError('machine credentials')


def main():
    os.umask(0o077)
    settings = json.loads(Path(os.getenv('INGRESS_CONFIG', '/etc/xboard-ingress-monitor.json')).read_text())
    validate(settings)
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, lambda *_: STOP.set())
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    before = counters(settings['network_interface'])
    STOP.wait(1)
    while not STOP.is_set():
        try:
            after = counters(settings['network_interface']); cpu, net = rates(before, after); before = after
            mem = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()}
            disk = os.statvfs('/')
            ingress = tunnel_status(settings['wireguard_interface'], settings['peers'])
            ingress['interface'] = settings['network_interface']
            payload = {'machine_id': settings['machine_id'], 'token': settings['token'], 'cpu': cpu,
                       'mem': {'total': mem['MemTotal'], 'used': mem['MemTotal'] - mem['MemAvailable']},
                       'disk': {'total': disk.f_blocks * disk.f_frsize, 'used': (disk.f_blocks - disk.f_bfree) * disk.f_frsize},
                       'net': net, 'ingress': ingress}
            request = urllib.request.Request(settings['panel_url'].rstrip('/') + '/api/v2/server/machine/status',
                                             data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'Xboard-Ingress-Monitor/1.0.0'})
            with http.open(request, timeout=20) as response:
                if json.loads(response.read(4096)).get('data') is not True: raise ValueError('report not accepted')
            print(json.dumps({'reported': True, 'peers': len(ingress['peers']), 'at': int(time.time())}), flush=True)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            print(json.dumps({'reported': False, 'error_type': type(error).__name__}), flush=True)
        STOP.wait(60)


if __name__ == '__main__': main()
