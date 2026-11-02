import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / '.docker/production/configure-go-domain.py'
spec = importlib.util.spec_from_file_location('go_domain', SCRIPT)
domain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(domain)
SOURCE = b'''server {
    listen 80;
    server_name taige.us;
}
server {
    listen 443 ssl http2;
    server_name taige.us;
    set_real_ip_from 155.103.118.155;
    set_real_ip_from 173.245.48.0/20;
    ssl_certificate /etc/letsencrypt/live/taige.us/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/taige.us/privkey.pem;
    include /root/Xboard/.docker/.data/qiyun-cdn-nginx.conf;
    include /opt/xboard-downloads/nginx.conf;
    location / {
        proxy_pass http://127.0.0.1:7001;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host taige.us;
    }
}
'''


class GoDomainTests(unittest.TestCase):
    def test_candidate_preserves_app_and_downloads_without_exposing_node_routes(self):
        with patch.object(domain, 'SOURCE_SHA', hashlib.sha256(SOURCE).hexdigest()):
            candidate = domain.https_config(SOURCE).decode()
        self.assertIn('server_name capybarago.uk;', candidate)
        self.assertIn('/etc/letsencrypt/live/capybarago.uk/fullchain.pem', candidate)
        self.assertIn('proxy_set_header X-Forwarded-Host capybarago.uk;', candidate)
        self.assertIn('proxy_pass http://127.0.0.1:7001;', candidate)
        self.assertIn('include /opt/xboard-downloads/nginx.conf;', candidate)
        self.assertIn('set_real_ip_from 173.245.48.0/20;', candidate)
        self.assertNotIn('155.103.118.155', candidate)
        self.assertNotIn('qiyun-cdn', candidate)
        self.assertIn('capybara_go_safe', candidate)

    def test_source_drift_stops_before_candidate_creation(self):
        with self.assertRaisesRegex(RuntimeError, 'Source vhost changed'):
            domain.https_config(SOURCE)

    def test_invalid_nginx_candidate_restores_previous_managed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'sites-enabled' / 'capybarago.uk.conf'
            target.parent.mkdir()
            before = domain.http_config().encode()
            target.write_bytes(before)
            with patch.object(domain, 'TARGET', target), patch.object(domain, 'run', side_effect=[RuntimeError('invalid nginx'), '', '']):
                with self.assertRaisesRegex(RuntimeError, 'invalid nginx'):
                    domain.activate_bytes(before + b'# candidate\n')
            self.assertEqual(target.read_bytes(), before)

    def test_unmanaged_vhost_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'capybarago.uk.conf'
            target.write_bytes(b'# another owner\n')
            with patch.object(domain, 'TARGET', target):
                with self.assertRaisesRegex(RuntimeError, 'unmanaged'):
                    domain.activate_bytes(domain.http_config().encode())
            self.assertEqual(target.read_bytes(), b'# another owner\n')


    def test_promote_rejects_unexpected_origins_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(domain, 'BACKUP', Path(directory)), patch.object(domain, 'verify'), patch.object(domain, 'application_settings', return_value={'app_url': 'https://other.example', 'subscribe_url': 'https://taige.us'}) as settings:
                with self.assertRaisesRegex(RuntimeError, 'Unexpected application origins'):
                    domain.change_primary('promote')
                settings.assert_called_once_with()
                self.assertFalse((Path(directory) / 'settings.before.json').exists())

    def test_promote_backs_up_only_origins_and_supports_guarded_rollback(self):
        old = {'app_url': 'https://taige.us', 'subscribe_url': 'https://taige.us'}
        new = {'app_url': 'https://capybarago.uk', 'subscribe_url': 'https://capybarago.uk'}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(domain, 'BACKUP', Path(directory)), patch.object(domain, 'verify'), patch.object(domain, 'run'), patch.object(domain, 'application_settings', side_effect=[old, new, new, old]) as settings:
                self.assertEqual(domain.change_primary('promote')['origins'], new)
                self.assertEqual((Path(directory) / 'settings.before.json').stat().st_mode & 0o777, 0o600)
                self.assertEqual(domain.change_primary('rollback-settings')['origins'], old)
                self.assertEqual(settings.call_args_list[1].args, (old, new))
                self.assertEqual(settings.call_args_list[3].args, (new, old))


    def test_probe_uses_the_published_origin_and_keeps_tls_verification(self):
        with patch.object(domain, 'run', side_effect=['点击进入官网', 'clients', 'desktop', '{"data": {}}', 'checksum']) as command:
            self.assertEqual(len(domain.verify()), 5)
            for call in command.call_args_list:
                self.assertIn('capybarago.uk:443:107.173.191.23', call.args)
                self.assertNotIn('-k', call.args)
                self.assertNotIn('--insecure', call.args)


if __name__ == '__main__':
    unittest.main()
