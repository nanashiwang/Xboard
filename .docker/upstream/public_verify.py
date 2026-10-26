#!/usr/bin/env python3
"""Restricted public-path snapshot and verification. No apply/report/reopen operation."""
import argparse
import base64
import concurrent.futures
import copy
import errno
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid

AGENT = Path('/etc/xboard-extension-probe/agent.json')
PLAN_ROOT = Path('/root/xboard-upstream-recovery')
APP_ROOT = Path('/root/Xboard')
SIBLING = Path(__file__).resolve().parent
BINARY_PATHS = ('/usr/local/bin/sing-box', '/usr/bin/sing-box', '/opt/xboard-node-probe/sing-box',
                '/root/Xboard/backups/fleet-20261017/sing-box')
ENTRY = 'node.lumavia.fyi'
KEYS = {'U%02d' % n for n in range(1,42)}
TARGETS = {'cloudflare': ('https://www.cloudflare.com/cdn-cgi/trace', 200),
           'google': ('https://www.gstatic.com/generate_204', 204)}
STAGE = 'arguments'
STOP = threading.Event()

class ContractError(Exception):
    pass

class BinaryNotFound(ContractError):
    pass

class RandomFingerprintUnsupported(ContractError):
    pass

def check(condition):
    if not condition:
        raise ContractError()

def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def clean_env():
    return {k:v for k,v in os.environ.items() if k.lower() not in ('http_proxy','https_proxy','all_proxy','no_proxy')}

def load_json(raw):
    def pairs(items):
        value={}
        for key,item in items:
            check(key not in value)
            value[key]=item
        return value
    return json.loads(raw, object_pairs_hook=pairs,parse_constant=lambda _:check(False))

def private_bytes(path):
    status=path.lstat()
    check(stat.S_ISREG(status.st_mode) and status.st_uid==os.geteuid() and not status.st_mode&0o077 and status.st_size<=20*1024*1024)
    return path.read_bytes()

def private_directory(path):
    status=path.lstat()
    check(stat.S_ISDIR(status.st_mode) and status.st_uid==os.geteuid() and not status.st_mode&0o077)

def indexed(rows, field='key'):
    check(isinstance(rows,list))
    result={}
    for row in rows:
        check(isinstance(row,dict) and row.get(field) not in result)
        result[row[field]]=row
    return result

def allocation():
    value=load_json((SIBLING/'allocation.json').read_bytes())
    rows=indexed(value.get('routes'))
    check(value.get('machine_id')==21 and set(rows)==KEYS)
    ids=[]
    for key,row in rows.items():
        n=int(key[1:])
        check(row.get('public_id')==358+2*n and row.get('backend_id')==357+2*n and row.get('port')==37000+n)
        ids.extend((row['public_id'],row['backend_id']))
    check(len(set(ids))==82)
    return value,rows

def plan_contract(plan_id,plan_sha,alloc):
    check(re.fullmatch('[a-f0-9]{32}',plan_id) and re.fullmatch('[a-f0-9]{64}',plan_sha))
    private_directory(PLAN_ROOT)
    directory=PLAN_ROOT/plan_id
    private_directory(directory)
    raw=private_bytes(directory/'plan.private.json')
    check(hashlib.sha256(raw).hexdigest()==plan_sha)
    plan=load_json(raw)
    check(plan.get('plan_id')==plan_id and plan.get('allocation_sha256')==digest(alloc))
    rows=indexed(plan.get('routes'))
    check(set(rows)==KEYS)
    for expected in alloc['routes']:
        current=rows[expected['key']]['snapshot']
        check(current['public']['id']==expected['public_id'] and current['backend']['id']==expected['backend_id'])
    return directory,plan

def agent_settings():
    settings=load_json(private_bytes(AGENT))
    check(set(settings)=={'panel_url','token'} and isinstance(settings['token'],str) and len(settings['token'])==64)
    parsed=urllib.parse.urlsplit(settings['panel_url'])
    check(parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password and
          not parsed.query and not parsed.fragment and parsed.path in ('','/') and parsed.port in (None,443))
    return settings

def scope(settings,alloc):
    payload=base64.b64encode(canonical({'token':settings['token'],'allocation':alloc})).decode()
    source=(SIBLING/'probe-scope.php').read_text()
    check(source.count('__INPUT_BASE64__')==1)
    source=source.replace('__INPUT_BASE64__',payload)
    result=subprocess.run(['docker','compose','exec','-T','xboard','php'],cwd=APP_ROOT,
                          input=source.encode(),capture_output=True,timeout=25,env=clean_env())
    value=load_json(result.stdout)
    if value.get('reason')=='probe_random_fingerprint_not_repeatable':
        raise RandomFingerprintUnsupported()
    check(result.returncode==0)
    check(value.get('scope_valid') is True and value.get('probe_id')==2)
    rows=indexed(value.get('routes'))
    check(set(rows)==KEYS)
    for expected in alloc['routes']:
        actual=rows[expected['key']]
        check(all(actual.get(k)==expected[k] for k in ('public_id','backend_id')))
        check(type(actual.get('show')) is bool and type(actual.get('enabled')) is bool and
              re.fullmatch('[a-f0-9]{64}',actual.get('public_config_sha256','')) and
              re.fullmatch('[a-f0-9]{64}',actual.get('state_sha256','')))
    return rows

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def fetch_public(settings):
    url=settings['panel_url'].rstrip('/')+'/api/v2/probe/config'
    request=urllib.request.Request(url,data=b'{"agent_version":"recovery-public-verify-v1"}',
        headers={'Authorization':'Bearer '+settings['token'],'Content-Type':'application/json',
                 'Accept':'application/json','User-Agent':'Xboard-Node-Probe/1.1.0'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(request,timeout=20) as response:
        check(response.status==200 and response.geturl()==url)
        raw=response.read(2*1024*1024+1)
        check(len(raw)<=2*1024*1024)
    return load_json(raw)['data']

def outbound_contract(outbound):
    check(isinstance(outbound,dict))
    allowed={'type','tag','server','server_port','uuid','packet_encoding','flow','tls','transport','multiplex'}
    check(not set(outbound)-allowed and outbound.get('type')=='vless' and outbound.get('server')==ENTRY and
          outbound.get('server_port')==443 and outbound.get('tag')=='node')
    check(str(uuid.UUID(outbound.get('uuid','')))==outbound['uuid'].lower())
    tls=outbound.get('tls',{})
    check(isinstance(tls,dict) and not set(tls)-{'enabled','insecure','server_name','utls','alpn'} and
          tls.get('enabled') is True and tls.get('insecure',False) is False and tls.get('server_name',ENTRY)==ENTRY)
    transport=outbound.get('transport',{})
    check(isinstance(transport,dict) and not set(transport)-{'type','path','headers','max_early_data','early_data_header_name'} and
          transport.get('type')=='ws' and isinstance(transport.get('path'),str) and
          transport['path'].startswith('/') and not re.search('[\x00-\x20\x7f]',transport['path']) and len(transport['path'])<=2048)
    headers=transport.get('headers',{})
    check(isinstance(headers,dict) and not set(headers)-{'Host'} and headers.get('Host',ENTRY)==ENTRY)
    check(transport.get('max_early_data',0)==0 and not transport.get('early_data_header_name'))
    return outbound

def public_config(config,scopes,alloc):
    check(config.get('version')==1)
    nodes=indexed(config.get('nodes'),'id')
    check(set(nodes)=={v['public_id'] for v in alloc['routes']})
    rows=[]
    for row in alloc['routes']:
        node=nodes[row['public_id']]
        check(set(node)=={'id','outbound'})
        outbound=outbound_contract(node['outbound'])
        check(digest(outbound)==scopes[row['key']]['public_config_sha256'])
        rows.append({'key':row['key'],'public_id':row['public_id'],'backend_id':row['backend_id'],
                     'outbound':outbound,'public_config_sha256':digest(outbound)})
    return rows

def secure_binary(path):
    resolved=path.resolve(strict=True)
    check(resolved.is_absolute())
    for parent in set((*path.parents,*resolved.parents)):
        value=parent.stat()
        check(stat.S_ISDIR(value.st_mode) and value.st_uid==0 and not value.st_mode&0o022)
    value=resolved.stat()
    check(stat.S_ISREG(value.st_mode) and value.st_uid==0 and not value.st_mode&0o022 and value.st_mode&0o111)
    hasher=hashlib.sha256()
    with resolved.open('rb') as source:
        for chunk in iter(lambda:source.read(1048576),b''):
            hasher.update(chunk)
    return {'path':str(path),'resolved_path':str(resolved),'sha256':hasher.hexdigest()}

def select_binary():
    for name in BINARY_PATHS:
        path=Path(name)
        if path.exists() or path.is_symlink():
            return secure_binary(path)
    return None

def bound_binary(saved):
    check(isinstance(saved,dict) and saved.get('path') in BINARY_PATHS)
    current=secure_binary(Path(saved['path']))
    check(current==saved)
    return current['resolved_path']

def save_exclusive(path,value):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as output:
        output.write(canonical(value))

def snapshot(directory,plan_id,plan_sha,alloc,settings):
    global STAGE
    check(not (directory/'public-cache.private.json').exists())
    STAGE='scope_before_snapshot'
    before=scope(settings,alloc)
    check(all(r['show'] and r['enabled'] for r in before.values()))
    STAGE='probe_config'
    rows=public_config(fetch_public(settings),before,alloc)
    STAGE='scope_after_snapshot'
    check(scope(settings,alloc)==before)
    STAGE='binary_selection'
    binary=select_binary()
    if binary is None:
        raise BinaryNotFound()
    cache={'schema':1,'plan_id':plan_id,'plan_sha256':plan_sha,'allocation_sha256':digest(alloc),
           'probe_id':2,'token_sha256':hashlib.sha256(settings['token'].encode()).hexdigest(),
           'created_at':int(time.time()),'binary':binary,'routes':rows,'scope_at_snapshot':before}
    STAGE='private_cache_storage'
    check(not STOP.is_set())
    save_exclusive(directory/'public-cache.private.json',cache)
    return {'status':'snapshotted','plan_id':plan_id,'plan_sha256':plan_sha,'cache_sha256':digest(cache),
            'routes':len(rows),'binary_status':'bound',
            'binary_sha256':binary['sha256'],
            'route_commitments':[{'key':r['key'],'public_config_sha256':r['public_config_sha256']} for r in rows],
            'probe_heartbeat_updated':True,'node_configuration_mutated':False}

def cache_contract(cache,plan_id,plan_sha,alloc,settings):
    check(cache.get('schema')==1 and cache.get('plan_id')==plan_id and cache.get('plan_sha256')==plan_sha and
          cache.get('allocation_sha256')==digest(alloc) and cache.get('probe_id')==2 and
          cache.get('token_sha256')==hashlib.sha256(settings['token'].encode()).hexdigest())
    rows=indexed(cache.get('routes'))
    check(set(rows)==KEYS)
    for expected in alloc['routes']:
        row=rows[expected['key']]
        check(all(row.get(k)==expected[k] for k in ('public_id','backend_id')))
        check(digest(outbound_contract(row['outbound']))==row.get('public_config_sha256'))
    return rows

def validate_selected(requested):
    check(isinstance(requested,list) and requested and len(requested)==len(set(requested)) and set(requested)<=KEYS)
    return sorted(requested)

def verify_scope(rows,current,selected,expect,expected_states):
    for key in selected:
        state=current[key]
        check(state['public_config_sha256']==rows[key]['public_config_sha256'])
        check(state['state_sha256']==expected_states[key])
        if expect=='success':
            check(state['enabled'])
        else:
            check(not state['enabled'] and not state['show'])

def exact(value,fields):
    check(isinstance(value,dict) and set(value)==set(fields))

def timestamp(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0

def original_selection(row,planned,allocation):
    identity=row.get('identity')
    check(row.get('candidate_digest')==digest(identity))
    if identity is None:
        return None
    exact(identity,('key','ip','port','sni','pin'))
    check(identity['key']==row['key'])
    matches=[]
    for candidate in planned.get('candidates',[]):
        observed=candidate.get('identity')
        if not isinstance(observed,dict):
            continue
        exact(observed,('key','ip','port','sni','pin'))
        check(candidate.get('candidate_digest')==digest(observed))
        normalized=dict(observed,pin=None) if allocation['upstream_type']=='vless' else observed
        if normalized==identity:
            matches.append(candidate['candidate_digest'])
    check(len(matches)==1)
    return matches[0]

def closed_state_hash(original):
    value=copy.deepcopy(original)
    check(isinstance(value,dict) and set(value)=={'backend','public'} and
          isinstance(value['backend'].get('custom_outbounds'),str))
    for section,field in (('backend','enabled'),('public','show')):
        flag=value[section].get(field)
        check(type(flag) in (int,bool) and flag in (0,1,False,True))
        value[section][field]=False if type(flag) is bool else 0
    return digest(value)

def receipt_binding(directory,execution_id,plan_id,plan_sha,plan,alloc,selected,expect):
    check(isinstance(execution_id,str) and re.fullmatch('[a-f0-9]{64}',execution_id))
    folder=directory/('maintenance-'+execution_id)
    private_directory(folder)
    known={kind+'-'+action+'.private.json' for kind in ('intent','receipt') for action in ('withdraw','apply_hidden','publish','rollback')}
    check(all(path.name in known for path in folder.iterdir() if path.name.startswith(('intent-','receipt-'))))
    allocations=indexed(alloc['routes'])
    planned=indexed(plan['routes'])
    phases=[]
    chain=[]
    previous=None
    selection_hash=None
    for action in ('withdraw','apply_hidden','publish','rollback'):
        intent_path=folder/('intent-'+action+'.private.json')
        receipt_path=folder/('receipt-'+action+'.private.json')
        request_path=folder/('request-'+action+'.private.json')
        intent_exists=intent_path.exists() or intent_path.is_symlink()
        receipt_exists=receipt_path.exists() or receipt_path.is_symlink()
        check(not intent_exists or receipt_exists)
        if not receipt_exists:
            continue
        check(intent_exists)
        receipt_raw=private_bytes(receipt_path)
        saved=load_json(receipt_raw)
        exact(saved,('schema','prepare_plan_id','prepare_plan_sha256','selection_sha256','response','at'))
        check(saved['schema']==1 and saved['prepare_plan_id']==plan_id and saved['prepare_plan_sha256']==plan_sha and timestamp(saved['at']))
        intent=load_json(private_bytes(intent_path))
        exact(intent,('schema','request_sha256','at'))
        request=load_json(private_bytes(request_path))
        exact(request,('schema','action','plan_id','routes'))
        check(intent['schema']==1 and timestamp(intent['at']) and intent['request_sha256']==digest(request))
        check(request['schema']==1 and request['action']==action and request['plan_id']==execution_id)
        requested=indexed(request['routes'])
        check(requested and set(requested)<=KEYS)
        check(previous is None or set(requested)==set(previous))
        selection={}
        bound=[]
        for key in sorted(requested):
            row=requested[key]
            check(all(row.get(field)==allocations[key][field] for field in ('public_id','backend_id')))
            original=planned[key]['snapshot']['state_sha256']
            check(re.fullmatch('[a-f0-9]{64}',original) and row.get('original_state_sha256')==original and digest(row.get('original_state'))==original)
            candidate=row.get('candidate_digest')
            check(isinstance(candidate,str) and re.fullmatch('[a-f0-9]{64}',candidate))
            selection[key]=original_selection(row,planned[key],allocations[key])
            bound.append({field:row[field] for field in ('key','backend_id','public_id','original_state_sha256','candidate_digest')})
            check(row.get('expected_sha256')==(previous[key] if previous is not None else original))
        check(digest({'schema':1,'machine_id':21,'routes':bound})==execution_id)
        check(saved['selection_sha256']==digest(selection))
        if selection_hash is not None:
            check(selection_hash==saved['selection_sha256'])
        selection_hash=saved['selection_sha256']
        response=saved['response']
        exact(response,('schema','action','plan_id','routes'))
        check(response['schema']==1 and response['action']==action and response['plan_id']==execution_id)
        responses=indexed(response['routes'])
        check(set(responses)==set(requested) and (previous is None or set(responses)==set(previous)))
        for key,row in responses.items():
            exact(row,('key','backend_id','public_id','state_sha256'))
            check(all(row[field]==allocations[key][field] for field in ('public_id','backend_id')) and
                  isinstance(row['state_sha256'],str) and re.fullmatch('[a-f0-9]{64}',row['state_sha256']))
            if action in ('withdraw','rollback'):
                check(row['state_sha256']==closed_state_hash(requested[key]['original_state']))
        previous={key:row['state_sha256'] for key,row in responses.items()}
        phases.append(action)
        chain.append({'action':action,'receipt_sha256':hashlib.sha256(receipt_raw).hexdigest(),'request_sha256':digest(request)})
    check(phases in (['withdraw'],['withdraw','apply_hidden'],['withdraw','apply_hidden','publish'],
                    ['withdraw','rollback'],['withdraw','apply_hidden','rollback'],['withdraw','apply_hidden','publish','rollback']))
    check((expect=='withdrawn' and phases[-1] in ('withdraw','rollback')) or (expect=='success' and phases[-1] in ('apply_hidden','publish')))
    check(set(selected)<=set(previous))
    return {'execution_plan_id':execution_id,'phase':phases[-1],'state_hashes':previous,
            'selection_sha256':selection_hash,'receipt_chain_sha256':digest(chain)}

def baseline_binding(plan,selected):
    planned=indexed(plan.get('routes'))
    check(set(planned)==KEYS and set(selected)<=set(planned))
    hashes={}
    for key in selected:
        snapshot=planned[key]['snapshot']
        check(isinstance(snapshot.get('state'),dict) and snapshot.get('state_sha256')==digest(snapshot['state']))
        hashes[key]=snapshot['state_sha256']
    return {'execution_plan_id':None,'phase':'prepared_baseline','state_hashes':hashes,
            'selection_sha256':None,'receipt_chain_sha256':None}

def runtime(outbound,port):
    outbound_contract(outbound)
    return {'log':{'level':'error','timestamp':False},'dns':{'servers':[{'type':'local','tag':'local'}]},
            'inbounds':[{'type':'socks','listen':'127.0.0.1','listen_port':port}],
            'outbounds':[copy.deepcopy(outbound)],'route':{'final':'node','default_domain_resolver':'local'}}

def log_class(log):
    patterns=[('public_key_rejection','unrecognized remote public key'),('certificate_error','x509:|certificate verify'),
              ('authentication_error','authentication failed|unauthorized|invalid user'),
              ('websocket_rejected','websocket.*bad handshake|bad handshake'),
              ('dns_error','no such host|name resolution'),('network_unreachable','network is unreachable|no route to host'),
              ('connection_refused','connection refused'),('timeout','i/o timeout|deadline exceeded|timed out')]
    for name,pattern in patterns:
        if re.search(pattern,log.lower()):
            return name
    return 'proxy_request_failed'

def check_target(port,target,folder):
    if STOP.is_set():
        return {'target':target,'success':False,'runner_valid':False,'classification':'cancelled'}
    url,status=TARGETS[target]
    body=folder/(target+'.body')
    args=['curl','-q','--silent','--show-error','--proxy','socks5h://127.0.0.1:'+str(port),'--noproxy','',
          '--proto','=https','--connect-timeout','5','--max-time','15','--max-filesize','65536',
          '--output',str(body),'--write-out','%{http_code} %{time_total} %{time_connect} %{remote_ip} %{remote_port}',url]
    try:
        result=subprocess.run(args,capture_output=True,timeout=18,env=clean_env())
        fields=result.stdout.decode(errors='replace').strip().split()
        valid_metrics=(len(fields)==5 and re.fullmatch('[0-9]{3}',fields[0]) and
                       re.fullmatch('[0-9]+(?:\.[0-9]+)?',fields[1]) and
                       re.fullmatch('[0-9]+(?:\.[0-9]+)?',fields[2]) and
                       fields[3]=='127.0.0.1' and fields[4]==str(port))
        runner_valid=bool(valid_metrics and float(fields[2])>0 and
                           result.returncode in (0,18,28,35,52,55,56,60,63,92,95,97))
        code=int(fields[0]) if valid_metrics else 0
        elapsed=float(fields[1]) if valid_metrics else None
        good=runner_valid and result.returncode==0 and code==status
        exit_hash=None
        if good and target=='cloudflare':
            values=[line[3:] for line in body.read_text(errors='replace').splitlines() if line.startswith('ip=')]
            try:
                check(len(values)==1)
                exit_hash=hashlib.sha256(str(ipaddress.ip_address(values[0])).encode()).hexdigest()
            except (ValueError,ContractError):
                good=False
        return {'target':target,'success':good,'runner_valid':runner_valid,'http_status':code,'curl_exit':result.returncode,
                'seconds':elapsed,'exit_ip_sha256':exit_hash,
                'proxy_path_usable':bool(runner_valid and result.returncode==0 and 100<=code<=599)}
    except subprocess.TimeoutExpired:
        return {'target':target,'success':False,'runner_valid':False,'classification':'runner_timeout'}

def remaining(deadline):
    if STOP.is_set():
        raise InterruptedError()
    value=deadline-time.monotonic()
    if value<=0:
        raise TimeoutError()
    return value

def wait_socket(stream,reading,deadline):
    while True:
        budget=min(.1,remaining(deadline))
        reads,writes,errors=select.select([stream] if reading else [],[] if reading else [stream],[stream],budget)
        if errors:
            raise OSError()
        if reads or writes:
            return

def resolve_entry(deadline):
    # getaddrinfo has no Python deadline; keep it in a bounded, disposable child.
    source='''import json,socket,sys
try:
 host=json.load(sys.stdin)
 answers=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
 print(json.dumps(sorted({r[4][0] for r in answers if r[0] in (socket.AF_INET,socket.AF_INET6)})))
except Exception:sys.exit(1)
'''
    process=None
    try:
        remaining(deadline)
        process=subprocess.Popen([sys.executable,'-c',source],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,env=clean_env())
        payload=canonical(ENTRY)
        while True:
            try:
                stdout,_=process.communicate(input=payload,timeout=min(.1,remaining(deadline)))
                break
            except subprocess.TimeoutExpired:
                payload=None
        remaining(deadline)
        if process.returncode or len(stdout)>65536:
            raise OSError()
        values=load_json(stdout)
        if not isinstance(values,list) or not 1<=len(values)<=64:
            raise OSError()
        addresses=[]
        for value in values:
            ip=ipaddress.ip_address(value)
            if not ip.is_global or ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_reserved:
                raise OSError()
            addresses.append(str(ip))
        return addresses
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=1)

def connect_entry(addresses,deadline):
    for address in addresses:
        remaining(deadline)
        raw=socket.socket(socket.AF_INET6 if ipaddress.ip_address(address).version==6 else socket.AF_INET,socket.SOCK_STREAM)
        try:
            raw.setblocking(False)
            code=raw.connect_ex((address,443))
            if code not in (0,errno.EINPROGRESS,errno.EWOULDBLOCK,errno.EALREADY):
                raise OSError(code,'entry_connect_failed')
            if code:
                wait_socket(raw,False,deadline)
                if raw.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR):
                    raise OSError()
            return raw
        except (InterruptedError,TimeoutError):
            raw.close()
            raise
        except OSError:
            raw.close()
    raise OSError()

def tls_action(action,stream,deadline):
    while True:
        remaining(deadline)
        try:
            value=action()
            remaining(deadline)
            return value
        except ssl.SSLWantReadError:
            wait_socket(stream,True,deadline)
        except ssl.SSLWantWriteError:
            wait_socket(stream,False,deadline)

def first_hop(outbound):
    # Diagnostic only; never used as an HTTPS target or as a traffic fallback.
    # Sends a WS upgrade without a VLESS identity or proxy application payload.
    report={'tls_verified':False,'http_status':None,'classification':'entry_unconfirmed'}
    deadline=time.monotonic()+6
    try:
        nonce=base64.b64encode(os.urandom(16)).decode()
        request=('GET '+outbound['transport']['path']+' HTTP/1.1\r\nHost: '+ENTRY+
                 '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: '+nonce+'\r\n\r\n').encode()
        addresses=resolve_entry(deadline)
        with connect_entry(addresses,deadline) as raw:
            remaining(deadline)
            with ssl.create_default_context().wrap_socket(raw,server_hostname=ENTRY,do_handshake_on_connect=False) as stream:
                tls_action(stream.do_handshake,stream,deadline)
                report['tls_verified']=True
                sent=0
                while sent<len(request):
                    count=tls_action(lambda:stream.send(request[sent:]),stream,deadline)
                    if not count:
                        raise OSError()
                    sent+=count
                data=b''
                while b'\r\n\r\n' not in data and len(data)<4096:
                    value=tls_action(lambda:stream.recv(min(1024,4096-len(data))),stream,deadline)
                    if not value:break
                    data+=value
                remaining(deadline)
        found=re.match(rb'HTTP/1\.[01] ([0-9]{3})(?: |\r)',data)
        code=int(found.group(1)) if found else None
        report.update(http_status=code,classification='public_path_rejected' if code in (404,410,502,503) else
                      'websocket_open' if code==101 else 'entry_response_unconfirmed')
    except ssl.SSLCertVerificationError:
        report['classification']='entry_certificate_error'
    except InterruptedError:
        report['classification']='cancelled'
    except TimeoutError:
        report['classification']='entry_deadline_exceeded'
    except (OSError,ValueError):
        pass
    return report

def verdict(expect,checks,hop,classification):
    passed=sum(v.get('success') is True for v in checks)
    if expect=='success':
        return ('passed','both_targets_passed') if len(checks)==2 and passed==2 else ('failed',classification)
    if passed or any(v.get('proxy_path_usable') is True for v in checks):
        return 'failed','cached_path_still_usable'
    if len(checks)==2 and all(v.get('runner_valid') is True and v.get('curl_exit') in (52,55,56,97) for v in checks) and hop and hop.get('tls_verified') is True and hop.get('classification')=='public_path_rejected':
        return 'passed','withdrawal_observed'
    return 'inconclusive','withdrawal_not_proven'

def measure(row,binary,expect):
    result={'key':row['key'],'public_config_sha256':row['public_config_sha256'],'checks':[],'status':'failed'}
    if STOP.is_set():
        return dict(result,classification='cancelled',temporary_process_terminated=True,temporary_directory_removed=True)
    process=None
    classification='isolated_core_failed'
    hop=first_hop(row['outbound']) if expect=='withdrawn' else None
    with tempfile.TemporaryDirectory(prefix='xboard-public-verify-') as dirname:
        folder=Path(dirname)
        try:
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
            path=folder/'core.json';path.write_bytes(canonical(runtime(row['outbound'],port)));path.chmod(0o600)
            checked=subprocess.run([binary,'check','-c',str(path)],capture_output=True,timeout=10,env=clean_env())
            check(checked.returncode==0)
            with (folder/'core.log').open('wb') as logfile:
                process=subprocess.Popen([binary,'run','-c',str(path)],stdin=subprocess.DEVNULL,
                                         stdout=logfile,stderr=subprocess.STDOUT,env=clean_env())
                ready=False
                for _ in range(50):
                    if process.poll() is not None:break
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.1):ready=True
                        break
                    except OSError:time.sleep(.1)
                check(ready)
                result['checks']=[check_target(port,target,folder) for target in TARGETS]
                classification='https_target_failed'
        except (OSError,ContractError,subprocess.SubprocessError):
            classification='isolated_runner_failed'
        finally:
            if process is not None:
                if process.poll() is None:process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=3)
            if (folder/'core.log').exists():
                log=(folder/'core.log').read_bytes()[-65536:].decode(errors='replace')
                if log:classification=log_class(log)
        result['status'],result['classification']=verdict(expect,result['checks'],hop,classification)
        if hop:result['entry_diagnostic']=hop
        result['temporary_process_terminated']=process is None or process.poll() is not None
    result['temporary_directory_removed']=not folder.exists()
    return result

def verify(directory,plan_id,plan_sha,plan,alloc,settings,selected,expect,execution_id,baseline=False):
    global STAGE
    STAGE='bound_cache'
    cache=load_json(private_bytes(directory/'public-cache.private.json'))
    rows=cache_contract(cache,plan_id,plan_sha,alloc,settings)
    STAGE='prepared_baseline' if baseline else 'maintenance_receipt'
    if baseline:
        check(expect=='success' and execution_id is None)
        binding=baseline_binding(plan,selected)
    else:
        binding=receipt_binding(directory,execution_id,plan_id,plan_sha,plan,alloc,selected,expect)
    STAGE='bound_binary'
    binary=bound_binary(cache.get('binary'))
    STAGE='scope_before_verify'
    before=scope(settings,alloc)
    verify_scope(rows,before,selected,expect,binding['state_hashes'])
    STAGE='public_path_test'
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results=list(executor.map(lambda key:measure(rows[key],binary,expect),selected))
    STAGE='scope_after_verify'
    check(not STOP.is_set())
    after=scope(settings,alloc)
    verify_scope(rows,after,selected,expect,binding['state_hashes'])
    check(all(before[k]==after[k] for k in selected))
    STAGE='binding_after_verify'
    check(hashlib.sha256(private_bytes(directory/'plan.private.json')).hexdigest()==plan_sha)
    if not baseline:
        check(receipt_binding(directory,execution_id,plan_id,plan_sha,plan,alloc,selected,expect)==binding)
    for result in results:
        result['state_sha256']=binding['state_hashes'][result['key']]
    passed=all(r['status']=='passed' and r['temporary_process_terminated'] and r['temporary_directory_removed'] for r in results)
    report={'status':'passed' if passed else 'failed','plan_id':plan_id,'plan_sha256':plan_sha,
            'operation':'baseline' if baseline else 'verify',
            'cache_sha256':digest(cache),'expect':expect,'checked_at':int(time.time()),'routes':results,
            'execution_plan_id':execution_id,'maintenance_phase':binding['phase'],'receipt_chain_sha256':binding['receipt_chain_sha256'],
            'configuration_source':'bound_pre_withdrawal_public_cache','strict_tls':True,'direct_fallback':False,
            'node_configuration_mutated':False,'probe_report_written':False,'fresh_core_per_route':True}
    save_exclusive(directory/('public-verify-'+('baseline' if baseline else expect)+'-'+uuid.uuid4().hex+'.json'),report)
    return report

def main():
    global STAGE
    os.umask(0o077)
    for signum in (signal.SIGTERM,signal.SIGINT):
        signal.signal(signum,lambda *_:STOP.set())
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('snapshot','verify','baseline'))
    parser.add_argument('--plan-id',required=True)
    parser.add_argument('--plan-sha256',required=True)
    parser.add_argument('--key',action='append',default=[])
    parser.add_argument('--expect',choices=('success','withdrawn'))
    parser.add_argument('--execution-plan-id')
    args=parser.parse_args()
    check(os.geteuid()==0)
    check((args.operation=='snapshot' and not args.key and args.expect is None and args.execution_plan_id is None) or
          (args.operation=='verify' and args.key and args.expect is not None and args.execution_plan_id is not None) or
          (args.operation=='baseline' and args.key and args.expect is None and args.execution_plan_id is None))
    STAGE='allocation';alloc,_=allocation()
    STAGE='plan_binding';directory,plan=plan_contract(args.plan_id,args.plan_sha256,alloc)
    STAGE='fixed_agent_settings';settings=agent_settings()
    if args.operation=='snapshot':
        report=snapshot(directory,args.plan_id,args.plan_sha256,alloc,settings)
    else:
        report=verify(directory,args.plan_id,args.plan_sha256,plan,alloc,settings,validate_selected(args.key),
                      'success' if args.operation=='baseline' else args.expect,args.execution_plan_id,args.operation=='baseline')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['status'] in ('passed','snapshotted') else 1

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        reason='binary_not_found' if isinstance(error,BinaryNotFound) else 'probe_random_fingerprint_not_repeatable' if isinstance(error,RandomFingerprintUnsupported) else 'public_verification_failed'
        print(json.dumps({'status':'error','reason':reason,'stage':STAGE,
                          'error_type':type(error).__name__}),flush=True)
        raise SystemExit(1)
