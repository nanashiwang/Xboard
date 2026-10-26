import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prepare', Path(__file__).resolve().parents[2] / '.docker/upstream/prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class CandidatePreparationTest(unittest.TestCase):
    def setUp(self):
        self.pin = base64.b64encode(b'a' * 32).decode()
        self.new_pin = base64.b64encode(b'b' * 32).decode()
        self.allocation = {'machine_id': 21, 'ordinary_owned_ids': [148], 'routes': []}
        self.approved, self.proxies, self.snapshot = [], [], {'machine_id': 21, 'routes': []}
        for n in range(1, 42):
            key, backend = 'U%02d' % n, 359 + (n - 1) * 2
            protocol = 'anytls' if n <= 28 else 'trojan' if n <= 31 else 'vless' if n <= 34 else 'hysteria2'
            self.allocation['routes'].append({'key': key, 'backend_id': backend, 'public_id': backend + 1, 'upstream_type': protocol})
            source = {'name': 'private-source-' + key, 'type': protocol, 'server': 'source.private.example', 'port': 443,
                      'sni': 'sni.private.example', 'password': 'never-print-password', 'skip-cert-verify': True}
            self.proxies.append(source)
            self.approved.append({'key': key, 'backend_id': backend, 'public_id': backend + 1,
                                  'source_name': source['name'], 'source_sha256': prepare.digest(source)})
            settings = {'server': '1.1.1.1', 'server_port': 443, 'password': source['password'],
                        'tls': {'enabled': True, 'insecure': False, 'server_name': source['sni'], 'certificate_public_key_sha256': [self.pin]}}
            self.snapshot['routes'].append({'key': key, 'backend': {'id': backend, 'machine_id': 21,
                'tags': ['upstream-extension-backend'], 'enabled': True, 'custom_outbounds': [{'protocol': protocol, 'settings': settings}]},
                'public': {'id': backend + 1, 'parent_id': backend, 'tags': ['upstream-extension-public'], 'show': True}})
        self.usage = {'expire': 10000, 'total': 1000, 'upload': 1, 'download': 2}

    def run_prepare(self, **kwargs):
        args = dict(allocation=self.allocation, approved=self.approved, snapshot=self.snapshot, proxies=self.proxies,
                    usage=self.usage, now=100, resolver=lambda h, p: (['8.8.8.8'], False),
                    observer=lambda ip, port, sni: {'pin': self.pin if ip == '1.1.1.1' else self.new_pin,
                    'not_before': 1, 'not_after': 99999, 'certificate_time_valid': True})
        args.update(kwargs)
        return prepare.prepare_rows(**args)

    def test_discovery_never_changes_input_or_approves_new_pin(self):
        before = copy.deepcopy((self.allocation, self.approved, self.snapshot, self.proxies))
        private, report = self.run_prepare()
        self.assertEqual(before, (self.allocation, self.approved, self.snapshot, self.proxies))
        self.assertEqual(41, len(report))
        self.assertEqual(31, sum(bool(row['candidates']) for row in report))
        self.assertTrue(all(c['reason'] == 'observed_not_approved' for r in report for c in r['candidates']))
        self.assertEqual([True, False], [x['old_pin_matches'] for x in report[0]['candidates']])
        self.assertEqual(self.new_pin, private[0]['candidates'][1]['identity']['pin'])

    def test_public_report_redacts_every_private_source_and_identity_field(self):
        _, report = self.run_prepare()
        raw = json.dumps(report)
        for secret in ['source.private.example', 'sni.private.example', 'never-print-password', '1.1.1.1', '8.8.8.8', self.pin, self.new_pin, 'private-source-']:
            self.assertNotIn(secret, raw)
        self.assertEqual(hashlib.sha256(b'private-source-U01').hexdigest(), report[0]['source_name_sha256'])

    def test_candidate_commitment_is_exact_stable_identity_tuple(self):
        private, report = self.run_prepare()
        identity = {'key': 'U01', 'ip': '8.8.8.8', 'port': 443, 'sni': 'sni.private.example', 'pin': self.new_pin}
        self.assertEqual(prepare.digest(identity), report[0]['candidates'][1]['candidate_digest'])
        self.assertEqual(report[0]['candidates'][1]['candidate_digest'], private[0]['candidates'][1]['candidate_digest'])

    def test_ambiguous_or_changed_source_produces_no_candidate(self):
        self.proxies.append(copy.deepcopy(self.proxies[0]))
        self.proxies[1]['password'] = 'changed'
        private, report = self.run_prepare()
        for row in report[:2]:
            self.assertFalse(row['source_matches_approved'])
            self.assertEqual([], row['candidates'])
            self.assertEqual('source_changed_or_ambiguous', row['reason'])

    def test_missing_scope_duplicate_id_or_wrong_parent_is_fatal(self):
        for mutation in [lambda: self.approved.pop(), lambda: self.snapshot['routes'][0]['public'].update(parent_id=999),
                         lambda: self.approved.append(copy.deepcopy(self.approved[0])),
                         lambda: self.allocation.update(machine_id=20)]:
            self.setUp();mutation()
            with self.assertRaises(prepare.ContractError): self.run_prepare()

    def test_no_quota_or_near_expiry_never_probes(self):
        for usage in [dict(self.usage, expire=300), dict(self.usage, download=999)]:
            _, report = self.run_prepare(usage=usage, observer=lambda *a: self.fail('must not probe'))
            self.assertTrue(all(row['reason'] == 'quota_or_expiry_rejected' for row in report))

    def test_dns_failure_still_observes_current_approved_endpoint(self):
        def failed(*a): raise RuntimeError('private-host-private-error')
        _, report = self.run_prepare(resolver=failed)
        self.assertEqual('dns_resolution_failed', report[0]['dns_reason'])
        self.assertEqual(1, len(report[0]['candidates']))
        self.assertTrue(report[0]['candidates'][0]['current_endpoint'])

    def test_current_insecure_or_source_credential_mismatch_is_rejected(self):
        for mutation in [lambda s: s['tls'].update(insecure=True), lambda s: s.update(password='other'),
                         lambda s: s['tls'].update(certificate_public_key_sha256=['bad'])]:
            self.setUp();mutation(self.snapshot['routes'][0]['backend']['custom_outbounds'][0]['settings'])
            _, report = self.run_prepare()
            self.assertEqual('current_source_contract_mismatch', report[0]['reason'])
            self.assertEqual([], report[0]['candidates'])

    def test_plan_is_private_exclusive_and_its_hash_covers_saved_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'plans'
            plan_id, digest, path = prepare.save_plan(root, {'routes': self.snapshot['routes']})
            self.assertEqual(32, len(plan_id))
            saved = path / 'plan.private.json'
            self.assertEqual(0o700, path.stat().st_mode & 0o777)
            self.assertEqual(0o600, saved.stat().st_mode & 0o777)
            self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(), digest)

    def test_private_file_rejects_world_readability_and_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'private';path.write_text('{}');path.chmod(0o644)
            with self.assertRaises(prepare.ContractError): prepare.private_file(path)
            path.chmod(0o600)
            alias = path.with_name('alias');alias.symlink_to(path)
            with self.assertRaises(prepare.ContractError): prepare.private_file(alias)
            self.assertEqual(b'{}', prepare.private_file(path))

    def test_resolver_rejects_private_answers(self):
        for address in ['127.0.0.1', '224.0.0.1', 'ff00::1', '240.0.0.1']:
            body = json.dumps([address]).encode()
            with patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, body)):
                with self.assertRaises(prepare.ContractError): prepare.resolve('allowed.example', 443)

    def test_failed_private_snapshot_exposes_only_whitelisted_stage(self):
        before = prepare.STAGE
        try:
            for stage, expected in [('mapping', 'database_snapshot_mapping'),
                                    ('secret-host-and-password', 'database_snapshot')]:
                prepare.STAGE = 'database_snapshot'
                reply = json.dumps({'error': 'snapshot_failed', 'stage': stage}).encode()
                with patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, reply)):
                    with self.assertRaises(prepare.ContractError): prepare.snapshot_database(self.allocation)
                self.assertEqual(expected, prepare.STAGE)
        finally:
            prepare.STAGE = before

    def test_certificate_spki_and_validity_use_real_openssl(self):
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary)
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(p/'key'),
                            '-out', str(p/'cert'), '-days', '1', '-subj', '/CN=test.invalid'], check=True, capture_output=True)
            der = subprocess.check_output(['openssl', 'x509', '-in', str(p/'cert'), '-outform', 'DER'])
            pin, start, end = prepare.certificate_data(der, lambda: 5)
            self.assertEqual(32, len(base64.b64decode(pin)))
            self.assertGreater(end, start)


if __name__ == '__main__': unittest.main()
