import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[2] / ".docker/production/website-relay-origin.py"
SPEC = importlib.util.spec_from_file_location("website_relay_origin", SCRIPT)
origin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(origin)

BEFORE = b"""# fixture contains both unchanged ACME and application servers
server {
    listen 80;
    server_name taige.us;
    location ^~ /.well-known/acme-challenge/ { root /var/www/xboard-acme; }
    location / { return 301 https://taige.us$request_uri; }
}
server {
    listen 443 ssl http2;
    server_name taige.us;
    ssl_certificate /etc/letsencrypt/live/taige.us/fullchain.pem;
    include /root/Xboard/.docker/.data/qiyun-cdn-nginx.conf;
    include /opt/xboard-downloads/nginx.conf;
    location / {
        proxy_pass http://127.0.0.1:7001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
"""


class OriginRelayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.config = root / "taige.us.conf"
        self.config.write_bytes(BEFORE)
        self.config.chmod(0o640)
        self.patches = [patch.object(origin, "CONFIG", self.config),
                        patch.object(origin, "BACKUPS", root / "backups"),
                        patch.object(origin, "BASELINE_SHA256", hashlib.sha256(BEFORE).hexdigest())]
        for item in self.patches:
            item.start()
        self.addCleanup(self.temporary.cleanup)
        for item in self.patches:
            self.addCleanup(item.stop)

    def prepare(self):
        with patch.object(origin, "run", return_value=(0, "", "")):
            return origin.prepare("test-change")

    def test_only_https_identity_changes_and_acme_includes_preserved(self):
        after = origin.build_candidate(BEFORE)
        previous, updated = origin.parse(BEFORE.decode()), origin.parse(after.decode())
        self.assertEqual(previous[0], updated[0])
        self.assertIn(b"include /root/Xboard/.docker/.data/qiyun-cdn-nginx.conf;", after)
        self.assertIn(b"include /opt/xboard-downloads/nginx.conf;", after)
        self.assertIn(b"set_real_ip_from 155.103.118.155;", after)
        self.assertIn(b"set_real_ip_from 2606:4700::/32;", after)
        self.assertNotIn(b"$proxy_add_x_forwarded_for", after)
        self.assertIn(b'proxy_set_header Forwarded "";', after)

    def test_baseline_and_target_file_conflicts_refuse_before_mutation(self):
        with self.assertRaisesRegex(origin.OperationError, "baseline_sha"):
            origin.build_candidate(BEFORE + b"# concurrent update\n")
        state = self.prepare()
        self.config.write_bytes(BEFORE + b"# concurrent update\n")
        with self.assertRaisesRegex(origin.OperationError, "active_config_conflict"):
            origin.apply_change("test-change")
        self.assertEqual(self.config.read_bytes(), BEFORE + b"# concurrent update\n")
        self.assertEqual(state["before_sha256"], hashlib.sha256(BEFORE).hexdigest())

    def test_symlink_target_rejected(self):
        other = self.config.with_suffix(".real")
        self.config.rename(other)
        self.config.symlink_to(other)
        with self.assertRaisesRegex(origin.OperationError, "not_regular"):
            origin.current_config()

    def test_prepare_is_private_and_does_not_activate(self):
        state = self.prepare()
        self.assertEqual(self.config.read_bytes(), BEFORE)
        backup = Path(state["backup_directory"])
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual((backup / "before.conf").stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.prepare()["already_prepared"])

    def test_apply_and_rollback_preserve_original_bytes_and_mode(self):
        self.prepare()
        with patch.object(origin, "run", return_value=(0, "", "")):
            result = origin.apply_change("test-change")
            self.assertEqual(result["active_sha256"], origin.digest(self.config.read_bytes()))
            self.assertNotEqual(self.config.read_bytes(), BEFORE)
            self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
            origin.apply_change("test-change", rollback=True)
        self.assertEqual(self.config.read_bytes(), BEFORE)

    def test_nginx_test_failure_restores_original_before_returning_failure(self):
        self.prepare()
        results = [(0, "", ""), (1, "", "secret config diagnostics"), (0, "", ""), (0, "", "")]
        with patch.object(origin, "run", side_effect=results) as commands:
            with self.assertRaisesRegex(origin.OperationError, "candidate_nginx_config_invalid_previous_config_restored"):
                origin.apply_change("test-change")
        self.assertEqual(self.config.read_bytes(), BEFORE)
        self.assertEqual(commands.call_args_list[-1].args[0], ["systemctl", "reload", "nginx"])

    def test_reload_failure_restores_original_and_reloads(self):
        self.prepare()
        results = [(0, "", ""), (0, "", ""), (1, "", ""), (0, "", ""), (0, "", "")]
        with patch.object(origin, "run", side_effect=results):
            with self.assertRaisesRegex(origin.OperationError, "candidate_nginx_reload_failed_previous_config_restored"):
                origin.apply_change("test-change")
        self.assertEqual(self.config.read_bytes(), BEFORE)

    def test_rollback_does_not_overwrite_later_changes(self):
        self.prepare()
        with patch.object(origin, "run", return_value=(0, "", "")):
            origin.apply_change("test-change")
        later = self.config.read_bytes() + b"# later operator change\n"
        self.config.write_bytes(later)
        with self.assertRaisesRegex(origin.OperationError, "active_config_conflict"):
            origin.apply_change("test-change", rollback=True)
        self.assertEqual(self.config.read_bytes(), later)

    def test_tampered_backup_rejected(self):
        state = self.prepare()
        (Path(state["backup_directory"]) / "after.conf").write_bytes(b"tampered")
        with self.assertRaisesRegex(origin.OperationError, "backup_after_hash_mismatch"):
            origin.read_state("test-change")

    def test_failed_verification_removes_temporary_location_and_listener(self):
        self.prepare()
        with patch.object(origin, "run", return_value=(0, "", "")):
            origin.apply_change("test-change")
        applied = self.config.read_bytes()
        receiver = Mock()
        receiver.server_address = ("127.0.0.1", 38001)
        with patch.object(origin, "ThreadingHTTPServer", return_value=receiver), \
                patch.object(origin, "run", return_value=(0, "", "")), \
                patch.object(origin, "curl_probe", side_effect=origin.OperationError("probe_failed")):
            with self.assertRaisesRegex(origin.OperationError, "probe_failed"):
                origin.verify("test-change")
        self.assertEqual(self.config.read_bytes(), applied)
        self.assertNotIn(b"__xboard_relay_verify", self.config.read_bytes())
        receiver.shutdown.assert_called_once()
        receiver.server_close.assert_called_once()

    def test_probe_retries_only_reload_404_or_connection_failure(self):
        with patch.object(origin, "run", side_effect=[(22, "\n404", ""), (0, "ok\n200", "")]), \
                patch.object(origin.time, "sleep"):
            self.assertEqual(origin.curl_probe("https://taige.us/probe", origin.RELAY), "ok")
        with patch.object(origin, "run", return_value=(22, "\n502", "")) as requests:
            with self.assertRaisesRegex(origin.OperationError, "verification_http_request_failed"):
                origin.curl_probe("https://taige.us/probe", origin.RELAY)
        self.assertEqual(requests.call_count, 1)

    def test_inspection_does_not_print_sensitive_headers_or_response_bodies(self):
        nodes = origin.parse('server { server_name taige.us; proxy_set_header Authorization "Bearer SECRET"; '
                             'proxy_set_header CF-Connecting-IP SECRET; return 200 "PRIVATE_BODY"; }')
        rendered = json.dumps(origin.render_safe(nodes))
        self.assertNotIn("SECRET", rendered)
        self.assertNotIn("PRIVATE_BODY", rendered)
        self.assertEqual(origin.safe_args("proxy_pass", ["https://user:pass@example.com/"]),
                         ["<upstream contains credentials or query; omitted>"])


if __name__ == "__main__":
    unittest.main()
