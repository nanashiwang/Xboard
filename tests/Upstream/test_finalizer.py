import base64
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/'.docker/upstream'
def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
z=module('finalizer_under_test',ROOT/'finalizer.py')
fixtures=module('finalizer_real_fixture',REPO/'tests/Upstream/test_maintain.py')

class FinalizerTests(unittest.TestCase):
 def setUp(self):
  f=self.f=fixtures.MaintenanceTests();f.setUp();self.addCleanup(f.tearDown)
  for row in f.rows:
   row['candidates'][0]['not_after']=100000
   row['snapshot'].update(key=row['key'],backend=copy.deepcopy(row['snapshot']['state']['backend']),public=copy.deepcopy(row['snapshot']['state']['public']))
  f.write_plan();self.base_id=f.plan_id;self.base_sha=f.plan_sha;self.initial=copy.deepcopy(f.states)
  z.a.private_write(f.private/'manifest.private',z.a.canonical(f.manifest))
  self.settings={'panel_url':'https://panel.test.invalid','token':'z'*64}
  public={'type':'vless','tag':'node','server':'node.lumavia.fyi','server_port':443,
          'uuid':'00000000-0000-4000-8000-000000000001','packet_encoding':'xudp',
          'tls':{'enabled':True,'server_name':'node.lumavia.fyi'},
          'transport':{'type':'ws','path':'/private-monitor-path','max_early_data':0}}
  cache={'schema':1,'plan_id':f.plan_id,'plan_sha256':f.plan_sha,'allocation_sha256':z.a.digest(f.allocation),'probe_id':2,
    'token_sha256':z.a.bytes_sha(self.settings['token'].encode()),'binary':{'path':'/fixture-binary','sha256':'d'*64},
    'routes':[dict(key=r['key'],backend_id=r['backend_id'],public_id=r['public_id'],outbound=copy.deepcopy(public),
                   public_config_sha256=z.a.digest(public)) for r in f.allocation['routes']]}
  z.a.private_write(f.directory/'public-cache.private.json',z.a.canonical(cache))
  selection={r['key']:r['candidates'][0]['candidate_digest'] for r in f.rows if r['key'] in z.BASE_KEYS}
  for phase in ('withdraw','apply_hidden'):base_result=f.run_action(phase,selection)
  self.base_execution=base_result['execution_plan_id'];f.now=1100
  self.fresh_id='2'*32;self.fresh_dir=f.plans/self.fresh_id;self.fresh_dir.mkdir(mode=0o700)
  self.third_pin=base64.b64encode(b'c'*32).decode();fresh_rows=[]
  for row in f.rows:
   item=copy.deepcopy(row);state=copy.deepcopy(f.backend.states[row['key']])
   item['snapshot']={'key':row['key'],'state':state,'state_sha256':z.a.digest(state),'backend':copy.deepcopy(state['backend']),'public':copy.deepcopy(state['public'])}
   candidate=item['candidates'][0];candidate['identity']['pin']=self.third_pin
   candidate['candidate_digest']=z.a.digest(candidate['identity']);candidate['old_pin_matches']=False
   fresh_rows.append(item)
  self.fresh_plan=dict(f.plan,plan_id=self.fresh_id,prepared_at=1100,routes=fresh_rows)
  self.fresh_sha=self.write_fresh()
  repair_selection={row['key']:row['candidates'][0]['candidate_digest'] for row in fresh_rows if row['key'] in z.REPAIR_KEYS}
  for phase in ('withdraw','apply_hidden'):
   repair_result=f.driver.run(self.fresh_id,self.fresh_sha,repair_selection,phase)
  self.repair_execution=repair_result['execution_plan_id']
  self.graph={'schema':1,'base':{'plan_id':self.base_id,'plan_sha256':self.base_sha,'execution_id':self.base_execution},
    'continuation':{'plan_id':self.fresh_id,'plan_sha256':self.fresh_sha},'repair_execution_id':self.repair_execution}
  self.driver=z.Driver(f.backend,plan_root=f.plans,private_root=f.private,sibling=ROOT,
    fetch=lambda:(copy.deepcopy(f.source),f.usage),backup=f.backup,clock=lambda:f.now)
  self.created=self.driver.create(self.graph);self.id=self.created['ledger_id'];self.sha=self.created['ledger_sha256']

 def write_fresh(self):
  path=self.fresh_dir/'plan.private.json';path.unlink(missing_ok=True);raw=z.a.canonical(self.fresh_plan);z.a.private_write(path,raw);return z.a.bytes_sha(raw)

 def load(self,rollback=False):return self.driver.load(self.id,self.sha,rollback=rollback)

 def approve(self):
  # The acceptance adapter itself has independent tests. This fixture provides
  # only its contract for testing the real bounded finalizer mutation pipeline.
  bound=self.load();verification='e'*32;raw=z.a.canonical({'status':'passed','verification_id':verification,'binding_sha256':bound['binding_sha256']})
  z.a.private_write(bound['directory']/('verification-'+verification+'.private.json'),raw)
  return verification,z.a.bytes_sha(raw)

 def publish(self):
  verification,sha=self.approve();adapter=type('Adapter',(),{'validate_report':staticmethod(lambda report,bound,*args:
   z.check(report=={'status':'passed','verification_id':verification,'binding_sha256':bound['binding_sha256']}))})
  original=z.module
  with patch.object(z,'module',side_effect=lambda name,path:adapter if name=='finalizer_acceptance_contract' else original(name,path)):
   return self.driver.run('publish',self.id,self.sha,verification,sha)

 def test_graph_uses_initial_originals_plus_only_five_repaired_identities(self):
  bound=self.load();self.assertEqual(len(bound['rows']),39);self.assertEqual(bound['repair_keys'],z.REPAIR_KEYS)
  self.driver.check_current(bound)
  for row in bound['rows']:
   self.assertEqual(row['original_state'],self.initial[row['key']])
   self.assertEqual(row['identity']['pin'],self.third_pin if row['key'] in z.REPAIR_KEYS else None if bound['scopes'][row['key']]['upstream_type']=='vless' else self.f.new_pin)
  self.assertEqual(bound['ledger']['valid_until'],1100+7200)

 def test_real_publish_restores_initial_show_and_rollback_restores_initial_outbound_closed(self):
  original_files={p:p.read_bytes() for d in (self.f.directory,self.fresh_dir) for p in d.rglob('*.private.json')}
  published=self.publish();self.assertEqual(published['phase'],'publish');self.driver.check_current(self.load())
  for key in z.BASE_KEYS:self.assertEqual(self.f.backend.states[key]['public']['show'],self.initial[key]['public']['show'])
  rolled=self.driver.run('rollback',self.id,self.sha);self.assertEqual(rolled['phase'],'rollback')
  for key in z.BASE_KEYS:
   actual=self.f.backend.states[key];self.assertEqual(actual['backend']['custom_outbounds'],self.initial[key]['backend']['custom_outbounds'])
   self.assertFalse(actual['backend']['enabled']);self.assertFalse(actual['public']['show'])
  self.assertEqual(original_files,{p:p.read_bytes() for p in original_files})
  self.assertEqual(self.driver.run('rollback',self.id,self.sha)['status'],'already_applied')

 def test_hidden_rollback_also_uses_initial_outbounds(self):
  self.driver.run('rollback',self.id,self.sha)
  for key in z.REPAIR_KEYS:
   self.assertEqual(self.f.backend.states[key]['backend']['custom_outbounds'],self.initial[key]['backend']['custom_outbounds'])

 def test_expiry_and_source_failure_do_not_block_safe_initial_rollback(self):
  self.f.now=999999;self.driver.fetch=lambda:(_ for _ in ()).throw(RuntimeError('secret failure'))
  with self.assertRaises(z.FinalizerError):self.load()
  result=self.driver.run('rollback',self.id,self.sha);self.assertEqual(result['phase'],'rollback')

 def test_expired_base_is_history_but_explicit_continuation_limit_is_not_extended(self):
  self.f.now=8250  # base age 7250; continuation age 7150.
  bound=self.load();self.assertEqual(bound['ledger']['valid_until'],8300)
  self.driver.check_current(bound)
  self.f.now=8301
  with self.assertRaisesRegex(z.FinalizerError,'continuation_expired'):self.load()

 def test_repair_scope_cannot_expand_beyond_fixed_five(self):
  path=self.fresh_dir/('maintenance-'+self.repair_execution)/'request-apply_hidden.private.json'
  request=json.loads(path.read_bytes());request['routes'][0]['key']='U01';path.write_bytes(z.a.canonical(request))
  with self.assertRaisesRegex(z.FinalizerError,'repair_scope_invalid'):self.load()

 def test_publish_requires_exact_report_and_phase(self):
  with self.assertRaises(z.FinalizerError):self.driver.run('publish',self.id,self.sha)
  self.driver.run('rollback',self.id,self.sha)
  with self.assertRaises(z.FinalizerError):self.driver.run('publish',self.id,self.sha,'e'*32,'f'*64)

 def test_database_drift_outside_39_prevents_action(self):
  self.f.backend.states['U18']['backend']['rate']='changed'
  with self.assertRaisesRegex(z.FinalizerError,'current_state_drift'):self.driver.run('rollback',self.id,self.sha)
  self.assertTrue(self.f.backend.states['U33']['backend']['enabled'])

 def test_unknown_mutation_result_is_never_replayed(self):
  self.f.backend.fail_after_mutation=True
  with self.assertRaisesRegex(z.FinalizerError,'finalizer_outcome_unknown'):self.driver.run('rollback',self.id,self.sha)
  self.f.backend.fail_after_mutation=False
  with self.assertRaisesRegex(z.FinalizerError,'finalizer_outcome_unknown'):self.driver.run('rollback',self.id,self.sha)

 def test_ledger_hash_and_source_graph_tamper_reject(self):
  with self.assertRaisesRegex(z.FinalizerError,'ledger_drift'):self.driver.load(self.id,'f'*64)
  path=self.f.directory/('maintenance-'+self.base_execution)/'receipt-apply_hidden.private.json'
  receipt=json.loads(path.read_bytes());receipt['response']['routes'][0]['state_sha256']='0'*64;path.write_bytes(z.a.canonical(receipt))
  with self.assertRaises(Exception):self.load()

 def test_continuation_full_snapshot_must_match_initial_hidden(self):
  self.fresh_plan['routes'][0]['snapshot']['state']['backend']['rate']='changed'
  self.fresh_plan['routes'][0]['snapshot']['state_sha256']=z.a.digest(self.fresh_plan['routes'][0]['snapshot']['state'])
  changed=self.write_fresh();graph=copy.deepcopy(self.graph);graph['continuation']['plan_sha256']=changed
  with self.assertRaisesRegex(z.FinalizerError,'continuation_snapshot_not_initial_hidden_state'):self.driver.resolve_graph(graph)

 def test_public_output_never_contains_identity_or_password(self):
  text=json.dumps(self.created)
  for secret in (self.f.new_pin,self.third_pin,'sni.test.invalid','test-only-password','do-not-output'):self.assertNotIn(secret,text)

 def test_publish_binding_commits_to_exact_hidden_acceptance_intent(self):
  self.publish();before=self.load()
  path=before['directory']/'intent-publish.private.json';value=json.loads(path.read_bytes())
  value['verification_sha256']='f'*64;path.write_bytes(z.a.canonical(value))
  after=self.load();self.assertNotEqual(before['binding_sha256'],after['binding_sha256'])
  self.assertNotEqual(before['receipt_chain_sha256'],after['receipt_chain_sha256'])

 def test_real_adapter_hidden_verify_publish_verify_and_sync_28_chain(self):
  adapter_module=module('real_finalizer_adapter',ROOT/'finalizer_acceptance.py')
  def measure(row,binary,expect):
   return {'key':row['key'],'public_config_sha256':row['public_config_sha256'],'status':'passed','classification':'both_targets_passed',
    'temporary_process_terminated':True,'temporary_directory_removed':True,
    'checks':[{'target':target,'success':True,'runner_valid':True,'curl_exit':0,'http_status':code,'seconds':.01,
               'proxy_path_usable':True,'exit_ip_sha256':'b'*64 if target=='cloudflare' else None}
              for target,code in (('cloudflare',200),('google',204))]}
  adapter=adapter_module.Driver(self.driver,sibling=ROOT,clock=lambda:self.f.now,measure=measure)
  cache=json.loads(self.load()['cache_bytes']);cached={r['key']:r for r in cache['routes']}
  def scope(*args):
   return {key:{'state_sha256':z.a.digest(state),'enabled':bool(state['backend']['enabled']),'show':bool(state['public']['show']),
      'public_config_sha256':cached[key]['public_config_sha256']} for key,state in self.f.backend.states.items()}
  with patch.object(adapter.public,'agent_settings',return_value=self.settings), \
       patch.object(adapter.public,'bound_binary',return_value='/fixture-binary'), \
       patch.object(adapter.public,'scope',side_effect=scope):
   hidden=adapter.verify(self.id,self.sha);self.assertEqual(hidden['status'],'passed')
   self.driver.run('publish',self.id,self.sha,hidden['verification_id'],hidden['verification_sha256'])
   self.f.now+=1
   published=adapter.verify(self.id,self.sha);self.assertEqual(published['status'],'passed')
   (self.f.private/'pinned.private').unlink()
   result=adapter.sync(self.id,self.sha,published['verification_id'],published['verification_sha256'],'absent')
  self.assertEqual(result['route_count'],28);self.assertEqual(result['status'],'pins_synced')
  pins=json.loads((self.f.private/'pinned.private').read_bytes())
  for row in pins:self.assertEqual(row['pin'],self.third_pin if row['key'] in z.REPAIR_KEYS else self.f.new_pin)

if __name__=='__main__':unittest.main()
