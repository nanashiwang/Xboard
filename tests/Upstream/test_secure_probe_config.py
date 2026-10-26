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

spec = importlib.util.spec_from_file_location('secure_probe_config', Path(__file__).resolve().parents[2]/'.docker/upstream/secure_probe_config.py')
secure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(secure)


class SecureProbeConfigTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.agent = self.root/'agent.json'
        self.plans = self.root/'plans'
        self.body = json.dumps({'panel_url':'https://taige.us/', 'token':'private-token-'.ljust(64,'x')}).encode()
        self.agent.write_bytes(self.body);self.agent.chmod(0o644)
        for name,value in [('AGENT',self.agent),('PLAN_ROOT',self.plans)]:
            p=patch.object(secure,name,value);p.start();self.addCleanup(p.stop)
        p=patch.object(secure,'root_owned',return_value=True);p.start();self.addCleanup(p.stop)
        p=patch.object(secure.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'LoadState=loaded\nUser=\nGroup=\nDynamicUser=no\n'))
        self.command=p.start();self.addCleanup(p.stop)

    def test_only_chmod_600_and_preserve_content_inode_owner_with_private_record_first(self):
        before=self.agent.stat();real_fchmod=os.fchmod
        def checked_chmod(fd, mode):
            records=list(self.plans.glob('*/probe-permission.private.json'))
            self.assertEqual(1,len(records))
            self.assertEqual(0o600,records[0].stat().st_mode&0o777)
            self.assertEqual(0o700,records[0].parent.stat().st_mode&0o777)
            record=json.loads(records[0].read_bytes())
            self.assertEqual(0o644,record['old_mode'])
            self.assertEqual(hashlib.sha256(self.body).hexdigest(),record['content_sha256'])
            self.assertEqual(0o644,self.agent.stat().st_mode&0o777)
            self.assertEqual(0o600,mode)
            real_fchmod(fd,mode)
        with patch.object(secure.os,'fchmod',side_effect=checked_chmod) as chmod:
            report=secure.secure()
        self.assertEqual(1,chmod.call_count)
        after=self.agent.stat()
        self.assertEqual((before.st_ino,before.st_uid,before.st_gid,before.st_mtime_ns),(after.st_ino,after.st_uid,after.st_gid,after.st_mtime_ns))
        self.assertEqual(self.body,self.agent.read_bytes())
        self.assertEqual(0o600,after.st_mode&0o777)
        self.assertEqual('secured',report['status'])
        self.assertEqual(hashlib.sha256(self.body).hexdigest(),report['content_sha256'])
        self.assertEqual(2,self.command.call_count)
        for call in self.command.call_args_list:
            self.assertEqual(['systemctl','show','xboard-extension-probe.service','--property=LoadState,User,Group,DynamicUser','--no-pager'],call.args[0])
            self.assertTrue(call.kwargs['capture_output'])
        raw=json.dumps(report)
        self.assertNotIn('private-token',raw);self.assertNotIn('taige.us',raw)

    def test_already_600_is_noop_without_backup_or_chmod(self):
        self.agent.chmod(0o600)
        with patch.object(secure.os,'fchmod') as chmod:
            report=secure.secure()
        self.assertEqual('already_private',report['status'])
        self.assertFalse(report['permissions_changed'])
        chmod.assert_not_called()
        self.assertEqual([],list(self.plans.glob('*/probe-permission.private.json')))
        self.assertEqual(1,self.command.call_count)

    def test_nonroot_or_dynamic_service_is_rejected_before_agent_change(self):
        for fields in (b'LoadState=loaded\nUser=www-data\nGroup=www-data\nDynamicUser=no\n',b'LoadState=loaded\nUser=\nGroup=\nDynamicUser=yes\n',b'LoadState=loaded\nUser=root\nGroup=root\nDynamicUser=yes\n'):
            self.command.return_value=subprocess.CompletedProcess([],0,fields)
            with patch.object(secure.os,'fchmod') as chmod:
                with self.assertRaisesRegex(secure.SecureProbeError,'^service_not_static_root$'):secure.secure()
            chmod.assert_not_called()
            self.assertEqual(0o644,self.agent.stat().st_mode&0o777)

    def test_static_root_with_explicit_group_keeps_root_read_access(self):
        self.command.return_value=subprocess.CompletedProcess([],0,b'LoadState=loaded\nUser=root\nGroup=static-service-group\nDynamicUser=no\n')
        result=secure.secure()
        self.assertEqual('secured',result['status'])
        record=json.loads(next(self.plans.glob('*/probe-permission.private.json')).read_bytes())
        self.assertTrue(record['service_criteria']['user_is_root_or_empty'])
        self.assertFalse(record['service_criteria']['group_is_root_or_empty'])
        self.assertNotIn('static-service-group',json.dumps(result))

    def test_nonexistent_unit_defaults_do_not_prove_static_root_identity(self):
        self.command.return_value=subprocess.CompletedProcess([],0,b'LoadState=not-found\nUser=\nGroup=\nDynamicUser=no\n')
        with patch.object(secure.os,'fchmod') as chmod:
            with self.assertRaisesRegex(secure.SecureProbeError,'^service_not_loaded$'):secure.secure()
        chmod.assert_not_called()
        self.assertEqual(0o644,self.agent.stat().st_mode&0o777)

    def test_symlink_nonroot_owner_and_nonregular_file_are_rejected(self):
        self.agent.rename(self.root/'original')
        self.agent.symlink_to(self.root/'original')
        with self.assertRaisesRegex(secure.SecureProbeError,'^agent_file_invalid$'):secure.secure()
        self.agent.unlink();self.agent.mkdir()
        with self.assertRaisesRegex(secure.SecureProbeError,'^agent_file_invalid$'):secure.secure()
        self.agent.rmdir();self.agent.write_bytes(self.body);self.agent.chmod(0o644)
        original=secure.root_owned
        def ownership(info):
            return False if info.st_ino==self.agent.stat().st_ino else original(info)
        with patch.object(secure,'root_owned',side_effect=ownership):
            with self.assertRaisesRegex(secure.SecureProbeError,'^agent_file_invalid$'):secure.secure()
        self.assertEqual(0o644,self.agent.stat().st_mode&0o777)

    def test_exact_json_https_public_root_url_and_token_length_required(self):
        valid=json.loads(self.body)
        bad=[dict(valid,other='secret'),dict(valid,token='short'),dict(valid,panel_url='http://taige.us/'),
             dict(valid,panel_url='https://unknown.private/'),dict(valid,panel_url='https://taige.us/private'),
             dict(valid,panel_url='https://user:secret@taige.us/'),dict(valid,panel_url='https://taige.us/?secret'),
             dict(valid,panel_url='https://taige.us/#secret'),dict(valid,panel_url='https://taige.us:7001/')]
        for body in bad:
            self.agent.write_text(json.dumps(body))
            with self.assertRaisesRegex(secure.SecureProbeError,'^agent_contract_invalid$'):secure.secure()
            self.assertEqual(0o644,self.agent.stat().st_mode&0o777)
        self.agent.write_bytes(b'{"token":"private-one","token":"private-two"}')
        with self.assertRaisesRegex(secure.SecureProbeError,'^agent_json_invalid$'):secure.secure()

    def test_metadata_save_failure_prevents_chmod(self):
        with patch.object(secure,'private_write',side_effect=OSError('private-metadata-error')),patch.object(secure.os,'fchmod') as chmod:
            with self.assertRaises(OSError):secure.secure()
        chmod.assert_not_called()
        self.assertEqual(0o644,self.agent.stat().st_mode&0o777)

    def test_content_or_path_drift_after_record_prevents_chmod(self):
        real_write=secure.private_write
        def changed(path,body):
            real_write(path,body)
            self.agent.write_bytes(self.body+b' ')
        with patch.object(secure,'private_write',side_effect=changed),patch.object(secure.os,'fchmod') as chmod:
            with self.assertRaisesRegex(secure.SecureProbeError,'^agent_changed$'):secure.secure()
        chmod.assert_not_called()
        self.assertEqual(0o644,self.agent.stat().st_mode&0o777)
        self.agent.write_bytes(self.body)
        def replaced(path,body):
            real_write(path,body)
            self.agent.rename(self.root/'old-inode')
            self.agent.write_bytes(self.body);self.agent.chmod(0o644)
        with patch.object(secure,'private_write',side_effect=replaced),patch.object(secure.os,'fchmod') as chmod:
            with self.assertRaisesRegex(secure.SecureProbeError,'^agent_changed$'):secure.secure()
        chmod.assert_not_called()

    def test_service_identity_drift_after_record_prevents_chmod(self):
        self.command.side_effect=[subprocess.CompletedProcess([],0,b'LoadState=loaded\nUser=\nGroup=\nDynamicUser=no\n'),
                                  subprocess.CompletedProcess([],0,b'LoadState=loaded\nUser=root\nGroup=root\nDynamicUser=no\n')]
        with patch.object(secure.os,'fchmod') as chmod:
            with self.assertRaisesRegex(secure.SecureProbeError,'^service_identity_changed$'):secure.secure()
        chmod.assert_not_called()

    def test_chmod_or_receipt_error_is_unknown_without_restoring_wide_permissions(self):
        real_fchmod=os.fchmod
        def partial(fd,mode):
            real_fchmod(fd,mode)
            raise OSError('private chmod failure')
        with patch.object(secure.os,'fchmod',side_effect=partial) as chmod:
            with self.assertRaisesRegex(secure.SecureProbeError,'^permission_change_outcome_unknown$'):secure.secure()
        self.assertEqual(1,chmod.call_count)
        self.assertEqual(0o600,self.agent.stat().st_mode&0o777)
        self.assertEqual(self.body,self.agent.read_bytes())
        self.agent.chmod(0o644)
        real_write=secure.private_write
        def no_receipt(path,body):
            if path.name=='probe-permission-receipt.private.json':raise OSError('private receipt failure')
            real_write(path,body)
        with patch.object(secure,'private_write',side_effect=no_receipt):
            with self.assertRaisesRegex(secure.SecureProbeError,'^permission_change_outcome_unknown$'):secure.secure()
        self.assertEqual(0o600,self.agent.stat().st_mode&0o777)

    def test_global_lock_prevents_concurrent_permission_change(self):
        with secure.operation_lock():
            with self.assertRaisesRegex(secure.SecureProbeError,'^operation_busy$'):secure.secure()
        self.assertEqual(0o644,self.agent.stat().st_mode&0o777)

    def test_service_errors_unknown_cli_and_unexpected_exception_are_redacted(self):
        self.command.side_effect=subprocess.TimeoutExpired(['private'],5,output=b'private-token',stderr=b'private-URL')
        with self.assertRaisesRegex(secure.SecureProbeError,'^service_inspection_failed$'):secure.secure()
        for error in (RuntimeError('private-token'),secure.SecureProbeError('private-URL')):
            output=io.StringIO()
            with patch.object(secure,'main',side_effect=error),contextlib.redirect_stdout(output):
                self.assertEqual(1,secure.safe_main())
            self.assertNotIn('private-token',output.getvalue());self.assertNotIn('private-URL',output.getvalue())
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(1,secure.safe_main(['private-token']))
        self.assertNotIn('private-token',output.getvalue())


if __name__ == '__main__':unittest.main()
