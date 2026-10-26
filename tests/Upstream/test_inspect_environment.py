import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
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
        self.guard_state = self.root/'guard-state.json'
        patcher = patch.object(inspect, 'GUARD_STATE', self.guard_state)
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

    def test_complete_inspection_only_runs_five_fixed_read_commands(self):
        before = list(self.root.iterdir())
        def response(arguments, **kwargs):
            if arguments[0] == 'systemctl':
                self.assertIn(arguments[2], (*inspect.UNITS,inspect.PROBE_UNIT))
                return subprocess.CompletedProcess(arguments, 0, b'ActiveState=inactive\nSubState=dead\nResult=success\n')
            self.assertEqual('ip', arguments[0]);self.assertIn('-6', arguments);self.assertIn('-j', arguments)
            return subprocess.CompletedProcess(arguments,0,b'[]')
        with patch.object(inspect, 'BINARY_PATHS', tuple(str(self.root/('binary'+str(n))) for n in range(4))), \
                patch.object(inspect.subprocess, 'run', side_effect=response) as runner:
            report = inspect.inspect_environment()
        self.assertEqual(5, runner.call_count)
        self.assertEqual(before, list(self.root.iterdir()))
        self.assertFalse(report['files_mutated'] or report['policy_mutated'] or report['network_mutated'] or report['binaries_executed'])

    def test_agent_reports_exact_permissions_and_numeric_ownership(self):
        self.config({'panel_url':'https://taige.us','token':'s'*64},mode=0o640)
        report=self.agent_report()
        self.assertEqual('0640',report['mode'])
        self.assertEqual(self.agent.stat().st_uid,report['uid'])
        self.assertEqual(self.agent.stat().st_gid,report['gid'])
        self.assertTrue(report['group_readable'])
        self.assertFalse(report['group_or_world_writable'] or report['world_accessible'])

    def test_probe_service_reports_only_identity_and_group_policy(self):
        agent={'uid':0,'gid':321,'regular_file':True,'owner_root':True,'mode':'0640','group_readable':True}
        body=b'LoadState=loaded\nUser=probe\nGroup=\nDynamicUser=no\nActiveState=active\nSubState=running\nResult=success\n'
        with patch.object(inspect,'command_output',return_value=(body,'ok')) as command, \
                patch.object(inspect.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=123,pw_gid=321)):
            report=inspect.probe_service_metadata(agent)
        self.assertTrue(report['identity_resolved'] and report['static_identity'] and report['group_matches_file_group'])
        self.assertTrue(report['group_read_matches_service'] and report['agent_read_policy_compatible'])
        self.assertFalse(report['user_matches_file_owner'])
        self.assertEqual((123,321),(report['effective_uid'],report['effective_gid']))
        self.assertEqual(inspect.PROBE_UNIT,command.call_args.args[0][2])
        with patch.object(inspect,'command_output',return_value=(body.replace(b'DynamicUser=no',b'DynamicUser=yes'),'ok')), \
                patch.object(inspect.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=123,pw_gid=321)):
            self.assertFalse(inspect.probe_service_metadata(agent)['agent_read_policy_compatible'])

    def test_probe_unexpected_identity_and_errors_are_not_exposed(self):
        body=b'LoadState=loaded\nUser=secret/user\nGroup=secret:group\nDynamicUser=no\nActiveState=secret-state\nSubState=running\nResult=success\n'
        with patch.object(inspect,'command_output',return_value=(body,'ok')):
            report=inspect.probe_service_metadata({})
        self.assertEqual('probe_identity_unresolved',report['classification'])
        self.assertNotIn('secret',json.dumps(report))

    def write_guard_state(self, value=None, mode=0o600):
        value = value if value is not None else {'checked_at':2000,'last_success_at':2000,'fetch_ok':True,'withdraw':[]}
        if self.guard_state.exists():self.guard_state.chmod(0o600)
        self.guard_state.write_text(json.dumps(value));self.guard_state.chmod(mode)

    def guard_report(self):
        with patch.object(inspect,'root_owned',return_value=True):return inspect.guard_state_metadata()

    def test_guard_state_only_exposes_bounded_facts_without_usage_or_errors(self):
        value={'checked_at':2000,'last_success_at':1900,'fetch_ok':False,
               'withdraw':[{'key':'U01','reason':'private-error','ip':'private-endpoint'}],
               'usage':{'expire':1234,'total':12345},'source_url':'https://private.invalid/?token=secret','error_type':'private-error'}
        self.write_guard_state(value)
        before=self.guard_state.read_bytes();report=self.guard_report()
        self.assertEqual({'classification':'inspected','checked_at':2000,'last_success_at':1900,'fetch_ok':False,'withdraw_count':1},report)
        self.assertEqual(before,self.guard_state.read_bytes())
        self.assertNotIn('private',json.dumps(report));self.assertNotIn('12345',json.dumps(report))
        self.write_guard_state()
        self.assertEqual(0,self.guard_report()['withdraw_count']);self.assertTrue(self.guard_report()['fetch_ok'])

    def test_guard_state_rejects_modes_symlink_nonroot_and_oversized_before_read(self):
        for mode in (0o400,0o640,0o644,0o660,0o4600):
            self.write_guard_state(mode=mode)
            with patch.object(inspect.os,'open') as opened:
                self.assertEqual('unsafe_guard_state_file',self.guard_report()['classification']);opened.assert_not_called()
        self.write_guard_state()
        with patch.object(inspect,'root_owned',return_value=False),patch.object(inspect.os,'open') as opened:
            self.assertEqual('unsafe_guard_state_file',inspect.guard_state_metadata()['classification']);opened.assert_not_called()
        self.guard_state.unlink();self.guard_state.symlink_to(self.root/'private-target')
        self.assertEqual('unsafe_guard_state_file',self.guard_report()['classification'])
        self.guard_state.unlink();self.guard_state.mkdir()
        self.assertEqual('unsafe_guard_state_file',self.guard_report()['classification'])
        self.guard_state.rmdir();self.guard_state.write_bytes(b'x'*65537);self.guard_state.chmod(0o600)
        self.assertEqual('unsafe_guard_state_file',self.guard_report()['classification'])

    def test_guard_state_json_duplicate_invalid_and_contract_failures_never_expose_raw(self):
        self.write_guard_state()
        for raw in (b'private-raw-error',b'{"fetch_ok":true,"fetch_ok":false}',b'{"checked_at":NaN}'):
            self.guard_state.write_bytes(raw)
            report=self.guard_report();self.assertEqual('guard_state_json_invalid',report['classification'])
            self.assertIsNone(report['checked_at']);self.assertNotIn('private',json.dumps(report))
        base={'checked_at':2000,'last_success_at':2000,'fetch_ok':True,'withdraw':[]}
        for changes in ({'checked_at':True},{'checked_at':2000.0},{'checked_at':253402300800},
                        {'last_success_at':2001},{'last_success_at':1999},{'fetch_ok':1},
                        {'withdraw':[{'key':'U01'}]*42},{'withdraw':[{'key':'U01'},{'key':'U01'}]},
                        {'withdraw':[{'key':'U42'}]},{'withdraw':['private-row']},{'withdraw':None}):
            self.write_guard_state(dict(base,**changes));report=self.guard_report()
            self.assertEqual('guard_state_contract_invalid',report['classification']);self.assertIsNone(report['withdraw_count'])

    def test_guard_state_inode_content_and_permission_drift_do_not_report_success(self):
        original=inspect.os.fstat
        for drift in ('inode','content','permission'):
            self.write_guard_state();count=[0]
            def changed(fd):
                count[0]+=1
                if count[0]==2:
                    if drift=='inode':
                        replacement=self.root/'replacement';replacement.write_bytes(self.guard_state.read_bytes());replacement.chmod(0o600);replacement.replace(self.guard_state)
                    elif drift=='content':self.guard_state.write_text(self.guard_state.read_text().replace('2000','2001'))
                    else:self.guard_state.chmod(0o640)
                return original(fd)
            with patch.object(inspect.os,'fstat',side_effect=changed):report=self.guard_report()
            self.assertEqual('guard_state_changed',report['classification']);self.assertIsNone(report['fetch_ok'])

    def test_guard_state_missing_permission_and_io_errors_are_fixed(self):
        self.assertEqual('missing',self.guard_report()['classification'])
        self.write_guard_state()
        for error,classification in ((PermissionError('private-permission'),'guard_state_permission_denied'),
                                      (OSError('private-path'),'guard_state_inspection_failed')):
            with patch.object(inspect.os,'open',side_effect=error):report=self.guard_report()
            self.assertEqual(classification,report['classification']);self.assertNotIn('private',json.dumps(report))

    def test_guard_state_sampling_runs_no_service_or_network_commands(self):
        self.write_guard_state()
        with patch.object(inspect.subprocess,'run') as command:
            report=self.guard_report();command.assert_not_called()
        self.assertEqual('inspected',report['classification'])

    def test_main_rejects_unknown_input_and_redacts_internal_error(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(1,inspect.main(['private-secret']))
        self.assertNotIn('private-secret',output.getvalue())
        output = io.StringIO()
        with patch.object(inspect.os,'geteuid',return_value=0),patch.object(inspect,'inspect_environment',side_effect=RuntimeError('private-secret')),contextlib.redirect_stdout(output):
            self.assertEqual(1,inspect.main([]))
        self.assertEqual({'status':'error','reason':'environment_inspection_failed'},json.loads(output.getvalue()))


if __name__ == '__main__':unittest.main()
