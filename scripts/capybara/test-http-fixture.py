"""Loopback-only, synthetic HTTP fixture for the PowerShell diagnostic tests."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import base64
import hashlib
import struct
import sys
import time


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        if self.path.startswith('/logs?'):
            key = self.headers['Sec-WebSocket-Key']
            accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', accept)
            self.end_headers()
            for text in ['x509: certificate failure private-path-canary', 'lookup secret.example: no such host', 'uuid-private-canary']:
                data = json.dumps({'type': 'warning', 'payload': text}).encode()
                prefix = bytes([0x81, len(data)]) if len(data) < 126 else b'\x81\x7e' + struct.pack('!H', len(data))
                self.wfile.write(prefix + data)
            self.wfile.flush()
            return
        if self.path == '/timeout':
            time.sleep(2)
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', 'http://127.0.0.1:1/credentials-must-not-follow')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        body = json.dumps({'authorized': self.headers.get('Authorization') == 'Bearer test-secret-never-export-123456'}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.path == '/body-timeout':
            time.sleep(2)
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
Path(sys.argv[1]).write_text(str(server.server_port))
server.serve_forever()
