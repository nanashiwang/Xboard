import base64
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2] / '.docker/upstream'
spec=importlib.util.spec_from_file_location('accept_source_address',ROOT/'accept_source_address.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class AddressAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.private=self.root/'private';self.private.mkdir(mode=0o700)
        self.plans=self.root/'plans';self.plans.mkdir(mode=0o700)
        self.plan_id='a'*32;self.directory=self.plans/self.plan_id;self.directory.mkdir(mode=0o700)
        self.allocation=json.loads((ROOT/'allocation.json').read_bytes())
        self.prepare=a.load_module('address_test_prepare',ROOT/'prepare.py')
        self.guard=a.load_module('address_test_guard',ROOT/'guard.py')
        self.now=1000.25;self.source=[];self.approved=[];self.rows=[];self.snapshots=[]
        pin=base64.b64encode(b'p'*32).decode()
        for scope in self.allocation['routes']:
            key=scope['key'];old={'type':scope['upstream_type'],'name':'fixture-'+key,'server':'8.8.8.8','port':443,
                'password':'fixture-secret','sni':'approved.test.invalid','udp':True,'skip-cert-verify':True,'client-fingerprint':'chrome'}
            fresh=dict(old,server='source.test.invalid') if key=='U01' else dict(old)
            approval={k:scope[k] for k in ('key','backend_id','public_id')}
            approval.update(source_name=old['name'],source_sha256=self.guard.fingerprint(old),extra_history={'keep':key})
            settings={'type':scope['upstream_type'],'server':old['server'],'server_port':443,'password':old['password'],
                      'tls':{'enabled':True,'insecure':False,'server_name':old['sni'],'certificate_public_key_sha256':[pin]}}
            backend={'id':scope['backend_id'],'machine_id':21,'parent_id':None,'enabled':1,'show':0,
                     'tags':['upstream-extension-backend'],'group_ids':[1,6],'custom_outbounds':a.canonical([{'protocol':scope['upstream_type'],'settings':settings}]).decode(),'protocol_settings':'{"keep":true}'}
            public={'id':scope['public_id'],'parent_id':scope['backend_id'],'tags':['upstream-extension-public'],'show':1,'enabled':0}
            state={'backend':copy.deepcopy(backend),'public':copy.deepcopy(public)}
            state['backend']['tags']=a.canonical(backend['tags']).decode();state['backend']['group_ids']='[1,6]'
            state['public']['tags']=a.canonical(public['tags']).decode()
            snap={'key':key,'backend':backend,'public':public,'state':state,'state_sha256':a.digest(state)}
            self.source.append(fresh);self.approved.append(approval);self.snapshots.append(snap)
            self.rows.append({'key':key,'approved':approval,'snapshot':snap,'source':fresh,'candidates':[]})
        self.snapshot_value={'machine_id':21,'routes':self.snapshots}
        self.manifest={'machine_id':21,'routes':[{k:r[k] for k in ('key','backend_id','public_id')} for r in self.approved]}
        self.approved_bytes=json.dumps(self.approved,indent=2).encode()
        a.private_write(self.private/'approved.private',self.approved_bytes)
        a.private_write(self.private/'manifest.private',a.canonical(self.manifest))
        a.private_write(self.private/'pinned.private',b'private-pins-must-not-change')
        a.private_write(self.private/'source-url.secret',b'https://private.example/secret-do-not-log')
        self.plan={'schema':1,'plan_id':self.plan_id,'prepared_at':1000,'allocation_sha256':a.digest(self.allocation),
                   'approved_file_sha256':a.bytes_sha(self.approved_bytes),'manifest_file_sha256':a.digest(self.manifest),'routes':self.rows}
        self.write_plan();self.new_sha=self.guard.fingerprint(self.source[0])
        self.usage={'expire':100000,'total':10000,'upload':1,'download':2}
        self.snapshot_calls=0;self.before_snapshot_return=None
        self.driver=a.Driver(private_root=self.private,plan_root=self.plans,sibling=ROOT,prepare=self.prepare,guard=self.guard,
                             fetch=lambda:(copy.deepcopy(self.source),self.usage),snapshot=self.snapshot,clock=lambda:self.now)

    def write_plan(self):
        path=self.directory/'plan.private.json'
        path.unlink(missing_ok=True);body=a.canonical(self.plan);a.private_write(path,body);self.plan_sha=a.bytes_sha(body)

    def snapshot(self,allocation,manifest):
        self.snapshot_calls+=1
        if self.before_snapshot_return:self.before_snapshot_return(self.snapshot_calls)
        return copy.deepcopy(self.snapshot_value)

    def run_accept(self,key='U01',sha=None):
        return self.driver.run(self.plan_id,self.plan_sha,key,sha or self.new_sha)

    def rejects(self,reason,call):
        with self.assertRaises(a.AcceptanceError) as found:call()
        self.assertEqual(reason,str(found.exception))

    def test_exact_server_proof_only_updates_one_fingerprint_preserving_every_other_field(self):
        original=copy.deepcopy(self.approved);pinned=(self.private/'pinned.private').read_bytes();url=(self.private/'source-url.secret').read_bytes()
        original_state=copy.deepcopy(self.snapshot_value)
        result=self.run_accept();saved=json.loads((self.private/'approved.private').read_bytes())
        self.assertEqual(saved[0]['source_sha256'],self.new_sha);saved[0]['source_sha256']=original[0]['source_sha256'];self.assertEqual(saved,original)
        self.assertEqual(original_state,self.snapshot_value);self.assertEqual(pinned,(self.private/'pinned.private').read_bytes());self.assertEqual(url,(self.private/'source-url.secret').read_bytes())
        self.assertTrue(result['source_baseline_mutated']);self.assertFalse(result['public_key_baseline_mutated']);self.assertFalse(result['database_mutated'])
        self.assertTrue(result['requires_reprepare']);self.assertTrue(result['prepare_plan_invalidated'])
        self.assertEqual(2,self.snapshot_calls)
        self.assertEqual(self.approved_bytes,(self.directory/'source-address-U01/backup/approved.private').read_bytes())
        for path in (self.directory/'source-address-U01').rglob('*'):self.assertEqual(0,path.stat().st_mode&0o077)
        self.assertEqual(0o600,(self.private/'approved.private').stat().st_mode&0o777)
        output=json.dumps(result)
        for secret in ('fixture-secret','approved.test.invalid','source.test.invalid','private.example',pinned.decode()):self.assertNotIn(secret,output)
        self.assertEqual([],list(self.private.glob('.source-address-*')))

    def test_fresh_source_must_match_plan_and_explicit_expected_sha(self):
        self.rejects('source_fingerprint_mismatch',lambda:self.run_accept(sha='f'*64))
        self.assertEqual(self.approved_bytes,(self.private/'approved.private').read_bytes())

    def test_non_server_field_changes_do_not_match_old_commitment(self):
        for field,value in [('password','other-secret'),('sni','different.test.invalid'),('client-fingerprint','firefox'),('udp',False),('skip-cert-verify',False),('new_field',1)]:
            with self.subTest(field=field):
                source=copy.deepcopy(self.source[0]);source[field]=value
                reason='source_contract_invalid' if field in ('password','sni') else 'not_exact_server_only_change'
                self.rejects(reason,lambda:a.exact_address_proof(self.prepare,self.guard,source,a.digest(source),self.approved[0],self.rows[0]['snapshot']['state']))
        self.assertEqual(self.approved_bytes,(self.private/'approved.private').read_bytes())

    def test_protocol_port_sni_transport_and_tls_boundaries_reject(self):
        for change in (lambda s:s.update(type='trojan'),lambda s:s.update(port=444),lambda s:s.update(network='ws')):
            source=copy.deepcopy(self.source[0]);change(source)
            with self.assertRaises(a.AcceptanceError):a.exact_address_proof(self.prepare,self.guard,source,a.digest(source),self.approved[0],self.rows[0]['snapshot']['state'])
        for mutate in (lambda tls:tls.update(insecure=True),lambda tls:tls.update(enabled=False),lambda tls:tls.update(certificate_public_key_sha256=[])):
            state=copy.deepcopy(self.rows[0]['snapshot']['state']);entries=json.loads(state['backend']['custom_outbounds']);mutate(entries[0]['settings']['tls']);state['backend']['custom_outbounds']=a.canonical(entries).decode()
            self.rejects('source_contract_invalid',lambda:a.exact_address_proof(self.prepare,self.guard,self.source[0],self.new_sha,self.approved[0],state))

    def test_other_key_or_free_endpoint_input_is_rejected(self):
        for key in ('U02','U00','U01,U02',None):self.rejects('arguments_invalid',lambda:self.run_accept(key=key))
        self.rejects('arguments_invalid',lambda:self.run_accept(sha='https://not-allowed'))
        self.assertEqual(0,self.snapshot_calls)

    def test_plan_approved_and_manifest_byte_hash_drift_rejected(self):
        self.rejects('plan_hash_mismatch',lambda:self.driver.run(self.plan_id,'f'*64,'U01',self.new_sha))
        path=self.private/'approved.private';path.write_bytes(self.approved_bytes+b' ')
        self.rejects('approved_file_drift',self.run_accept);path.write_bytes(self.approved_bytes)
        path=self.private/'manifest.private';path.write_bytes(path.read_bytes()+b' ')
        self.rejects('manifest_drift',self.run_accept)

    def test_actual_full_database_state_drift_rejected_without_backup_or_write(self):
        self.snapshots[5]['state']['backend']['group_ids']='[2,6]';self.snapshots[5]['state_sha256']=a.digest(self.snapshots[5]['state'])
        # Keep the committed plan unchanged while simulating a later DB edit.
        self.rejects('database_state_drift',self.run_accept)
        self.assertFalse((self.directory/'source-address-U01/backup').exists())
        self.assertEqual(self.approved_bytes,(self.private/'approved.private').read_bytes())

    def test_second_database_snapshot_drift_aborts_before_intent(self):
        def drift(call):
            if call==2:
                self.snapshots[1]['state']['backend']['protocol_settings']='{"changed":true}'
                self.snapshots[1]['state_sha256']=a.digest(self.snapshots[1]['state'])
        self.before_snapshot_return=drift
        self.rejects('database_state_drift',self.run_accept)
        self.assertTrue((self.directory/'source-address-U01/backup/approved.private').exists())
        self.assertFalse((self.directory/'source-address-U01/intent.private.json').exists())
        self.assertEqual(self.approved_bytes,(self.private/'approved.private').read_bytes())

    def test_backups_and_durable_intent_exist_before_atomic_replace(self):
        replace=os.replace;seen=[]
        def inspect(source,target):
            operation=self.directory/'source-address-U01'
            self.assertEqual(self.approved_bytes,(operation/'backup/approved.private').read_bytes())
            self.assertEqual((self.private/'manifest.private').read_bytes(),(operation/'backup/manifest.private').read_bytes())
            self.assertTrue((operation/'request.private.json').is_file());self.assertTrue((operation/'intent.private.json').is_file())
            seen.append(True);return replace(source,target)
        with patch.object(a.os,'replace',side_effect=inspect):self.run_accept()
        self.assertEqual([True],seen)

    def test_atomic_failure_preserves_old_file_and_blocks_replay(self):
        with patch.object(a.os,'replace',side_effect=OSError('private-not-for-output')):
            self.rejects('accept_outcome_unknown',self.run_accept)
        self.assertEqual(self.approved_bytes,(self.private/'approved.private').read_bytes())
        self.assertEqual([],list(self.private.glob('.source-address-*')))
        self.rejects('previous_outcome_unknown',self.run_accept)

    def test_last_atomic_comparison_detects_new_writer(self):
        original=a.atomic_approved_replace
        def concurrent(path,old,new):
            path.write_bytes(old+b' ')
            return original(path,old,new)
        with patch.object(a,'atomic_approved_replace',side_effect=concurrent):self.rejects('accept_outcome_unknown',self.run_accept)
        self.assertEqual(self.approved_bytes+b' ',(self.private/'approved.private').read_bytes())
        self.rejects('previous_outcome_unknown',self.run_accept)

    def test_receipt_failure_does_not_rollback_accepted_baseline_or_allow_replay(self):
        write=a.private_write
        def fail_receipt(path,value):
            if path.name=='receipt.private.json':raise OSError('private-failure')
            return write(path,value)
        with patch.object(a,'private_write',side_effect=fail_receipt):self.rejects('accept_outcome_unknown',self.run_accept)
        self.assertEqual(self.new_sha,json.loads((self.private/'approved.private').read_bytes())[0]['source_sha256'])
        self.rejects('previous_outcome_unknown',self.run_accept)

    def test_successful_acceptance_is_not_replayed(self):
        self.run_accept();self.rejects('acceptance_already_recorded',self.run_accept)

    def test_expired_plan_duplicate_source_or_bad_quota_do_not_write(self):
        self.now=9000;self.rejects('plan_invalid_or_expired',self.run_accept);self.now=1000.25
        self.source.append(copy.deepcopy(self.source[0]));self.rejects('source_missing_or_ambiguous',self.run_accept);self.source.pop()
        self.usage['total']=1;self.rejects('source_quota_or_expiry',self.run_accept)
        self.assertEqual(self.approved_bytes,(self.private/'approved.private').read_bytes())

    def test_source_expiry_window_is_rechecked_before_write(self):
        self.usage['expire']=1400
        self.before_snapshot_return=lambda call:setattr(self,'now',1200) if call==2 else None
        self.rejects('source_quota_or_expiry',self.run_accept)
        self.assertFalse((self.directory/'source-address-U01/intent.private.json').exists())
        self.assertEqual(self.approved_bytes,(self.private/'approved.private').read_bytes())

    def test_global_and_plan_locks_prevent_parallel_acceptance(self):
        for path in (self.plans/'scope-restore.lock',self.directory/'maintenance.lock'):
            with a.lock(path):self.rejects('acceptance_busy',self.run_accept)

    def test_private_storage_and_unknown_input_keys_cannot_be_used(self):
        path=self.private/'approved.private';path.chmod(0o644)
        self.rejects('private_file_invalid',self.run_accept);path.chmod(0o600)
        original=self.private/'actual-approved';path.rename(original);path.symlink_to(original)
        with self.assertRaises(OSError):self.run_accept()

    def test_backup_failure_never_reaches_approved_replacement(self):
        write=a.private_write
        def broken(path,value):
            if path.name=='manifest.private':raise OSError('private-backup-error')
            return write(path,value)
        with patch.object(a,'private_write',side_effect=broken),patch.object(a.os,'replace') as replace:
            with self.assertRaises(OSError):self.run_accept()
            replace.assert_not_called()
        self.assertEqual(self.approved_bytes,(self.private/'approved.private').read_bytes())

    def test_safe_cli_rejects_unknown_fields_and_redacts_exceptions(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(1,a.safe_main(['--ip','private-do-not-print']))
        self.assertNotIn('private-do-not-print',output.getvalue())
        output=io.StringIO()
        with patch.object(a,'main',side_effect=RuntimeError('private-do-not-print')),contextlib.redirect_stdout(output):self.assertEqual(1,a.safe_main([]))
        self.assertNotIn('private-do-not-print',output.getvalue())

if __name__=='__main__':unittest.main()
