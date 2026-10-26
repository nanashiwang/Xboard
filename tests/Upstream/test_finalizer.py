import base64
import copy
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
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

class OrderedFinalizerTests(unittest.TestCase):
 def setUp(self):
  self.previous=FinalizerTests();self.previous.setUp();self.addCleanup(self.previous.doCleanups)
  self.f=self.previous.f;self.driver=self.previous.driver;self.initial=self.previous.initial
  self.keys={'U01','U02','U03','U04','U05','U20','U21','U22','U23','U24','U26','U27','U28','U29','U30','U31','U32','U33','U34','U35','U38','U40','U41'}
  self.graph=self.append_round(self.previous.graph,self.previous.created,'3',self.keys)
  self.created=self.driver.create(self.graph);self.id=self.created['ledger_id'];self.sha=self.created['ledger_sha256']

 def append_round(self,previous_graph,predecessor,digit,keys,expires=None):
  self.f.now+=100;plan_id=digit*32;directory=self.f.plans/plan_id;directory.mkdir(mode=0o700)
  plan=copy.deepcopy(self.previous.fresh_plan);plan.update(plan_id=plan_id,prepared_at=self.f.now)
  for row in plan['routes']:
   state=copy.deepcopy(self.f.backend.states[row['key']])
   row['snapshot']={'key':row['key'],'state':state,'state_sha256':z.a.digest(state),
                    'backend':copy.deepcopy(state['backend']),'public':copy.deepcopy(state['public'])}
   candidate=row['candidates'][0];candidate['identity']['pin']=base64.b64encode(digit.encode()*32).decode()
   candidate['candidate_digest']=z.a.digest(candidate['identity']);candidate['old_pin_matches']=False
   if expires is not None and row['key'] in keys:candidate['not_after']=expires
  raw=z.a.canonical(plan);z.a.private_write(directory/'plan.private.json',raw);plan_sha=z.a.bytes_sha(raw)
  selection={r['key']:r['candidates'][0]['candidate_digest'] for r in plan['routes'] if r['key'] in keys}
  for phase in ('withdraw','apply_hidden'):result=self.f.driver.run(plan_id,plan_sha,selection,phase)
  return {'schema':2,'base':copy.deepcopy(previous_graph['base']),
          'repairs':copy.deepcopy(self.driver.repairs(previous_graph))+[{'plan_id':plan_id,'plan_sha256':plan_sha,'execution_id':result['execution_plan_id']}],
          'predecessor':{'ledger_id':predecessor['ledger_id'],'ledger_sha256':predecessor['ledger_sha256']}}

 def load(self,rollback=False):return self.driver.load(self.id,self.sha,rollback=rollback)

 def test_last_choice_and_original_rollback_with_all_23_real_maintenance_receipts(self):
  bound=self.load();self.driver.check_current(bound)
  for row in bound['rows']:
   self.assertEqual(row['original_state'],self.initial[row['key']])
   if row['key'] in self.keys:
    self.assertEqual(row['identity']['pin'],None if bound['scopes'][row['key']]['upstream_type']=='vless' else base64.b64encode(b'3'*32).decode())
  self.assertEqual(bound['ledger']['valid_until'],1200+7200)
  before={p:p.read_bytes() for d in (self.f.directory,self.previous.fresh_dir,self.f.plans/('3'*32),self.f.plans/('finalizer-'+self.previous.id)) for p in d.rglob('*.private.json')}
  self.driver.run('rollback',self.id,self.sha)
  for key in z.BASE_KEYS:
   state=self.f.backend.states[key];self.assertEqual(state['backend']['custom_outbounds'],self.initial[key]['backend']['custom_outbounds'])
   self.assertFalse(state['backend']['enabled']);self.assertFalse(state['public']['show'])
  self.assertEqual(before,{p:p.read_bytes() for p in before})

 def test_existing_schema1_graph_binding_stays_exact(self):
  prior=self.driver.load(self.previous.id,self.previous.sha,rollback=True)
  self.assertEqual(prior['source_graph_sha256'],prior['ledger']['source_graph_sha256'])
  self.assertEqual(prior['ledger']['graph'],self.previous.graph)

 def test_predecessor_unknown_result_rejects_even_when_database_stays_hidden(self):
  directory=self.f.plans/('finalizer-'+self.previous.id)
  z.a.private_write(directory/'intent-publish.private.json',b'{}')
  with self.assertRaisesRegex(z.FinalizerError,'finalizer_outcome_unknown'):self.load()

 def test_predecessor_published_or_rolled_back_cannot_be_adopted(self):
  current=copy.deepcopy(self.f.backend.states);prior=self.driver.load(self.previous.id,self.previous.sha,rollback=True)
  prefix=copy.deepcopy(self.initial)
  for row in prior['rows']:prefix[row['key']]=z.derive(row)['hidden']
  self.f.backend.states=prefix;self.previous.publish();published=copy.deepcopy(self.f.backend.states)
  self.f.backend.states=copy.deepcopy(current)
  with self.assertRaisesRegex(z.FinalizerError,'predecessor_not_hidden'):self.load()
  self.f.backend.states=published;self.driver.run('rollback',self.previous.id,self.previous.sha)
  self.f.backend.states=current
  with self.assertRaisesRegex(z.FinalizerError,'predecessor_not_hidden'):self.load()

 def test_order_scope_duplicates_and_prefix_are_fail_closed(self):
  cases=[]
  reversed_graph=copy.deepcopy(self.graph);reversed_graph['repairs'].reverse();cases.append(reversed_graph)
  duplicate=copy.deepcopy(self.graph);duplicate['repairs'].append(copy.deepcopy(duplicate['repairs'][0]));cases.append(duplicate)
  missing=copy.deepcopy(self.graph);del missing['predecessor'];cases.append(missing)
  wrong_sha=copy.deepcopy(self.graph);wrong_sha['predecessor']['ledger_sha256']='0'*64;cases.append(wrong_sha)
  skipped=copy.deepcopy(self.graph);skipped['repairs'].append({'plan_id':'4'*32,'plan_sha256':'5'*64,'execution_id':'6'*64});cases.append(skipped)
  for graph in cases:
   with self.subTest(graph=graph):
    with self.assertRaises(z.FinalizerError):self.driver.resolve_graph(graph)

 def test_full_snapshot_drift_on_unselected_healthy_key_rejects(self):
  ref=self.graph['repairs'][-1];path=self.f.plans/ref['plan_id']/'plan.private.json';plan=json.loads(path.read_bytes())
  row=next(r for r in plan['routes'] if r['key']=='U18');row['snapshot']['state']['backend']['rate']='drift'
  row['snapshot']['state_sha256']=z.a.digest(row['snapshot']['state']);raw=z.a.canonical(plan);path.write_bytes(raw)
  graph=copy.deepcopy(self.graph);graph['repairs'][-1]['plan_sha256']=z.a.bytes_sha(raw)
  with self.assertRaisesRegex(z.FinalizerError,'continuation_snapshot_not_previous_hidden_state'):self.driver.resolve_graph(graph)

 def test_latest_expiry_does_not_extend_and_offline_rollback_survives(self):
  self.f.now=8350;self.driver.check_current(self.load())
  self.f.now=8401
  with self.assertRaisesRegex(z.FinalizerError,'continuation_expired'):self.load()
  self.driver.fetch=lambda:(_ for _ in ()).throw(RuntimeError('must-not-output'))
  self.assertEqual(self.driver.run('rollback',self.id,self.sha)['phase'],'rollback')

 def test_three_repairs_allowed_fourth_refused_and_locks_acquired_once(self):
  graph=self.append_round(self.graph,self.created,'4',{'U01','U33'})
  created=self.driver.create(graph)
  calls=[];original=z.a.lock
  @contextmanager
  def once(path):
   self.assertNotIn(path,calls);calls.append(path)
   with original(path):yield
  with patch.object(z.a,'lock',side_effect=once):
   with self.driver.locked(created['ledger_id']):
    bound=self.driver.load(created['ledger_id'],created['ledger_sha256']);self.driver.check_current(bound)
  self.assertEqual(calls[0],self.f.plans/'scope-restore.lock')
  self.assertEqual(len(calls),8) # global + four plans + three ledgers
  fourth=copy.deepcopy(graph);fourth['repairs'].append({'plan_id':'5'*32,'plan_sha256':'6'*64,'execution_id':'7'*64})
  with self.assertRaisesRegex(z.FinalizerError,'repair_round_limit'):self.driver.graph_contract(fourth)
  self.assertEqual(next(r for r in bound['rows'] if r['key']=='U01')['identity']['pin'],base64.b64encode(b'4'*32).decode())

 def test_final_identity_certificate_comes_from_last_selected_plan(self):
  graph=self.append_round(self.graph,self.created,'4',{'U01'},expires=1350)
  created=self.driver.create(graph);self.f.now=1351
  with self.assertRaisesRegex(z.FinalizerError,'final_certificate_expired'):
   self.driver.load(created['ledger_id'],created['ledger_sha256'])
  self.assertEqual(self.driver.run('rollback',created['ledger_id'],created['ledger_sha256'])['phase'],'rollback')

 def test_real_adapter_cycle_keeps_last_identities_and_new_pin_map_after_rollback(self):
  adapter_module=module('ordered_finalizer_adapter',ROOT/'finalizer_acceptance.py')
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
  with patch.object(adapter.public,'agent_settings',return_value=self.previous.settings),patch.object(adapter.public,'bound_binary',return_value='/fixture-binary'),patch.object(adapter.public,'scope',side_effect=scope):
   hidden=adapter.verify(self.id,self.sha);self.assertEqual(hidden['status'],'passed')
   self.driver.run('publish',self.id,self.sha,hidden['verification_id'],hidden['verification_sha256']);self.f.now+=1
   published=adapter.verify(self.id,self.sha);self.assertEqual(published['status'],'passed')
   (self.f.private/'pinned.private').unlink();result=adapter.sync(self.id,self.sha,published['verification_id'],published['verification_sha256'],'absent')
  self.assertEqual(result['route_count'],28)
  pins=(self.f.private/'pinned.private').read_bytes();selected={r['key']:r['identity'] for r in self.load()['rows']}
  for row in json.loads(pins):self.assertEqual(row,selected[row['key']])
  self.driver.run('rollback',self.id,self.sha);self.assertEqual((self.f.private/'pinned.private').read_bytes(),pins)


class FinalizerCliInputTests(unittest.TestCase):
 def graph(self):
  return {'schema':1,'base':{'plan_id':'1'*32,'plan_sha256':'2'*64,'execution_id':'3'*64},
          'continuation':{'plan_id':'4'*32,'plan_sha256':'5'*64},'repair_execution_id':'6'*64}

 def invoke(self,raw,arguments=None):
  # A real subprocess pipe exercises inherited stdin. The fake backend models
  # an initialization command that drains every remaining byte on entry.
  script='''
import importlib.util,json,os,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('pipeline_finalizer',Path(PATH))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original_module=m.module
class DrainingBackend:
 def __init__(self,**kwargs):pass
 def __enter__(self):
  remainder=sys.stdin.buffer.read()
  print(json.dumps({'backend_entered':True,'remaining_stdin_bytes':len(remainder)}))
  return self
 def __exit__(self,*args):pass
class FakeMaintenance: DockerBackend=DrainingBackend
class FakeDriver:
 graph_contract=staticmethod(m.Driver.graph_contract)
 def __init__(self,backend):pass
 def create(self,graph):return {'status':'prepared_fixture','received_graph_sha256':m.a.digest(graph)}
m.Driver=FakeDriver
m.module=lambda name,path:FakeMaintenance if name=='finalizer_cli_maintenance' else original_module(name,path)
m.os.geteuid=lambda:0
raise SystemExit(m.safe_main(ARGS))
'''.replace('PATH',repr(str(ROOT/'finalizer.py'))).replace('ARGS',repr(arguments or ['prepare']))
  return subprocess.run([sys.executable,'-c',script],input=raw,capture_output=True,timeout=10)

 def test_real_pipe_is_consumed_before_draining_backend_enters(self):
  graph=self.graph();result=self.invoke(z.a.canonical(graph))
  self.assertEqual(result.returncode,0,result.stderr.decode())
  lines=[json.loads(line) for line in result.stdout.splitlines()]
  self.assertEqual(lines[0],{'backend_entered':True,'remaining_stdin_bytes':0})
  self.assertEqual(lines[1],{'status':'prepared_fixture','received_graph_sha256':z.a.digest(graph)})

 def test_ordered_graph_pipe_is_also_validated_before_draining_backend(self):
  graph={'schema':2,'base':self.graph()['base'],
         'repairs':[dict(self.graph()['continuation'],execution_id='6'*64)],
         'predecessor':{'ledger_id':'7'*32,'ledger_sha256':'8'*64}}
  result=self.invoke(z.a.canonical(graph));self.assertEqual(result.returncode,0)
  lines=[json.loads(line) for line in result.stdout.splitlines()]
  self.assertEqual(lines[0],{'backend_entered':True,'remaining_stdin_bytes':0})
  self.assertEqual(lines[1]['received_graph_sha256'],z.a.digest(graph))
  for invalid in [dict(graph,repairs=[]),dict(graph,predecessor={}),dict(graph,repairs=graph['repairs']*4)]:
   result=self.invoke(z.a.canonical(invalid));self.assertEqual(result.returncode,1)
   self.assertNotIn(b'backend_entered',result.stdout)

 def test_invalid_empty_or_oversized_graph_never_initializes_backend(self):
  cases=[b'',b'x'*4097,b'{}',b'{"schema":1,"schema":1}',
         z.a.canonical(dict(self.graph(),identity={'pin':'must-not-output'}))]
  for raw in cases:
   with self.subTest(size=len(raw)):
    result=self.invoke(raw);self.assertEqual(result.returncode,1)
    self.assertNotIn(b'backend_entered',result.stdout)
    self.assertNotIn(b'must-not-output',result.stdout)
    self.assertEqual(json.loads(result.stdout)['status'],'rejected')
  result=self.invoke(z.a.canonical(self.graph()),['prepare','--ledger-id','a'*32])
  self.assertEqual(result.returncode,1);self.assertNotIn(b'backend_entered',result.stdout)

if __name__=='__main__':unittest.main()
