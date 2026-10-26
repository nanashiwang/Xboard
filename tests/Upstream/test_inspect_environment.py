import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('inspect_environment', Path(__file__).resolve().parents[2] / '.docker/upstream/inspect_environment.py')
inspect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspect)


class EnvironmentInspectionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.agent = self.root/'agent.json'
        patcher = patch.object(inspect, 'AGENT', self.agent)
        patcher.start();self.addCleanup(patcher.stop)

    def config(self, value, mode=0o600):
        self.agent.write_text(json.dumps(value))
        self.agent.chmod(mode)

    def agent_report(self):
        with patch.object(inspect, 'root_owned', return_value=True):
            return inspect.agent_metadata()

    def test_agent_only_exposes_shape_and_bounded_token_length(self):
        secret = 'never-print-token-'*80
        url = 'http://private-user:private-password@127.0.0.1:7001/private-path?private-query#private-fragment'
        self.config({'panel_url': url, 'token': secret})
        report = self.agent_report()
        self.assertTrue(report['regular_file'] and report['owner_root'] and report['private_permissions'])
        self.assertTrue(report['exact_known_fields'])
        self.assertEqual(['panel_url', 'token'], report['field_names'])
        self.assertEqual(512, report['token_length'])
        self.assertTrue(report['token_length_capped'])
        meta = report['panel_url']
        self.assertEqual('http', meta['scheme'])
        self.assertTrue(meta['host_is_loopback'])
        self.assertEqual('7001', meta['port_class'])
        self.assertFalse(meta['host_is_expected_public'] or meta['path_is_root'])
        self.assertTrue(meta['has_userinfo'] and meta['has_query'] and meta['has_fragment'])
        raw = json.dumps(report)
        for value in (secret, url, 'private-user', 'private-password', 'private-path', 'private-query', 'private-fragment', '127.0.0.1'):
            self.assertNotIn(value, raw)

    def test_unknown_fields_and_non_string_token_never_print_values_or_unsafe_field_names(self):
        self.config({'panel_url': 'https://private.invalid', 'token': {'private': 'secret'},
                     'agent_version': 'private-version', 'private-name/with-secret': 'private-value', 'x'*33: 'private-value'})
        report = self.agent_report()
        self.assertFalse(report['exact_known_fields'])
        self.assertFalse(report['token_is_string'])
        self.assertIsNone(report['token_length'])
        self.assertEqual(['agent_version', 'panel_url', 'token', 'unknown'], report['field_names'])
        self.assertNotIn('private', json.dumps({k:v for k,v in report.items() if k != 'private_permissions'}))

    def test_url_metadata_has_only_fixed_scheme_port_and_host_classes(self):
        for value, scheme, loopback, expected, port in [
                ('https://taige.us/', 'https', False, True, 'default'),
                ('https://board.taige.us:443', 'https', False, True, '443'),
                ('http://localhost:7001/', 'http', True, False, '7001'),
                ('http://[::1]:7001/', 'http', True, False, '7001'),
                ('http://[::ffff:127.0.0.1]:7001/', 'http', True, False, '7001'),
                ('private-secret://private.invalid:12345/', 'other', False, False, 'other')]:
            report = inspect.panel_url_metadata(value)
            self.assertEqual((scheme, loopback, expected, port), (report['scheme'], report['host_is_loopback'], report['host_is_expected_public'], report['port_class']))
            self.assertNotIn(value, json.dumps(report))
        for malformed in ('https://[invalid', 'https://private.invalid:secret', 'https://private.invalid\n', None, 42):
            self.assertFalse(inspect.panel_url_metadata(malformed)['parse_valid'])

    def test_missing_symlink_permissions_and_duplicate_json_are_distinguished_safely(self):
        self.assertEqual('missing', self.agent_report()['classification'])
        self.agent.symlink_to(self.root/'missing')
        self.assertEqual('unsafe_agent_file', self.agent_report()['classification'])
        self.agent.unlink()
        self.config({'panel_url': 'https://taige.us', 'token': 'a'*64}, mode=0o644)
        report = self.agent_report()
        self.assertFalse(report['private_permissions'])
        self.assertTrue(report['exact_known_fields'])
        self.agent.write_text('{"token":"private-one","token":"private-two"}')
        self.assertEqual('agent_json_invalid', self.agent_report()['classification'])
        self.agent.write_bytes(b'x'*65537)
        self.assertEqual('agent_file_too_large', self.agent_report()['classification'])

    def test_non_root_owned_agent_is_not_read(self):
        self.config({'token': 'private-token'})
        with patch.object(inspect, 'root_owned', return_value=False), patch.object(inspect.os, 'open') as opened:
            self.assertEqual('unsafe_agent_file', inspect.agent_metadata()['classification'])
            opened.assert_not_called()

    def test_binary_hashes_without_execution_and_refuses_unsafe_or_dangling(self):
        binary = self.root/'sing-box'
        binary.write_bytes(b'public binary fixture');binary.chmod(0o755)
        with patch.object(inspect, 'root_owned', return_value=True), patch.object(inspect, 'secure_parents', return_value=True), \
                patch.object(inspect.subprocess, 'run') as process:
            report = inspect.binary_metadata(str(binary))
            self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), report['sha256'])
            process.assert_not_called()
            binary.chmod(0o777)
            report = inspect.binary_metadata(str(binary))
            self.assertEqual('unsafe_binary', report['classification'])
            self.assertIsNone(report['sha256'])
        binary.unlink();binary.symlink_to(self.root/'private-target')
        report = inspect.binary_metadata(str(binary))
        self.assertEqual('dangling_binary_link', report['classification'])
        self.assertNotIn('private-target', json.dumps(report))

    def test_systemctl_outputs_only_whitelisted_properties_and_safe_values(self):
        body = b'ActiveState=active\nSubState=waiting\nResult=success\nTimeoutStartUSec=1min 30s\nExecStart=private-token\nDescription=private-host\n'
        with patch.object(inspect.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, body, b'private stderr')) as runner:
            report = inspect.unit_metadata(inspect.UNITS[0])
        self.assertEqual({'ActiveState':'active','SubState':'waiting','Result':'success','TimeoutStartUSec':'1min 30s'}, report['properties'])
        self.assertNotIn('private', json.dumps(report))
        self.assertEqual('systemctl', runner.call_args.args[0][0])
        self.assertTrue(runner.call_args.kwargs['capture_output'])
        self.assertEqual(5, runner.call_args.kwargs['timeout'])
        with patch.object(inspect, 'command_output', return_value=(b'ActiveState=private-secret\nTimeoutStartUSec=private-timeout\n', 'ok')):
            report = inspect.unit_metadata(inspect.UNITS[1])
        self.assertEqual('unknown', report['properties']['ActiveState'])
        self.assertEqual('unknown', report['properties']['TimeoutStartUSec'])

    def test_ipv6_exposes_only_presence_and_does_not_forward_addresses(self):
        routes = [{'dst':'default','gateway':'2001:db8::private','dev':'private-device'}]
        addresses = [{'ifname':'private-device','addr_info':[{'family':'inet6','scope':'global','local':'2001:db8::secret'}]}]
        with patch.object(inspect, 'command_output', side_effect=[(json.dumps(routes).encode(),'ok'),(json.dumps(addresses).encode(),'ok')]) as command:
            report = inspect.ipv6_metadata()
        self.assertTrue(report['default_route']['present'] and report['global_address']['present'])
        self.assertNotIn('private', json.dumps(report));self.assertNotIn('2001:', json.dumps(report))
        self.assertEqual(['ip','-6','-j','route','show','default'], command.call_args_list[0].args[0])
        with patch.object(inspect, 'command_output', return_value=(b'[]','ok')):
            report = inspect.ipv6_metadata()
        self.assertFalse(report['default_route']['present'] or report['global_address']['present'])

    def test_command_timeout_and_errors_never_forward_stderr_or_raw_exception(self):
        for error, classification in ((FileNotFoundError('private-command'), 'command_unavailable'),
                                       (subprocess.TimeoutExpired(['private'],5,output=b'private-output',stderr=b'private-stderr'),'command_timeout'),
                                       (OSError('private-exception'),'command_failed')):
            with patch.object(inspect.subprocess, 'run', side_effect=error):
                self.assertEqual((None,classification), inspect.command_output(['systemctl']))
        with patch.object(inspect.subprocess,'run',return_value=subprocess.CompletedProcess([],1,b'private',b'private')):
            self.assertEqual((None,'command_failed'),inspect.command_output(['ip']))

    def test_complete_inspection_only_runs_four_fixed_read_commands(self):
        before = list(self.root.iterdir())
        def response(arguments, **kwargs):
            if arguments[0] == 'systemctl':
                self.assertIn(arguments[2], inspect.UNITS)
                return subprocess.CompletedProcess(arguments, 0, b'ActiveState=inactive\nSubState=dead\nResult=success\n')
            self.assertEqual('ip', arguments[0]);self.assertIn('-6', arguments);self.assertIn('-j', arguments)
            return subprocess.CompletedProcess(arguments,0,b'[]')
        with patch.object(inspect, 'BINARY_PATHS', tuple(str(self.root/('binary'+str(n))) for n in range(4))), \
                patch.object(inspect.subprocess, 'run', side_effect=response) as runner:
            report = inspect.inspect_environment()
        self.assertEqual(4, runner.call_count)
        self.assertEqual(before, list(self.root.iterdir()))
        self.assertFalse(report['files_mutated'] or report['policy_mutated'] or report['network_mutated'] or report['binaries_executed'])

    def test_main_rejects_unknown_input_and_redacts_internal_error(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(1,inspect.main(['private-secret']))
        self.assertNotIn('private-secret',output.getvalue())
        output = io.StringIO()
        with patch.object(inspect.os,'geteuid',return_value=0),patch.object(inspect,'inspect_environment',side_effect=RuntimeError('private-secret')),contextlib.redirect_stdout(output):
            self.assertEqual(1,inspect.main([]))
        self.assertEqual({'status':'error','reason':'environment_inspection_failed'},json.loads(output.getvalue()))


if __name__ == '__main__':unittest.main()
