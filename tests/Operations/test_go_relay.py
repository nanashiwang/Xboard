import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
def load(name, filename):
    spec=importlib.util.spec_from_file_location(name, ROOT/'.docker/production'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

go=load('go_origin', 'go-relay-origin.py')
relay=load('go_relay', 'go-relay-deploy.py')
BEFORE=b'''server { server_name capybarago.uk; listen 80; }
log_format capybara_go_safe '$status';
server {
    server_name capybarago.uk;
    set_real_ip_from 173.245.48.0/20;
    real_ip_header CF-Connecting-IP;
    real_ip_recursive off;
    location / { proxy_set_header X-Forwarded-For $remote_addr; }
}
'''

class GoRelayTests(unittest.TestCase):
    def test_origin_adds_only_exact_relay_trust(self):
        with patch.object(go.origin,'BASELINE_SHA256', hashlib.sha256(BEFORE).hexdigest()):
            after=go.build_candidate(BEFORE)
        self.assertEqual(after.replace(b'    set_real_ip_from 155.103.118.155;\n',b''), BEFORE)
        self.assertEqual(len(list(go.origin.matching_servers(go.origin.parse(after.decode())))),2)

    def test_origin_rejects_drift(self):
        with self.assertRaisesRegex(go.origin.OperationError,'baseline_sha'):
            go.build_candidate(BEFORE)

    def test_template_derivation_uses_unique_names_and_strict_tls(self):
        text=(ROOT/'.docker/production/go-relay.conf').read_text()
        self.assertEqual(text,(ROOT/'.docker/production/website-relay.conf').read_text().replace('taige.us','capybarago.uk').replace('xboard_website','capybara_go_relay').replace('xboard-website','capybara-go-relay').replace('@xboard_origin_acme','@capybara_go_origin_acme'))
        for value in ['proxy_ssl_verify on;', 'proxy_set_header CF-Connecting-IP $remote_addr;', 'proxy_set_header X-Forwarded-For $remote_addr;', 'try_files $uri @capybara_go_origin_acme;', 'proxy_cache off;']:
            self.assertIn(value,text)
        self.assertNotIn('$proxy_add_x_forwarded_for',text)

    def test_failed_activation_removes_only_new_vhost(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'sites-enabled'/'capybarago.uk';target.parent.mkdir()
            with patch.object(relay,'TARGET',target),patch.object(relay,'run',side_effect=[RuntimeError('nginx failed'),'','']):
                with self.assertRaises(RuntimeError):relay.activate(b'new candidate')
            self.assertFalse(target.exists())

    def test_unknown_existing_vhost_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'capybarago.uk';target.write_bytes(b'other owner')
            with patch.object(relay,'TARGET',target):
                with self.assertRaisesRegex(RuntimeError,'another Go'):relay.activate(b'new candidate')
            self.assertEqual(target.read_bytes(),b'other owner')

    def test_laravel_diagnostics_match_selected_domain(self):
        import subprocess
        samples=[{'name':'probe','expected':'127.0.0.1','headers':{}}]
        def capture(*args, **kwargs):
            self.assertIn("https://capybarago.uk/",kwargs['input'])
            self.assertIn("=== 'capybarago.uk'",kwargs['input'])
            return subprocess.CompletedProcess(args,0,'{"probe":{"client_ip_matches":true,"scheme_https":true,"host_matches":true}}','')
        with patch.object(go.origin.subprocess,'run',side_effect=capture):
            go.origin.laravel_assertions(samples)

if __name__=='__main__':unittest.main()
