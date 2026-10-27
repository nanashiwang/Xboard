import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'.docker/upstream'))
import deploy_runtime as deploy
import install_entry_identity as installer


class RuntimeDeploymentTest(unittest.TestCase):
    def test_forced_command_key_restricts_source_forwarding_and_shell(self):
        blob=b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20'+b'a'*32
        public='ssh-ed25519 '+base64.b64encode(blob).decode()+' xboard-runtime-identity-20261027'
        line=installer.validate_key(public).decode()
        self.assertTrue(line.startswith('from="107.173.191.23",restrict,command="'))
        self.assertIn('/usr/bin/timeout 40s /usr/bin/python3 -E -s',line)
        self.assertNotIn('sudo',line)
        for invalid in (public+'\nssh-ed25519 bad',public.replace('ssh-ed25519','ssh-rsa'),public.replace('20261027','arbitrary')):
            with self.assertRaises(ValueError):installer.validate_key(invalid)

    def test_preflight_identity_failure_has_no_writes_or_guard_apply(self):
        node={'name':'approved','type':'anytls'}
        approved=[dict(key='U04',backend_id=365,public_id=366,source_name='approved',source_sha256=deploy.guard.fingerprint(node))]
        checks=[{'key':'U%02d'%i,'reason':'runtime_identity_check_failed'} for i in range(1,29)]
        saved={'phase':'prepared','source_hashes':{n:deploy.sha((deploy.SOURCE/n).read_bytes()) for n in deploy.FILES},'database_states':{'x':'same'}}
        with patch.object(deploy,'state',return_value=saved), patch.object(deploy,'read',side_effect=lambda p:deploy.KNOWN_HOST), \
             patch.object(deploy,'inputs',return_value=(approved,[],{}, {'x':'same'})), \
             patch.object(deploy.entry_identity,'evaluate_identity',return_value=checks), \
             patch.object(deploy,'write') as writes, patch.object(deploy.guard,'apply') as apply:
            self.assertEqual('preflight_identity_failed',deploy.preflight()['status'])
            writes.assert_not_called();apply.assert_not_called()

    def test_reviewed_unhealthy_keys_enable_guard_but_never_approve_identities(self):
        failed={'U08':'runtime_identity_timeout','U32':'runtime_tcp_unreachable'}
        report={'negative_pin_rejected':True,'metadata_ok':True,
                'identity_checks':[dict(key=k,reason=v) for k,v in failed.items()]}
        self.assertEqual(failed,deploy.reviewed_failures(report,failed))
        self.assertEqual({},deploy.reviewed_failures(dict(report,identity_checks=[]),failed))
        for expected in ({},{'U08':'runtime_public_key_mismatch'},{'U08':'runtime_identity_timeout'}):
            with self.assertRaises(ValueError):deploy.reviewed_failures(report,expected)
        for report in (dict(report,negative_pin_rejected=False),dict(report,metadata_ok=False),
                       dict(report,identity_checks=[{'key':'U01','reason':'runtime_identity_check_failed'}])):
            with self.assertRaises(ValueError):deploy.reviewed_failures(report,failed)

    def test_rollback_rejects_corrupt_backup_before_stopping_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);private=root/'private';record=root/'record';private.mkdir();record.mkdir()
            before={};source={}
            for name in deploy.FILES:
                (private/name).write_bytes(b'current');(record/(name+'.before')).write_bytes(b'original')
                before[name]={'sha256':deploy.sha(b'original'),'mode':0o600};source[name]=deploy.sha(b'current')
            (record/'guard.py.before').write_bytes(b'corrupted')
            with patch.object(deploy,'PRIVATE',private),patch.object(deploy,'RECORD',record), \
                 patch.object(deploy,'DROPIN',root/'missing'),patch.object(deploy,'state',return_value={'phase':'deployed','before':before,'source_hashes':source}), \
                 patch.object(deploy,'read',side_effect=lambda p,private=True:p.read_bytes()),patch.object(deploy,'run') as run:
                with self.assertRaisesRegex(ValueError,'backup_drift'):deploy.rollback()
                run.assert_not_called()
                self.assertEqual(b'current',(private/'guard.py').read_bytes())

    def test_source_change_is_reported_without_trust_or_database_writes(self):
        node={'name':'approved','type':'anytls','server':'original'}
        approved=[dict(key='U04',backend_id=365,public_id=366,source_name='approved',source_sha256=deploy.guard.fingerprint(node))]
        mappings=[dict(key='U04',pin='original-pin')]
        original=copy.deepcopy((approved,mappings))
        checks=[{'key':'U%02d'%i} for i in range(1,29)]
        saved={'phase':'prepared','source_hashes':{n:deploy.sha((deploy.SOURCE/n).read_bytes()) for n in deploy.FILES},'database_states':{'x':'same'}}
        with patch.object(deploy,'state',return_value=saved), patch.object(deploy,'read',return_value=deploy.KNOWN_HOST), \
             patch.object(deploy,'inputs',return_value=(approved,mappings,{}, {'x':'same'})), \
             patch.object(deploy.guard,'fetch_subscription',return_value=([dict(node,server='changed')],{'expire':10**12,'total':100,'upload':0,'download':0})), \
             patch.object(deploy.entry_identity,'evaluate_identity',side_effect=[checks,[{'key':'U04','reason':'runtime_public_key_mismatch'}]]), \
             patch.object(deploy,'write') as writes, patch.object(deploy.guard,'apply') as apply:
            result=deploy.preflight()
        self.assertEqual('preflight_metadata_failed',result['status'])
        self.assertFalse(result['metadata_ok']);self.assertTrue(result['negative_pin_rejected'])
        self.assertEqual('source_changed_requires_acceptance',result['metadata_checks'][0]['reason'])
        self.assertEqual(original,(approved,mappings));writes.assert_not_called();apply.assert_not_called()
        self.assertNotIn('original-pin',json.dumps(result));self.assertNotIn('server',json.dumps(result))

    def test_metadata_failure_requires_exact_separate_review_and_cannot_hide_runtime_failure(self):
        expected={'U06':'source_changed_requires_acceptance'}
        report={'negative_pin_rejected':True,'metadata_ok':False,'metadata_checks':[dict(key=k,reason=v) for k,v in expected.items()],
                'identity_checks':[dict(key='U06',reason='runtime_identity_timeout')]}
        runtime={'U06':'runtime_identity_timeout'}
        self.assertEqual(runtime,deploy.reviewed_failures(report,runtime,expected))
        for args in ((report,runtime,{}),(report,{},expected),
                     (dict(report,metadata_ok=True),runtime,expected),
                     (dict(report,metadata_checks=[dict(key='U07',reason='source_changed_requires_acceptance')]),runtime,expected),
                     (dict(report,metadata_checks=[dict(key='U06',reason='quota_exhausted')]),runtime,expected),
                     (dict(report,negative_pin_rejected=False),runtime,expected)):
            with self.assertRaises(ValueError):deploy.reviewed_failures(*args)

    def test_rollback_restores_only_code_and_timer_without_pins_database_or_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);private=root/'private';record=root/'record';private.mkdir();record.mkdir()
            before={};source={}
            for name in deploy.FILES:
                (private/name).write_bytes(b'current');source[name]=deploy.sha(b'current')
                before[name]=None if name=='entry_identity.py' else {'sha256':deploy.sha(b'original'),'mode':0o600}
                if before[name]:(record/(name+'.before')).write_bytes(b'original')
            for name in ('pinned.private','approved.private','guard-state.json'):(private/name).write_bytes(b'keep')
            dropin=root/'override';dropin.write_bytes(deploy.OVERRIDE)
            saved={'phase':'deployed','before':before,'source_hashes':source}
            with patch.object(deploy,'PRIVATE',private),patch.object(deploy,'RECORD',record),patch.object(deploy,'DROPIN',dropin), \
                 patch.object(deploy,'state',return_value=saved),patch.object(deploy,'read',side_effect=lambda p,private=True:p.read_bytes()), \
                 patch.object(deploy,'write',side_effect=lambda p,data,**kw:p.write_bytes(data)),patch.object(deploy,'run') as run, \
                 patch.object(deploy,'props',return_value={'ActiveState':'active'}):
                result=deploy.rollback()
            self.assertEqual('rolled_back',result['status'])
            self.assertFalse((private/'entry_identity.py').exists());self.assertFalse(dropin.exists())
            self.assertTrue(all((private/n).read_bytes()==b'keep' for n in ('pinned.private','approved.private','guard-state.json')))
            self.assertEqual(b'original',(private/'guard.py').read_bytes())
            self.assertTrue(all(call.args[0][0]=='systemctl' for call in run.call_args_list))


if __name__=='__main__':unittest.main()
