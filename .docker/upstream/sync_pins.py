#!/usr/bin/env python3
"""Explicitly sync 28 applied AnyTLS identities after published-path acceptance."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import time
import uuid

SIBLING=Path(__file__).resolve().parent
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

a=module('sync_private_io',SIBLING/'accept_source_address.py')
STAGE='arguments'

class SyncError(Exception):pass
def check(value,reason):
    if not value:raise SyncError(reason)

class Driver:
    def __init__(self,private_root=a.PRIVATE_ROOT,plan_root=a.PLAN_ROOT,sibling=SIBLING,
                 snapshot=None,fetch=None,clock=time.time):
        self.private_root,self.plan_root,self.sibling=private_root,plan_root,sibling
        self.maintain=module('sync_maintenance',sibling/'maintain.py')
        self.public=module('sync_public_verifier',sibling/'public_verify.py')
        self.prepare=module('sync_prepare',sibling/'prepare.py')
        self.guard=module('sync_guard',sibling/'guard.py')
        self.snapshot=snapshot or self.prepare.snapshot_database
        self.fetch=fetch or self.fetch_live;self.clock=clock

    def fetch_live(self):
        a.private_read(self.private_root/'source-url.secret')
        return self.guard.fetch_subscription(self.private_root)

    def load(self,plan_id,plan_sha,execution,verification_id,verification_sha):
        a.private_directory(self.private_root,strict=False);a.private_directory(self.plan_root)
        directory=self.plan_root/plan_id;a.private_directory(directory)
        plan_bytes=a.private_read(directory/'plan.private.json')
        check(a.bytes_sha(plan_bytes)==plan_sha,'plan_drift')
        plan=a.parse_json(plan_bytes);now=self.clock()
        check(plan.get('schema')==1 and plan.get('plan_id')==plan_id and type(plan.get('prepared_at')) is int and
              0<=now-plan['prepared_at']<=7200 and plan.get('production_mutated') is False,'plan_invalid_or_expired')
        lineage=plan.get('reviewed_import',{})
        check(lineage.get('schema')==1 and lineage.get('manual_selection_required') is True and
              isinstance(lineage.get('parent_plan_id'),str) and a.ID32.fullmatch(lineage['parent_plan_id']) and
              isinstance(lineage.get('parent_plan_sha256'),str) and a.HEX64.fullmatch(lineage['parent_plan_sha256']),'derived_plan_required')
        allocation_bytes=(self.sibling/'allocation.json').read_bytes();allocation=a.parse_json(allocation_bytes)
        check(a.bytes_sha(allocation_bytes)==a.ALLOCATION_BYTES_SHA and a.digest(allocation)==plan.get('allocation_sha256'),'allocation_drift')
        approved_bytes=a.private_read(self.private_root/'approved.private');approved=a.parse_json(approved_bytes)
        manifest_bytes=a.private_read(self.private_root/'manifest.private');manifest=a.parse_json(manifest_bytes)
        check(a.bytes_sha(approved_bytes)==plan.get('approved_file_sha256'),'approved_drift')
        check(a.bytes_sha(manifest_bytes)==plan.get('manifest_file_sha256'),'manifest_drift')
        scopes,approvals=a.validate_scope(allocation,approved,manifest);planned=a.rows_by_key(plan['routes'])
        check(all(planned[key]['approved']==approvals[key] and
                  self.guard.fingerprint(planned[key]['source'])==approvals[key]['source_sha256'] for key in a.KEYS),'approved_row_drift')
        anytls={key for key,row in scopes.items() if row['upstream_type']=='anytls'}
        check(len(anytls)==28,'anytls_scope_invalid')
        binding=self.public.receipt_binding(directory,execution,plan_id,plan_sha,plan,allocation,sorted(anytls),'success')
        check(binding['phase']=='publish','published_receipt_required')
        folder=directory/('maintenance-'+execution)
        request_bytes=a.private_read(folder/'request-publish.private.json');request=a.parse_json(request_bytes)
        requested=self.maintain.unique(request['routes'])
        selection={key:self.public.original_selection(row,planned[key],scopes[key]) for key,row in requested.items()}
        selected=self.maintain.selected_rows(plan,selection,scopes,approvals,'publish',now)
        check(self.maintain.execution_plan_id(selected)==execution and anytls<=set(selection),'execution_binding_invalid')
        selected=self.maintain.unique(selected)
        for key,row in requested.items():
            check(row['identity']==selected[key]['identity'] and row['original_state']==selected[key]['original_state'],
                  'published_identity_drift')
        baseline={'machine_id':21,'routes':[planned[key]['snapshot'] for key in sorted(a.KEYS)]}
        expected=a.snapshot_hashes(self.prepare,allocation,approved,baseline)
        expected.update(binding['state_hashes'])
        report_path=directory/('public-verify-success-'+verification_id+'.json')
        report_bytes=a.private_read(report_path)
        check(a.bytes_sha(report_bytes)==verification_sha,'verification_drift')
        report=a.parse_json(report_bytes)
        check(report.get('status')=='passed' and report.get('operation')=='verify' and report.get('expect')=='success' and
              report.get('plan_id')==plan_id and report.get('plan_sha256')==plan_sha and
              report.get('execution_plan_id')==execution and report.get('maintenance_phase')=='publish' and
              report.get('receipt_chain_sha256')==binding['receipt_chain_sha256'] and report.get('strict_tls') is True and
              report.get('direct_fallback') is False and report.get('node_configuration_mutated') is False and
              report.get('fresh_core_per_route') is True and self.public.timestamp(report.get('checked_at')) and
              0<=now-report['checked_at']<=7200,'published_public_acceptance_required')
        publish=a.parse_json(a.private_read(folder/'receipt-publish.private.json'))
        check(report['checked_at']>=int(publish['at']),'verification_precedes_publish')
        verified=self.public.indexed(report.get('routes'))
        check(anytls<=set(verified)<=set(binding['state_hashes']),'verification_scope_invalid')
        for key,row in verified.items():
            check(row.get('status')=='passed' and row.get('temporary_process_terminated') is True and
                  row.get('temporary_directory_removed') is True and row.get('state_sha256')==expected[key],'verification_route_invalid')
        cache_bytes=a.private_read(directory/'public-cache.private.json');cache=a.parse_json(cache_bytes)
        check(cache.get('plan_id')==plan_id and cache.get('plan_sha256')==plan_sha and
              report.get('cache_sha256')==a.digest(cache),'verification_cache_drift')
        return dict(directory=directory,plan=plan,plan_bytes=plan_bytes,allocation=allocation,approved=approved,
                    approved_bytes=approved_bytes,manifest_bytes=manifest_bytes,scopes=scopes,anytls=anytls,
                    binding=binding,expected=expected,selection=selection,selected=selected,
                    report_path=report_path,report_bytes=report_bytes,cache_bytes=cache_bytes,request_bytes=request_bytes)

    def current(self,bound):
        # Reuse maintenance's current source contract for every approved route,
        # then compare full current state after the network read.
        try:proxies,usage=self.fetch()
        except Exception:raise SyncError('source_fetch_failed') from None
        a.validate_usage(usage,self.clock())
        self.maintain.verify_source(bound['plan'],{key:None for key in a.KEYS},proxies,usage,self.clock())
        snapshot=self.snapshot(bound['allocation'],bound['manifest_bytes'])
        hashes=a.snapshot_hashes(self.prepare,bound['allocation'],bound['approved'],snapshot)
        check(hashes==bound['expected'],'database_state_drift')
        rows=a.rows_by_key(snapshot['routes']);mappings=[]
        for key in sorted(bound['anytls']):
            state=rows[key]['state'];identity=bound['selected'][key]['identity']
            settings=self.prepare.settings_for({'backend':state['backend']},'anytls');tls=settings.get('tls',{})
            check(state['backend'].get('enabled') in (1,True) and settings.get('server')==identity['ip'] and
                  settings.get('server_port')==identity['port'] and tls.get('server_name')==identity['sni'] and
                  tls.get('enabled') is True and tls.get('insecure',False) is False and
                  tls.get('certificate_public_key_sha256')==[identity['pin']],'applied_identity_mismatch')
            self.guard.validate_identity(identity)
            mappings.append(copy.deepcopy(identity))
        check(len(mappings)==28,'anytls_scope_invalid')
        check(a.private_read(bound['directory']/'plan.private.json')==bound['plan_bytes'],'plan_drift')
        check(a.private_read(self.private_root/'approved.private')==bound['approved_bytes'],'approved_drift')
        check(a.private_read(self.private_root/'manifest.private')==bound['manifest_bytes'],'manifest_drift')
        check(a.private_read(bound['report_path'])==bound['report_bytes'] and
              a.private_read(bound['directory']/'public-cache.private.json')==bound['cache_bytes'],'verification_drift')
        check(0<=self.clock()-bound['plan']['prepared_at']<=7200,'plan_invalid_or_expired')
        a.validate_usage(usage,self.clock())
        return snapshot,mappings

    def old_map(self,expected,anytls):
        path=self.private_root/'pinned.private'
        if expected=='absent':
            check(not os.path.lexists(path),'pinned_map_drift');return None
        raw=a.private_read(path);check(a.bytes_sha(raw)==expected,'pinned_map_drift')
        rows=self.maintain.unique(a.parse_json(raw))
        check(set(rows)<=anytls,'non_anytls_mapping_present')
        for row in rows.values():self.guard.validate_identity(row)
        return raw

    def result(self,bound,request,replacement):
        return {'status':'pins_synced','plan_id':request['plan_id'],'plan_sha256':request['plan_sha256'],
                'execution_plan_id':request['execution_id'],'verification_id':request['verification_id'],
                'verification_sha256':request['verification_sha256'],'keys':sorted(bound['anytls']),
                'pinned_sha256':a.bytes_sha(replacement),'old_pinned_sha256':request['expected_pinned_sha256'],'route_count':28,
                'source_baseline_mutated':False,'database_mutated':False,'public_key_baseline_mutated':True,
                'identities_from_published_selection':True,'identity_handshakes_performed':False}

    def run(self,plan_id,plan_sha,execution,verification_id,verification_sha,pinned_sha):
        global STAGE
        check(isinstance(plan_id,str) and a.ID32.fullmatch(plan_id) and isinstance(verification_id,str) and
              a.ID32.fullmatch(verification_id) and all(isinstance(v,str) and a.HEX64.fullmatch(v) for v in
              (plan_sha,execution,verification_sha)) and (pinned_sha=='absent' or isinstance(pinned_sha,str) and a.HEX64.fullmatch(pinned_sha)),
              'arguments_invalid')
        a.private_directory(self.plan_root)
        with a.lock(self.plan_root/'scope-restore.lock'):
            directory=self.plan_root/plan_id;a.private_directory(directory)
            with a.lock(directory/'maintenance.lock'):
                STAGE='published_binding'
                bound=self.load(plan_id,plan_sha,execution,verification_id,verification_sha)
                record=directory/('pin-map-'+execution);a.private_directory(record,create=True)
                request={'schema':1,'plan_id':plan_id,'plan_sha256':plan_sha,'execution_id':execution,
                         'verification_id':verification_id,'verification_sha256':verification_sha,'expected_pinned_sha256':pinned_sha}
                if list(record.iterdir()):
                    # Never overwrite or replay an uncertain metadata change.
                    check(os.path.lexists(record/'receipt.private.json'),'pin_sync_outcome_unknown')
                    check(os.path.lexists(record/'intent.private.json'),'pin_sync_outcome_unknown')
                    saved=a.parse_json(a.private_read(record/'receipt.private.json'))
                    check(saved.get('request_sha256')==a.digest(request),'pin_sync_already_recorded')
                    check(a.parse_json(a.private_read(record/'request.private.json'))==request,'pin_sync_receipt_invalid')
                    _,mapping=self.current(bound)
                    check(a.private_read(self.private_root/'pinned.private')==a.canonical(mapping),'pinned_map_drift')
                    result=self.result(bound,request,a.canonical(mapping))
                    intent=a.parse_json(a.private_read(record/'intent.private.json'))
                    check(set(intent)=={'schema','request_sha256','new_pinned_sha256','receipt_chain_sha256','at'} and
                          intent['schema']==1 and intent['request_sha256']==a.digest(request) and
                          intent['new_pinned_sha256']==result['pinned_sha256'] and
                          intent['receipt_chain_sha256']==bound['binding']['receipt_chain_sha256'] and
                          self.public.timestamp(intent['at']),'pin_sync_receipt_invalid')
                    check(set(saved)=={'schema','request_sha256','result','at'} and saved['schema']==1 and
                          saved['result']==result and self.public.timestamp(saved['at']),'pin_sync_receipt_invalid')
                    return dict(result,status='already_synced')
                old=self.old_map(pinned_sha,bound['anytls'])
                STAGE='current_source_and_state'
                before,mapping=self.current(bound);replacement=a.canonical(mapping)
                a.private_write(record/'request.private.json',a.canonical(request))
                a.private_write(record/'approved.private',bound['approved_bytes'])
                a.private_write(record/'manifest.private',bound['manifest_bytes'])
                a.private_write(record/'snapshot-before.private.json',a.canonical(before))
                a.private_write(record/'verification.private.json',bound['report_bytes'])
                if old is not None:a.private_write(record/'pinned-before.private',old)
                a.private_write(record/'pinned-before-state.private.json',a.canonical({'exists':old is not None,'sha256':pinned_sha}))
                a.sync_directory(record)
                STAGE='final_source_and_state'
                _,again=self.current(bound);check(again==mapping,'applied_identity_mismatch')
                fresh=self.load(plan_id,plan_sha,execution,verification_id,verification_sha)
                check(fresh['binding']==bound['binding'] and self.old_map(pinned_sha,bound['anytls'])==old,'prewrite_drift')
                intent={'schema':1,'request_sha256':a.digest(request),'new_pinned_sha256':a.bytes_sha(replacement),
                        'receipt_chain_sha256':bound['binding']['receipt_chain_sha256'],'at':self.clock()}
                a.private_write(record/'intent.private.json',a.canonical(intent));a.sync_directory(record)
                temporary=self.private_root/('.pinned-sync-'+uuid.uuid4().hex+'.tmp')
                try:
                    STAGE='atomic_pinned_map'
                    a.private_write(temporary,replacement)
                    check(self.old_map(pinned_sha,bound['anytls'])==old,'pinned_map_drift')
                    check(0<=self.clock()-bound['plan']['prepared_at']<=7200,'plan_invalid_or_expired')
                    if old is None:
                        # Atomic create-if-absent; never overwrite a file that
                        # appeared after the final missing-state comparison.
                        os.link(temporary,self.private_root/'pinned.private');temporary.unlink()
                    else:os.replace(temporary,self.private_root/'pinned.private')
                    a.sync_directory(self.private_root)
                    check(a.private_read(self.private_root/'pinned.private')==replacement,'pinned_readback_failed')
                    result=self.result(bound,request,replacement)
                    a.private_write(record/'receipt.private.json',a.canonical({'schema':1,'request_sha256':a.digest(request),'result':result,'at':self.clock()}))
                    a.sync_directory(record)
                    return result
                except Exception:raise SyncError('pin_sync_outcome_unknown') from None
                finally:
                    if os.path.lexists(temporary):temporary.unlink()

class SafeParser(argparse.ArgumentParser):
    def error(self,message):raise SyncError('arguments_invalid')

def main(argv=None):
    parser=SafeParser(description=__doc__)
    for name in ('plan-id','plan-sha256','execution-id','verification-id','verification-sha256','pinned-sha256'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv);check(os.geteuid()==0,'root_required');os.umask(0o077)
    result=Driver().run(args.plan_id,args.plan_sha256,args.execution_id,args.verification_id,args.verification_sha256,args.pinned_sha256)
    print(json.dumps(result,sort_keys=True),flush=True);return 0

def safe_main(argv=None):
    try:return main(argv)
    except (SyncError,a.AcceptanceError) as error:
        print(json.dumps({'status':'rejected','reason':str(error),'stage':STAGE}),flush=True);return 1
    except Exception:
        print(json.dumps({'status':'rejected','reason':'pin_sync_contract_failed','stage':STAGE}),flush=True);return 1

if __name__=='__main__':raise SystemExit(safe_main())
