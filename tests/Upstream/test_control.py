import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('control', Path(__file__).resolve().parents[2]/'.docker/upstream/control.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class ControlTest(unittest.TestCase):
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


if __name__ == '__main__': unittest.main()
