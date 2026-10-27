#!/usr/bin/env python3
"""Explicit fixed-host deployment of the reviewed runtime guard; never change pins."""
import argparse
import base64
import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

import guard
import entry_identity
import prepare

SOURCE = Path(__file__).resolve().parent
PRIVATE = Path('/root/Xboard/backups/upstream-20261022')
RECORD = Path('/root/xboard-runtime-guard-deploy/20261027')
IDENTITY = Path('/etc/xboard-upstream-identity')
DROPIN = Path('/etc/systemd/system/xboard-upstream-guard.service.d/runtime-identity.conf')
SERVICE = 'xboard-upstream-guard.service'
TIMER = 'xboard-upstream-guard.timer'
FILES = ('guard.py','guard-apply.php','allocation.json','entry_identity.py')
OLD = {'guard.py':'56197b13cf36c01135abecd6870deb34b3ddabfdeaaef830814b79926e974bd5',
       'guard-apply.php':'4b8e66a8f137c2bcc7b61f91bb2b3416bd239bad5b2e4c909c0fc6321ea7729a'}
APPROVED = '196083b3072d38ebc0d1cae7fbfeecefa81a1299e6c504cb492145273c6aa6fb'
PINS = 'cdd97606da3a03f128177f075a59802d269da4260baf9e6cf83112eebff1eae8'
CATALOG = '552b6a820def4a1a8c9e7775691205c1dc8a87ed9eeeb7a77943daf02c605769'
KNOWN_HOST = b'143.203.200.5 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL7CW/UfRm5ZOoWtNvObxquMstqJNCVLjbHfxvcpZYTd\n'
OVERRIDE = ('[Service]\nExecStart=\nExecStart=/usr/bin/python3 '+str(PRIVATE/'guard.py')+' --entry-worker\n'
            'Environment=PYTHONDONTWRITEBYTECODE=1\nTimeoutStartSec=180\n').encode()


def require(value, code):
    if not value:raise ValueError(code)


def sha(body):return hashlib.sha256(body).hexdigest()


def read(path, private=True):
    st=path.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and not st.st_mode & (0o077 if private else 0o022)
            and st.st_size <= 5*1024*1024,'unsafe_file')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        data=os.read(fd,5*1024*1024+1)
        after=os.fstat(fd)
        require((st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),'file_drift')
        return data
    finally:os.close(fd)


def directory(path, mode=0o700):
    if not path.exists():path.mkdir(mode=mode)
    st=path.lstat();require(stat.S_ISDIR(st.st_mode) and st.st_uid==0 and not st.st_mode&0o022,'unsafe_directory')


def write(path, data, mode=0o600, absent=False):
    if absent:require(not os.path.lexists(path),'unexpected_existing_file')
    elif os.path.lexists(path):read(path,private=False)
    temporary=path.with_name('.'+path.name+'.runtime-next')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
        os.replace(temporary,path)
        require(read(path,private=False)==data,'write_readback_failed')
    finally:
        if temporary.exists():temporary.unlink()


def run(args, timeout=60, data=None):
    result=subprocess.run(args,input=data,capture_output=True,timeout=timeout)
    require(result.returncode==0,'command_failed')
    return result.stdout


def props(unit):
    raw=run(['systemctl','show',unit,'-p','ActiveState','-p','SubState','-p','Result','-p','ExecMainStatus','-p','TimeoutStartUSec','-p','FragmentPath','-p','DropInPaths'])
    return dict(line.split('=',1) for line in raw.decode().splitlines() if '=' in line)


def inputs():
    approved_bytes=read(PRIVATE/'approved.private');pins_bytes=read(PRIVATE/'pinned.private')
    require(sha(approved_bytes)==APPROVED and sha(pins_bytes)==PINS,'approved_identity_drift')
    catalog=(SOURCE/'allocation.json').read_bytes();require(sha(catalog)==CATALOG,'allocation_drift')
    approved=json.loads(approved_bytes);mappings=json.loads(pins_bytes);allocation=json.loads(catalog)
    manifest=guard.private_manifest(PRIVATE)
    snapshot=prepare.snapshot_database(allocation,entry_identity.encode(manifest))
    scope,approved_rows,rows=prepare.validate_scope(allocation,approved,snapshot)
    anytls={k for k,r in scope.items() if r['upstream_type']=='anytls'}
    mapped=prepare.unique(mappings);require(set(mapped)==anytls and len(anytls)==28,'pin_scope_invalid')
    for key in anytls:
        settings=prepare.settings_for(rows[key],'anytls');tls=settings.get('tls',{});m=mapped[key]
        guard.validate_identity(m)
        require(settings.get('server')==m['ip'] and settings.get('server_port')==m['port']
                and tls.get('server_name')==m['sni'] and tls.get('enabled') is True
                and tls.get('insecure',False) is False and tls.get('certificate_public_key_sha256')==[m['pin']], 'database_identity_drift')
    return approved,mappings,allocation,{r['key']:r['state_sha256'] for r in snapshot['routes']}


def bootstrap():
    require(not os.path.lexists(RECORD) and not os.path.lexists(IDENTITY) and not os.path.lexists(DROPIN),'already_prepared')
    for name,expected in OLD.items():require(sha(read(PRIVATE/name,False))==expected,'unreviewed_installed_code')
    approved,mappings,allocation,states=inputs()
    service=props(SERVICE);timer=props(TIMER)
    require(service['Result']=='success' and timer['ActiveState']=='active','old_guard_unhealthy')
    require(service['FragmentPath']=='/etc/systemd/system/'+SERVICE and not service['DropInPaths'],'unexpected_service_layout')
    directory(RECORD.parent);directory(RECORD)
    before={}
    for name in FILES:
        path=PRIVATE/name
        if os.path.lexists(path):
            body=read(path,False);write(RECORD/(name+'.before'),body,absent=True);before[name]={'sha256':sha(body),'mode':stat.S_IMODE(path.stat().st_mode)}
        else:before[name]=None
    unit=Path(service['FragmentPath']);write(RECORD/'service.before',read(unit,False),absent=True)
    write(RECORD/'guard-state.before',read(PRIVATE/'guard-state.json'),absent=True)
    directory(IDENTITY)
    run(['ssh-keygen','-q','-t','ed25519','-N','','-C','xboard-runtime-identity-20261027','-f',str(IDENTITY/'id_ed25519')])
    write(IDENTITY/'known_hosts',KNOWN_HOST,absent=True)
    state={'schema':1,'phase':'prepared','before':before,'source_hashes':{n:sha((SOURCE/n).read_bytes()) for n in FILES},
           'database_states':states,'unit_sha256':sha(read(unit,False)),'at':int(time.time())}
    write(RECORD/'deployment.json',entry_identity.encode(state),absent=True)
    return {'status':'prepared','public_key':read(IDENTITY/'id_ed25519.pub',False).decode().strip(),
            'routes':41,'anytls':28,'database_mutated':False,'guard_mutated':False,'backup_path':str(RECORD)}


def state():return json.loads(read(RECORD/'deployment.json'))


def preflight():
    saved=state();require(saved['phase'] in ('prepared','deployed'),'deployment_state_invalid')
    require({n:sha((SOURCE/n).read_bytes()) for n in FILES}==saved['source_hashes'],'source_bundle_drift')
    require(read(IDENTITY/'known_hosts')==KNOWN_HOST,'ssh_host_key_drift');read(IDENTITY/'id_ed25519')
    approved,mappings,allocation,states=inputs()
    require(states==saved['database_states'],'database_state_drift')
    checks=entry_identity.evaluate_identity(approved,allocation,mappings)
    require(len(checks)==28,'identity_count_invalid')
    failures=[r for r in checks if 'reason' in r]
    if any(r['reason'] not in {'runtime_identity_timeout','runtime_tcp_unreachable','runtime_tls_failed','runtime_public_key_mismatch'} for r in failures):
        return {'status':'preflight_identity_failed','identity_checks':checks,'files_mutated':False}
    proxies,usage=guard.fetch_subscription(PRIVATE)
    require(not guard.evaluate(approved,proxies,usage,int(time.time())),'source_metadata_not_approved')
    # One deliberately wrong synthetic pin verifies rejection end-to-end; never write the map.
    target=next(m for m in mappings if m['key']=='U04').copy();target['pin']=base64.b64encode(b'\0'*32).decode()
    selected=[r for r in approved if r['key']=='U04']
    negative=entry_identity.evaluate_identity(selected,allocation,[target])
    require(len(negative)==1 and negative[0].get('reason')=='runtime_public_key_mismatch','negative_identity_not_rejected')
    return {'status':'preflight_identity_failed' if failures else 'preflight_passed','identity_checks':checks,'negative_pin_rejected':True,
            'approved_map_unchanged':True,'database_mutated':False,'metadata_ok':True,'checked_at':int(time.time())}


def public_check():
    """Fresh read-only acceptance for this deployment, never a maintenance receipt."""
    import public_verify as public
    saved=state();require(saved['phase']=='deployed','guard_not_deployed')
    approved,mappings,allocation,states=inputs()
    current=json.loads(read(PRIVATE/'guard-state.json'))
    allowed_closed=set(saved.get('reviewed_preflight_failures',{})) | {r['key'] for r in current.get('withdraw',[])}
    settings=public.agent_settings()
    before=public.scope(settings,allocation)
    withdrawn={k for k,r in before.items() if not r['enabled'] and not r['show']}
    require(withdrawn<=allowed_closed<=set(states),'invalid_withdraw_scope')
    require(all(states[k]==saved['database_states'][k] for k in states if k not in withdrawn),'database_state_drift')
    base_id='af436e4bfc7a4dc9bf1c074c37bcc7e9'
    base_sha='e5c972fe5e78fd4a264add9ed37f8fe673a52f7686eca05283b8e6b14ca845ee'
    cache=public.load_json(public.private_bytes(Path('/root/xboard-upstream-recovery')/base_id/'public-cache.private.json'))
    require(public.digest(cache)=='e8246c3edde3dfaf7bf317d39655de5809759b2061e4f59e6924032769a19dd6','public_cache_drift')
    indexed=public.cache_contract(cache,base_id,base_sha,allocation,settings)
    require(set(indexed)==set(states) and len(indexed)==41,'public_scope_invalid')
    active=sorted(set(indexed)-withdrawn);closed=sorted(withdrawn)
    require(all(before[k]['show'] and before[k]['enabled'] for k in active),'unexpected_withdrawal')
    public.verify_scope(indexed,before,active,'success',states)
    public.verify_scope(indexed,before,closed,'withdrawn',states)
    binary=cache['binary']
    require(binary['sha256']=='031042edfd30a215e4c69d83eb7d13c194e6ef50c782e2e1308d9d8fa128454a','binary_drift')
    path=public.bound_binary(binary)
    started=int(time.time())
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        measurements=list(executor.map(lambda key:public.measure(indexed[key],path,'withdrawn' if key in withdrawn else 'success'),sorted(indexed)))
    after=public.scope(settings,allocation)
    public.verify_scope(indexed,after,active,'success',states)
    public.verify_scope(indexed,after,closed,'withdrawn',states)
    require(before==after and inputs()[3]==states,'public_scope_changed')
    passed=all(row['status']=='passed' and row['temporary_process_terminated'] and row['temporary_directory_removed'] for row in measurements)
    report={'status':'passed' if passed else 'failed','purpose':'runtime_guard_deployment_readonly',
            'not_a_maintenance_acceptance':True,'started_at':started,'checked_at':int(time.time()),
            'active_routes':active,'withdrawn_routes':closed,'routes':measurements,'strict_tls':True,'direct_fallback':False,'fresh_core_per_route':True,
            'node_configuration_mutated':False,'binary_sha256':binary['sha256']}
    write(RECORD/('public-check-'+str(started)+'.json'),entry_identity.encode(report),absent=True)
    return report


def status():
    current=json.loads(read(PRIVATE/'guard-state.json'))
    return {'status':'inspected','deployment_phase':state()['phase'],'guard':props(SERVICE),'timer':props(TIMER),
            'installed_hashes':{n:sha(read(PRIVATE/n,False)) if (PRIVATE/n).exists() else None for n in FILES},
            'checked_at':current.get('checked_at'),'fetch_ok':current.get('fetch_ok'),'identity_ok':current.get('identity_ok'),
            'identity_checks':current.get('identity_checks',[]),'withdraw':current.get('withdraw',[]),
            'apply':current.get('apply'),'pinned_sha256':sha(read(PRIVATE/'pinned.private'))}


def reviewed_failures(result, expected_failures):
    expected_failures=expected_failures or {}
    require(isinstance(expected_failures,dict) and len(expected_failures)<=28 and
            all(re.fullmatch(r'U(?:0[1-9]|[1-3][0-9]|4[01])',k) and v in {'runtime_identity_timeout','runtime_tcp_unreachable','runtime_tls_failed','runtime_public_key_mismatch'} for k,v in expected_failures.items()),'invalid_expected_failures')
    failures={r['key']:r['reason'] for r in result.get('identity_checks',[]) if 'reason' in r}
    require(result.get('negative_pin_rejected') is True and result.get('metadata_ok') is True and
            all(expected_failures.get(k)==v for k,v in failures.items()),'preflight_not_passed')
    return failures


def deploy(expected_failures=None):
    saved=state();require(saved['phase']=='prepared','deployment_not_prepared')
    result=preflight()
    failures=reviewed_failures(result,expected_failures)
    saved['reviewed_preflight_failures']=failures
    require(not os.path.lexists(DROPIN),'unexpected_dropin')
    require(sha(read(Path('/etc/systemd/system')/SERVICE,False))==saved['unit_sha256'],'service_unit_drift')
    for name,before in saved['before'].items():
        require((sha(read(PRIVATE/name,False)) if os.path.lexists(PRIVATE/name) else None)==(before['sha256'] if before else None),'installed_file_drift')
    # Stop only the timer and drain any running old oneshot before replacing code.
    run(['systemctl','stop',TIMER])
    for _ in range(50):
        if props(SERVICE)['ActiveState'] not in ('activating','active'):break
        time.sleep(2)
    else:raise ValueError('old_guard_did_not_finish_timer_stopped')
    saved['phase']='installing';write(RECORD/'deployment.json',entry_identity.encode(saved))
    for name in FILES:write(PRIVATE/name,(SOURCE/name).read_bytes())
    directory(DROPIN.parent,0o755);write(DROPIN,OVERRIDE,mode=0o644,absent=True)
    run(['systemctl','daemon-reload'])
    saved['phase']='deployed';saved['deployed_at']=int(time.time());write(RECORD/'deployment.json',entry_identity.encode(saved))
    run(['systemctl','start',SERVICE],timeout=200)
    run(['systemctl','start',TIMER])
    result=status();require(result['guard']['Result']=='success' and result['timer']['ActiveState']=='active','runtime_service_unhealthy')
    require(len(result['identity_checks'])==28 and result['checked_at']>=saved['deployed_at'],'fresh_runtime_check_missing')
    result['status']='deployed';result['backup_path']=str(RECORD);return result


def rollback():
    saved=state();require(saved['phase'] in ('installing','deployed'),'rollback_phase_invalid')
    # Never restore DB, pins or previous runtime status; only this deployment's files.
    for name in FILES:
        current=sha(read(PRIVATE/name,False)) if (PRIVATE/name).exists() else None
        before=saved['before'][name]
        require(current in (saved['source_hashes'][name],before['sha256'] if before else None),'rollback_file_drift')
    if DROPIN.exists():require(read(DROPIN,False)==OVERRIDE,'rollback_dropin_drift')
    for name,before in saved['before'].items():
        if before:require(sha(read(RECORD/(name+'.before')))==before['sha256'],'backup_drift')
    run(['systemctl','stop',TIMER]);run(['systemctl','stop',SERVICE])
    for name,before in saved['before'].items():
        if before:
            body=read(RECORD/(name+'.before'));require(sha(body)==before['sha256'],'backup_drift')
            write(PRIVATE/name,body,mode=before['mode'])
        elif (PRIVATE/name).exists():(PRIVATE/name).unlink()
    if DROPIN.exists():DROPIN.unlink()
    run(['systemctl','daemon-reload']);run(['systemctl','start',TIMER])
    saved['phase']='rolled_back';write(RECORD/'deployment.json',entry_identity.encode(saved))
    return {'status':'rolled_back','database_mutated':False,'pins_mutated':False,'timer':props(TIMER),
            'note':'previous metadata guard restored; withdrawn routes are not re-enabled'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['bootstrap','preflight','deploy','status','rollback','public-check']);parser.add_argument('--expected-failures',default='{}');args=parser.parse_args()
    require(len(args.expected_failures)<=2048,'expected_failures_too_large')
    expected=entry_identity.decode(args.expected_failures.encode())
    require(args.operation=='deploy' or expected=={},'unexpected_failure_approval')
    require(os.geteuid()==0,'root_required');os.umask(0o077)
    with open('/run/lock/xboard-upstream-runtime-deploy.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=deploy(expected) if args.operation=='deploy' else globals()[args.operation.replace('-','_')]()
    print(json.dumps(result,sort_keys=True))
    return 1 if result.get('status') in ('preflight_identity_failed','failed') else 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        # Error messages here are fixed locally; never echo arbitrary subprocess data.
        allowed=isinstance(error,ValueError) and re.fullmatch('[a-z_]+',str(error))
        print(json.dumps({'status':'failed','reason':str(error) if allowed else type(error).__name__}))
        raise SystemExit(2)
