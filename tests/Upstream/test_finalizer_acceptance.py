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

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]/'.docker/upstream'
if not REPO.is_dir():REPO=Path.cwd()/'.docker/upstream'
ADAPTER=HERE/'finalizer_acceptance.py'
if not ADAPTER.is_file():ADAPTER=REPO/'finalizer_acceptance.py'
spec=importlib.util.spec_from_file_location('finalizer_acceptance',ADAPTER)
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class FakeCore:
    def __init__(self,root,bound,states):
        self.private_root=root/'private';self.private_root.mkdir(mode=0o700)
        self.bound=bound;self.states=states;self.loads=0;self.currents=0;self.on_load=None;self.on_current=None
    @contextlib.contextmanager
    def locked(self,ledger_id):yield
    def load(self,*args,**kwargs):
        self.loads+=1
        if self.on_load:self.on_load(self.loads)
        return copy.deepcopy(self.bound)
    def check_current(self,bound,live_source=True):
        self.currents+=1
        if self.on_current:self.on_current(self.currents)
        if {key:a.digest(state) for key,state in self.states.items()}!=bound['expected']:raise RuntimeError('private-state-drift')
        return copy.deepcopy(self.states)

class AggregateAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.directory=self.root/'ledger';self.directory.mkdir(mode=0o700)
        self.base=self.root/'base';self.base.mkdir(mode=0o700)
        self.ledger_id='a'*32;self.ledger_sha='b'*64;self.now=1001
        allocation=json.loads((REPO/'allocation.json').read_bytes());states={};rows=[];cache_rows=[]
        pin=base64.b64encode(b'x'*32).decode()
        for row in allocation['routes']:
            key=row['key'];protocol=row['upstream_type'];identity={'key':key,'ip':'8.8.8.8','port':443,'sni':'private-upstream.invalid','pin':None if protocol=='vless' else pin}
            tls={'enabled':True,'insecure':False,'server_name':identity['sni']}
            if protocol!='vless':tls['certificate_public_key_sha256']=[pin]
            settings={'type':protocol,'server':identity['ip'],'server_port':443,'tls':tls,'password':'private-password'}
            state={'backend':{'id':row['backend_id'],'enabled':1,'custom_outbounds':a.canonical([{'protocol':protocol,'settings':settings}]).decode()},
                   'public':{'id':row['public_id'],'show':0 if key in a.SELECTED else 1}}
            states[key]=state
            if key in a.SELECTED:rows.append({'key':key,'identity':identity,'candidate_digest':a.digest(identity),'original_state':{'public':{'show':1}}})
            public={'type':'vless','tag':'node','server':'node.lumavia.fyi','server_port':443,
                    'uuid':'00000000-0000-4000-8000-000000000001','packet_encoding':'xudp','tls':{'enabled':True,'server_name':'node.lumavia.fyi'},
                    'transport':{'type':'ws','path':'/private-path','max_early_data':0}}
            cache_rows.append({'key':key,'backend_id':row['backend_id'],'public_id':row['public_id'],'outbound':public,'public_config_sha256':a.digest(public)})
        self.settings={'panel_url':'https://private-panel.invalid','token':'z'*64}
        cache={'schema':1,'plan_id':'c'*32,'plan_sha256':'d'*64,'allocation_sha256':a.digest(allocation),'probe_id':2,
               'token_sha256':a.sha(self.settings['token'].encode()),'binary':{'path':'/private/binary','sha256':'e'*64},'routes':cache_rows}
        cache_bytes=a.canonical(cache);self.cache_bytes=cache_bytes
        (self.base/'public-cache.private.json').write_bytes(cache_bytes);(self.base/'public-cache.private.json').chmod(0o600)
        bound={'directory':self.directory,'ledger':{'created_at':1000,'valid_until':8200},'rows':rows,'expected':{k:a.digest(v) for k,v in states.items()},
               'phase':'hidden','phase_at':1000.0,'binding_sha256':'f'*64,'base_directory':self.base,'base_plan_id':'c'*32,
               'base_plan_sha256':'d'*64,'allocation':allocation,'plan':{'prepared_at':1000},'approved_bytes':b'approved',
               'manifest_bytes':b'manifest','cache_bytes':cache_bytes,'execution_id':'1'*64,
               'anytls':{r['key'] for r in allocation['routes'] if r['upstream_type']=='anytls'}}
        self.core=FakeCore(self.root,bound,states)
        self.adapter=a.Driver(self.core,sibling=REPO,clock=lambda:self.now,measure=self.measure)
        for mocked in (patch.object(self.adapter.public,'agent_settings',return_value=self.settings),
                       patch.object(self.adapter.public,'bound_binary',return_value='/private/binary'),
                       patch.object(self.adapter.public,'scope',side_effect=self.scope)):
            mocked.start();self.addCleanup(mocked.stop)
        self.failed=set()

    def scope(self,*args):
        cached={r['key']:r for r in json.loads(self.cache_bytes)['routes']}
        return {key:{'state_sha256':a.digest(value),'public_config_sha256':cached[key]['public_config_sha256'],
                     'enabled':bool(value['backend']['enabled']),'show':bool(value['public']['show'])} for key,value in self.core.states.items()}

    def measure(self,row,binary,expect):
        good=row['key'] not in self.failed
        return {'key':row['key'],'public_config_sha256':row['public_config_sha256'],'status':'passed' if good else 'failed',
                'classification':'both_targets_passed' if good else 'public_key_rejection','temporary_process_terminated':True,
                'temporary_directory_removed':True,'private-secret-field':'private-upstream.invalid',
                'checks':[{'target':target,'success':good,'runner_valid':True,'curl_exit':0 if good else 97,'http_status':code if good else 0,
                           'seconds':.01,'proxy_path_usable':good,'exit_ip_sha256':'2'*64 if target=='cloudflare' and good else None}
                          for target,code in [('cloudflare',200),('google',204)]]}

    def verify(self):return self.adapter.verify(self.ledger_id,self.ledger_sha)
    def publish(self):
        self.core.bound.update(phase='publish',phase_at=1001.0,binding_sha256='3'*64)
        for key in a.SELECTED:self.core.states[key]['public']['show']=1
        self.core.bound['expected']={k:a.digest(v) for k,v in self.core.states.items()};self.now=1002
    def sync(self,report,pinsha='absent'):
        return self.adapter.sync(self.ledger_id,self.ledger_sha,report['verification_id'],report['verification_sha256'],pinsha)

    def test_hidden_public39_report_binds_original_cache_and_redacts_values(self):
        report=self.verify();self.assertEqual('passed',report['status']);self.assertEqual(39,len(report['routes']))
        self.assertEqual(a.sha(self.cache_bytes),report['cache_sha256'])
        path=self.directory/('verification-'+report['verification_id']+'.private.json')
        self.assertEqual(a.sha(path.read_bytes()),report['verification_sha256']);self.assertEqual(0o600,path.stat().st_mode&0o777)
        self.assertEqual(self.cache_bytes,(self.base/'public-cache.private.json').read_bytes())
        for secret in ('private-password','private-upstream','private-panel','private-path','private-secret-field'):
            self.assertNotIn(secret,json.dumps(report))
        self.assertEqual(2,self.core.currents)

    def test_one_failed_route_never_authorizes_publish_or_pin_sync(self):
        self.failed={'U33'};report=self.verify();self.assertEqual('failed',report['status'])
        with self.assertRaises(a.AcceptanceError):a.validate_report(report,self.core.bound,'hidden',self.now,self.ledger_id,self.ledger_sha)
        with self.assertRaisesRegex(a.AcceptanceError,'published_aggregate_required'):self.sync(report)

    def test_report_requires_exact39_two_targets_and_all_bindings(self):
        report=self.verify()
        for mutate in (lambda r:r['routes'].pop(),lambda r:r.update(phase='publish'),lambda r:r.update(cache_sha256='0'*64),
                       lambda r:r.update(binary_sha256='0'*64),lambda r:r.update(direct_fallback=True),
                       lambda r:r['routes'][0].update(state_sha256='0'*64),lambda r:r['routes'][0].update(temporary_directory_removed=False),
                       lambda r:r['routes'][0]['checks'].pop(),lambda r:r['routes'][0]['checks'][0].update(success=False),
                       lambda r:r['routes'][0].update(public_config_sha256='0'*64)):
            bad=copy.deepcopy(report);mutate(bad)
            with self.assertRaises(a.AcceptanceError):a.validate_report(bad,self.core.bound,'hidden',self.now,self.ledger_id,self.ledger_sha)

    def test_binding_or_current_state_drift_prevents_report_publication(self):
        self.core.on_load=lambda count:self.core.bound.update(binding_sha256='4'*64) if count==2 else None
        with self.assertRaisesRegex(a.AcceptanceError,'aggregate_binding_changed'):self.verify()
        self.assertEqual([],list(self.directory.glob('verification-*')))
        self.core.on_load=None
        self.core.on_current=lambda count:self.core.states['U01']['public'].update(show=1) if count==4 else None
        with self.assertRaises(RuntimeError):self.verify()
        self.assertEqual([],list(self.directory.glob('verification-*')))

    def test_phase_time_and_expiration_are_enforced(self):
        report=self.verify()
        for updates in ({'started_at':999},{'checked_at':999},{'checked_at':99999}):
            with self.assertRaises(a.AcceptanceError):a.validate_report(dict(report,**updates),self.core.bound,'hidden',self.now,self.ledger_id,self.ledger_sha)
        with self.assertRaises(a.AcceptanceError):a.validate_report(report,self.core.bound,'hidden',9000,self.ledger_id,self.ledger_sha)

    def test_publish_then_verify_sync28_only_from_current_db_and_idempotent(self):
        hidden=self.verify();self.publish()
        with self.assertRaises(a.AcceptanceError):self.sync(hidden)
        report=self.verify();result=self.sync(report)
        self.assertEqual('pins_synced',result['status']);self.assertEqual(28,result['route_count'])
        mapping=json.loads((self.core.private_root/'pinned.private').read_bytes())
        self.assertEqual(self.core.bound['anytls'],{r['key'] for r in mapping})
        self.assertEqual(0o600,(self.core.private_root/'pinned.private').stat().st_mode&0o777)
        self.assertFalse(result['identity_handshakes_performed']);self.assertFalse(result['database_mutated'])
        self.assertEqual('already_synced',self.sync(report)['status'])
        self.assertEqual(self.cache_bytes,(self.base/'public-cache.private.json').read_bytes())
        self.assertNotIn('private-upstream',json.dumps(result))

    def test_existing_map_requires_exact_hash_and_is_backed_up(self):
        self.publish();report=self.verify()
        old=a.canonical([copy.deepcopy(next(row['identity'] for row in self.core.bound['rows'] if row['key'] in self.core.bound['anytls']))])
        path=self.core.private_root/'pinned.private';path.write_bytes(old);path.chmod(0o600)
        with self.assertRaisesRegex(a.AcceptanceError,'pinned_map_drift'):self.sync(report,'0'*64)
        self.assertEqual(old,path.read_bytes())
        self.sync(report,a.sha(old));self.assertEqual(old,(self.directory/'pin-map/pinned-before.private').read_bytes())

    def test_absent_does_not_follow_dangling_symlink_or_overwrite_racing_file(self):
        self.publish();report=self.verify();path=self.core.private_root/'pinned.private';path.symlink_to(self.root/'private-missing')
        with self.assertRaisesRegex(a.AcceptanceError,'pinned_map_drift'):self.sync(report)
        self.assertTrue(path.is_symlink());path.unlink()
        original=os.link
        def racing(source,destination):
            path.write_bytes(b'race-winner');path.chmod(0o600);return original(source,destination)
        with patch.object(a.os,'link',side_effect=racing):
            with self.assertRaisesRegex(a.AcceptanceError,'pin_sync_outcome_unknown'):self.sync(report)
        self.assertEqual(b'race-winner',path.read_bytes())
        self.assertTrue((self.directory/'pin-map/intent.private.json').exists())
        self.assertFalse((self.directory/'pin-map/receipt.private.json').exists())
        with self.assertRaisesRegex(a.AcceptanceError,'pin_sync_outcome_unknown'):self.sync(report)

    def test_actual_db_pin_mismatch_is_rejected_even_if_state_hash_rebound(self):
        self.publish();report=self.verify();key=next(iter(self.core.bound['anytls']))
        state=self.core.states[key];out=json.loads(state['backend']['custom_outbounds']);out[0]['settings']['tls']['certificate_public_key_sha256']=[base64.b64encode(b'y'*32).decode()]
        state['backend']['custom_outbounds']=a.canonical(out).decode();self.core.bound['expected'][key]=a.digest(state)
        with self.assertRaises(a.AcceptanceError):self.adapter.mappings(self.core.bound,self.core.states)
        self.assertFalse((self.core.private_root/'pinned.private').exists())

    def test_original_hidden_visibility_is_preserved_during_map_sync(self):
        self.publish();key=next(iter(self.core.bound['anytls']))
        selected=next(row for row in self.core.bound['rows'] if row['key']==key)
        selected['original_state']['public']['show']=0
        self.core.states[key]['public']['show']=0
        self.core.bound['expected'][key]=a.digest(self.core.states[key])
        report=self.verify();self.assertEqual('passed',report['status'])
        self.assertEqual('pins_synced',self.sync(report)['status'])
        self.assertEqual(0,self.core.states[key]['public']['show'])

    def test_expiry_crossed_after_final_validation_prevents_map_write(self):
        self.publish();report=self.verify();original=self.adapter.io.private_write
        def write(path,raw):
            original(path,raw)
            if path.name=='intent.private.json':self.now=8201
        with patch.object(self.adapter.io,'private_write',side_effect=write):
            with self.assertRaisesRegex(a.AcceptanceError,'pin_sync_outcome_unknown'):self.sync(report)
        self.assertFalse((self.core.private_root/'pinned.private').exists())

    def test_report_tamper_and_rollback_never_sync(self):
        self.publish();report=self.verify();path=self.directory/('verification-'+report['verification_id']+'.private.json')
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(a.AcceptanceError,'verification_drift'):self.sync(report)
        self.core.bound['phase']='rollback'
        with self.assertRaisesRegex(a.AcceptanceError,'aggregate_phase_invalid'):self.verify()
        with self.assertRaisesRegex(a.AcceptanceError,'published_aggregate_required'):self.sync(report)

    def test_intent_and_full_state_backup_precede_pin_creation(self):
        self.publish();report=self.verify();original=os.link
        def observed(source,destination):
            directory=self.directory/'pin-map'
            self.assertTrue((directory/'intent.private.json').exists())
            self.assertEqual(set(a.KEYS),set(json.loads((directory/'snapshot-before.private.json').read_bytes())))
            self.assertFalse(Path(destination).exists())
            return original(source,destination)
        with patch.object(a.os,'link',side_effect=observed):self.sync(report)

    def test_cancelled_verification_and_sync_do_not_publish_files(self):
        self.adapter.public.STOP.set()
        with self.assertRaisesRegex(a.AcceptanceError,'cancelled'):self.verify()
        self.assertEqual([],list(self.directory.glob('verification-*')))
        self.adapter.public.STOP.clear();self.publish();report=self.verify();self.adapter.public.STOP.set()
        with self.assertRaisesRegex(a.AcceptanceError,'cancelled'):self.sync(report)
        self.assertFalse((self.core.private_root/'pinned.private').exists())
        self.assertFalse((self.directory/'pin-map/intent.private.json').exists())

    def test_cleanup_failure_after_create_is_unknown_and_does_not_remove_target(self):
        self.publish();report=self.verify();original=Path.unlink
        def cleanup(path,*args,**kwargs):
            if path.name.startswith('.aggregate-pins-'):raise OSError('private-cleanup-error')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',cleanup):
            with self.assertRaisesRegex(a.AcceptanceError,'^pin_sync_outcome_unknown$'):self.sync(report)
        self.assertTrue((self.core.private_root/'pinned.private').exists())
        self.assertTrue((self.directory/'pin-map/intent.private.json').exists())
        self.assertFalse((self.directory/'pin-map/receipt.private.json').exists())

    def test_cli_and_exception_output_never_echo_arguments(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(1,a.safe_main(['private-secret']))
        self.assertNotIn('private-secret',output.getvalue())
        output=io.StringIO()
        with patch.object(a,'main',side_effect=RuntimeError('private-secret')),contextlib.redirect_stdout(output):
            self.assertEqual(1,a.safe_main([]))
        self.assertNotIn('private-secret',output.getvalue())

if __name__=='__main__':unittest.main()
