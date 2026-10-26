#!/usr/bin/env python3
"""Explicit continuation ledger; never edits historical plans or receipts."""
import argparse
from contextlib import ExitStack,contextmanager
import copy
import importlib.util
import json
import math
import os
from pathlib import Path
import time
import uuid

SIBLING=Path(__file__).resolve().parent
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
a=module('finalizer_private',SIBLING/'accept_source_address.py')
BASE_KEYS=a.KEYS-{'U18','U19'}
REPAIR_KEYS={'U26','U29','U33','U34','U40'}
STAGE='arguments'
class FinalizerError(Exception):pass
def check(value,reason='finalizer_contract_invalid'):
    if not value:raise FinalizerError(reason)
def exact(value,fields):check(isinstance(value,dict) and set(value)==set(fields),'unexpected_fields')
def hex_value(value,pattern):return isinstance(value,str) and pattern.fullmatch(value)

def derive(row):
    """Mirror recovery.php's finite state derivation, including raw JSON strings."""
    original=row['original_state'];identity=row['identity']
    check(a.digest(original)==row['original_state_sha256'] and a.digest(identity)==row['candidate_digest'])
    closed=copy.deepcopy(original)
    for section,field in (('backend','enabled'),('public','show')):
        value=closed[section][field];check(type(value) in (int,bool) and value in (0,1))
        closed[section][field]=False if type(value) is bool else 0
    entries=a.parse_json(original['backend']['custom_outbounds'])
    check(isinstance(entries,list) and len(entries)==1 and isinstance(entries[0],dict))
    was_string=isinstance(entries[0]['settings'],str)
    settings=a.parse_json(entries[0]['settings']) if was_string else entries[0]['settings']
    check(settings['server_port']==identity['port'] and settings['tls']['server_name']==identity['sni'] and
          settings['tls'].get('enabled') is True and settings['tls'].get('insecure',False) is False)
    settings['server']=identity['ip']
    if entries[0]['protocol']=='vless':check(identity['pin'] is None and 'certificate_public_key_sha256' not in settings['tls'])
    else:settings['tls']['certificate_public_key_sha256']=[identity['pin']]
    entries[0]['settings']=a.canonical(settings).decode() if was_string else settings
    hidden=copy.deepcopy(closed);hidden['backend']['custom_outbounds']=a.canonical(entries).decode()
    hidden['backend']['enabled']=True if type(original['backend']['enabled']) is bool else 1
    published=copy.deepcopy(hidden);published['public']['show']=original['public']['show']
    return {'hidden':hidden,'publish':published,'rollback':closed}

class Driver:
    def __init__(self,backend,plan_root=a.PLAN_ROOT,private_root=a.PRIVATE_ROOT,sibling=SIBLING,fetch=None,backup=None,clock=time.time):
        self.backend,self.plan_root,self.private_root,self.sibling=backend,plan_root,private_root,sibling
        self.maintain=module('finalizer_maintenance',sibling/'maintain.py')
        self.public=module('finalizer_public',sibling/'public_verify.py')
        self.prepare_module=module('finalizer_prepare',sibling/'prepare.py')
        self.guard=module('finalizer_guard',sibling/'guard.py')
        self.clock=clock;self.fetch=fetch or self.fetch_live
        self.backup=backup or self.maintain.Driver(backend,plan_root=plan_root,private_root=private_root,sibling=sibling).backup_live

    def fetch_live(self):
        a.private_read(self.private_root/'source-url.secret');return self.guard.fetch_subscription(self.private_root)

    def graph_contract(self,graph):
        exact(graph,('schema','base','continuation','repair_execution_id'))
        check(type(graph['schema']) is int and graph['schema']==1)
        exact(graph['base'],('plan_id','plan_sha256','execution_id'));exact(graph['continuation'],('plan_id','plan_sha256'))
        for reference in (graph['base'],graph['continuation']):
            check(hex_value(reference['plan_id'],a.ID32) and hex_value(reference['plan_sha256'],a.HEX64))
        check(graph['base']['plan_id']!=graph['continuation']['plan_id'],'fresh_continuation_required')
        check(hex_value(graph['base']['execution_id'],a.HEX64) and
              (graph['repair_execution_id'] is None or hex_value(graph['repair_execution_id'],a.HEX64)))

    def inputs(self):
        a.private_directory(self.plan_root);a.private_directory(self.private_root,strict=False)
        allocation_bytes=(self.sibling/'allocation.json').read_bytes();check(a.bytes_sha(allocation_bytes)==a.ALLOCATION_BYTES_SHA,'allocation_drift')
        allocation=a.parse_json(allocation_bytes);approved_bytes=a.private_read(self.private_root/'approved.private')
        manifest_bytes=a.private_read(self.private_root/'manifest.private')
        check(self.backend.manifest()==manifest_bytes,'manifest_drift')
        approved=a.parse_json(approved_bytes);scopes,approvals=a.validate_scope(allocation,approved,a.parse_json(manifest_bytes))
        return dict(allocation=allocation,approved=approved,approved_bytes=approved_bytes,manifest_bytes=manifest_bytes,scopes=scopes,approvals=approvals)

    def plan(self,reference,inputs,historical=False,rollback=False):
        directory=self.plan_root/reference['plan_id'];a.private_directory(directory)
        raw=a.private_read(directory/'plan.private.json');check(a.bytes_sha(raw)==reference['plan_sha256'],'plan_drift')
        plan=a.parse_json(raw)
        check(plan.get('schema')==1 and plan.get('plan_id')==reference['plan_id'] and type(plan.get('prepared_at')) is int)
        check(historical or rollback or 0<=self.clock()-plan['prepared_at']<=7200,'continuation_expired')
        check(plan.get('approved_file_sha256')==a.bytes_sha(inputs['approved_bytes']) and
              plan.get('manifest_file_sha256')==a.bytes_sha(inputs['manifest_bytes']) and
              plan.get('allocation_sha256')==a.digest(inputs['allocation']),'plan_input_drift')
        rows=a.rows_by_key(plan['routes'])
        check(all(rows[key]['approved']==inputs['approvals'][key] and
                  self.guard.fingerprint(rows[key]['source'])==inputs['approvals'][key]['source_sha256'] for key in a.KEYS),'source_approval_drift')
        expected=a.snapshot_hashes(self.prepare_module,inputs['allocation'],inputs['approved'],
            {'machine_id':21,'routes':[rows[key]['snapshot'] for key in sorted(a.KEYS)]})
        return directory,plan,raw,rows,expected

    def execution(self,directory,reference,plan,inputs,execution,keys):
        binding=self.public.receipt_binding(directory,execution,reference['plan_id'],reference['plan_sha256'],plan,inputs['allocation'],sorted(keys),'success')
        check(binding['phase']=='apply_hidden','applied_hidden_chain_required')
        folder=directory/('maintenance-'+execution)
        request_bytes=a.private_read(folder/'request-apply_hidden.private.json');request=a.parse_json(request_bytes)
        rows=self.maintain.unique(request['routes']);check(set(rows)==set(keys),'execution_scope_invalid')
        planned=a.rows_by_key(plan['routes'])
        selection={key:self.public.original_selection(row,planned[key],inputs['scopes'][key]) for key,row in rows.items()}
        resolved=self.maintain.selected_rows(plan,selection,inputs['scopes'],inputs['approvals'],'rollback',self.clock())
        check(self.maintain.execution_plan_id(resolved)==execution,'execution_binding_invalid')
        for row in resolved:
            check(row['identity'] is not None and row['identity']==rows[row['key']]['identity'])
            check(a.digest(derive(row)['hidden'])==binding['state_hashes'][row['key']],'historical_derived_state_mismatch')
        receipt=a.parse_json(a.private_read(folder/'receipt-apply_hidden.private.json'))
        return binding,self.maintain.unique(resolved),selection,receipt['at']

    def resolve_graph(self,graph,rollback=False):
        self.graph_contract(graph);inputs=self.inputs()
        base_dir,base,base_raw,base_rows,base_expected=self.plan(graph['base'],inputs,historical=True)
        base_binding,base_request,base_selection,base_at=self.execution(base_dir,graph['base'],base,inputs,graph['base']['execution_id'],BASE_KEYS)
        ready=dict(base_expected);ready.update(base_binding['state_hashes'])
        fresh_dir,fresh,fresh_raw,fresh_rows,fresh_expected=self.plan(graph['continuation'],inputs,rollback=rollback)
        check(fresh['prepared_at']>=int(base_at),'continuation_precedes_initial_apply')
        check(fresh_expected==ready,'continuation_snapshot_not_initial_hidden_state')
        final=copy.deepcopy(base_request);repair_binding=None;repair_at=None;repair_keys=set()
        if graph['repair_execution_id'] is not None:
            path=fresh_dir/('maintenance-'+graph['repair_execution_id'])/'request-apply_hidden.private.json'
            request=a.parse_json(a.private_read(path));repair_keys=set(self.maintain.unique(request['routes']))
            check(repair_keys and repair_keys<=REPAIR_KEYS,'repair_scope_invalid')
            repair_binding,repair_request,repair_selection,repair_at=self.execution(fresh_dir,graph['continuation'],fresh,inputs,graph['repair_execution_id'],repair_keys)
            check(repair_at>=base_at,'repair_precedes_initial_apply')
            for key in repair_keys:
                final[key]['identity']=repair_request[key]['identity']
                final[key]['candidate_digest']=a.digest(final[key]['identity'])
                check(a.digest(derive(final[key])['hidden'])==repair_binding['state_hashes'][key],'repair_not_derivable_from_initial_state')
            ready.update(repair_binding['state_hashes'])
        rows=[final[key] for key in sorted(BASE_KEYS)];execution=self.maintain.execution_plan_id(rows)
        derived={phase:dict(base_expected) for phase in ('hidden','publish','rollback')}
        for row in rows:
            for phase,state in derive(row).items():derived[phase][row['key']]=a.digest(state)
        check(derived['hidden']==ready,'aggregate_hidden_state_mismatch')
        # All final identities remain an explicit choice. Certificate validity
        # is checked at publish-time, while expired/network-broken rollback stays available.
        if not rollback:
            for key,row in final.items():
                candidates=(fresh_rows if key in repair_keys else base_rows)[key]['candidates']
                matches=[c for c in candidates if (dict(c['identity'],pin=None) if inputs['scopes'][key]['upstream_type']=='vless' else c['identity'])==row['identity']]
                check(len(matches)==1 and matches[0].get('certificate_time_valid') is True and
                      all(type(matches[0].get(field)) in (int,float) and math.isfinite(matches[0][field]) for field in ('not_before','not_after')) and
                      matches[0]['not_before']<=self.clock()<=matches[0]['not_after'],'final_certificate_expired')
        cache_bytes=a.private_read(base_dir/'public-cache.private.json')
        source_graph_sha=a.digest({'graph':graph,'base_chain':base_binding['receipt_chain_sha256'],
            'repair_chain':repair_binding['receipt_chain_sha256'] if repair_binding else None,
            'base_cache_sha256':a.bytes_sha(cache_bytes),'rows':rows,'ready':ready})
        return dict(**inputs,rows=rows,derived=derived,expected=ready,phase='hidden',execution_id=execution,
                    source_graph_sha256=source_graph_sha,base_directory=base_dir,base_plan_id=graph['base']['plan_id'],
                    base_plan_sha256=graph['base']['plan_sha256'],cache_bytes=cache_bytes,plan=fresh,
                    base_plan_bytes=base_raw,continuation_plan_bytes=fresh_raw,continuation_directory=fresh_dir,
                    latest_apply_at=max(base_at,repair_at or base_at),repair_keys=repair_keys,
                    anytls={key for key,row in inputs['scopes'].items() if row['upstream_type']=='anytls'})

    @contextmanager
    def graph_locks(self,graph,ledger_directory=None):
        self.graph_contract(graph);a.private_directory(self.plan_root)
        with ExitStack() as stack:
            stack.enter_context(a.lock(self.plan_root/'scope-restore.lock'))
            for plan_id in sorted({graph['base']['plan_id'],graph['continuation']['plan_id']}):
                directory=self.plan_root/plan_id;a.private_directory(directory)
                stack.enter_context(a.lock(directory/'maintenance.lock'))
            if ledger_directory is not None:stack.enter_context(a.lock(ledger_directory/'finalizer.lock'))
            yield

    @contextmanager
    def locked(self,ledger_id):
        check(hex_value(ledger_id,a.ID32),'arguments_invalid');directory=self.plan_root/('finalizer-'+ledger_id)
        a.private_directory(directory);ledger=a.parse_json(a.private_read(directory/'ledger.private.json'))
        with self.graph_locks(ledger['graph'],directory):yield

    def load(self,ledger_id,ledger_sha,rollback=False):
        check(hex_value(ledger_id,a.ID32) and hex_value(ledger_sha,a.HEX64),'arguments_invalid')
        directory=self.plan_root/('finalizer-'+ledger_id);a.private_directory(directory)
        raw=a.private_read(directory/'ledger.private.json');check(a.bytes_sha(raw)==ledger_sha,'ledger_drift')
        ledger=a.parse_json(raw)
        exact(ledger,('schema','ledger_id','created_at','valid_until','graph','source_graph_sha256','execution_id','ready_state_sha256','route_keys','base_cache_sha256'))
        check(type(ledger['schema']) is int and ledger['schema']==1 and ledger['ledger_id']==ledger_id and ledger['route_keys']==sorted(BASE_KEYS) and
              type(ledger['created_at']) is int and ledger['created_at']<=self.clock())
        bound=self.resolve_graph(ledger['graph'],rollback=rollback)
        check(ledger['source_graph_sha256']==bound['source_graph_sha256'] and ledger['execution_id']==bound['execution_id'] and
              ledger['ready_state_sha256']==bound['derived']['hidden'] and ledger['base_cache_sha256']==a.bytes_sha(bound['cache_bytes']) and
              ledger['valid_until']==bound['plan']['prepared_at']+7200,'ledger_graph_drift')
        known={kind+'-'+action+'.private.json' for kind in ('intent','request','receipt') for action in ('publish','rollback')}
        check(all(path.name in known for path in directory.iterdir() if path.name.startswith(('intent-','request-','receipt-'))),'unknown_operation_record')
        phases=[];chain=[];expected=bound['derived']['hidden'];phase_at=max(ledger['created_at'],bound['latest_apply_at'])
        for action in ('publish','rollback'):
            intent_path=directory/('intent-'+action+'.private.json');receipt_path=directory/('receipt-'+action+'.private.json')
            request_path=directory/('request-'+action+'.private.json')
            if os.path.lexists(request_path):check(os.path.lexists(intent_path) and os.path.lexists(receipt_path),'finalizer_outcome_unknown')
            if os.path.lexists(intent_path):check(os.path.lexists(receipt_path),'finalizer_outcome_unknown')
            if not os.path.lexists(receipt_path):continue
            check(os.path.lexists(intent_path),'receipt_without_intent')
            intent_raw=a.private_read(intent_path);intent=a.parse_json(intent_raw);receipt_raw=a.private_read(receipt_path);receipt=a.parse_json(receipt_raw)
            exact(intent,('schema','ledger_sha256','request_sha256','at','verification_id','verification_sha256'))
            check(intent['schema']==1 and self.public.timestamp(intent['at']) and
                  (hex_value(intent['verification_id'],a.ID32) and hex_value(intent['verification_sha256'],a.HEX64) if action=='publish' else
                   intent['verification_id'] is None and intent['verification_sha256'] is None),'operation_intent_invalid')
            request=a.parse_json(a.private_read(request_path))
            expected_rows=[dict(row,expected_sha256=expected[row['key']]) for row in bound['rows']]
            wanted={'schema':1,'action':action,'plan_id':bound['execution_id'],'routes':expected_rows}
            check(request==wanted and intent.get('request_sha256')==a.digest(request) and intent.get('ledger_sha256')==ledger_sha,
                  'operation_request_drift')
            exact(receipt,('schema','ledger_id','ledger_sha256','request_sha256','response','at'))
            check(receipt['schema']==1 and receipt['ledger_id']==ledger_id and receipt['ledger_sha256']==ledger_sha and
                  receipt['request_sha256']==a.digest(request) and self.public.timestamp(receipt['at']) and receipt['at']>=intent['at'],'operation_receipt_invalid')
            hashes=self.maintain.safe_response(receipt['response'],action,bound['execution_id'],expected_rows)
            check(hashes=={key:bound['derived'][action][key] for key in BASE_KEYS},'operation_response_drift')
            expected=bound['derived'][action];phases.append(action)
            phase_at=receipt['at']
            chain.append({'action':action,'intent_sha256':a.bytes_sha(intent_raw),'receipt_sha256':a.bytes_sha(receipt_raw),'request_sha256':a.digest(request)})
        check(phases in ([],['publish'],['rollback'],['publish','rollback']),'operation_phase_invalid')
        phase=phases[-1] if phases else 'hidden'
        bound.update(directory=directory,ledger=ledger,ledger_bytes=raw,ledger_id=ledger_id,ledger_sha256=ledger_sha,
                     phase=phase,phase_at=phase_at,expected=expected,receipt_chain_sha256=a.digest(chain))
        bound['binding_sha256']=a.digest({'ledger_sha256':ledger_sha,'source_graph_sha256':bound['source_graph_sha256'],
                                        'phase':phase,'operation_receipts':chain})
        return bound

    def check_current(self,bound,live_source=True):
        if live_source:
            try:proxies,usage=self.fetch()
            except Exception:raise FinalizerError('source_fetch_failed') from None
            a.validate_usage(usage,self.clock());self.maintain.verify_source(bound['plan'],{key:None for key in a.KEYS},proxies,usage,self.clock())
        current=self.maintain.unique(self.backend.snapshot(sorted(a.KEYS)))
        check(set(current)==a.KEYS,'current_scope_invalid')
        for key,row in current.items():
            check(row.get('state_sha256')==a.digest(row.get('state'))==bound['expected'][key] and
                  row.get('backend_id')==bound['scopes'][key]['backend_id'] and row.get('public_id')==bound['scopes'][key]['public_id'],'current_state_drift')
        check(a.private_read(self.private_root/'approved.private')==bound['approved_bytes'] and
              a.private_read(self.private_root/'manifest.private')==bound['manifest_bytes'],'live_input_drift')
        check(a.private_read(bound['base_directory']/'public-cache.private.json')==bound['cache_bytes'],'base_cache_drift')
        if live_source:check(0<=self.clock()-bound['plan']['prepared_at']<=7200,'continuation_expired')
        return {key:row['state'] for key,row in current.items()}

    def create(self,graph):
        global STAGE
        with self.graph_locks(graph):
            STAGE='resolve_explicit_graph';bound=self.resolve_graph(graph)
            STAGE='current_continuation';self.check_current(bound)
            # Two independent snapshots prevent a read-only adoption ledger
            # from certifying a state that changed during source verification.
            repeated=self.resolve_graph(graph);check(repeated['source_graph_sha256']==bound['source_graph_sha256'],'graph_drift')
            self.check_current(repeated)
            ledger_id=uuid.uuid4().hex;directory=self.plan_root/('finalizer-'+ledger_id);directory.mkdir(mode=0o700)
            ledger={'schema':1,'ledger_id':ledger_id,'created_at':int(self.clock()),'valid_until':bound['plan']['prepared_at']+7200,
                    'graph':graph,'source_graph_sha256':bound['source_graph_sha256'],'execution_id':bound['execution_id'],
                    'ready_state_sha256':bound['derived']['hidden'],'route_keys':sorted(BASE_KEYS),'base_cache_sha256':a.bytes_sha(bound['cache_bytes'])}
            raw=a.canonical(ledger);a.private_write(directory/'ledger.private.json',raw);a.sync_directory(directory);a.sync_directory(self.plan_root)
            return {'status':'finalizer_prepared','ledger_id':ledger_id,'ledger_sha256':a.bytes_sha(raw),'execution_id':bound['execution_id'],
                    'keys':sorted(BASE_KEYS),'repair_keys':sorted(bound['repair_keys']),'valid_until':ledger['valid_until'],
                    'database_mutated':False,'historical_plans_or_receipts_mutated':False}

    def run(self,action,ledger_id,ledger_sha,verification_id=None,verification_sha=None):
        global STAGE
        check(action in ('publish','rollback'),'arguments_invalid')
        with self.locked(ledger_id):
            STAGE='load_finalizer';bound=self.load(ledger_id,ledger_sha,rollback=action=='rollback')
            if bound['phase']==action:
                self.check_current(bound,live_source=action!='rollback')
                return {'status':'already_applied','ledger_id':ledger_id,'ledger_sha256':ledger_sha,'phase':action,'execution_id':bound['execution_id']}
            check(bound['phase']=='hidden' if action=='publish' else bound['phase'] in ('hidden','publish'),'operation_phase_invalid')
            if action=='publish':
                check(hex_value(verification_id,a.ID32) and hex_value(verification_sha,a.HEX64),'verification_binding_required')
                report_raw=a.private_read(bound['directory']/('verification-'+verification_id+'.private.json'))
                check(a.bytes_sha(report_raw)==verification_sha,'verification_drift')
                adapter=module('finalizer_acceptance_contract',self.sibling/'finalizer_acceptance.py')
                report=a.parse_json(report_raw);check(report.get('verification_id')==verification_id,'verification_id_mismatch')
                adapter.validate_report(report,bound,'hidden',self.clock(),ledger_id,ledger_sha)
            STAGE='before_action';self.check_current(bound,live_source=action!='rollback')
            backup_dir=bound['directory']/'backup';a.private_directory(backup_dir,create=True)
            if not os.path.lexists(backup_dir/'backup.private.json'):
                backup=self.backup(backup_dir);a.private_write(backup_dir/'backup.private.json',a.canonical(backup));a.sync_directory(backup_dir)
            again=self.load(ledger_id,ledger_sha,rollback=action=='rollback')
            check(again['binding_sha256']==bound['binding_sha256'],'binding_drift');self.check_current(again,live_source=action!='rollback')
            if action=='publish':
                check(a.private_read(bound['directory']/('verification-'+verification_id+'.private.json'))==report_raw,'verification_drift')
                adapter.validate_report(report,again,'hidden',self.clock(),ledger_id,ledger_sha)
            request={'schema':1,'action':action,'plan_id':bound['execution_id'],
                     'routes':[dict(row,expected_sha256=bound['expected'][row['key']]) for row in bound['rows']]}
            directory=bound['directory'];a.private_write(directory/('request-'+action+'.private.json'),a.canonical(request))
            intent={'schema':1,'ledger_sha256':ledger_sha,'request_sha256':a.digest(request),'at':self.clock(),
                    'verification_id':verification_id if action=='publish' else None,'verification_sha256':verification_sha if action=='publish' else None}
            a.private_write(directory/('intent-'+action+'.private.json'),a.canonical(intent));a.sync_directory(directory)
            STAGE='bounded_database_transaction'
            try:
                response=self.backend.mutate(request)
                hashes=self.maintain.safe_response(response,action,bound['execution_id'],request['routes'])
                check(hashes=={key:bound['derived'][action][key] for key in BASE_KEYS},'response_state_mismatch')
                post=dict(bound,expected=bound['derived'][action]);self.check_current(post,live_source=False)
                receipt={'schema':1,'ledger_id':ledger_id,'ledger_sha256':ledger_sha,'request_sha256':a.digest(request),'response':response,'at':self.clock()}
                a.private_write(directory/('receipt-'+action+'.private.json'),a.canonical(receipt));a.sync_directory(directory)
            except Exception:raise FinalizerError('finalizer_outcome_unknown') from None
            return {'status':'applied','ledger_id':ledger_id,'ledger_sha256':ledger_sha,'phase':action,'execution_id':bound['execution_id'],
                    'routes':response['routes'],'historical_plans_or_receipts_mutated':False}

class SafeParser(argparse.ArgumentParser):
    def error(self,message):raise FinalizerError('arguments_invalid')
def main(argv=None):
    parser=SafeParser(description=__doc__);parser.add_argument('operation',choices=('prepare','publish','rollback'))
    for name in ('ledger-id','ledger-sha256','verification-id','verification-sha256'):parser.add_argument('--'+name)
    args=parser.parse_args(argv);check(os.geteuid()==0,'root_required');os.umask(0o077)
    import sys
    m=module('finalizer_cli_maintenance',SIBLING/'maintain.py')
    with m.DockerBackend(sibling=SIBLING) as backend:
        driver=Driver(backend)
        if args.operation=='prepare':
            check(not any((args.ledger_id,args.ledger_sha256,args.verification_id,args.verification_sha256)))
            raw=sys.stdin.buffer.read(4097);check(0<len(raw)<=4096,'graph_input_size_invalid');result=driver.create(a.parse_json(raw))
        else:result=driver.run(args.operation,args.ledger_id,args.ledger_sha256,args.verification_id,args.verification_sha256)
    print(json.dumps(result,sort_keys=True),flush=True);return 0
def safe_main(argv=None):
    try:return main(argv)
    except (FinalizerError,a.AcceptanceError) as error:
        print(json.dumps({'status':'rejected','reason':str(error),'stage':STAGE}),flush=True);return 1
    except Exception:
        print(json.dumps({'status':'rejected','reason':'finalizer_contract_failed','stage':STAGE}),flush=True);return 1
if __name__=='__main__':raise SystemExit(safe_main())
