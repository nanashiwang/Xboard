import contextlib
import copy
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


HERE=Path(__file__).resolve().parents[2]/'.docker/upstream'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
repair=load('legacy_guard_scope',HERE/'legacy_guard_scope.py')
scope=load('legacy_scope_test',HERE/'scope_restore.py')
prepare=load('legacy_prepare_test',HERE/'prepare.py')


class LegacyScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.private=self.root/'private';self.private.mkdir(mode=0o700)
        self.plans=self.root/'plans';self.plans.mkdir(mode=0o700)
        self.approved=[];rows=[]
        self.allocation=json.loads((HERE/'allocation.json').read_bytes())
        for route in self.allocation['routes']:
            key=route['key']
            self.approved.append({**{field:route[field] for field in ('key','backend_id','public_id')},
                                  'source_name':'private-source-'+key,'source_sha256':'a'*64})
            backend={'id':route['backend_id'],'machine_id':21,'tags':['upstream-extension-backend'],
                     'enabled':True,'custom_outbounds':'private-credentials','group_ids':'[1]'}
            public={'id':route['public_id'],'parent_id':route['backend_id'],'tags':['upstream-extension-public'],'show':True}
            state={'backend':copy.deepcopy(backend),'public':copy.deepcopy(public)}
            rows.append({'key':key,'backend':backend,'public':public,'state':state,'state_sha256':scope.digest(state)})
        self.snapshot={'machine_id':21,'routes':rows}
        self.fake=SimpleNamespace(validate_scope=prepare.validate_scope,snapshot_database=lambda *_:copy.deepcopy(self.snapshot))
        (self.private/'approved.private').write_bytes(scope.canonical(self.approved));(self.private/'approved.private').chmod(0o600)
        minimal={'machine_id':21,'routes':[{field:r[field] for field in ('key','backend_id','public_id')} for r in self.allocation['routes']]}
        self.manifest=scope.canonical(minimal)
        (self.private/'manifest.private').write_bytes(self.manifest);(self.private/'manifest.private').chmod(0o600)
        for module in (scope,repair):
            for name,value in [('PRIVATE_ROOT',self.private),('PLAN_ROOT',self.plans)]:
                patcher=patch.object(module,name,value);patcher.start();self.addCleanup(patcher.stop)
        original=repair.code_signature
        # Test files are owned by the current developer; production still requires root.
        def signature(info):
            fields={key:getattr(info,key) for key in ('st_dev','st_ino','st_uid','st_gid','st_mode','st_size','st_mtime_ns','st_ctime_ns')}
            fields['st_uid']=0
            return original(SimpleNamespace(**fields))
        patcher=patch.object(repair,'code_signature',side_effect=signature);patcher.start();self.addCleanup(patcher.stop)
        fixtures={'guard.py':b'reviewed metadata guard fixture\n','guard-apply.php':b'reviewed metadata withdrawal fixture\n'}
        patcher=patch.object(repair,'REVIEWED',{name:repair.sha(body) for name,body in fixtures.items()})
        patcher.start();self.addCleanup(patcher.stop)
        for name,body in fixtures.items():
            path=self.private/name;path.write_bytes(body);path.chmod(0o600)
        self.calls=[];self.container_exists=False;self.target_matches=False;self.target_private=False;self.parent_safe=True

    def container(self,action,raw):
        self.assertEqual(self.manifest,raw)
        self.calls.append(action)
        if action=='restore':
            intents=list(self.plans.glob('*/legacy-guard-scope-intent.private.json'))
            self.assertEqual(1,len(intents));self.assertEqual(0o600,intents[0].stat().st_mode&0o777)
            self.assertEqual(0o700,intents[0].parent.stat().st_mode&0o777)
            self.container_exists=self.target_matches=self.target_private=True
        return {'status':'restored' if action=='restore' else 'inspected','manifest_sha256':repair.sha(raw),
                'target_exists':self.container_exists,'target_matches':self.target_matches,'target_private':self.target_private,
                'parent_safe':self.parent_safe,'manifest_created':action=='restore'}

    def run_tool(self,action):
        return repair.run(action,scope,self.fake,self.container)

    def test_inspect_hashes_exact_reviewed_code_and_has_no_secret_or_mutation(self):
        before=(copy.deepcopy(self.snapshot),(self.private/'approved.private').read_bytes())
        report=self.run_tool('inspect')
        self.assertTrue(report['metadata_only_exact']);self.assertEqual(41,report['route_count'])
        self.assertEqual(['inspect'],self.calls);self.assertEqual([],list(path for path in self.plans.iterdir() if path.is_dir()))
        self.assertEqual(before,(self.snapshot,(self.private/'approved.private').read_bytes()))
        self.assertFalse(any(report[k] for k in ('database_mutated','guard_code_mutated','public_key_baseline_mutated','source_baseline_mutated','guard_executed')))
        self.assertNotIn('private-source',json.dumps(report));self.assertNotIn('private-credentials',json.dumps(report))

    def test_restore_only_missing_scope_intent_before_copy_and_receipt_after(self):
        before=(self.private/'manifest.private').read_bytes()
        report=self.run_tool('restore')
        self.assertEqual(['inspect','restore','inspect'],self.calls)
        self.assertEqual('legacy_guard_scope_restored',report['status'])
        self.assertEqual(before,(self.private/'manifest.private').read_bytes())
        directory=self.plans/report['metadata_id']
        self.assertEqual(report,json.loads((directory/'legacy-guard-scope-receipt.private.json').read_bytes()))
        intent=json.loads((directory/'legacy-guard-scope-intent.private.json').read_bytes())
        self.assertTrue(intent['target_missing_before']);self.assertEqual(41,len(intent['state_sha256']))

    def test_different_guard_hash_inspect_reports_false_restore_refuses_before_db(self):
        (self.private/'guard.py').write_text('new runtime guard or arbitrary code')
        report=self.run_tool('inspect');self.assertFalse(report['metadata_only_exact'])
        self.calls.clear()
        with self.assertRaisesRegex(repair.ScopeRepairError,'installed_guard_not_reviewed_metadata_only'):self.run_tool('restore')
        self.assertEqual([],self.calls)

    def test_installed_code_symlink_or_writable_file_refused(self):
        path=self.private/'guard.py';path.chmod(0o622)
        with self.assertRaisesRegex(repair.ScopeRepairError,'installed_guard_file_invalid'):self.run_tool('inspect')
        path.unlink();path.symlink_to(HERE/'guard.py')
        with self.assertRaisesRegex(repair.ScopeRepairError,'installed_guard_file_invalid'):self.run_tool('inspect')

    def test_existing_different_or_nonprivate_manifest_never_overwritten(self):
        self.container_exists=True
        for matches,private,reason in [(False,True,'container_manifest_conflict'),(True,False,'container_manifest_permissions')]:
            self.target_matches,self.target_private=matches,private
            with self.assertRaisesRegex(repair.ScopeRepairError,reason):self.run_tool('restore')
        self.assertNotIn('restore',self.calls)

    def test_existing_exact_private_manifest_is_noop(self):
        self.container_exists=self.target_matches=self.target_private=True
        report=self.run_tool('restore')
        self.assertEqual('legacy_guard_scope_already_matches',report['status'])
        self.assertEqual(['inspect'],self.calls);self.assertEqual([],list(path for path in self.plans.iterdir() if path.is_dir()))

    def test_host_manifest_must_exactly_match_fixed_allocation(self):
        (self.private/'manifest.private').write_bytes(self.manifest+b' ')
        with self.assertRaisesRegex(repair.ScopeRepairError,'host_manifest_not_exact_minimal_scope'):self.run_tool('restore')
        self.assertEqual([],self.calls)

    def test_db_ownership_and_full_state_drift_prevent_restore(self):
        self.snapshot['routes'][0]['public']['parent_id']=148
        with self.assertRaises(scope.ScopeError):self.run_tool('restore')
        self.assertEqual([],self.calls)
        self.snapshot['routes'][0]['public']['parent_id']=self.snapshot['routes'][0]['backend']['id']
        count=[0]
        def snapshot(*_):
            count[0]+=1
            result=copy.deepcopy(self.snapshot)
            if count[0]==2:
                result['routes'][0]['state']['backend']['group_ids']='[1,2]'
                result['routes'][0]['state_sha256']=scope.digest(result['routes'][0]['state'])
            return result
        self.fake.snapshot_database=snapshot
        with self.assertRaisesRegex(repair.ScopeRepairError,'database_state_changed'):self.run_tool('restore')
        self.assertNotIn('restore',self.calls)

    def test_host_approval_drift_after_intent_prevents_dispatch(self):
        original=scope.private_write
        def write(path,raw):
            original(path,raw)
            if path.name=='legacy-guard-scope-intent.private.json':
                (self.private/'approved.private').write_bytes(scope.canonical(self.approved)+b' ')
        with patch.object(scope,'private_write',side_effect=write):
            with self.assertRaisesRegex(repair.ScopeRepairError,'repair_input_changed'):self.run_tool('restore')
        self.assertNotIn('restore',self.calls)

    def test_host_approval_drift_during_second_snapshot_prevents_dispatch(self):
        count=[0]
        def snapshot(*_):
            count[0]+=1
            if count[0]==2:
                (self.private/'approved.private').write_bytes(scope.canonical(self.approved)+b' ')
            return copy.deepcopy(self.snapshot)
        self.fake.snapshot_database=snapshot
        with self.assertRaisesRegex(repair.ScopeRepairError,'repair_input_changed'):self.run_tool('restore')
        self.assertNotIn('restore',self.calls)

    def test_after_dispatch_timeout_is_unknown_and_preserves_intent(self):
        original=self.container
        def unavailable(action,raw):
            if action=='restore':raise subprocess.TimeoutExpired('private-command',30,stderr=b'private-password')
            return original(action,raw)
        with self.assertRaisesRegex(repair.ScopeRepairError,'^container_commit_unknown$'):
            repair.run('restore',scope,self.fake,unavailable)
        self.assertEqual(1,len(list(self.plans.glob('*/legacy-guard-scope-intent.private.json'))))
        self.assertEqual([],list(self.plans.glob('*/legacy-guard-scope-receipt.private.json')))

    def test_container_response_fixed_contract_and_no_raw_error_leak(self):
        for response in (b'private-server-error',b'{"reason":"private-password"}'):
            with patch.object(repair.subprocess,'run',return_value=subprocess.CompletedProcess([],1,response,b'private-stderr')):
                with self.assertRaises(repair.ScopeRepairError) as error:repair.container_scope('restore',self.manifest)
                self.assertNotIn('private',str(error.exception))

    def test_cli_arguments_and_generic_failure_are_fixed(self):
        for args in ([],['restore','/private/path'],['start']):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):self.assertEqual(1,repair.safe_main(args))
            self.assertEqual('invalid_arguments',json.loads(output.getvalue())['reason'])
            self.assertNotIn('/private/path',output.getvalue())
        output=io.StringIO()
        with patch.object(repair.os,'geteuid',return_value=0),patch.object(repair,'run',side_effect=RuntimeError('private-secret')),contextlib.redirect_stdout(output):
            self.assertEqual(1,repair.safe_main(['inspect']))
        self.assertNotIn('private-secret',output.getvalue())


if __name__=='__main__':unittest.main()
