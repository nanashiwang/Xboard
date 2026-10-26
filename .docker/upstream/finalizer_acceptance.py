#!/usr/bin/env python3
"""Read aggregate public acceptance; sync only explicitly published DB pins."""
import argparse
import concurrent.futures
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import time
import uuid

SIBLING=Path(__file__).resolve().parent
KEYS={'U%02d'%n for n in range(1,42)}
SELECTED=KEYS-{'U18','U19'}
HEX64=re.compile(r'^[a-f0-9]{64}$')
ID32=re.compile(r'^[a-f0-9]{32}$')
STAGE='arguments'

class AcceptanceError(Exception):pass

def check(value,reason):
    if not value:raise AcceptanceError(reason)

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return sha(canonical(value))
def valid_time(value):return type(value) in (int,float) and math.isfinite(value) and value>=0

def indexed(rows):
    check(isinstance(rows,list),'invalid_rows')
    result={}
    for row in rows:
        check(isinstance(row,dict) and isinstance(row.get('key'),str) and row['key'] not in result,'invalid_rows')
        result[row['key']]=row
    return result

def validate_report(report,bound,phase,now,ledger_id,ledger_sha):
    """Shared by explicit finalizer publish and post-publish pin-map sync."""
    check(phase in ('hidden','publish') and isinstance(report,dict),'public_acceptance_invalid')
    check(report.get('schema')==1 and report.get('status')=='passed' and report.get('phase')==phase and
          report.get('ledger_id')==ledger_id and report.get('ledger_sha256')==ledger_sha and
          report.get('binding_sha256')==bound['binding_sha256'] and report.get('execution_id')==bound['execution_id'] and
          report.get('cache_sha256')==sha(bound['cache_bytes']) and report.get('strict_tls') is True and
          report.get('direct_fallback') is False and report.get('fresh_core_per_route') is True and
          report.get('node_configuration_mutated') is False and report.get('configuration_source')=='original_bound_public_cache',
          'public_acceptance_binding_invalid')
    check(isinstance(report.get('verification_id'),str) and ID32.fullmatch(report['verification_id']) and
          isinstance(report.get('binary_sha256'),str) and HEX64.fullmatch(report['binary_sha256']),'public_acceptance_invalid')
    cache=json.loads(bound['cache_bytes'])
    check(cache.get('schema')==1 and cache.get('plan_id')==bound['base_plan_id'] and cache.get('plan_sha256')==bound['base_plan_sha256'] and
          isinstance(cache.get('binary'),dict) and report['binary_sha256']==cache['binary'].get('sha256'),'public_acceptance_cache_invalid')
    cached=indexed(cache.get('routes'));check(set(cached)==KEYS,'public_acceptance_cache_invalid')
    phase_at=bound['phase_at']
    check(valid_time(phase_at) and valid_time(report.get('started_at')) and valid_time(report.get('checked_at')) and
          math.floor(phase_at)<=report['started_at']<=report['checked_at']<=now and now-report['checked_at']<=7200 and
          report['checked_at']<=bound['ledger']['valid_until'],
          'public_acceptance_stale')
    rows=indexed(report.get('routes'));check(set(rows)==SELECTED,'public_acceptance_scope_invalid')
    for key,row in rows.items():
        check(row.get('status')=='passed' and row.get('classification')=='both_targets_passed' and
              row.get('state_sha256')==bound['expected'][key] and row.get('temporary_process_terminated') is True and
              row.get('temporary_directory_removed') is True,'public_acceptance_route_invalid')
        check(row.get('public_config_sha256')==cached[key].get('public_config_sha256')==digest(cached[key].get('outbound')),
              'public_acceptance_config_invalid')
        checks=row.get('checks');check(isinstance(checks,list) and len(checks)==2,'public_acceptance_targets_invalid')
        targets={}
        for target in checks:
            check(isinstance(target,dict) and target.get('target') in ('cloudflare','google') and target['target'] not in targets,
                  'public_acceptance_targets_invalid')
            targets[target['target']]=target
        for target,code in (('cloudflare',200),('google',204)):
            item=targets.get(target,{})
            check(item.get('success') is True and item.get('runner_valid') is True and type(item.get('curl_exit')) is int and item['curl_exit']==0 and
                  type(item.get('http_status')) is int and item['http_status']==code and item.get('proxy_path_usable') is True,'public_acceptance_targets_invalid')
        check(isinstance(targets['cloudflare'].get('exit_ip_sha256'),str) and HEX64.fullmatch(targets['cloudflare']['exit_ip_sha256']),
              'public_acceptance_targets_invalid')
    return report


def safe_measure(result,key,config_sha,state_sha):
    """Never allow raw runner fields/errors into the saved public report."""
    check(isinstance(result,dict) and result.get('key')==key and result.get('public_config_sha256')==config_sha,'runner_result_invalid')
    classes={'both_targets_passed','cancelled','isolated_runner_failed','isolated_core_failed','https_target_failed',
             'public_key_rejection','certificate_error','authentication_error','websocket_rejected','dns_error',
             'network_unreachable','connection_refused','timeout','proxy_request_failed'}
    checks=result.get('checks');check(isinstance(checks,list) and len(checks)<=2,'runner_result_invalid')
    safe=[]
    for value in checks:
        check(isinstance(value,dict) and value.get('target') in ('cloudflare','google'),'runner_result_invalid')
        item={'target':value['target'],'success':value.get('success') is True,'runner_valid':value.get('runner_valid') is True,
              'proxy_path_usable':value.get('proxy_path_usable') is True}
        for name,low,high in (('http_status',0,599),('curl_exit',-255,255)):
            number=value.get(name)
            item[name]=number if type(number) is int and low<=number<=high else None
        seconds=value.get('seconds');item['seconds']=seconds if valid_time(seconds) else None
        checksum=value.get('exit_ip_sha256');item['exit_ip_sha256']=checksum if isinstance(checksum,str) and HEX64.fullmatch(checksum) else None
        if value.get('classification') in ('cancelled','runner_timeout'):item['classification']=value['classification']
        safe.append(item)
    return {'key':key,'public_config_sha256':config_sha,'state_sha256':state_sha,'checks':safe,
            'status':'passed' if result.get('status')=='passed' else 'failed',
            'classification':result.get('classification') if result.get('classification') in classes else 'public_path_failed',
            'temporary_process_terminated':result.get('temporary_process_terminated') is True,
            'temporary_directory_removed':result.get('temporary_directory_removed') is True}


class Driver:
    def __init__(self,core,sibling=SIBLING,clock=time.time,measure=None):
        self.core,self.clock=core,clock
        self.io=module('aggregate_acceptance_io',sibling/'accept_source_address.py')
        self.public=module('aggregate_public_runner',sibling/'public_verify.py')
        self.guard=module('aggregate_identity_contract',sibling/'guard.py')
        self.measure=measure or self.public.measure

    def same(self,left,right):
        for field in ('binding_sha256','execution_id','expected','phase','cache_bytes','approved_bytes','manifest_bytes'):
            check(left[field]==right[field],'aggregate_binding_changed')

    def cache(self,bound):
        cache=self.io.parse_json(bound['cache_bytes'])
        settings=self.public.agent_settings()
        rows=self.public.cache_contract(cache,bound['base_plan_id'],bound['base_plan_sha256'],bound['allocation'],settings)
        check(sha(self.io.private_read(bound['base_directory']/'public-cache.private.json'))==sha(bound['cache_bytes']),'cache_drift')
        binary=self.public.bound_binary(cache.get('binary'))
        check(set(indexed(bound['rows']))==SELECTED and set(bound['expected'])==KEYS,'aggregate_scope_invalid')
        return cache,settings,rows,binary

    def verify(self,ledger_id,ledger_sha):
        global STAGE
        check(isinstance(ledger_id,str) and ID32.fullmatch(ledger_id) and isinstance(ledger_sha,str) and HEX64.fullmatch(ledger_sha),'arguments_invalid')
        with self.core.locked(ledger_id):
            STAGE='aggregate_binding';bound=self.core.load(ledger_id,ledger_sha)
            check(bound['phase'] in ('hidden','publish'),'aggregate_phase_invalid')
            cache,settings,rows,binary=self.cache(bound)
            STAGE='source_and_state_before';self.core.check_current(bound,live_source=True)
            before=self.public.scope(settings,bound['allocation'])
            self.public.verify_scope(rows,before,sorted(SELECTED),'success',bound['expected'])
            check(not self.public.STOP.is_set(),'cancelled')
            started=int(self.clock());STAGE='aggregate_public_paths'
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                measurements=list(executor.map(lambda key:self.measure(rows[key],binary,'success'),sorted(SELECTED)))
            results=[safe_measure(result,key,rows[key]['public_config_sha256'],bound['expected'][key])
                     for key,result in zip(sorted(SELECTED),measurements)]
            STAGE='source_and_state_after';self.core.check_current(bound,live_source=True)
            after=self.public.scope(settings,bound['allocation'])
            self.public.verify_scope(rows,after,sorted(SELECTED),'success',bound['expected'])
            check(before==after and not self.public.STOP.is_set(),'public_scope_changed')
            fresh=self.core.load(ledger_id,ledger_sha);self.same(bound,fresh)
            self.cache(fresh)
            report={'schema':1,'verification_id':uuid.uuid4().hex,'status':'passed','ledger_id':ledger_id,'ledger_sha256':ledger_sha,
                    'phase':bound['phase'],'binding_sha256':bound['binding_sha256'],'execution_id':bound['execution_id'],
                    'cache_sha256':sha(bound['cache_bytes']),'binary_sha256':cache['binary']['sha256'],
                    'strict_tls':True,'direct_fallback':False,'fresh_core_per_route':True,'node_configuration_mutated':False,
                    'configuration_source':'original_bound_public_cache','started_at':started,'checked_at':int(self.clock()),'routes':results}
            try:validate_report(report,bound,bound['phase'],self.clock(),ledger_id,ledger_sha)
            except AcceptanceError:report['status']='failed'
            check(not self.public.STOP.is_set(),'cancelled')
            body=canonical(report);STAGE='aggregate_report_storage'
            self.io.private_write(bound['directory']/('verification-'+report['verification_id']+'.private.json'),body)
            self.io.sync_directory(bound['directory'])
            return dict(report,verification_sha256=sha(body))

    def accepted(self,bound,ledger_id,ledger_sha,verification_id,verification_sha):
        path=bound['directory']/('verification-'+verification_id+'.private.json')
        raw=self.io.private_read(path);check(sha(raw)==verification_sha,'verification_drift')
        report=self.io.parse_json(raw);check(report.get('verification_id')==verification_id,'verification_id_mismatch')
        validate_report(report,bound,'publish',self.clock(),ledger_id,ledger_sha)
        cache,_,rows,_=self.cache(bound)
        check(report['binary_sha256']==cache['binary']['sha256'],'verification_binary_drift')
        for row in report['routes']:check(row['public_config_sha256']==rows[row['key']]['public_config_sha256'],'verification_config_drift')
        return path,raw

    def mappings(self,bound,states):
        check(isinstance(states,dict) and set(states)==KEYS and set(bound['anytls'])<=SELECTED and len(bound['anytls'])==28,'anytls_scope_invalid')
        selected=indexed(bound['rows']);result=[]
        for key in sorted(bound['anytls']):
            state=states[key];identity=selected[key]['identity']
            check(digest(state)==bound['expected'][key] and selected[key]['candidate_digest']==digest(identity),'applied_identity_drift')
            self.public.exact(identity,('key','ip','port','sni','pin'));self.guard.validate_identity(identity)
            check(identity['key']==key,'applied_identity_drift')
            values=self.io.parse_json(state['backend']['custom_outbounds'])
            check(isinstance(values,list) and len(values)==1 and values[0].get('protocol')=='anytls','applied_identity_drift')
            settings=values[0]['settings']
            if isinstance(settings,str):settings=self.io.parse_json(settings)
            tls=settings.get('tls',{})
            check(state['backend'].get('enabled') in (1,True) and
                  state['public'].get('show')==selected[key]['original_state']['public']['show'] and
                  settings.get('server')==identity['ip'] and settings.get('server_port')==identity['port'] and
                  tls.get('enabled') is True and tls.get('insecure',False) is False and tls.get('server_name')==identity['sni'] and
                  tls.get('certificate_public_key_sha256')==[identity['pin']],'applied_identity_drift')
            result.append(copy.deepcopy(identity))
        return result

    def old_map(self,expected,anytls):
        path=self.core.private_root/'pinned.private'
        if expected=='absent':
            check(not os.path.lexists(path),'pinned_map_drift');return None
        raw=self.io.private_read(path);check(sha(raw)==expected,'pinned_map_drift')
        rows=indexed(self.io.parse_json(raw));check(set(rows)<=set(anytls),'pinned_scope_invalid')
        for key,row in rows.items():
            self.public.exact(row,('key','ip','port','sni','pin'));self.guard.validate_identity(row)
        return raw

    def sync(self,ledger_id,ledger_sha,verification_id,verification_sha,pinned_sha):
        global STAGE
        check(all(isinstance(v,str) and ID32.fullmatch(v) for v in (ledger_id,verification_id)) and
              all(isinstance(v,str) and HEX64.fullmatch(v) for v in (ledger_sha,verification_sha)) and
              isinstance(pinned_sha,str) and (pinned_sha=='absent' or HEX64.fullmatch(pinned_sha)),'arguments_invalid')
        with self.core.locked(ledger_id):
            STAGE='published_aggregate_binding';bound=self.core.load(ledger_id,ledger_sha)
            check(bound['phase']=='publish','published_aggregate_required')
            report_path,report_raw=self.accepted(bound,ledger_id,ledger_sha,verification_id,verification_sha)
            STAGE='published_current_state';states=self.core.check_current(bound,live_source=True)
            mappings=self.mappings(bound,states);replacement=canonical(mappings)
            record=bound['directory']/'pin-map';self.io.private_directory(record,create=True)
            request={'schema':1,'ledger_id':ledger_id,'ledger_sha256':ledger_sha,'verification_id':verification_id,
                     'verification_sha256':verification_sha,'expected_pinned_sha256':pinned_sha,
                     'binding_sha256':bound['binding_sha256'],'execution_id':bound['execution_id']}
            result={'status':'pins_synced','ledger_id':ledger_id,'ledger_sha256':ledger_sha,'execution_id':bound['execution_id'],
                    'verification_id':verification_id,'verification_sha256':verification_sha,'route_count':28,'keys':sorted(bound['anytls']),
                    'pinned_sha256':sha(replacement),'old_pinned_sha256':pinned_sha,'source_baseline_mutated':False,
                    'database_mutated':False,'public_key_baseline_mutated':True,'identities_from_published_selection':True,
                    'identity_handshakes_performed':False}
            if list(record.iterdir()):
                check(os.path.lexists(record/'receipt.private.json') and os.path.lexists(record/'intent.private.json'),'pin_sync_outcome_unknown')
                receipt=self.io.parse_json(self.io.private_read(record/'receipt.private.json'))
                intent=self.io.parse_json(self.io.private_read(record/'intent.private.json'))
                check(self.io.parse_json(self.io.private_read(record/'request.private.json'))==request and
                      intent.get('request_sha256')==digest(request) and intent.get('new_pinned_sha256')==sha(replacement) and
                      receipt.get('request_sha256')==digest(request) and receipt.get('result')==result,'pin_sync_receipt_invalid')
                check(self.io.private_read(self.core.private_root/'pinned.private')==replacement,'pinned_map_drift')
                return dict(result,status='already_synced')
            old=self.old_map(pinned_sha,bound['anytls'])
            self.io.private_write(record/'request.private.json',canonical(request))
            self.io.private_write(record/'approved.private',bound['approved_bytes'])
            self.io.private_write(record/'manifest.private',bound['manifest_bytes'])
            self.io.private_write(record/'verification.private.json',report_raw)
            self.io.private_write(record/'snapshot-before.private.json',canonical(states))
            self.io.private_write(record/'pinned-before-state.private.json',canonical({'exists':old is not None,'sha256':pinned_sha}))
            if old is not None:self.io.private_write(record/'pinned-before.private',old)
            self.io.sync_directory(record);self.io.sync_directory(bound['directory'])
            STAGE='final_source_and_state';again=self.core.load(ledger_id,ledger_sha);self.same(bound,again)
            check(self.mappings(again,self.core.check_current(again,live_source=True))==mappings,'applied_identity_drift')
            self.accepted(again,ledger_id,ledger_sha,verification_id,verification_sha)
            check(self.old_map(pinned_sha,bound['anytls'])==old,'pinned_map_drift')
            check(not self.public.STOP.is_set(),'cancelled')
            intent={'schema':1,'request_sha256':digest(request),'new_pinned_sha256':sha(replacement),'at':self.clock()}
            self.io.private_write(record/'intent.private.json',canonical(intent));self.io.sync_directory(record)
            temporary=self.core.private_root/('.aggregate-pins-'+uuid.uuid4().hex+'.tmp')
            try:
                STAGE='atomic_pinned_map';check(not self.public.STOP.is_set(),'cancelled');self.io.private_write(temporary,replacement)
                check(self.old_map(pinned_sha,bound['anytls'])==old,'pinned_map_drift')
                check(self.clock()<=bound['ledger']['valid_until'],'continuation_expired')
                if old is None:os.link(temporary,self.core.private_root/'pinned.private');temporary.unlink()
                else:os.replace(temporary,self.core.private_root/'pinned.private')
                self.io.sync_directory(self.core.private_root)
                check(self.io.private_read(self.core.private_root/'pinned.private')==replacement,'pinned_readback_failed')
                self.core.check_current(bound,live_source=False)
                self.io.private_write(record/'receipt.private.json',canonical({'schema':1,'request_sha256':digest(request),'result':result,'at':self.clock()}))
                self.io.sync_directory(record)
                return result
            except Exception:raise AcceptanceError('pin_sync_outcome_unknown') from None
            finally:
                try:
                    if os.path.lexists(temporary):temporary.unlink()
                except Exception:raise AcceptanceError('pin_sync_outcome_unknown') from None

class SafeParser(argparse.ArgumentParser):
    def error(self,message):raise AcceptanceError('arguments_invalid')

def main(argv=None):
    parser=SafeParser(description=__doc__);parser.add_argument('operation',choices=('verify','sync'))
    for name in ('ledger-id','ledger-sha256'):parser.add_argument('--'+name,required=True)
    for name in ('verification-id','verification-sha256','pinned-sha256'):parser.add_argument('--'+name)
    args=parser.parse_args(argv);check(os.geteuid()==0,'root_required');os.umask(0o077)
    core=module('aggregate_finalizer_core',SIBLING/'finalizer.py')
    maintenance=module('aggregate_docker_backend',SIBLING/'maintain.py')
    with maintenance.DockerBackend() as backend:
        driver=Driver(core.Driver(backend))
        for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,lambda *_:driver.public.STOP.set())
        if args.operation=='verify':
            check(all(getattr(args,field) is None for field in ('verification_id','verification_sha256','pinned_sha256')),'arguments_invalid')
            report=driver.verify(args.ledger_id,args.ledger_sha256)
        else:report=driver.sync(args.ledger_id,args.ledger_sha256,args.verification_id,args.verification_sha256,args.pinned_sha256)
    print(json.dumps(report,sort_keys=True),flush=True)
    return 0 if report['status'] in ('passed','pins_synced','already_synced') else 1

def safe_main(argv=None):
    try:return main(argv)
    except AcceptanceError as error:
        print(json.dumps({'status':'rejected','reason':str(error),'stage':STAGE}),flush=True);return 1
    except Exception:
        print(json.dumps({'status':'rejected','reason':'aggregate_acceptance_failed','stage':STAGE}),flush=True);return 1

if __name__=='__main__':raise SystemExit(safe_main())
