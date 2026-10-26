#!/usr/bin/env python3
"""Import explicitly reviewed, encrypted observations into a new PRIVATE plan.
No trust acceptance, DB update, source-baseline update, pin-map update or apply.
"""
import argparse
import base64
import copy
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

SIBLING=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('reviewed_private_io',SIBLING/'accept_source_address.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
PRIVATE_ROOT=a.PRIVATE_ROOT
PLAN_ROOT=a.PLAN_ROOT
MAX_PAYLOAD=60*1024
STAGE='arguments'

class ImportErrorBounded(Exception):
    pass

def fail(reason):raise ImportErrorBounded(reason)
def check(condition,reason='contract_invalid'):
    if not condition:fail(reason)
def exact(value,fields):check(isinstance(value,dict) and set(value)==set(fields),'unexpected_fields')
def finite(value):return type(value) in (int,float) and math.isfinite(value)
def hex64(value):return isinstance(value,str) and a.HEX64.fullmatch(value)
def canon(value):return a.canonical(value)
def digest(value):return a.digest(value)
def bsha(value):return a.bytes_sha(value)

def openssl(arguments,body=None,timeout=60):
    try:
        result=subprocess.run(['openssl',*arguments],input=body,capture_output=True,timeout=timeout)
        check(result.returncode==0 and len(result.stdout)<=MAX_PAYLOAD,'crypto_operation_failed')
        return result.stdout
    except ImportErrorBounded:raise
    except Exception:fail('crypto_operation_failed')

def public_from_key(key_bytes):
    public=openssl(['pkey','-pubout'],key_bytes)
    check(public.startswith(b'-----BEGIN PUBLIC KEY-----\n') and public.endswith(b'-----END PUBLIC KEY-----\n'),'recipient_invalid')
    details=openssl(['pkey','-pubin','-text','-noout'],public)
    check(re.search(rb'Public-Key:\s*\(4096 bit\)',details) is not None,'recipient_key_size_invalid')
    return public

def decode64(value,length=None):
    check(isinstance(value,str),'invalid_ciphertext')
    try:decoded=base64.b64decode(value,validate=True)
    except Exception:fail('invalid_ciphertext')
    check(base64.b64encode(decoded).decode()==value and (length is None or len(decoded)==length),'invalid_ciphertext')
    return decoded

def payload_envelope(raw,plan_id,plan_sha):
    """Validate only the public ciphertext envelope, also used by control.py."""
    check(isinstance(raw,bytes) and 0<len(raw)<=MAX_PAYLOAD,'payload_size_invalid')
    payload=a.parse_json(raw)
    exact(payload,('schema','plan_id','plan_sha256','recipient_sha256','rows'))
    check(type(payload['schema']) is int and payload['schema']==1 and payload['plan_id']==plan_id and
          payload['plan_sha256']==plan_sha and hex64(payload['recipient_sha256']),'payload_binding_invalid')
    rows=payload['rows'];check(isinstance(rows,list) and 1<=len(rows)<=41,'scope_invalid')
    seen=set()
    for row in rows:
        exact(row,('key','candidate_digest','ciphertext','not_before','not_after','witnesses'))
        check(isinstance(row['key'],str) and row['key'] in a.KEYS and row['key'] not in seen and hex64(row['candidate_digest']),'scope_invalid')
        seen.add(row['key']);decode64(row['ciphertext'],512)
        check(finite(row['not_before']) and finite(row['not_after']) and row['not_before']<=row['not_after'],'certificate_time_invalid')
        exact(row['witnesses'],('entry','independent'))
        for witness in row['witnesses'].values():
            exact(witness,('observer_sha256','evidence_sha256','identity_sha256','observed_at','source_dns','ca_validated'))
            check(hex64(witness['observer_sha256']) and hex64(witness['evidence_sha256']) and
                  witness['identity_sha256']==row['candidate_digest'] and finite(witness['observed_at']) and
                  type(witness['source_dns']) is bool and type(witness['ca_validated']) is bool,'witness_binding_invalid')
    return payload

def witness_contract(value,commitment,now,not_before,not_after,ca,hostname_source):
    exact(value,('entry','independent'))
    for role in ('entry','independent'):
        item=value[role]
        exact(item,('observer_sha256','evidence_sha256','identity_sha256','observed_at','source_dns','ca_validated'))
        check(hex64(item['observer_sha256']) and hex64(item['evidence_sha256']) and item['identity_sha256']==commitment,'witness_binding_invalid')
        observed=item['observed_at']
        check(finite(observed) and now-7200<=observed<=now+60 and not_before<=observed<=not_after,'witness_time_invalid')
        check(type(item['source_dns']) is bool and type(item['ca_validated']) is bool,'witness_invalid')
        check(not ca or item['ca_validated'] is True,'ca_witness_required')
    check(value['entry']['observer_sha256']!=value['independent']['observer_sha256'] and
          value['entry']['evidence_sha256']!=value['independent']['evidence_sha256'],'independent_witness_required')
    check(not hostname_source or value['entry']['source_dns'] is True,'entry_source_dns_required')

class Driver:
    def __init__(self,private_root=PRIVATE_ROOT,plan_root=PLAN_ROOT,sibling=SIBLING,prepare=None,guard=None,
                 snapshot=None,fetch=None,clock=time.time):
        self.private_root,self.plan_root,self.sibling=private_root,plan_root,sibling
        self.prepare=prepare or a.load_module('reviewed_prepare',sibling/'prepare.py')
        self.guard=guard or a.load_module('reviewed_guard',sibling/'guard.py')
        self.snapshot=snapshot or self.prepare.snapshot_database
        self.fetch=fetch or self.fetch_live
        self.clock=clock

    def fetch_live(self):
        a.private_read(self.private_root/'source-url.secret')
        return self.guard.fetch_subscription(self.private_root)

    def load(self,plan_id,plan_sha):
        check(isinstance(plan_id,str) and a.ID32.fullmatch(plan_id) and hex64(plan_sha),'arguments_invalid')
        a.private_directory(self.private_root,strict=False);a.private_directory(self.plan_root)
        directory=self.plan_root/plan_id;a.private_directory(directory)
        body=a.private_read(directory/'plan.private.json')
        check(bsha(body)==plan_sha,'plan_hash_mismatch')
        plan=a.parse_json(body);now=self.clock()
        check(isinstance(plan,dict) and type(plan.get('schema')) is int and plan['schema']==1 and plan.get('plan_id')==plan_id and
              type(plan.get('prepared_at')) is int and finite(now) and 0<=now-plan['prepared_at']<=7200 and
              plan.get('production_mutated') is False,'plan_invalid_or_expired')
        allocation_bytes=(self.sibling/'allocation.json').read_bytes();allocation=a.parse_json(allocation_bytes)
        check(bsha(allocation_bytes)==a.ALLOCATION_BYTES_SHA and digest(allocation)==plan.get('allocation_sha256'),'allocation_drift')
        approved_bytes=a.private_read(self.private_root/'approved.private')
        manifest_bytes=a.private_read(self.private_root/'manifest.private')
        check(bsha(approved_bytes)==plan.get('approved_file_sha256'),'approved_drift')
        check(bsha(manifest_bytes)==plan.get('manifest_file_sha256'),'manifest_drift')
        approved=a.parse_json(approved_bytes);manifest=a.parse_json(manifest_bytes)
        scopes,approvals=a.validate_scope(allocation,approved,manifest)
        planned=a.rows_by_key(plan.get('routes'))
        check(all(planned[key].get('approved')==approvals[key] for key in a.KEYS),'approved_row_drift')
        baseline={'machine_id':21,'routes':[planned[key]['snapshot'] for key in sorted(a.KEYS)]}
        hashes=a.snapshot_hashes(self.prepare,allocation,approved,baseline)
        return {'directory':directory,'body':body,'plan':plan,'allocation':allocation,'approved':approved,'approved_bytes':approved_bytes,
                'manifest_bytes':manifest_bytes,'scopes':scopes,'approvals':approvals,'planned':planned,'state_hashes':hashes}

    def current(self,bound,fetch=True):
        now=self.clock();plan=bound['plan']
        check(finite(now) and 0<=now-plan['prepared_at']<=7200,'plan_invalid_or_expired')
        result=None
        if fetch:
            try:proxies,usage=self.fetch()
            except Exception:fail('source_fetch_failed')
            a.validate_usage(usage,self.clock())
            check(isinstance(proxies,list),'source_invalid')
            result={}
            for key,old in bound['approvals'].items():
                matches=[row for row in proxies if isinstance(row,dict) and row.get('name')==old['source_name']]
                check(len(matches)==1,'source_missing_or_ambiguous')
                source=matches[0]
                check(self.guard.fingerprint(source)==old['source_sha256'] and digest(source)==digest(bound['planned'][key].get('source')),'source_fingerprint_drift')
                check(source.get('type')==bound['scopes'][key]['upstream_type'],'source_protocol_changed')
                result[key]=source
        # Read actual state after the network operation, then recheck every
        # private binding immediately before returning to the publication step.
        now=self.clock()
        check(finite(now) and 0<=now-plan['prepared_at']<=7200,'plan_invalid_or_expired')
        actual=self.snapshot(bound['allocation'],bound['manifest_bytes'])
        check(a.snapshot_hashes(self.prepare,bound['allocation'],bound['approved'],actual)==bound['state_hashes'],'database_state_drift')
        check(a.private_read(bound['directory']/'plan.private.json')==bound['body'],'plan_hash_mismatch')
        check(a.private_read(self.private_root/'approved.private')==bound['approved_bytes'],'approved_drift')
        check(a.private_read(self.private_root/'manifest.private')==bound['manifest_bytes'],'manifest_drift')
        if fetch:a.validate_usage(usage,self.clock())
        return result

    def run(self,operation,plan_id,plan_sha,payload=None):
        global STAGE
        check(operation in ('recipient','import'),'arguments_invalid')
        bound=self.load(plan_id,plan_sha)
        with a.lock(self.plan_root/'scope-restore.lock'):
            with a.lock(bound['directory']/'maintenance.lock'):
                # Re-read after acquiring the common maintenance/metadata locks.
                bound=self.load(plan_id,plan_sha)
                STAGE='recipient' if operation=='recipient' else 'import_binding'
                if operation=='recipient':return self.recipient(bound,plan_id,plan_sha)
                return self.import_payload(bound,plan_id,plan_sha,payload)

    def recipient(self,bound,plan_id,plan_sha):
        folder=bound['directory']/'reviewed-recipient'
        a.private_directory(folder,create=True)
        key_path=folder/'recipient.private.pem';binding_path=folder/'binding.private.json'
        if list(folder.iterdir()):
            check(os.path.lexists(key_path) and os.path.lexists(binding_path),'recipient_incomplete')
            binding=a.parse_json(a.private_read(binding_path));public=public_from_key(a.private_read(key_path))
            check(binding=={'schema':1,'plan_id':plan_id,'plan_sha256':plan_sha,'public_key_sha256':bsha(public)},'recipient_binding_invalid')
        else:
            private=openssl(['genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:4096'])
            public=public_from_key(private)
            a.private_write(key_path,private)
            a.private_write(binding_path,canon({'schema':1,'plan_id':plan_id,'plan_sha256':plan_sha,'public_key_sha256':bsha(public)}))
            a.sync_directory(folder);a.sync_directory(bound['directory'])
        return {'status':'recipient_ready','schema':1,'plan_id':plan_id,'plan_sha256':plan_sha,
                'public_key_pem_base64':base64.b64encode(public).decode(),'public_key_sha256':bsha(public),
                'algorithm':'RSA-4096-OAEP-SHA256','production_mutated':False,'source_baseline_mutated':False,'public_key_baseline_mutated':False}

    def decrypt(self,key_path,ciphertext):
        a.private_read(key_path)
        plain=openssl(['pkeyutl','-decrypt','-inkey',str(key_path),'-pkeyopt','rsa_padding_mode:oaep',
                       '-pkeyopt','rsa_oaep_md:sha256','-pkeyopt','rsa_mgf1_md:sha256'],decode64(ciphertext,512))
        check(0<len(plain)<=446,'plaintext_size_invalid')
        return a.parse_json(plain)

    def candidate(self,row,identity,bound,source,now):
        exact(identity,('key','ip','port','sni','pin'))
        key=row['key'];scope=bound['scopes'][key];original=bound['planned'][key]['snapshot']['state']
        check(identity['key']==key and digest(identity)==row['candidate_digest'],'candidate_digest_mismatch')
        try:
            address=ipaddress.ip_address(identity['ip'])
            check(isinstance(identity['ip'],str) and address.is_global and not address.is_multicast and not address.is_reserved,'non_global_ip')
            settings=self.prepare.settings_for({'backend':original['backend']},scope['upstream_type'])
            ca=scope['upstream_type']=='vless'
            target=self.prepare.source_target_ca(source,settings) if ca else self.prepare.source_target(source,settings)
            _,port,sni,pins,current_ip,*_=target
            check(type(identity['port']) is int and identity['port']==port and identity['sni']==sni,'candidate_contract_invalid')
            pin=decode64(identity['pin'],32)
            check(base64.b64encode(pin).decode()==identity['pin'],'invalid_pin')
            check(ca or len(pins)==1,'pin_shape_invalid')
            try:literal=ipaddress.ip_address(source['server'])
            except ValueError:literal=None
            check(literal is None or address==literal,'source_literal_ip_mismatch')
        except (ImportErrorBounded,a.AcceptanceError):raise
        except Exception:fail('candidate_contract_invalid')
        before,after=row['not_before'],row['not_after']
        check(finite(before) and finite(after) and before<=now<=after,'certificate_time_invalid')
        witness_contract(row['witnesses'],row['candidate_digest'],now,before,after,ca,literal is None)
        # These fields retain the existing maintenance candidate contract. The
        # added provenance makes clear that DNS/CA were witnessed externally.
        result={'identity':identity,'candidate_digest':row['candidate_digest'],'pin':identity['pin'],
                'not_before':before,'not_after':after,'certificate_time_valid':True,
                'old_pin_matches':identity['pin'] in pins,'current_endpoint':current_ip is not None and address==ipaddress.ip_address(current_ip),
                'source_dns_endpoint':True,'source_dns_observation_point':'entry' if literal is None else 'source_literal',
                'panel_dns_observed':False,'candidate_origin':'manual_external_witnesses','manual_selection_required':True,
                'external_witnesses':copy.deepcopy(row['witnesses'])}
        if ca:result.update(ca_validated=True,ca_validation_observation_point='external_witnesses')
        return result

    def import_payload(self,bound,plan_id,plan_sha,raw):
        global STAGE
        payload=payload_envelope(raw,plan_id,plan_sha)
        folder=bound['directory']/'reviewed-recipient';a.private_directory(folder)
        binding=a.parse_json(a.private_read(folder/'binding.private.json'))
        public=public_from_key(a.private_read(folder/'recipient.private.pem'))
        check(binding=={'schema':1,'plan_id':plan_id,'plan_sha256':plan_sha,'public_key_sha256':bsha(public)} and payload['recipient_sha256']==bsha(public),'recipient_binding_invalid')
        rows=payload['rows']
        commitment=digest(payload)
        evidence_commitment=digest({'schema':1,'plan_id':plan_id,'plan_sha256':plan_sha,'recipient_sha256':payload['recipient_sha256'],
            'rows':sorted([{k:v for k,v in row.items() if k!='ciphertext'} for row in rows],key=lambda row:row['key'])})
        imports=bound['directory']/'reviewed-imports';a.private_directory(imports,create=True)
        record=imports/evidence_commitment;a.private_directory(record,create=True)
        check(not list(record.iterdir()),'payload_already_recorded')
        STAGE='fresh_source_and_state'
        sources=self.current(bound)
        updated=copy.deepcopy(bound['plan']);new_rows=a.rows_by_key(updated['routes'])
        report=[]
        for row in rows:
            STAGE='decrypt_and_validate'
            identity=self.decrypt(folder/'recipient.private.pem',row['ciphertext'])
            candidate=self.candidate(row,identity,bound,sources[row['key']],self.clock())
            current=new_rows[row['key']].get('candidates')
            check(isinstance(current,list) and not any(c.get('candidate_digest')==row['candidate_digest'] for c in current),'candidate_already_present')
            current.append(candidate)
            report.append({'key':row['key'],'candidate_digest':row['candidate_digest'],'candidate_origin':'manual_external_witnesses',
                           'source_dns_observation_point':candidate['source_dns_observation_point'],'panel_dns_observed':False,
                           'old_pin_matches':candidate['old_pin_matches'],'ca_validated':candidate.get('ca_validated',False)})
        STAGE='final_state_and_source'
        self.current(bound)  # Includes a second fresh all-41 metadata validation.
        now=self.clock()
        for row in rows:
            check(row['not_before']<=now<=row['not_after'],'certificate_time_invalid')
            for witness in row['witnesses'].values():check(now-7200<=witness['observed_at']<=now+60,'witness_time_invalid')
        new_id=uuid.uuid4().hex
        updated['plan_id']=new_id
        updated['reviewed_import']={'schema':1,'parent_plan_id':plan_id,'parent_plan_sha256':plan_sha,'payload_sha256':commitment,
                                    'recipient_sha256':bsha(public),'evidence_commitment_sha256':evidence_commitment,'imported_at':now,'manual_selection_required':True}
        # Keep prepared_at and all original snapshots/source/approval bindings:
        # imported evidence does not extend the lifetime of the old observations.
        updated['trust_status']='candidate_observations_only_not_approved'
        new_body=canon(updated);new_sha=bsha(new_body)
        a.private_write(record/'ciphertext-control.private.json',raw)
        intent={'schema':1,'parent_plan_id':plan_id,'parent_plan_sha256':plan_sha,'payload_sha256':commitment,
                'new_plan_id':new_id,'new_plan_sha256':new_sha,'evidence_commitment_sha256':evidence_commitment,'at':now}
        a.private_write(record/'intent.private.json',canon(intent));a.sync_directory(record)
        try:
            STAGE='new_private_plan'
            target=self.plan_root/new_id;target.mkdir(mode=0o700)
            a.private_write(target/'plan.private.json',new_body);a.sync_directory(target);a.sync_directory(self.plan_root)
            check(a.private_read(target/'plan.private.json')==new_body,'new_plan_readback_failed')
            result={'status':'reviewed_candidates_imported','schema':1,'parent_plan_id':plan_id,'parent_plan_sha256':plan_sha,
                    'plan_id':new_id,'plan_sha256':new_sha,'payload_sha256':commitment,'evidence_commitment_sha256':evidence_commitment,'routes':sorted(report,key=lambda r:r['key']),
                    'manual_selection_required':True,'source_baseline_mutated':False,'public_key_baseline_mutated':False,
                    'database_mutated':False,'original_plan_mutated':False,'production_mutated':False,'prepared_at_preserved':True}
            a.private_write(record/'receipt.private.json',canon({'schema':1,'request_sha256':commitment,'result':result,'at':self.clock()}));a.sync_directory(record)
        except Exception:fail('import_outcome_unknown')
        return result

class SafeParser(argparse.ArgumentParser):
    def error(self,message):fail('arguments_invalid')

def main(argv=None):
    parser=SafeParser(description=__doc__)
    parser.add_argument('operation',choices=('recipient','import'))
    parser.add_argument('--plan-id',required=True);parser.add_argument('--plan-sha256',required=True)
    args=parser.parse_args(argv)
    check(os.geteuid()==0,'root_required');os.umask(0o077)
    import sys
    payload=sys.stdin.buffer.read(MAX_PAYLOAD+1) if args.operation=='import' else None
    result=Driver().run(args.operation,args.plan_id,args.plan_sha256,payload)
    print(json.dumps(result,sort_keys=True),flush=True)
    return 0

def safe_main(argv=None):
    try:return main(argv)
    except (ImportErrorBounded,a.AcceptanceError) as error:
        print(json.dumps({'status':'rejected','reason':str(error),'stage':STAGE}),flush=True);return 1
    except Exception:
        print(json.dumps({'status':'rejected','reason':'reviewed_import_failed','stage':STAGE}),flush=True);return 1

if __name__=='__main__':raise SystemExit(safe_main())
