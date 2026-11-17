"""Exercise the pinned GOST service limiter with real concurrent transfers."""
import concurrent.futures
import http.server
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest

spec = importlib.util.spec_from_file_location('endpoints', Path(__file__).parents[2] / '.docker/proxy-endpoints/manage.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
PAYLOAD = b'x' * (256 * 1024)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)


@unittest.skipUnless(os.environ.get('GOST_TEST_BINARY'), 'Set GOST_TEST_BINARY to the verified executable')
class LimiterTest(unittest.TestCase):
    def test_concurrent_connections_share_limit_and_endpoints_are_independent(self):
        servers = []
        rows = []
        for _ in range(2):
            for port in range(24000, 25000):
                if any(r['port'] == port for r in rows):
                    continue
                try:
                    with socket.socket() as s:
                        s.bind(('127.0.0.1', port))
                    server = http.server.ThreadingHTTPServer(('127.0.0.1', port + 1000), Handler)
                    break
                except OSError:
                    continue
            servers.append(server)
            rows.append({'port': port})
            threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'gost.json'
            config.write_text(json.dumps(module.config_for('127.0.0.1', rows, rate=65536)))
            child = subprocess.Popen([os.environ['GOST_TEST_BINARY'], '-C', str(config)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(30):
                    try:
                        with socket.create_connection(('127.0.0.1', rows[-1]['port']), timeout=.1):
                            break
                    except OSError:
                        time.sleep(.1)

                def transfer(row):
                    start = time.monotonic()
                    r = subprocess.run(['curl', '--noproxy', '*', '-fsS', '--max-time', '25',
                                        f"http://127.0.0.1:{row['port']}/"], capture_output=True)
                    self.assertEqual(r.returncode, 0)
                    self.assertEqual(r.stdout, PAYLOAD)
                    return time.monotonic() - start

                start = time.monotonic()
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                    durations = list(pool.map(transfer, [rows[0], rows[0], rows[1], rows[1]]))
                elapsed = time.monotonic() - start
                # Per-connection limiting would finish around four seconds. A shared
                # limiter across both endpoints would take about sixteen seconds.
                self.assertGreater(elapsed, 6)
                self.assertLess(elapsed, 13)
                self.assertGreater(max(durations[:2]), 6)
                self.assertGreater(max(durations[2:]), 6)
                print(json.dumps({'four_transfers_seconds': round(elapsed, 2),
                                  'bytes_each': len(PAYLOAD), 'bytes_per_second_per_endpoint': 65536}))
            finally:
                child.terminate()
                child.wait(timeout=5)
                for server in servers:
                    server.shutdown()
                    server.server_close()


if __name__ == '__main__':
    unittest.main()
