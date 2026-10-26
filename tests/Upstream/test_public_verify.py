import copy
import hashlib
import importlib.util
import io
import json
import os
import socket
from pathlib import Path
import stat
import ssl
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('public_verify',Path(__file__).resolve().parents[2] / '.docker/upstream/public_verify.py')
p=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(p)

def outbound():
    return {'type':'vless','tag':'node','server':p.ENTRY,'server_port':443,
            'uuid':'00000000-0000-4000-8000-000000000001','packet_encoding':'xudp',
            'tls':{'enabled':True,'insecure':False,'server_name':p.ENTRY},
            'transport':{'type':'ws','path':'/reviewed-path','max_early_data':0}}

class Contracts(unittest.TestCase):
    def setUp(self):
        self.alloc,self.rows=p.allocation()
        self.settings={'panel_url':'https://panel.example.test','token':'a'*64}
        self.scopes={r['key']:{'key':r['key'],'public_id':r['public_id'],'backend_id':r['backend_id'],
                             'show':True,'enabled':True,'public_config_sha256':p.digest(outbound()),'state_sha256':'d'*64}
                     for r in self.alloc['routes']}
        self.config={'version':1,'nodes':[{'id':r['public_id'],'outbound':outbound()} for r in self.alloc['routes']]}
        self.cache={'schema':1,'plan_id':'a'*32,'plan_sha256':'b'*64,'allocation_sha256':p.digest(self.alloc),
                    'probe_id':2,'token_sha256':hashlib.sha256(self.settings['token'].encode()).hexdigest(),
                    'routes':p.public_config(self.config,self.scopes,self.alloc)}

    def receipt_fixture(self,directory,phases=('withdraw','apply_hidden'),keys=('U04','U05'),null_keys=()):
        planned=[];originals={};identities={};original_selection={}
        for row in self.alloc['routes']:
            state={'backend':{'id':row['backend_id'],'enabled':1,'custom_outbounds':'[]'},
                   'public':{'id':row['public_id'],'show':1}}
            originals[row['key']]=state
            observed={'key':row['key'],'ip':'1.1.1.1','port':443,'sni':'fixture.example','pin':'fixture-pin'}
            identities[row['key']]=dict(observed,pin=None) if row['upstream_type']=='vless' else observed
            original_selection[row['key']]=p.digest(observed)
            planned.append({'key':row['key'],'snapshot':{'state':state,'state_sha256':p.digest(state)},
                            'candidates':[{'identity':observed,'candidate_digest':p.digest(observed)}]})
        for key in null_keys:identities[key]=None;original_selection[key]=None
        rows=[{'key':key,'backend_id':self.rows[key]['backend_id'],'public_id':self.rows[key]['public_id'],
               'original_state':originals[key],'original_state_sha256':p.digest(originals[key]),
               'identity':identities[key],'candidate_digest':p.digest(identities[key])} for key in keys]
        bound=[{k:r[k] for k in ('key','backend_id','public_id','original_state_sha256','candidate_digest')} for r in sorted(rows,key=lambda r:r['key'])]
        execution=p.digest({'schema':1,'machine_id':21,'routes':bound})
        folder=directory/('maintenance-'+execution);folder.mkdir(mode=0o700)
        hashes={r['key']:r['original_state_sha256'] for r in rows}
        for action in phases:
            requested=[{**r,'expected_sha256':hashes[r['key']]} for r in rows]
            request={'schema':1,'action':action,'plan_id':execution,'routes':requested}
            p.save_exclusive(folder/('request-'+action+'.private.json'),request)
            p.save_exclusive(folder/('intent-'+action+'.private.json'),{'schema':1,'request_sha256':p.digest(request),'at':1.25})
            hashes={r['key']:p.closed_state_hash(r['original_state']) if action in ('withdraw','rollback')
                    else p.digest({'phase':action,'key':r['key']}) for r in rows}
            response={'schema':1,'action':action,'plan_id':execution,'routes':[{'key':r['key'],'backend_id':r['backend_id'],
                       'public_id':r['public_id'],'state_sha256':hashes[r['key']]} for r in rows]}
            p.save_exclusive(folder/('receipt-'+action+'.private.json'),{'schema':1,'prepare_plan_id':'a'*32,
                'prepare_plan_sha256':'b'*64,'selection_sha256':p.digest({r['key']:original_selection[r['key']] for r in rows}),
                'response':response,'at':1.5})
        return execution,{'routes':planned},folder,hashes

    def read_binding(self,directory,fixture,selected=('U04',),expect='success'):
        execution,plan,_,_=fixture
        return p.receipt_binding(directory,execution,'a'*32,'b'*64,plan,self.alloc,list(selected),expect)

    def test_exact_fixed_41_scope(self):
        self.assertEqual(len(self.rows),41)
        self.assertEqual(self.rows['U01']['public_id'],360)
        self.assertEqual(self.rows['U41']['public_id'],440)

    def test_unknown_and_duplicate_selected_keys_rejected(self):
        for keys in ([],['U01','U01'],['U42'],['U00'],['U1']):
            with self.subTest(keys=keys),self.assertRaises(p.ContractError):p.validate_selected(keys)
        self.assertEqual(p.validate_selected(['U05','U04']),['U04','U05'])

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(p.ContractError):p.load_json('{"nodes":[],"nodes":[]}')

    def test_missing_extra_duplicate_or_hidden_api_node_rejected(self):
        bad=[]
        x=copy.deepcopy(self.config);x['nodes'].pop();bad.append(x)
        x=copy.deepcopy(self.config);x['nodes'].append({'id':999,'outbound':outbound()});bad.append(x)
        x=copy.deepcopy(self.config);x['nodes'].append(x['nodes'][0]);bad.append(x)
        x=copy.deepcopy(self.config);x['nodes'][0]={'id':360,'error':'node_unavailable'};bad.append(x)
        for value in bad:
            with self.assertRaises(p.ContractError):p.public_config(value,self.scopes,self.alloc)

    def test_api_config_hash_drift_rejected(self):
        x=copy.deepcopy(self.config);x['nodes'][0]['outbound']['transport']['path']='/changed'
        with self.assertRaises(p.ContractError):p.public_config(x,self.scopes,self.alloc)

    def test_tls_off_insecure_and_pin_trust_changes_rejected(self):
        for changes in ({'enabled':False},{'insecure':True},{'insecure':'false'},{'certificate_public_key_sha256':['new']},
                        {'server_name':'other.example'},{'reality':{'enabled':True}}):
            value=outbound();value['tls'].update(changes)
            with self.assertRaises(p.ContractError):p.outbound_contract(value)

    def test_endpoint_scope_direct_detour_and_path_injection_rejected(self):
        for key,value in [('server','other.example'),('server_port',444),('type','direct'),('detour','DIRECT'),('bind_interface','lo')]:
            bad=outbound();bad[key]=value
            with self.assertRaises(p.ContractError):p.outbound_contract(bad)
        bad=outbound();bad['transport']['path']='/hello\r\nInjected: yes'
        with self.assertRaises(p.ContractError):p.outbound_contract(bad)

    def test_runtime_has_exactly_one_outbound_and_no_fallback(self):
        value=p.runtime(outbound(),1234)
        self.assertEqual(value['outbounds'],[outbound()])
        self.assertEqual(value['route'],{'final':'node','default_domain_resolver':'local'})
        self.assertEqual(value['inbounds'][0]['listen'],'127.0.0.1')

    def test_cache_binds_plan_token_scope_and_outbound(self):
        self.assertEqual(len(p.cache_contract(self.cache,'a'*32,'b'*64,self.alloc,self.settings)),41)
        for field,value in [('plan_id','c'*32),('plan_sha256','c'*64),('probe_id',1),('token_sha256','c'*64)]:
            changed=copy.deepcopy(self.cache);changed[field]=value
            with self.assertRaises(p.ContractError):p.cache_contract(changed,'a'*32,'b'*64,self.alloc,self.settings)
        changed=copy.deepcopy(self.cache);changed['routes'][0]['outbound']['uuid']='00000000-0000-4000-8000-000000000002'
        with self.assertRaises(p.ContractError):p.cache_contract(changed,'a'*32,'b'*64,self.alloc,self.settings)

    def test_hidden_success_permitted_only_with_enabled_backend(self):
        rows=p.indexed(self.cache['routes']);scope=copy.deepcopy(self.scopes)
        scope['U01']['show']=False
        p.verify_scope(rows,scope,['U01'],'success',{'U01':'d'*64})
        scope['U01']['enabled']=False
        with self.assertRaises(p.ContractError):p.verify_scope(rows,scope,['U01'],'success',{'U01':'d'*64})

    def test_withdrawal_requires_db_hidden_and_backend_disabled(self):
        rows=p.indexed(self.cache['routes']);scope=copy.deepcopy(self.scopes)
        for show,enabled in [(True,True),(True,False),(False,True)]:
            scope['U01'].update(show=show,enabled=enabled)
            with self.assertRaises(p.ContractError):p.verify_scope(rows,scope,['U01'],'withdrawn',{'U01':'d'*64})
        scope['U01'].update(show=False,enabled=False)
        p.verify_scope(rows,scope,['U01'],'withdrawn',{'U01':'d'*64})

    def test_withdrawal_timeout_is_not_success(self):
        checks=[{'success':False},{'success':False}]
        for hop in (None,{'tls_verified':False,'classification':'public_path_rejected'},
                    {'tls_verified':True,'classification':'websocket_open'}):
            self.assertEqual(p.verdict('withdrawn',checks,hop,'timeout')[0],'inconclusive')

    def test_withdrawal_needs_both_failed_checks_and_rejected_verified_entry(self):
        hop={'tls_verified':True,'classification':'public_path_rejected'}
        valid=[{'success':False,'runner_valid':True,'curl_exit':97}]*2
        self.assertEqual(p.verdict('withdrawn',valid,hop,'proxy'),('passed','withdrawal_observed'))
        self.assertEqual(p.verdict('withdrawn',[{'success':True},{'success':False}],hop,'proxy'),('failed','cached_path_still_usable'))
        self.assertEqual(p.verdict('withdrawn',[],hop,'runner')[0],'inconclusive')

    def test_success_requires_both_targets(self):
        self.assertEqual(p.verdict('success',[{'success':True},{'success':True}],None,'')[0],'passed')
        self.assertEqual(p.verdict('success',[{'success':True},{'success':False}],None,'timeout')[0],'failed')

    def test_plan_hash_and_private_permissions_enforced(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(p,'PLAN_ROOT',Path(temp)):
            directory=Path(temp)/('a'*32);directory.mkdir(mode=0o700)
            value={'plan_id':'a'*32,'allocation_sha256':p.digest(self.alloc),'routes':[{'key':r['key'],
                'snapshot':{'public':{'id':r['public_id']},'backend':{'id':r['backend_id']}}} for r in self.alloc['routes']]}
            path=directory/'plan.private.json';path.write_bytes(p.canonical(value));path.chmod(0o600)
            sha=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(p.plan_contract('a'*32,sha,self.alloc)[0],directory)
            with self.assertRaises(p.ContractError):p.plan_contract('a'*32,'b'*64,self.alloc)
            path.chmod(0o644)
            with self.assertRaises(p.ContractError):p.plan_contract('a'*32,sha,self.alloc)

    def test_snapshot_scope_failure_prevents_api_call(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(p,'scope',side_effect=p.ContractError()),patch.object(p,'fetch_public') as fetch:
            with self.assertRaises(p.ContractError):p.snapshot(Path(temp),'a'*32,'b'*64,self.alloc,self.settings)
            fetch.assert_not_called()

    def test_snapshot_cannot_reopen_hidden_or_missing_routes(self):
        hidden=copy.deepcopy(self.scopes);hidden['U01']['show']=False
        with tempfile.TemporaryDirectory() as temp,patch.object(p,'scope',return_value=hidden),patch.object(p,'fetch_public') as fetch:
            with self.assertRaises(p.ContractError):p.snapshot(Path(temp),'a'*32,'b'*64,self.alloc,self.settings)
            fetch.assert_not_called()

    def test_snapshot_without_binary_does_not_leave_unusable_cache(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(p,'scope',return_value=self.scopes),patch.object(p,'fetch_public',return_value=self.config),patch.object(p,'select_binary',return_value=None):
            with self.assertRaises(p.BinaryNotFound):p.snapshot(Path(temp),'a'*32,'b'*64,self.alloc,self.settings)
            self.assertFalse((Path(temp)/'public-cache.private.json').exists())
            with self.assertRaises(p.ContractError):p.bound_binary(None)

    def test_snapshot_with_binary_saves_complete_private_cache(self):
        binary={'path':p.BINARY_PATHS[-1],'resolved_path':p.BINARY_PATHS[-1],'sha256':'c'*64}
        with tempfile.TemporaryDirectory() as temp,patch.object(p,'scope',return_value=self.scopes),patch.object(p,'fetch_public',return_value=self.config),patch.object(p,'select_binary',return_value=binary):
            report=p.snapshot(Path(temp),'a'*32,'b'*64,self.alloc,self.settings)
            self.assertEqual(report['binary_status'],'bound')
            path=Path(temp)/'public-cache.private.json'
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertEqual(len(json.loads(path.read_text())['routes']),41)
            self.assertNotIn(self.settings['token'],path.read_text())
            self.assertNotIn(outbound()['uuid'],json.dumps(report))

    def test_exclusive_cache_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'cache';p.save_exclusive(path,{'original':True})
            with self.assertRaises(FileExistsError):p.save_exclusive(path,{'original':False})
            self.assertEqual(json.loads(path.read_text()),{'original':True})

    def test_binary_path_and_hash_are_bound(self):
        saved={'path':p.BINARY_PATHS[0],'resolved_path':'/trusted/sing-box','sha256':'a'*64}
        with patch.object(p,'secure_binary',return_value=saved):self.assertEqual(p.bound_binary(saved),'/trusted/sing-box')
        with patch.object(p,'secure_binary',return_value={**saved,'sha256':'b'*64}):
            with self.assertRaises(p.ContractError):p.bound_binary(saved)
        with self.assertRaises(p.ContractError):p.bound_binary({**saved,'path':'/tmp/untrusted'})

    def test_binary_rejects_untrusted_owner_or_writable_path(self):
        for uid,mode in [(501,stat.S_IFDIR|0o755),(0,stat.S_IFDIR|0o777)]:
            with patch.object(Path,'resolve',return_value=Path('/trusted/core')),patch.object(Path,'stat',return_value=SimpleNamespace(st_mode=mode,st_uid=uid)):
                with self.assertRaises(p.ContractError):p.secure_binary(Path(p.BINARY_PATHS[0]))

    def test_log_classification_never_contains_private_text(self):
        secret='PRIVATE_TOKEN_MUST_NOT_APPEAR'
        for text,expected in [(secret+' unrecognized remote public key','public_key_rejection'),(secret+' unknown error','proxy_request_failed')]:
            self.assertEqual(p.log_class(text),expected)
            self.assertNotIn(secret,p.log_class(text))

    def test_proxy_environment_removed(self):
        with patch.dict(os.environ,{'HTTP_PROXY':'private','https_proxy':'private','ALL_PROXY':'private','NO_PROXY':'*'},clear=True):
            self.assertEqual(p.clean_env(),{})

    def test_historical_binary_candidate_is_explicitly_allowed(self):
        self.assertIn('/root/Xboard/backups/fleet-20261017/sing-box',p.BINARY_PATHS)

    def test_runner_failures_and_target_timeout_never_prove_withdrawal(self):
        hop={'tls_verified':True,'classification':'public_path_rejected'}
        for value in ({'success':False,'classification':'runner_timeout','runner_valid':False},
                      {'success':False,'classification':'cancelled','runner_valid':False},
                      {'success':False,'runner_valid':False,'curl_exit':7},
                      {'success':False,'runner_valid':True,'curl_exit':28},
                      {'success':False,'runner_valid':True,'curl_exit':35},
                      {'success':False,'runner_valid':True,'curl_exit':60}):
            self.assertEqual(p.verdict('withdrawn',[value,value],hop,'failure')[0],'inconclusive')

    def test_target_http_failure_still_proves_cached_proxy_usable(self):
        hop={'tls_verified':True,'classification':'public_path_rejected'}
        value={'success':False,'runner_valid':True,'curl_exit':0,'http_status':503,'proxy_path_usable':True}
        self.assertEqual(p.verdict('withdrawn',[value,value],hop,'http')[1],'cached_path_still_usable')

    def test_local_proxy_or_curl_usage_errors_mark_runner_invalid(self):
        with tempfile.TemporaryDirectory() as temp:
            for code,metrics in [(2,b'000 0.1 0.01 127.0.0.1 1234'),(7,b'000 0.1 0.01 127.0.0.1 1234'),
                                 (97,b'000 0.1 0.00 127.0.0.1 1234'),(97,b'000 0.1 0.01 127.0.0.1 9999')]:
                with patch.object(p.subprocess,'run',return_value=SimpleNamespace(returncode=code,stdout=metrics)):
                    self.assertFalse(p.check_target(1234,'google',Path(temp))['runner_valid'])
            with patch.object(p.subprocess,'run',return_value=SimpleNamespace(returncode=97,stdout=b'000 0.1 0.01 127.0.0.1 1234')):
                self.assertTrue(p.check_target(1234,'google',Path(temp))['runner_valid'])

    def test_dns_timeout_kills_its_child_within_shared_deadline(self):
        clock=[0.0]
        class Child:
            returncode=None
            killed=False
            waited=False
            def communicate(self,input=None,timeout=None):
                clock[0]+=timeout
                raise subprocess.TimeoutExpired('child',timeout)
            def poll(self):return self.returncode
            def kill(self):self.killed=True;self.returncode=-9
            def wait(self,timeout=None):self.waited=True;return self.returncode
        child=Child()
        with patch.object(p.time,'monotonic',side_effect=lambda:clock[0]),patch.object(p.subprocess,'Popen',return_value=child):
            with self.assertRaises(TimeoutError):p.resolve_entry(6)
        self.assertLessEqual(clock[0],6.00001)
        self.assertTrue(child.killed and child.waited)

    def test_dns_stop_kills_its_child(self):
        class Child:
            returncode=None
            killed=False
            def communicate(self,input=None,timeout=None):
                p.STOP.set();raise subprocess.TimeoutExpired('child',timeout)
            def poll(self):return self.returncode
            def kill(self):self.killed=True;self.returncode=-9
            def wait(self,timeout=None):return self.returncode
        child=Child()
        try:
            with patch.object(p.subprocess,'Popen',return_value=child):
                with self.assertRaises(InterruptedError):p.resolve_entry(p.time.monotonic()+6)
            self.assertTrue(child.killed)
        finally:p.STOP.clear()

    def test_first_hop_slowloris_cannot_reset_total_deadline(self):
        clock=[0.0]
        class Stream:
            ready=False
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def do_handshake(self):pass
            def send(self,value):return len(value)
            def recv(self,count):
                if not self.ready:raise ssl.SSLWantReadError()
                self.ready=False
                return b'H'
        stream=Stream()
        def select(reads,writes,errors,timeout):
            clock[0]+=timeout;stream.ready=True
            return reads,writes,[]
        context=SimpleNamespace(wrap_socket=lambda *a,**k:stream)
        with patch.object(p.time,'monotonic',side_effect=lambda:clock[0]),patch.object(p,'resolve_entry',return_value=['1.1.1.1']),patch.object(p,'connect_entry',return_value=stream),patch.object(p.ssl,'create_default_context',return_value=context),patch.object(p.select,'select',side_effect=select):
            result=p.first_hop(outbound())
        self.assertEqual(result['classification'],'entry_deadline_exceeded')
        self.assertLessEqual(clock[0],6.00001)

    def test_first_hop_stop_interrupts_read_wait(self):
        class Stream:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def do_handshake(self):pass
            def send(self,value):return len(value)
            def recv(self,count):raise ssl.SSLWantReadError()
        stream=Stream();context=SimpleNamespace(wrap_socket=lambda *a,**k:stream)
        def select(*args):p.STOP.set();return [],[],[]
        try:
            with patch.object(p,'resolve_entry',return_value=['1.1.1.1']),patch.object(p,'connect_entry',return_value=stream),patch.object(p.ssl,'create_default_context',return_value=context),patch.object(p.select,'select',side_effect=select):
                self.assertEqual(p.first_hop(outbound())['classification'],'cancelled')
        finally:p.STOP.clear()

    def test_actual_loopback_socks_rejection_is_valid_network_attempt(self):
        with socket.socket() as server,tempfile.TemporaryDirectory() as temp:
            server.bind(('127.0.0.1',0));server.listen(1);server.settimeout(3)
            port=server.getsockname()[1];observed=[]
            def reject():
                try:
                    with server.accept()[0] as connection:
                        connection.settimeout(2)
                        greeting=connection.recv(256)
                        if greeting[:1]!=b'\x05':return
                        connection.sendall(b'\x05\x00')
                        request=connection.recv(512)
                        observed.append(request[:3]==b'\x05\x01\x00')
                        connection.sendall(b'\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00')
                except OSError:pass
            worker=threading.Thread(target=reject);worker.start()
            try:result=p.check_target(port,'google',Path(temp))
            finally:worker.join(timeout=4)
            self.assertFalse(worker.is_alive())
            self.assertEqual(observed,[True])
            self.assertEqual(result['curl_exit'],97)
            self.assertTrue(result['runner_valid'])
            self.assertFalse(result['proxy_path_usable'])

    def test_receipt_latest_phase_and_subset_are_bound(self):
        for phases,expect in [(('withdraw',),'withdrawn'),(('withdraw','apply_hidden'),'success'),(('withdraw','apply_hidden','publish'),'success')]:
            with tempfile.TemporaryDirectory() as temp:
                directory=Path(temp);fixture=self.receipt_fixture(directory,phases)
                binding=self.read_binding(directory,fixture,expect=expect)
                self.assertEqual(binding['phase'],phases[-1])
                self.assertEqual(binding['state_hashes'],fixture[3])
                with self.assertRaises(p.ContractError):self.read_binding(directory,fixture,selected=('U06',),expect=expect)

    def test_receipt_wrong_expectation_or_illegal_sequence_rejected(self):
        for phases,expect in [(('withdraw',),'success'),(('withdraw','apply_hidden'),'withdrawn'),(('withdraw','rollback'),'success'),(('apply_hidden',),'success')]:
            with tempfile.TemporaryDirectory() as temp:
                directory=Path(temp);fixture=self.receipt_fixture(directory,phases)
                with self.assertRaises(p.ContractError):self.read_binding(directory,fixture,expect=expect)

    def test_unknown_outcome_or_unknown_phase_blocks_verification(self):
        for filename in ('intent-publish.private.json','intent-other.private.json'):
            with tempfile.TemporaryDirectory() as temp:
                directory=Path(temp);fixture=self.receipt_fixture(directory)
                p.save_exclusive(fixture[2]/filename,{'schema':1})
                with self.assertRaises(p.ContractError):self.read_binding(directory,fixture)

    def test_receipt_requires_matching_intent_request_and_selection(self):
        for corruption in ('intent_missing','request_changed','selection_changed','prepare_changed','id_changed'):
            with tempfile.TemporaryDirectory() as temp:
                directory=Path(temp);fixture=self.receipt_fixture(directory);folder=fixture[2]
                if corruption=='intent_missing':(folder/'intent-apply_hidden.private.json').unlink()
                elif corruption=='request_changed':
                    path=folder/'request-apply_hidden.private.json';data=json.loads(path.read_text());data['routes'][0]['expected_sha256']='f'*64;path.write_bytes(p.canonical(data))
                else:
                    path=folder/'receipt-apply_hidden.private.json';data=json.loads(path.read_text())
                    if corruption=='selection_changed':data['selection_sha256']='f'*64
                    elif corruption=='prepare_changed':data['prepare_plan_sha256']='f'*64
                    else:data['response']['routes'][0]['backend_id']=999
                    path.write_bytes(p.canonical(data))
                with self.assertRaises(p.ContractError):self.read_binding(directory,fixture)

    def test_receipt_original_state_must_match_prepared_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);fixture=self.receipt_fixture(directory)
            fixture[1]['routes'][3]['snapshot']['state_sha256']='f'*64
            with self.assertRaises(p.ContractError):self.read_binding(directory,fixture)

    def test_full_state_drift_rejected_even_when_public_config_unchanged(self):
        rows=p.indexed(self.cache['routes']);scope=copy.deepcopy(self.scopes)
        scope['U01']['state_sha256']='e'*64
        with self.assertRaises(p.ContractError):p.verify_scope(rows,scope,['U01'],'success',{'U01':'d'*64})

    def test_random_fingerprint_rejection_is_fixed_reason(self):
        result=SimpleNamespace(returncode=1,stdout=b'{"scope_valid":false,"reason":"probe_random_fingerprint_not_repeatable"}')
        with patch.object(p.subprocess,'run',return_value=result):
            with self.assertRaises(p.RandomFingerprintUnsupported):p.scope(self.settings,self.alloc)

    def test_receipt_accepts_real_float_timestamps_but_not_bool_or_nonfinite(self):
        self.assertTrue(p.timestamp(1.25))
        for value in (True,False,float('nan'),float('inf'),-1):self.assertFalse(p.timestamp(value))
        with self.assertRaises(p.ContractError):p.load_json('{"at":NaN}')

    def test_ca_selection_recovers_pre_normalization_candidate_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);fixture=self.receipt_fixture(directory,keys=('U06',))
            binding=self.read_binding(directory,fixture,selected=('U06',))
            self.assertEqual(binding['phase'],'apply_hidden')
            request=json.loads((fixture[2]/'request-apply_hidden.private.json').read_text())
            original=fixture[1]['routes'][5]['candidates'][0]['candidate_digest']
            self.assertNotEqual(request['routes'][0]['candidate_digest'],original)
            self.assertEqual(binding['selection_sha256'],p.digest({'U06':original}))

    def test_null_withdraw_selection_recovers_none_not_digest_none(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);fixture=self.receipt_fixture(directory,phases=('withdraw',),keys=('U04',),null_keys=('U04',))
            binding=self.read_binding(directory,fixture,expect='withdrawn')
            self.assertEqual(binding['selection_sha256'],p.digest({'U04':None}))

    def test_ambiguous_ca_candidates_do_not_guess_original_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);fixture=self.receipt_fixture(directory,keys=('U06',))
            candidate=copy.deepcopy(fixture[1]['routes'][5]['candidates'][0]);candidate['identity']['pin']='other-pin';candidate['candidate_digest']=p.digest(candidate['identity'])
            fixture[1]['routes'][5]['candidates'].append(candidate)
            with self.assertRaises(p.ContractError):self.read_binding(directory,fixture,selected=('U06',))

    def test_rollback_requires_derived_original_outbound_closed_state(self):
        for phases in (('withdraw','rollback'),('withdraw','apply_hidden','rollback'),('withdraw','apply_hidden','publish','rollback')):
            with tempfile.TemporaryDirectory() as temp:
                directory=Path(temp);fixture=self.receipt_fixture(directory,phases)
                self.assertEqual(self.read_binding(directory,fixture,expect='withdrawn')['phase'],'rollback')
                path=fixture[2]/'receipt-rollback.private.json';data=json.loads(path.read_text())
                data['response']['routes'][0]['state_sha256']='f'*64;path.write_bytes(p.canonical(data))
                with self.assertRaises(p.ContractError):self.read_binding(directory,fixture,expect='withdrawn')

    def test_baseline_binds_full_prepare_state_and_rejects_changed_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);fixture=self.receipt_fixture(directory)
            binding=p.baseline_binding(fixture[1],['U18','U19'])
            self.assertEqual(binding['phase'],'prepared_baseline')
            scope=copy.deepcopy(self.scopes)
            for key,value in binding['state_hashes'].items():scope[key]['state_sha256']=value
            p.verify_scope(p.indexed(self.cache['routes']),scope,['U18','U19'],'success',binding['state_hashes'])
            scope['U18']['state_sha256']='f'*64
            with self.assertRaises(p.ContractError):p.verify_scope(p.indexed(self.cache['routes']),scope,['U18','U19'],'success',binding['state_hashes'])

    def test_real_maintenance_driver_receipts_pin_ca_null_and_rollback(self):
        local=Path(__file__).with_name('test_maintain.py')
        source=local if local.exists() else Path.cwd()/'tests/Upstream/test_maintain.py'
        spec=importlib.util.spec_from_file_location('maintain_cross_fixture',source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for ca_and_null in (False,True):
            fixture=module.MaintenanceTests();fixture.setUp()
            try:
                fixture.now=1000.25
                selection={'U06':fixture.rows[5]['candidates'][0]['candidate_digest']}
                selection['U04']=None if ca_and_null else fixture.rows[3]['candidates'][0]['candidate_digest']
                phases=('withdraw','rollback') if ca_and_null else ('withdraw','apply_hidden','publish','rollback')
                for phase in phases:
                    response=fixture.run_action(phase,selection)
                    expect='withdrawn' if phase in ('withdraw','rollback') else 'success'
                    binding=p.receipt_binding(fixture.directory,response['execution_plan_id'],fixture.plan_id,
                        fixture.plan_sha,fixture.plan,fixture.allocation,['U04','U06'],expect)
                    self.assertEqual(binding['phase'],phase)
                    self.assertEqual(binding['selection_sha256'],p.digest(selection))
                    self.assertEqual(binding['state_hashes'],{key:module.m.digest(fixture.backend.states[key]) for key in selection})
                    receipt=json.loads((fixture.directory/('maintenance-'+response['execution_plan_id'])/('receipt-'+phase+'.private.json')).read_text())
                    self.assertIs(type(receipt['at']),float)
            finally:fixture.tearDown()

if __name__=='__main__':unittest.main()
