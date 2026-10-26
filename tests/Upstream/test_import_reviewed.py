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

def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

r=module('reviewed_import',ROOT/'import_reviewed.py')
fixture_module=module('address_fixture',Path(__file__).with_name('test_accept_source_address.py'))
maintain=module('imported_maintenance',ROOT/'maintain.py')

class ImportTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.private=r.openssl(['genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:4096'])
  cls.public=r.public_from_key(cls.private)

 def setUp(self):
  self.fixture=fixture_module.AddressAcceptanceTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
  f=self.fixture
  for source,approval,planned in zip(f.source,f.approved,f.rows):
   source['server']='source.test.invalid';approval['source_sha256']=f.guard.fingerprint(source);planned['source']=copy.deepcopy(source)
  # The imported plan is a normal current prepare result, with no accepted pins.
  f.approved_bytes=r.canon(f.approved);(f.private/'approved.private').write_bytes(f.approved_bytes)
  f.plan.update(approved_file_sha256=r.bsha(f.approved_bytes),production_mutated=False,trust_status='candidate_observations_only_not_approved')
  f.write_plan();self.driver=r.Driver(private_root=f.private,plan_root=f.plans,sibling=ROOT,prepare=f.prepare,guard=f.guard,
     snapshot=f.snapshot,fetch=lambda:(copy.deepcopy(f.source),f.usage),clock=lambda:f.now)
  original=r.openssl
  def crypto(args,body=None,timeout=60):
   return self.private if args[0]=='genpkey' else original(args,body,timeout)
  self.crypto=patch.object(r,'openssl',side_effect=crypto);self.crypto.start();self.addCleanup(self.crypto.stop)
  self.recipient=self.driver.run('recipient',f.plan_id,f.plan_sha)

 def identity(self,key='U01'):
  return {'key':key,'ip':'2606:4700:4700::1111','port':443,'sni':'approved.test.invalid','pin':base64.b64encode(b'n'*32).decode()}

 def encrypt(self,identity):
  # Test-only public-key file; plaintext is stdin, never an argument or output.
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'public.pem';path.write_bytes(self.public)
   raw=r.openssl(['pkeyutl','-encrypt','-pubin','-inkey',str(path),'-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256','-pkeyopt','rsa_mgf1_md:sha256'],r.canon(identity))
  self.assertEqual(len(raw),512)
  return base64.b64encode(raw).decode()

 def row(self,key='U01'):
  identity=self.identity(key);commit=r.digest(identity)
  witness=lambda role:{'observer_sha256':('1' if role=='entry' else '2')*64,'evidence_sha256':('3' if role=='entry' else '4')*64,
    'identity_sha256':commit,'observed_at':1000,'source_dns':role=='entry','ca_validated':False}
  return {'key':key,'candidate_digest':commit,'ciphertext':self.encrypt(identity),'not_before':900,'not_after':2000,
          'witnesses':{'entry':witness('entry'),'independent':witness('independent')}}

 def payload(self,rows=None):
  f=self.fixture
  return {'schema':1,'plan_id':f.plan_id,'plan_sha256':f.plan_sha,'recipient_sha256':self.recipient['public_key_sha256'],'rows':rows or [self.row()]}

 def run_import(self,payload=None):
  f=self.fixture
  return self.driver.run('import',f.plan_id,f.plan_sha,r.canon(payload or self.payload()))

 def reject(self,reason,fn):
  with self.assertRaises((r.ImportErrorBounded,r.a.AcceptanceError)) as e:fn()
  self.assertEqual(reason,str(e.exception))

 def test_recipient_is_4096_public_only_and_never_overwritten(self):
  f=self.fixture;folder=f.directory/'reviewed-recipient';before={p.name:p.read_bytes() for p in folder.iterdir()}
  self.assertEqual(self.recipient,self.driver.run('recipient',f.plan_id,f.plan_sha))
  self.assertEqual(before,{p.name:p.read_bytes() for p in folder.iterdir()})
  for p in folder.iterdir():self.assertEqual(p.stat().st_mode&0o777,0o600)
  self.assertNotIn('PRIVATE KEY',json.dumps(self.recipient));self.assertNotIn(self.private.decode(),json.dumps(self.recipient))

 def test_import_creates_only_new_plan_and_preserves_bindings_and_validity(self):
  f=self.fixture;before=(f.directory/'plan.private.json').read_bytes();original_files={name:(f.private/name).read_bytes() for name in ('approved.private','manifest.private','pinned.private','source-url.secret')}
  result=self.run_import();newpath=f.plans/result['plan_id']/'plan.private.json';new=json.loads(newpath.read_bytes())
  self.assertEqual(before,(f.directory/'plan.private.json').read_bytes());self.assertEqual(r.bsha(newpath.read_bytes()),result['plan_sha256'])
  self.assertEqual(f.plan['prepared_at'],new['prepared_at']);self.assertEqual(f.plan['approved_file_sha256'],new['approved_file_sha256'])
  self.assertEqual(f.plan['manifest_file_sha256'],new['manifest_file_sha256']);self.assertEqual(f.plan['routes'][0]['snapshot'],new['routes'][0]['snapshot'])
  self.assertEqual(original_files,{name:(f.private/name).read_bytes() for name in original_files})
  for key in ('source_baseline_mutated','public_key_baseline_mutated','database_mutated','original_plan_mutated','production_mutated'):self.assertFalse(result[key])
  candidate=new['routes'][0]['candidates'][0];self.assertFalse(candidate['panel_dns_observed']);self.assertEqual(candidate['source_dns_observation_point'],'entry')
  self.assertTrue(candidate['source_dns_endpoint']);self.assertTrue(result['manual_selection_required'])
  self.assertEqual(newpath.stat().st_mode&0o777,0o600)
  text=json.dumps(result)
  for secret in ('source.test.invalid','approved.test.invalid','2606:4700:4700::1111',self.identity()['pin'],'fixture-secret'):self.assertNotIn(secret,text)
  scopes,approvals=maintain.validate_scope(f.allocation,f.approved,f.manifest)
  selected=maintain.selected_rows(new,{'U01':candidate['candidate_digest']},scopes,approvals,'withdraw',f.now)
  self.assertEqual(selected[0]['identity'],self.identity())

 def test_ciphertext_reencrypt_and_row_order_cannot_replay_same_evidence(self):
  payload=self.payload([self.row('U01'),self.row('U04')]);self.run_import(payload)
  second=copy.deepcopy(payload);second['rows'].reverse()
  for row in second['rows']:row['ciphertext']=self.encrypt(self.identity(row['key']))
  self.reject('payload_already_recorded',lambda:self.run_import(second))

 def test_wrong_recipient_plan_or_candidate_digest_rejected(self):
  for field,value in [('recipient_sha256','f'*64),('plan_sha256','f'*64),('plan_id','f'*32)]:
   payload=self.payload();payload[field]=value
   with self.assertRaises(r.ImportErrorBounded):self.run_import(payload)
  payload=self.payload();payload['rows'][0]['candidate_digest']='e'*64
  for witness in payload['rows'][0]['witnesses'].values():witness['identity_sha256']='e'*64
  self.reject('candidate_digest_mismatch',lambda:self.run_import(payload))

 def test_duplicate_unknown_key_extra_plaintext_fields_and_size_rejected(self):
  for rows in ([self.row(),self.row()], [dict(self.row(),key='U42')], [dict(self.row(),ip='8.8.8.8')]):
   with self.assertRaises(r.ImportErrorBounded):self.run_import(self.payload(rows))
  f=self.fixture
  self.reject('payload_size_invalid',lambda:self.driver.run('import',f.plan_id,f.plan_sha,b'x'*(r.MAX_PAYLOAD+1)))

 def test_corrupt_ciphertext_and_plaintext_fields_cannot_import(self):
  payload=self.payload();payload['rows'][0]['ciphertext']=base64.b64encode(b'x'*512).decode()
  self.reject('crypto_operation_failed',lambda:self.run_import(payload))
  identity=dict(self.identity(),password='not-allowed');payload=self.payload();payload['rows'][0].update(candidate_digest=r.digest(identity),ciphertext=self.encrypt(identity))
  for witness in payload['rows'][0]['witnesses'].values():witness['identity_sha256']=r.digest(identity)
  self.reject('unexpected_fields',lambda:self.run_import(payload))

 def test_global_ip_port_sni_and_single_pin_contracts_reject(self):
  for field,value in [('ip','127.0.0.1'),('ip','ff02::1'),('port',444),('sni','changed.test.invalid'),('pin','bad')]:
   identity=self.identity();identity[field]=value;payload=self.payload();row=payload['rows'][0]
   row.update(ciphertext=self.encrypt(identity),candidate_digest=r.digest(identity))
   for witness in row['witnesses'].values():witness['identity_sha256']=row['candidate_digest']
   with self.assertRaises((r.ImportErrorBounded,r.a.AcceptanceError)):self.run_import(payload)

 def test_entry_dns_independent_witness_commitment_and_times_required(self):
  for modify in (lambda row:row['witnesses']['entry'].update(source_dns=False),
                 lambda row:row['witnesses']['independent'].update(observer_sha256='1'*64),
                 lambda row:row['witnesses']['independent'].update(identity_sha256='f'*64),
                 lambda row:row['witnesses']['independent'].update(observed_at=800),
                 lambda row:row.update(not_after=999)):
   payload=self.payload();modify(payload['rows'][0])
   with self.assertRaises(r.ImportErrorBounded):self.run_import(payload)

 def test_all_41_fresh_source_and_quota_are_required(self):
  self.fixture.source[40]['password']='unexpected'
  self.reject('source_fingerprint_drift',self.run_import)
  self.fixture.source[40]['password']='fixture-secret';self.fixture.usage['total']=1
  self.reject('source_quota_or_expiry',self.run_import)

 def test_plan_approved_manifest_and_full_db_drift_reject(self):
  f=self.fixture;f.snapshots[8]['state']['backend']['group_ids']='[6]';f.snapshots[8]['state_sha256']=r.digest(f.snapshots[8]['state'])
  self.reject('database_state_drift',self.run_import)
  (f.private/'manifest.private').write_bytes((f.private/'manifest.private').read_bytes()+b' ')
  self.reject('manifest_drift',self.run_import)

 def test_source_literal_ip_cannot_be_replaced_by_geodns_claim(self):
  f=self.fixture;source=f.source[0];source['server']='8.8.8.8';f.approved[0]['source_sha256']=f.guard.fingerprint(source);f.rows[0]['source']=copy.deepcopy(source)
  (f.private/'approved.private').write_bytes(r.canon(f.approved));f.plan['approved_file_sha256']=r.digest(f.approved);f.write_plan()
  # A new binding requires a new recipient; old binding is deliberately rejected.
  bound=self.driver.load(f.plan_id,f.plan_sha);row=self.row()
  self.reject('source_literal_ip_mismatch',lambda:self.driver.candidate(row,self.identity(),bound,source,f.now))

 def test_ca_needs_external_ca_validation_and_remains_unpinned_for_execution(self):
  f=self.fixture;k=5;key='U06';source={'type':'vless','name':f.source[k]['name'],'server':'source.test.invalid','port':443,
     'sni':'approved.test.invalid','uuid':'00000000-0000-4000-8000-000000000001','tls':True,'skip-cert-verify':False}
  settings={'type':'vless','server':'8.8.8.8','server_port':443,'uuid':source['uuid'],'tls':{'enabled':True,'insecure':False,'server_name':source['sni']}}
  raw=r.canon([{'protocol':'vless','settings':settings}]).decode();f.snapshots[k]['backend']['custom_outbounds']=raw;f.snapshots[k]['state']['backend']['custom_outbounds']=raw;f.snapshots[k]['state_sha256']=r.digest(f.snapshots[k]['state'])
  f.source[k]=source;f.rows[k]['source']=source;f.approved[k]['source_sha256']=f.guard.fingerprint(source)
  bound={'scopes':r.a.rows_by_key(f.allocation['routes']),'planned':r.a.rows_by_key(f.rows)};row=self.row(key);identity=self.identity(key)
  self.reject('ca_witness_required',lambda:self.driver.candidate(row,identity,bound,source,f.now))
  for witness in row['witnesses'].values():witness['ca_validated']=True
  candidate=self.driver.candidate(row,identity,bound,source,f.now);self.assertTrue(candidate['ca_validated'])
  f.rows[k]['candidates']=[candidate]
  scopes,approvals=maintain.validate_scope(f.allocation,f.approved,f.manifest)
  selected=maintain.selected_rows(f.plan,{key:candidate['candidate_digest']},scopes,approvals,'withdraw',f.now)
  self.assertIsNone(selected[0]['identity']['pin'])
  self.assertNotIn('certificate_public_key_sha256',settings['tls'])

 def test_final_drift_aborts_without_import_intent(self):
  f=self.fixture
  def drift(call):
   if call==2:(f.private/'approved.private').write_bytes((f.private/'approved.private').read_bytes()+b' ')
  f.before_snapshot_return=drift
  self.reject('approved_drift',self.run_import)
  self.assertEqual([],list(f.directory.glob('reviewed-imports/*/intent.private.json')))

 def test_receipt_failure_preserves_new_plan_and_blocks_replay(self):
  payload=self.payload();write=r.a.private_write
  def broken(path,value):
   if path.name=='receipt.private.json':raise OSError('do-not-print')
   return write(path,value)
  with patch.object(r.a,'private_write',side_effect=broken):self.reject('import_outcome_unknown',lambda:self.run_import(payload))
  self.assertEqual(2,len(list(self.fixture.plans.glob('*/plan.private.json'))))
  self.reject('payload_already_recorded',lambda:self.run_import(payload))

 def test_locked_paths_permissions_and_safe_errors(self):
  f=self.fixture
  with r.a.lock(f.plans/'scope-restore.lock'):self.reject('acceptance_busy',self.run_import)
  output=io.StringIO()
  with patch.object(r,'main',side_effect=RuntimeError('fixture-secret')),contextlib.redirect_stdout(output):self.assertEqual(1,r.safe_main([]))
  self.assertNotIn('fixture-secret',output.getvalue())

if __name__=='__main__':unittest.main()
