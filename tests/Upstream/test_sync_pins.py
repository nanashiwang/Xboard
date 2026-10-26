import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/'.docker/upstream'
def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
s=module('sync_pins',ROOT/'sync_pins.py')
fixtures=module('sync_real_maintenance_fixture',REPO/'tests/Upstream/test_maintain.py')

class SyncTests(unittest.TestCase):
 def setUp(self):
  f=self.f=fixtures.MaintenanceTests();f.setUp();self.addCleanup(f.tearDown)
  f.plan.update(production_mutated=False,reviewed_import={'schema':1,'parent_plan_id':'a'*32,'parent_plan_sha256':'b'*64,'manual_selection_required':True})
  if self._testMethodName=='test_omitted_insecure_stays_strict_and_is_not_added_to_database':
   for key,state in f.states.items():
    entries=json.loads(state['backend']['custom_outbounds']);entries[0]['settings']['tls'].pop('insecure')
    state['backend']['custom_outbounds']=s.a.canonical(entries).decode()
    f.backend.states[key]=copy.deepcopy(state)
   for row in f.rows:row['snapshot']['state_sha256']=s.a.digest(row['snapshot']['state'])
  for row in f.rows:
   row['snapshot'].update(key=row['key'],backend=copy.deepcopy(row['snapshot']['state']['backend']),public=copy.deepcopy(row['snapshot']['state']['public']))
  f.write_plan()
  s.a.private_write(f.private/'manifest.private',s.a.canonical(f.manifest))
  (f.private/'pinned.private').unlink()
  self.anytls={r['key'] for r in f.allocation['routes'] if r['upstream_type']=='anytls'}
  f.selection={row['key']:row['candidates'][0]['candidate_digest'] for row in f.rows if row['key'] in self.anytls}
  for action in ('withdraw','apply_hidden','publish'):last=f.run_action(action)
  self.execution=last['execution_plan_id'];self.verification_id='c'*32
  self.driver=s.Driver(private_root=f.private,plan_root=f.plans,sibling=ROOT,
     fetch=lambda:(copy.deepcopy(f.source),f.usage),snapshot=self.snapshot,clock=lambda:f.now)
  self.calls=0;self.on_snapshot=None
  self.binding=self.driver.public.receipt_binding(f.directory,self.execution,f.plan_id,f.plan_sha,f.plan,f.allocation,sorted(self.anytls),'success')
  cache={'plan_id':f.plan_id,'plan_sha256':f.plan_sha,'private_monitor':'fixture-sensitive'}
  s.a.private_write(f.directory/'public-cache.private.json',s.a.canonical(cache))
  self.report={'status':'passed','operation':'verify','expect':'success','plan_id':f.plan_id,'plan_sha256':f.plan_sha,
    'execution_plan_id':self.execution,'maintenance_phase':'publish','receipt_chain_sha256':self.binding['receipt_chain_sha256'],
    'strict_tls':True,'direct_fallback':False,'node_configuration_mutated':False,'fresh_core_per_route':True,
    'checked_at':f.now,'cache_sha256':s.a.digest(cache),'routes':[{'key':key,'status':'passed','state_sha256':self.binding['state_hashes'][key],
      'temporary_process_terminated':True,'temporary_directory_removed':True} for key in sorted(self.anytls)]}
  self.write_report()

 def write_report(self):
  path=self.f.directory/('public-verify-success-'+self.verification_id+'.json');path.unlink(missing_ok=True)
  raw=s.a.canonical(self.report);s.a.private_write(path,raw);self.verification_sha=s.a.bytes_sha(raw)

 def snapshot(self,allocation,manifest):
  self.calls+=1
  if self.on_snapshot:self.on_snapshot(self.calls)
  rows=[]
  for key,state in self.f.backend.states.items():
   rows.append({'key':key,'state':copy.deepcopy(state),'state_sha256':s.a.digest(state),
     'backend':copy.deepcopy(state['backend']),'public':copy.deepcopy(state['public'])})
  return {'machine_id':21,'routes':rows}

 def run_sync(self,expected='absent'):
  f=self.f
  return self.driver.run(f.plan_id,f.plan_sha,self.execution,self.verification_id,self.verification_sha,expected)

 def test_real_maintenance_receipts_generate_exact_28_no_handshakes_and_no_database_change(self):
  original=copy.deepcopy(self.f.backend.states);approved=(self.f.private/'approved.private').read_bytes()
  with patch.object(self.driver.guard,'probe_identity',side_effect=AssertionError('must not collect')):
   result=self.run_sync()
  self.assertEqual(result['status'],'pins_synced');self.assertEqual(result['route_count'],28)
  rows=json.loads((self.f.private/'pinned.private').read_bytes());self.assertEqual({r['key'] for r in rows},self.anytls)
  self.assertEqual(original,self.f.backend.states);self.assertEqual(approved,(self.f.private/'approved.private').read_bytes())
  self.assertEqual(2,self.calls);self.assertFalse(result['database_mutated']);self.assertFalse(result['source_baseline_mutated'])
  for p in (self.f.private/'pinned.private',self.f.directory/('pin-map-'+self.execution)):
   self.assertEqual(p.stat().st_mode&0o077,0)
  for secret in ('sni.test.invalid','provider.test.invalid','test-only-password',self.f.new_pin,'fixture-sensitive'):
   self.assertNotIn(secret,json.dumps(result))

 def test_omitted_insecure_stays_strict_and_is_not_added_to_database(self):
  result=self.run_sync();self.assertEqual(result['route_count'],28)
  for state in self.f.backend.states.values():
   self.assertNotIn('insecure',json.loads(state['backend']['custom_outbounds'])[0]['settings']['tls'])

 def test_existing_valid_anytls_map_is_backed_up_before_atomic_replace(self):
  old=[dict(self.f.rows[0]['candidates'][0]['identity'],pin=self.f.pin)]
  raw=s.a.canonical(old);s.a.private_write(self.f.private/'pinned.private',raw)
  original_replace=s.os.replace;seen=[]
  def replace(src,dst):
   record=self.f.directory/('pin-map-'+self.execution)
   self.assertEqual((record/'pinned-before.private').read_bytes(),raw)
   self.assertTrue((record/'intent.private.json').exists());seen.append(True);return original_replace(src,dst)
  with patch.object(s.os,'replace',side_effect=replace):self.run_sync(s.a.bytes_sha(raw))
  self.assertEqual(seen,[True])

 def test_existing_non_anytls_or_wrong_expected_map_is_rejected(self):
  identity=next(r['candidates'][0]['identity'] for r in self.f.rows if r['key'] not in self.anytls)
  raw=s.a.canonical([identity]);s.a.private_write(self.f.private/'pinned.private',raw)
  with self.assertRaises(s.SyncError):self.run_sync()
  with self.assertRaises(s.SyncError):self.run_sync(s.a.bytes_sha(raw))
  self.assertEqual(raw,(self.f.private/'pinned.private').read_bytes())

 def test_retry_is_idempotent_but_unknown_intent_never_replays(self):
  first=self.run_sync();second=self.run_sync();self.assertEqual(second['status'],'already_synced')
  self.assertEqual(first['pinned_sha256'],second['pinned_sha256'])
  (self.f.directory/('pin-map-'+self.execution)/'receipt.private.json').unlink()
  with self.assertRaisesRegex(s.SyncError,'pin_sync_outcome_unknown'):self.run_sync()

 def test_atomic_error_is_unknown_and_cannot_repeat(self):
  with patch.object(s.os,'link',side_effect=OSError('sensitive failure')):
   with self.assertRaisesRegex(s.SyncError,'pin_sync_outcome_unknown'):self.run_sync()
  self.assertFalse((self.f.private/'pinned.private').exists())
  with self.assertRaisesRegex(s.SyncError,'pin_sync_outcome_unknown'):self.run_sync()

 def test_receipt_write_failure_leaves_applied_map_and_blocks_replay(self):
  original=s.a.private_write
  def fail_receipt(path,body):
   if path.name=='receipt.private.json':raise OSError('private error must not leak')
   return original(path,body)
  with patch.object(s.a,'private_write',side_effect=fail_receipt):
   with self.assertRaisesRegex(s.SyncError,'pin_sync_outcome_unknown'):self.run_sync()
  self.assertEqual(len(json.loads((self.f.private/'pinned.private').read_bytes())),28)
  with self.assertRaisesRegex(s.SyncError,'pin_sync_outcome_unknown'):self.run_sync()

 def test_create_if_absent_cannot_overwrite_racing_creator(self):
  original=s.os.link
  def race(src,dst):
   s.a.private_write(Path(dst),b'concurrent-map');return original(src,dst)
  with patch.object(s.os,'link',side_effect=race):
   with self.assertRaisesRegex(s.SyncError,'pin_sync_outcome_unknown'):self.run_sync()
  self.assertEqual((self.f.private/'pinned.private').read_bytes(),b'concurrent-map')

 def test_full_db_state_drift_on_second_check_keeps_map_absent(self):
  def drift(count):
   if count==2:self.f.backend.states['U18']['backend']['rate']='changed outside chosen scope'
  self.on_snapshot=drift
  with self.assertRaisesRegex(s.SyncError,'database_state_drift'):self.run_sync()
  self.assertFalse((self.f.private/'pinned.private').exists())

 def test_source_all_41_and_quota_checked(self):
  self.f.source[40]['password']='changed'
  with self.assertRaises(Exception):self.run_sync()
  self.f.source[40]['password']='test-only-password';self.f.usage['total']=1
  with self.assertRaises(Exception):self.run_sync()
  self.assertFalse((self.f.private/'pinned.private').exists())

 def test_publish_phase_report_full_coverage_and_exact_state_are_required(self):
  for field,value in [('status','failed'),('maintenance_phase','apply_hidden'),('direct_fallback',True),('receipt_chain_sha256','f'*64)]:
   original=self.report[field];self.report[field]=value;self.write_report()
   with self.assertRaises(s.SyncError):self.run_sync()
   self.report[field]=original
  self.report['routes'].pop();self.write_report()
  with self.assertRaises(s.SyncError):self.run_sync()

 def test_report_and_approved_and_manifest_bytes_bound(self):
  (self.f.private/'approved.private').write_bytes(b'[]')
  with self.assertRaisesRegex(s.SyncError,'approved_drift'):self.run_sync()

 def test_expired_plan_cannot_refresh_pin_baseline(self):
  self.f.now+=7201
  with self.assertRaisesRegex(s.SyncError,'plan_invalid_or_expired'):self.run_sync()

 def test_rollback_after_publish_cannot_sync(self):
  self.f.run_action('rollback')
  with self.assertRaises(Exception):self.run_sync()
  self.assertFalse((self.f.private/'pinned.private').exists())

 def test_receipt_does_not_echo_untrusted_saved_fields(self):
  self.run_sync();path=self.f.directory/('pin-map-'+self.execution)/'receipt.private.json'
  value=json.loads(path.read_bytes());value['result']['secret']='must-not-output';path.write_bytes(s.a.canonical(value))
  with self.assertRaisesRegex(s.SyncError,'pin_sync_receipt_invalid'):self.run_sync()

if __name__=='__main__':unittest.main()
