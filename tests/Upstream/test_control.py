import importlib.util
import base64
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('control', Path(__file__).resolve().parents[2]/'.docker/upstream/control.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class ControlTest(unittest.TestCase):
    def encrypted(self, count=1):
        witness = lambda n: {'observer_sha256': str(n)*64, 'evidence_sha256': str(n+2)*64,
            'identity_sha256': 'd'*64, 'observed_at': 1793043699.123456,
            'source_dns': n == 1, 'ca_validated': False}
        row = {'key': 'U01', 'candidate_digest': 'd'*64, 'ciphertext': base64.b64encode(b'x'*512).decode(),
               'not_before': 1793000000.0, 'not_after': 1795000000.0,
               'witnesses': {'entry': witness(1), 'independent': witness(2)}}
        return {'schema': 1, 'plan_id': 'a'*32, 'plan_sha256': 'b'*64, 'recipient_sha256': 'c'*64,
                'rows': [dict(row, key='U%02d'%n) for n in range(1, count+1)]}

    def import_value(self, count=1):
        return {'operation': 'import-reviewed', 'plan_id': 'a'*32, 'plan_sha256': 'b'*64,
                'selection': {}, 'execution_id': '', 'ciphertext': self.encrypted(count)}

    def value(self, operation='withdraw'):
        return {'operation': operation, 'plan_id': 'a'*32, 'plan_sha256': 'b'*64, 'selection': {'U04': 'c'*64},
                'execution_id': 'e'*64 if operation in ('verify-success', 'verify-withdrawn') else ''}

    def test_injection_and_unknown_scope_never_reach_subprocess(self):
        for field, bad in [('operation', 'withdraw; sh'), ('plan_id', '$(whoami)'),
                           ('plan_sha256', 'b'*64+';id'), ('selection', {'U42': None}),
                           ('selection', {'U04': '1.2.3.4'})]:
            value = self.value(); value[field] = bad
            with self.assertRaises(ValueError): c.command(value)
        with self.assertRaises(ValueError): c.parse('{"operation":"prepare","operation":"publish"}')

    def test_exact_phase_control_and_argument_array(self):
        for operation in ('withdraw', 'apply_hidden', 'publish', 'rollback'):
            result = c.command(self.value(operation))
            self.assertEqual(operation, result[result.index('--operation')+1])
            self.assertTrue(result[1].endswith('/maintain.py'))
        value = self.value('verify-withdrawn')
        self.assertEqual(['--expect', 'withdrawn', '--key', 'U04'], c.command(value)[-4:])
        value = self.value('snapshot'); value['selection'] = {}
        self.assertEqual('snapshot', c.command(value)[2])

    def test_prepare_cannot_receive_a_plan_or_unbound_executable(self):
        value = {'operation': 'prepare', 'plan_id': '', 'plan_sha256': '', 'selection': {}, 'execution_id': ''}
        with self.assertRaises(ValueError): c.command(value)
        self.assertEqual('d'*64, c.command(value, 'd'*64)[-1])
        value['plan_id'] = 'a'*32
        with self.assertRaises(ValueError): c.command(value, 'd'*64)

    def test_snapshot_and_verify_require_different_selection_scope(self):
        with self.assertRaises(ValueError): c.command(self.value('snapshot'))
        value = self.value('verify-success'); value['selection'] = {}
        with self.assertRaises(ValueError): c.command(value)

    def test_unchanged_baseline_has_no_maintenance_execution(self):
        value = self.value('verify-baseline')
        self.assertEqual('baseline', c.command(value)[2])
        self.assertNotIn('--execution-plan-id', c.command(value))
        value['execution_id'] = 'e'*64
        with self.assertRaises(ValueError): c.command(value)

    def test_source_address_acceptance_is_only_explicit_u01_hash(self):
        value = self.value('accept-source-address')
        with self.assertRaises(ValueError): c.command(value)
        value['selection'] = {'U01': 'f'*64}
        self.assertEqual(['--key', 'U01', '--expected-source-sha256', 'f'*64], c.command(value)[-4:])
        value['selection'] = {'U01': None}
        with self.assertRaises(ValueError): c.command(value)

    def test_inspector_has_no_plan_selection_or_shell_arguments(self):
        value = {'operation': 'inspect-environment', 'plan_id': '', 'plan_sha256': '', 'selection': {}, 'execution_id': ''}
        self.assertEqual(2, len(c.command(value)))
        value['selection'] = {'U01': None}
        with self.assertRaises(ValueError): c.command(value)

    def test_probe_config_permission_operation_cannot_take_paths_plans_or_selection(self):
        value = {'operation': 'secure-probe-config', 'plan_id': '', 'plan_sha256': '', 'selection': {}, 'execution_id': ''}
        result = c.command(value)
        self.assertEqual(2, len(result))
        self.assertTrue(result[1].endswith('/secure_probe_config.py'))
        for field, content in [('plan_id', 'a'*32), ('plan_sha256', 'b'*64),
                               ('selection', {'U01': None}), ('execution_id', 'c'*64),
                               ('path', '/private/other-file')]:
            invalid = dict(value)
            invalid[field] = content
            with self.assertRaises(ValueError): c.command(invalid)

    def test_scope_reconstruction_is_an_explicit_separate_action(self):
        value = {'operation': 'audit-scope', 'plan_id': '', 'plan_sha256': '', 'selection': {}, 'execution_id': ''}
        self.assertEqual('audit', c.command(value)[-1])
        value.update(operation='restore-scope', plan_id='a'*32, plan_sha256='b'*64)
        self.assertEqual('restore', c.command(value)[2])
        value['selection'] = {'U04': 'c'*64}
        with self.assertRaises(ValueError): c.command(value)

    def test_public_verification_requires_an_exact_execution_receipt(self):
        value = self.value('verify-success'); value['execution_id'] = ''
        with self.assertRaises(ValueError): c.command(value)
        value['execution_id'] = 'e'*64
        args = c.command(value)
        self.assertEqual(value['execution_id'], args[args.index('--execution-plan-id')+1])

    def test_recipient_and_import_have_only_bound_arguments_and_ciphertext_stdin(self):
        value = self.value('recipient'); value['selection'] = {}
        self.assertEqual('recipient', c.command(value)[2])
        value = self.import_value()
        args = c.command(value)
        self.assertEqual('import', args[2]); self.assertNotIn(value['ciphertext']['rows'][0]['ciphertext'], args)
        with patch.object(c.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(0, c.execute(value))
            self.assertEqual(json.loads(run.call_args.kwargs['input']), value['ciphertext'])
            self.assertFalse(run.call_args.kwargs.get('shell', False))
        for field, bad in [('selection', {'U01': 'd'*64}), ('execution_id', 'e'*64), ('plan_id', '')]:
            invalid = dict(value, **{field: bad})
            with self.assertRaises(ValueError): c.command(invalid)

    def test_ciphertext_accepts_only_public_envelope_fields_and_exact_plan(self):
        value = self.import_value()
        for field, bad in [('ip', '8.8.8.8'), ('pin', 'private'), ('password', 'secret')]:
            value['ciphertext']['rows'][0][field] = bad
            with self.assertRaises(ValueError): c.command(value)
            del value['ciphertext']['rows'][0][field]
        value['ciphertext']['plan_sha256'] = 'f'*64
        with self.assertRaises(ValueError): c.command(value)
        value = self.import_value(); value['operation'] = 'recipient'
        with self.assertRaises(ValueError): c.command(value)
        value = self.import_value(); value['ciphertext']['rows'][0]['ciphertext'] = 'not-base64'
        with self.assertRaises(ValueError): c.command(value)

    def test_realistic_rows_and_dispatch_escaping_respect_both_bounds(self):
        value = self.import_value(39)
        c.command(value)
        env = {key.upper(): json.dumps(item, sort_keys=True, separators=(',', ':')) if isinstance(item, dict) else item
               for key, item in value.items()}
        self.assertLess(len(env['CIPHERTEXT'].encode()), 60*1024)
        self.assertLess(len(json.dumps({key.lower(): item for key, item in env.items()}, separators=(',', ':')).encode()), 65535)
        with patch.dict(os.environ, env, clear=True): self.assertEqual(c.from_environment(), value)
        with self.assertRaises(ValueError): c.command(self.import_value(41))
        with patch.dict(os.environ, dict(env, CIPHERTEXT=env['CIPHERTEXT']+' '*5000), clear=True):
            with self.assertRaises(ValueError): c.from_environment()
        with self.assertRaises(ValueError): c.parse(b' '*65536)


if __name__ == '__main__': unittest.main()
