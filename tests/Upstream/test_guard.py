import importlib.util
import base64
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('guard', Path(__file__).resolve().parents[2] / '.docker/upstream/guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.node = {'name': 'approved', 'type': 'anytls', 'password': 'test-only'}
        self.approved = [{'key': 'U01', 'source_name': 'approved', 'source_sha256': guard.fingerprint(self.node),
                          'backend_id': 359, 'public_id': 360}]
        self.usage = {'expire': 10000, 'total': 1000, 'upload': 1, 'download': 2}

    def test_unchanged_and_unknown_addition_do_not_mutate_approved_routes(self):
        self.assertEqual([], guard.evaluate(self.approved, [self.node, {'name': 'new-unapproved'}], self.usage, 100))

    def test_changed_credentials_are_withdrawn_without_being_installed(self):
        result = guard.evaluate(self.approved, [dict(self.node, password='rotated-test')], self.usage, 100)
        self.assertEqual('source_changed_requires_acceptance', result[0]['reason'])
        self.assertNotIn('password', str(result))

    def test_expiry_and_quota_fail_closed(self):
        for usage, expected in [(dict(self.usage, expire=399), 'expired_or_near_expiry'),
                                (dict(self.usage, download=999), 'quota_exhausted')]:
            self.assertEqual(expected, guard.evaluate(self.approved, [self.node], usage, 100)[0]['reason'])

    def test_missing_and_duplicate_name_never_silently_remap(self):
        for nodes in [[], [self.node, self.node]]:
            result = guard.evaluate(self.approved, nodes, self.usage, 100)
            self.assertEqual('missing_or_ambiguous_source', result[0]['reason'])
            self.assertEqual(359, result[0]['backend_id'])


class AllocationTest(unittest.TestCase):
    def test_live_contract_is_nested_and_separate_from_owned_nodes(self):
        import json
        data = json.loads((Path(__file__).resolve().parents[2] / '.docker/upstream/allocation.json').read_text())
        routes = data['routes']
        self.assertEqual([8, 16, 28, 41], [sum(r['tier'] <= tier for r in routes) for tier in range(1, 5)])
        self.assertEqual(82, len({r[k] for r in routes for k in ('backend_id', 'public_id')}))
        self.assertFalse(set(data['ordinary_owned_ids']) & {r['public_id'] for r in routes})
        self.assertEqual(4, sum(r['low_traffic'] for r in routes))
        self.assertEqual(8, sum(r['udp_limited'] for r in routes))
        self.assertEqual({1, 2, 5}, {r['rate'] for r in routes})


class RuntimeGuardTest(unittest.TestCase):
    def setUp(self):
        self.node = {'name': 'accepted-source', 'type': 'anytls', 'password': 'secret-test-password',
                     'server': 'untrusted-subscription.example', 'sni': 'untrusted-sni.example'}
        self.approved = [dict(key=key, backend_id=backend, public_id=backend + 1,
                              source_name=self.node['name'], source_sha256=guard.fingerprint(self.node))
                         for key, backend in [('U01', 359), ('U04', 365), ('U05', 367), ('U06', 369)]]
        self.allocation = {'routes': [dict(row, upstream_type='vless' if row['key'] == 'U06' else 'anytls')
                                      for row in self.approved]}
        self.pin = base64.b64encode(b'a' * 32).decode()
        self.maps = [dict(key=row['key'], ip='192.0.2.1', port=443, sni='approved.invalid', pin=self.pin)
                     for row in self.approved if row['key'] != 'U06']
        self.usage = dict(expire=200000, total=1000, upload=1, download=2)
        self.previous = dict(last_success_at=100, usage=self.usage)

    def check(self, probe=None, fetch=None, now=200, **overrides):
        args = dict(approved=self.approved, previous=self.previous, allocation=self.allocation,
                    mappings=self.maps, now=now, fetch=fetch or (lambda: ([self.node], self.usage)),
                    probe=probe or (lambda mapping: None))
        args.update(overrides)
        return guard.check(**args)

    def test_singapore_unchanged_subscription_changed_runtime_key_withdraws_only_pair(self):
        original = copy.deepcopy((self.approved, self.maps))
        seen = []

        def probe(mapping):
            seen.append(mapping.copy())
            return 'runtime_public_key_mismatch' if mapping['key'] in ('U04', 'U05') else None

        state = self.check(probe)
        self.assertEqual([365, 367], [r['backend_id'] for r in state['withdraw']])
        self.assertEqual([366, 368], [r['public_id'] for r in state['withdraw']])
        self.assertTrue(state['fetch_ok'])
        self.assertFalse(state['identity_ok'])
        self.assertEqual(original, (self.approved, self.maps))
        self.assertEqual({'U01', 'U04', 'U05'}, {r['key'] for r in seen})
        self.assertTrue(all(r['sni'] == 'approved.invalid' and r['ip'] == '192.0.2.1' for r in seen))
        for secret in (self.pin, 'approved.invalid', '192.0.2.1', 'secret-test-password', 'untrusted-subscription.example'):
            self.assertNotIn(secret, json.dumps(state))

    def test_fetch_failure_grace_never_hides_runtime_mismatch(self):
        def failed_fetch():
            raise RuntimeError('secret-test-password https://secret.invalid/token')
        state = self.check(lambda m: 'runtime_public_key_mismatch' if m['key'] == 'U04' else None,
                           fetch=failed_fetch)
        self.assertFalse(state['fetch_ok'])
        self.assertEqual(100, state['last_success_at'])
        self.assertEqual(['U04'], [r['key'] for r in state['withdraw']])
        self.assertNotIn('secret', json.dumps(state))
        for now, previous, reason in [(86501, self.previous, 'metadata_stale'),
                                      (200, dict(self.previous, usage=dict(self.usage, expire=500)), 'known_expiry')]:
            with self.subTest(reason=reason):
                stale = self.check(fetch=failed_fetch, now=now, previous=previous)
                self.assertEqual(4, len(stale['withdraw']))
                self.assertEqual({reason}, {r['reason'] for r in stale['withdraw']})

    def test_metadata_reason_precedes_identity_but_both_remain_visible(self):
        state = self.check(lambda m: 'runtime_public_key_mismatch',
                           fetch=lambda: ([self.node], dict(self.usage, download=999)))
        self.assertEqual(4, len(state['withdraw']))
        self.assertEqual({'quota_exhausted'}, {r['reason'] for r in state['withdraw']})
        self.assertEqual({'runtime_public_key_mismatch'}, {r['reason'] for r in state['identity_checks']})

    def test_missing_duplicate_malformed_identity_maps_never_pass(self):
        for maps in (None, {}, [], self.maps + [self.maps[0]],
                     [dict(r, pin='bad-pin') for r in self.maps],
                     [dict(r, pin=base64.b64encode(b'a' * 31).decode()) for r in self.maps],
                     [dict(r, ip='dns-rotation.example') for r in self.maps],
                     [dict(r, ip=1) for r in self.maps],
                     [dict(r, port=True) for r in self.maps],
                     [dict(r, port=65536) for r in self.maps],
                     [dict(r, sni='') for r in self.maps]):
            with self.subTest(maps=type(maps).__name__):
                state = self.check(mappings=maps)
                self.assertFalse(state['identity_ok'])
                self.assertEqual({'runtime_identity_mapping_invalid'}, {r['reason'] for r in state['withdraw']})
                self.assertNotIn('U06', {r['key'] for r in state['withdraw']})

    def test_scope_mismatch_or_missing_catalog_fails_closed_without_network(self):
        for allocation in (None, {}, {'routes': []},
                           {'routes': [dict(r, backend_id=1) for r in self.allocation['routes']]},
                           {'routes': self.allocation['routes'] * 2}):
            with self.subTest(allocation=type(allocation).__name__):
                with patch.object(guard, 'probe_identity') as probe:
                    checks = guard.evaluate_identity(self.approved, allocation, self.maps)
                probe.assert_not_called()
                self.assertEqual(4, len(checks))
                self.assertEqual({'runtime_identity_scope_invalid'}, {r['reason'] for r in checks})

    def test_unknown_maps_cannot_add_probes_or_withdrawals(self):
        state = self.check(mappings=self.maps + [dict(self.maps[0], key='unapproved')])
        self.assertEqual([], state['withdraw'])
        self.assertEqual({'U01', 'U04', 'U05'}, {r['key'] for r in state['identity_checks']})

    def test_non_anytls_scope_does_not_claim_identity_success_or_withdraw(self):
        state = self.check(approved=[self.approved[-1]])
        self.assertFalse(state['identity_ok'])
        self.assertEqual([], state['identity_checks'])
        self.assertEqual([], state['withdraw'])

    def test_check_exception_is_not_identity_success_or_sensitive_output(self):
        def failure(mapping):
            raise RuntimeError('secret-test-password approved.invalid ' + self.pin)
        state = self.check(failure)
        self.assertEqual(3, len(state['withdraw']))
        self.assertEqual({'runtime_identity_check_failed'}, {r['reason'] for r in state['withdraw']})
        self.assertNotIn(self.pin, json.dumps(state))

    def test_cli_read_only_never_loads_subscription_writes_state_or_applies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in [('approved.private', self.approved), ('allocation.json', self.allocation),
                               ('pinned.private', self.maps), ('guard-state.json', self.previous)]:
                (root / name).write_text(json.dumps(data))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            args = ['--root', directory, '--allocation', str(root / 'allocation.json'), '--check-identity',
                    '--key', 'U04', '--key', 'U05']
            with patch.object(guard, 'fetch_subscription') as fetch, patch.object(guard, 'apply') as apply, \
                    patch.object(guard, 'probe_identity', return_value='runtime_public_key_mismatch'), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(1, guard.main(args))
            fetch.assert_not_called()
            apply.assert_not_called()
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            self.assertEqual([365, 367], [r['backend_id'] for r in json.loads(output.getvalue())['identity_checks']])

    def test_cli_normal_run_applies_only_withdrawals_and_never_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in [('approved.private', self.approved), ('allocation.json', self.allocation),
                               ('pinned.private', self.maps), ('guard-state.json', self.previous)]:
                (root / name).write_text(json.dumps(data))
            args = ['--root', directory, '--allocation', str(root / 'allocation.json')]
            with patch.object(guard, 'fetch_subscription', return_value=([self.node], self.usage)), \
                    patch.object(guard.time, 'time', return_value=200), \
                    patch.object(guard, 'apply', return_value={'withdrawn': ['U04', 'U05']}) as apply, \
                    patch.object(guard, 'probe_identity', side_effect=lambda m: 'runtime_public_key_mismatch' if m['key'] != 'U01' else None), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, guard.main(args))
                self.assertEqual(['U04', 'U05'], [r['key'] for r in apply.call_args[0][0]])
                self.assertEqual(root, apply.call_args[0][1])
            self.assertEqual(0o600, (root / 'guard-state.json').stat().st_mode & 0o777)
            with patch.object(guard, 'fetch_subscription', return_value=([self.node], self.usage)), \
                    patch.object(guard.time, 'time', return_value=201), \
                    patch.object(guard, 'apply') as apply, patch.object(guard, 'probe_identity', return_value=None), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, guard.main(args))
            apply.assert_not_called()
            self.assertEqual([], json.loads((root / 'guard-state.json').read_text())['withdraw'])

    def test_cli_configuration_error_is_redacted_and_nonzero(self):
        with tempfile.TemporaryDirectory(prefix='secret-test-') as directory:
            (Path(directory) / 'approved.private').write_text('sensitive-invalid-json')
            result = subprocess.run(['python3', str(Path(guard.__file__)), '--check-identity', '--root', directory],
                                    capture_output=True, text=True)
        self.assertEqual(2, result.returncode)
        self.assertEqual({'error_type': 'JSONDecodeError'}, json.loads(result.stdout))
        self.assertEqual('', result.stderr)


if __name__ == '__main__':
    unittest.main()
