"""Verify public endpoints using a private manifest. Outputs only ports and check outcomes."""
import argparse
import base64
import concurrent.futures
import json
from pathlib import Path
import socket
import ssl
import struct
import subprocess


def receive(conn, count):
    result = b''
    while len(result) < count:
        chunk = conn.recv(count - len(result))
        if not chunk:
            break
        result += chunk
    return result


def socks_auth(row, username=None, password=None, anonymous=False):
    with socket.create_connection((row['host'], row['port']), timeout=8) as conn:
        conn.settimeout(8)
        conn.sendall(b'\x05\x01' + (b'\x00' if anonymous else b'\x02'))
        greeting = receive(conn, 2)
        if anonymous:
            return greeting == b'\x05\xff'
        if greeting != b'\x05\x02':
            return False
        user = (username if username is not None else row['username']).encode()
        secret = (password if password is not None else row['password']).encode()
        conn.sendall(b'\x01' + bytes([len(user)]) + user + bytes([len(secret)]) + secret)
        return receive(conn, 2) == b'\x01\x01'


def http_auth_rejected(row, username=None, password=None):
    with socket.create_connection((row['host'], row['port']), timeout=8) as conn:
        conn.settimeout(8)
        auth = ''
        if username is not None:
            value = base64.b64encode((username + ':' + password).encode()).decode()
            auth = 'Proxy-Authorization: Basic ' + value + '\r\n'
        conn.sendall(('CONNECT www.cloudflare.com:443 HTTP/1.1\r\nHost: www.cloudflare.com:443\r\n' + auth + '\r\n').encode())
        data = b''
        while b'\r\n' not in data and len(data) < 2048:
            chunk = conn.recv(512)
            if not chunk:
                break
            data += chunk
        return b' 407 ' in data.split(b'\r\n')[0]


def curl(row, protocol, url):
    options = {'proxy': f"{protocol}://{row['host']}:{row['port']}",
               'proxy-user': row['username'] + ':' + row['password'], 'url': url,
               'max-time': '18', 'connect-timeout': '8', 'noproxy': ''}
    config = '\n'.join(k + ' = ' + json.dumps(v) for k, v in options.items())
    r = subprocess.run(['curl', '-fsS', '--config', '-', '--write-out', '\n%{http_code}'],
                       input=config, text=True, capture_output=True, timeout=23)
    body, _, code = r.stdout.rpartition('\n')
    return r.returncode, body, code


def verify(row, other):
    checks = {}
    for protocol in ['socks5h', 'http']:
        rc, body, status = curl(row, protocol, 'https://www.cloudflare.com/cdn-cgi/trace')
        checks[protocol + '_https_exit'] = rc == 0 and status == '200' and ('ip=' + row['host']) in body.splitlines()
        if not checks[protocol + '_https_exit']:
            rc, body, status = curl(row, protocol, 'https://www.cloudflare.com/cdn-cgi/trace')
            checks[protocol + '_https_exit'] = rc == 0 and status == '200' and ('ip=' + row['host']) in body.splitlines()
    rc, body, status = curl(row, 'http', 'http://www.cloudflare.com/cdn-cgi/trace')
    checks['http_forward_exit'] = rc == 0 and status == '200' and ('ip=' + row['host']) in body.splitlines()
    checks['socks5_no_auth_rejected'] = socks_auth(row, anonymous=True)
    checks['socks5_wrong_password_rejected'] = socks_auth(row, password='invalid-fixture-password')
    checks['socks5_cross_port_rejected'] = socks_auth(row, other['username'], other['password'])
    checks['http_no_auth_rejected'] = http_auth_rejected(row)
    checks['http_wrong_password_rejected'] = http_auth_rejected(row, row['username'], 'invalid-fixture-password')
    checks['http_cross_port_rejected'] = http_auth_rejected(row, other['username'], other['password'])
    with socket.create_connection((row['host'], row['port']), timeout=8) as conn:
        conn.settimeout(8)
        conn.sendall(b'\x04\x01' + struct.pack('!H', 443) + socket.inet_aton('1.1.1.1') + row['username'].encode() + b'\x00')
        response = receive(conn, 8)
        checks['socks4_rejected'] = len(response) < 2 or response[1] != 0x5a
    for protocol in ['http', 'socks5h']:
        rc, _, status = curl(row, protocol, 'http://127.0.0.1:22/')
        checks[protocol + '_private_destination_rejected'] = rc != 0
    # A raw TLS connection must not become a separate unauthenticated SNI proxy.
    with socket.create_connection((row['host'], row['port']), timeout=8) as conn:
        conn.settimeout(5)
        try:
            with ssl.create_default_context().wrap_socket(conn, server_hostname='www.cloudflare.com'):
                checks['raw_tls_rejected'] = False
        except (ssl.SSLError, OSError):
            checks['raw_tls_rejected'] = True
    return {'host': row['host'], 'port': row['port'], 'checks': checks, 'ok': all(checks.values())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    rows = json.loads(args.manifest.read_text())['endpoints']

    def safe(index):
        try:
            return verify(rows[index], rows[(index + 1) % len(rows)])
        except Exception as exc:
            return {'host': rows[index]['host'], 'port': rows[index]['port'], 'ok': False, 'error': type(exc).__name__}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(safe, range(len(rows))))
    print(json.dumps({'results': results, 'passed': sum(row['ok'] for row in results), 'total': len(rows)}))
    raise SystemExit(0 if all(row['ok'] for row in results) else 1)
