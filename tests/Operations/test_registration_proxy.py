import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('guardproxy',ROOT/'.docker/production/registration-proxy.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
class ProxyPolicyTest(unittest.TestCase):
    def test_relay_trusts_only_cf_preserves_upstream_and_go(self):
        original=(ROOT/'.docker/production/website-relay.conf').read_bytes()
        candidate=guard.candidate(original,'relay').decode()
        self.assertEqual(candidate.count('set_real_ip_from '),22)
        self.assertIn('set_real_ip_from 2606:4700::/32;',candidate)
        self.assertNotIn('set_real_ip_from 0.0.0.0/0',candidate)
        self.assertIn('proxy_ssl_verify on;',candidate)
        self.assertIn('proxy_set_header CF-Connecting-IP $remote_addr;',candidate)
        self.assertIn('real_ip_recursive off;',candidate)
        self.assertNotIn('real_ip_header',(ROOT/'.docker/production/go-relay.conf').read_text())
    def test_changed_configs_are_rejected(self):
        with self.assertRaises(guard.base.OperationError): guard.candidate(b'unknown','relay')
        with self.assertRaises(guard.base.OperationError): guard.candidate(b'unknown','board')
    def test_board_only_adds_scoped_trust_and_sanitized_headers(self):
        source='''server { listen 80; server_name board.taige.us; return 301 https://$host$request_uri; }
server {
    ssl_certificate /etc/nginx/ssl/board.taige.us/fullchain.pem;
    location / {
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
'''.encode()
        original_sha=guard.BOARD_SHA
        try:
            guard.BOARD_SHA=guard.base.digest(source)
            result=guard.candidate(source,'board').decode()
            self.assertNotIn('$proxy_add_x_forwarded_for',result)
            self.assertIn('proxy_set_header X-Forwarded-For $remote_addr;',result)
            self.assertIn('proxy_set_header Forwarded "";',result)
            self.assertNotIn('set_real_ip_from 155.103.118.155;',result)
        finally: guard.BOARD_SHA=original_sha
if __name__=='__main__': unittest.main()
