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
            if protocol == 'vless':
                source.pop('password')
                source.update(uuid='00000000-0000-4000-8000-000000000001', tls=True, **{'skip-cert-verify': False})
                settings.pop('password')
                settings['uuid'] = source['uuid']
                settings['tls'].pop('certificate_public_key_sha256')
                self.approved[-1]['source_sha256'] = prepare.digest(source)
            self.snapshot['routes'].append({'key': key, 'backend': {'id': backend, 'machine_id': 21,
                'tags': ['upstream-extension-backend'], 'enabled': True, 'custom_outbounds': [{'protocol': protocol, 'settings': settings}]},
                'public': {'id': backend + 1, 'parent_id': backend, 'tags': ['upstream-extension-public'], 'show': True}})
        self.usage = {'expire': 10000, 'total': 1000, 'upload': 1, 'download': 2}

    def run_prepare(self, **kwargs):
        args = dict(allocation=self.allocation, approved=self.approved, snapshot=self.snapshot, proxies=self.proxies,
                    usage=self.usage, now=100, resolver=lambda h, p: (['8.8.8.8'], False),
                    observer=lambda ip, port, sni: {'pin': self.pin if ip == '1.1.1.1' else self.new_pin,
                    'not_before': 1, 'not_after': 99999, 'certificate_time_valid': True},
                    quic_observer=lambda ip, port, sni, alpn: {'pin': self.pin if ip == '1.1.1.1' else self.new_pin,
                    'not_before': 1, 'not_after': 99999, 'certificate_time_valid': True},
                    ca_observer=lambda ip, port, sni, alpn: {'pin': self.new_pin, 'not_before': 1,
                    'not_after': 99999, 'certificate_time_valid': True, 'ca_validated': True})
        args.update(kwargs)
        return prepare.prepare_rows(**args)

    def test_discovery_never_changes_input_or_approves_new_pin(self):
        before = copy.deepcopy((self.allocation, self.approved, self.snapshot, self.proxies))
        private, report = self.run_prepare()
        self.assertEqual(before, (self.allocation, self.approved, self.snapshot, self.proxies))
        self.assertEqual(41, len(report))
        self.assertEqual(41, sum(bool(row['candidates']) for row in report))
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
                    with self.assertRaises(prepare.ContractError): prepare.snapshot_database(self.allocation, b'{}')
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

    def test_snapshot_diagnostics_never_forward_arbitrary_values(self):
        details = {'manifest_exists': False, 'manifest_readable': 'secret', 'route_count': 41,
                   'machine_matches': True, 'unknown': 'password'}
        reply = json.dumps({'error': 'snapshot_failed', 'stage': 'manifest', 'diagnostics': details}).encode()
        with patch.object(prepare, 'DIAGNOSTICS', {}), patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, reply)):
            with self.assertRaises(prepare.ContractError): prepare.snapshot_database(self.allocation, b'{}')
            self.assertEqual({'manifest_exists': False, 'machine_matches': True, 'route_count': 41}, prepare.DIAGNOSTICS)

    def test_hy2_uses_quic_only_and_preserves_candidate_and_source_commitments(self):
        tcp, quic = [], []
        def observe_tcp(ip, port, sni):
            tcp.append((ip, port, sni))
            return {'reason': 'tls_failed'}
        def observe_quic(ip, port, sni, alpn):
            quic.append((ip, port, sni, alpn))
            return {'pin': self.new_pin, 'not_before': 1, 'not_after': 99999, 'certificate_time_valid': False}
        private, report = self.run_prepare(observer=observe_tcp, quic_observer=observe_quic)
        self.assertEqual(62, len(tcp))
        self.assertEqual(14, len(quic))
        self.assertTrue(all(call[-1] == ['h3'] for call in quic))
        for index in range(34, 41):
            row = report[index]
            self.assertEqual(self.approved[index]['source_sha256'], row['approved_source_sha256'])
            self.assertEqual(row['approved_source_sha256'], row['observed_source_sha256'])
            self.assertTrue(row['source_matches_approved'])
            for candidate, stored in zip(row['candidates'], private[index]['candidates']):
                self.assertEqual(prepare.digest(stored['identity']), candidate['candidate_digest'])
                self.assertFalse(candidate['certificate_time_valid'])
                self.assertFalse(candidate['old_pin_matches'])
                self.assertEqual('observed_not_approved', candidate['reason'])
        self.assertTrue(all(row['candidates'][0]['ca_validated'] for row in report[31:34]))

    def test_hy2_rejects_changed_source_insecure_obfs_hopping_and_transport_mismatch(self):
        mutations = [lambda source, settings: source.update(obfs='salamander'),
                     lambda source, settings: settings.update(obfs={'type': 'salamander', 'password': 'secret'}),
                     lambda source, settings: source.update(ports='443-444'),
                     lambda source, settings: settings.update(server_ports=['443:444']),
                     lambda source, settings: source.update(alpn=['private-protocol']),
                     lambda source, settings: settings['tls'].update(alpn=['private-protocol']),
                     lambda source, settings: settings['tls'].update(insecure=True),
                     lambda source, settings: source.update(network='ws')]
        for mutation in mutations:
            self.setUp()
            source = self.proxies[34]
            settings = self.snapshot['routes'][34]['backend']['custom_outbounds'][0]['settings']
            mutation(source, settings)
            self.approved[34]['source_sha256'] = prepare.digest(source)
            _, report = self.run_prepare()
            self.assertEqual('current_source_contract_mismatch', report[34]['reason'])
            self.assertEqual([], report[34]['candidates'])
        self.setUp()
        self.proxies[34]['password'] = 'changed-source'
        _, report = self.run_prepare()
        self.assertEqual('source_changed_or_ambiguous', report[34]['reason'])
        self.assertEqual([], report[34]['candidates'])

    def test_missing_quic_observer_never_falls_back_to_tcp(self):
        _, report = self.run_prepare(quic_observer=None)
        self.assertEqual(34, sum(bool(row['candidates']) for row in report))
        self.assertTrue(all(row['reason'] == 'identity_tool_unavailable' for row in report[34:]))

    def test_quic_tool_requires_private_regular_fixed_sibling_and_exact_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary = directory / prepare.QUIC_TOOL_NAME
            binary.write_bytes(b'controlled-binary-fixture')
            binary.chmod(0o700)
            checksum = hashlib.sha256(binary.read_bytes()).hexdigest()
            with patch.object(prepare, 'SIBLING', directory):
                self.assertEqual(binary, prepare.verify_quic_tool(checksum))
                for wrong in ['f' * 64, 'secret-value', None]:
                    with self.assertRaises(prepare.ContractError): prepare.verify_quic_tool(wrong)
                binary.chmod(0o755)
                with self.assertRaises(prepare.ContractError): prepare.verify_quic_tool(checksum)
                binary.chmod(0o700)
                directory.chmod(0o755)
                with self.assertRaises(prepare.ContractError): prepare.verify_quic_tool(checksum)
                directory.chmod(0o700)
                binary.rename(directory / 'other')
                binary.symlink_to(directory / 'other')
                with self.assertRaises((OSError, prepare.ContractError)): prepare.verify_quic_tool(checksum)

    def test_quic_wrapper_sends_no_auth_and_accepts_only_private_validated_output(self):
        observed = {'pin': self.new_pin, 'not_before': 1, 'not_after': 9999999999, 'certificate_time_valid': True}
        with patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(observed).encode(), b'private stderr')) as runner:
            result = prepare.observe_quic(Path('/controlled/helper'), '8.8.8.8', 443, 'sni.private.example', ['h3'])
        self.assertEqual(observed, result)
        self.assertEqual(['/controlled/helper'], runner.call_args.args[0])
        sent = json.loads(runner.call_args.kwargs['input'])
        self.assertEqual({'ip': '8.8.8.8', 'port': 443, 'sni': 'sni.private.example', 'alpn': ['h3']}, sent)
        self.assertEqual(8, runner.call_args.kwargs['timeout'])
        self.assertTrue(runner.call_args.kwargs['capture_output'])
        observed['not_after'] = 2
        with patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(observed).encode())):
            self.assertFalse(prepare.observe_quic(Path('/controlled/helper'), '8.8.8.8', 443, 'sni.private.example', ['h3'])['certificate_time_valid'])

    def test_quic_wrapper_rejects_opaque_extra_duplicate_and_invalid_output(self):
        valid = {'pin': self.pin, 'not_before': 1, 'not_after': 9999999999, 'certificate_time_valid': True}
        outputs = [b'raw private error', b'{"reason":"private endpoint"}',
                   b'{"reason":"tls_failed","password":"private"}',
                   b'{"reason":"tls_failed","reason":"tls_failed"}', b'[]', b'x' * 4097,
                   json.dumps(dict(valid, password='private')).encode(), json.dumps(dict(valid, pin='bad')).encode(),
                   json.dumps(dict(valid, not_before=True)).encode(), json.dumps(dict(valid, certificate_time_valid='yes')).encode(),
                   json.dumps(dict(valid, not_after=0)).encode()]
        for body in outputs:
            with patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, body, b'secret stderr')):
                self.assertEqual({'reason': 'identity_observer_invalid_output'}, prepare.observe_quic(Path('/controlled/helper'), '8.8.8.8', 443, 'sni.private.example', ['h3']))

    def test_quic_wrapper_failure_categories_and_timeout_are_fixed(self):
        for reason in prepare.QUIC_FAILURES:
            code = 2 if reason == 'invalid_input' else 1
            with patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, json.dumps({'reason': reason}).encode(), b'secret')):
                self.assertEqual({'reason': reason}, prepare.observe_quic(Path('/controlled/helper'), '8.8.8.8', 443, 'private', ['h3']))
        for error, reason in [(subprocess.TimeoutExpired(['secret-path'], 8, output=b'secret endpoint'), 'identity_timeout'),
                              (FileNotFoundError('private missing path'), 'identity_tool_unavailable')]:
            with patch.object(prepare.subprocess, 'run', side_effect=error):
                self.assertEqual({'reason': reason}, prepare.observe_quic(Path('/controlled/helper'), '8.8.8.8', 443, 'private', ['h3']))

    def test_matching_explicit_hy2_alpn_is_passed_as_bounded_protocol_list(self):
        source = self.proxies[34]
        settings = self.snapshot['routes'][34]['backend']['custom_outbounds'][0]['settings']
        source['alpn'] = ['h3', 'h3-29']
        settings['tls']['alpn'] = list(source['alpn'])
        self.approved[34]['source_sha256'] = prepare.digest(source)
        seen = []
        def observer(ip, port, sni, alpn):
            seen.append(alpn)
            return {'reason': 'tls_failed'}
        _, report = self.run_prepare(quic_observer=observer)
        self.assertTrue(all(item['reason'] == 'tls_failed' for item in report[34]['candidates']))
        self.assertEqual(2, sum(item == ['h3', 'h3-29'] for item in seen))

    def test_ca_hostname_uses_only_dns_and_keeps_observed_pin_out_of_production(self):
        before = copy.deepcopy(self.snapshot)
        settings = self.snapshot['routes'][31]['backend']['custom_outbounds'][0]['settings']
        settings['server'] = self.proxies[31]['server']
        before = copy.deepcopy(self.snapshot)
        private, report = self.run_prepare()
        self.assertEqual(before, self.snapshot)
        self.assertEqual(1, len(report[31]['candidates']))
        candidate = report[31]['candidates'][0]
        self.assertTrue(candidate['ca_validated'])
        self.assertFalse(candidate['current_endpoint'])
        self.assertTrue(candidate['source_dns_endpoint'])
        self.assertFalse(candidate['old_pin_matches'])
        self.assertEqual(self.new_pin, private[31]['candidates'][0]['identity']['pin'])
        self.assertEqual(prepare.digest(private[31]['candidates'][0]['identity']), candidate['candidate_digest'])
        self.assertNotIn('certificate_public_key_sha256', settings['tls'])

    def test_ca_requires_matching_uuid_flow_ws_sni_port_and_strict_source_and_current_tls(self):
        mutations = [lambda source, settings: settings.update(uuid='changed'),
                     lambda source, settings: settings.update(flow='xtls-rprx-vision'),
                     lambda source, settings: settings['tls'].update(insecure=True),
                     lambda source, settings: settings['tls'].update(certificate_public_key_sha256=[self.pin]),
                     lambda source, settings: settings['tls'].update(server_name='other.private.example'),
                     lambda source, settings: settings['tls'].update(certificate='custom-root'),
                     lambda source, settings: settings.update(server_port=444),
                     lambda source, settings: settings.update(transport={'type': 'ws', 'path': '/other'}),
                     lambda source, settings: source.update(**{'skip-cert-verify': True}),
                     lambda source, settings: source.update(tls=False),
                     lambda source, settings: source.update(alpn=['different']),
                     lambda source, settings: source.update(**{'reality-opts': {'public-key': 'private'}}),
                     lambda source, settings: settings.update(server='different-hostname.private.example')]
        for mutation in mutations:
            self.setUp()
            source = self.proxies[31]
            settings = self.snapshot['routes'][31]['backend']['custom_outbounds'][0]['settings']
            mutation(source, settings)
            self.approved[31]['source_sha256'] = prepare.digest(source)
            _, report = self.run_prepare()
            self.assertEqual('current_source_contract_mismatch', report[31]['reason'])
            self.assertEqual([], report[31]['candidates'])

    def test_ca_transport_match_dns_failure_and_unvalidated_observation_fail_closed(self):
        source = self.proxies[31]
        source.update(network='ws', **{'ws-opts': {'path': '/private-path', 'headers': {'Host': 'private-host'}}})
        settings = self.snapshot['routes'][31]['backend']['custom_outbounds'][0]['settings']
        settings.update(server=source['server'], transport={'type': 'ws', 'path': '/private-path', 'headers': {'Host': 'private-host'}})
        self.approved[31]['source_sha256'] = prepare.digest(source)
        _, report = self.run_prepare()
        self.assertEqual(1, len(report[31]['candidates']))
        def failed(*args): raise OSError('private exception')
        _, report = self.run_prepare(resolver=failed)
        self.assertEqual([], report[31]['candidates'])
        self.assertEqual('dns_resolution_failed', report[31]['dns_reason'])
        _, report = self.run_prepare(ca_observer=lambda *args: {'pin': self.pin})
        self.assertEqual('ca_validation_failed', report[31]['candidates'][0]['reason'])

    def test_hy2_source_hostname_uses_only_dns_preserving_original_pin(self):
        settings = self.snapshot['routes'][34]['backend']['custom_outbounds'][0]['settings']
        settings['server'] = self.proxies[34]['server']
        private, report = self.run_prepare()
        self.assertEqual(1, len(report[34]['candidates']))
        candidate = report[34]['candidates'][0]
        self.assertTrue(candidate['source_dns_endpoint'])
        self.assertFalse(candidate['current_endpoint'])
        self.assertFalse(candidate['old_pin_matches'])
        self.assertEqual([self.pin], settings['tls']['certificate_public_key_sha256'])
        self.assertEqual(self.new_pin, private[34]['candidates'][0]['identity']['pin'])
        settings['server'] = 'unrelated.private.example'
        _, report = self.run_prepare()
        self.assertEqual('current_source_contract_mismatch', report[34]['reason'])



if __name__ == '__main__': unittest.main()
