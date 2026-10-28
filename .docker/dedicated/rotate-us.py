"""Fixed-scope US exit retirement. Run on the panel through its existing SSH workflow."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.parse

ROOT = Path('/root/Xboard')
BACKUP = ROOT / 'backups/us-retirement-20261028'
SIBLING = Path(__file__).resolve().parent
BINARY = ROOT / 'backups/fleet-20261017/sing-box'


def app(mode):
    boot = "require '/www/vendor/autoload.php';$app=require '/www/bootstrap/app.php';$app->make(Illuminate\\Contracts\\Console\\Kernel::class)->bootstrap();"
    code = '<?php\n' + boot + '\n$mode=' + json.dumps(mode) + ';\n'
    code += (SIBLING/'rotate-us.php').read_text().removeprefix('<?php')
    code += (SIBLING/'rotate-us-driver.php').read_text().removeprefix('<?php')
    result = subprocess.run(['docker','compose','exec','-T','xboard','php'],input=code,text=True,capture_output=True,cwd=ROOT,timeout=90)
    if result.returncode:
        # Only the driver's fixed error codes are safe to print.
        safe = [line for line in result.stderr.splitlines() if line.startswith('rotation_failed:')]
        raise RuntimeError('app_'+mode+': '+(';'.join(safe) or 'failed'))
    return json.loads(result.stdout)


def proxy(item):
    with tempfile.TemporaryDirectory(prefix='us-retirement-') as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        path=Path(directory)/'client.json'
        path.write_text(json.dumps({'log':{'level':'error'},'inbounds':[{'type':'socks','tag':'local','listen':'127.0.0.1','listen_port':port}],
            'outbounds':[item['outbound']],'route':{'final':'node'}}))
        with (Path(directory)/'core.log').open('w') as log:
            core=subprocess.Popen([str(BINARY),'run','-c',str(path)],stdout=log,stderr=log)
            try:
                ready=False
                for _ in range(40):
                    if core.poll() is not None: break
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.1): ready=True;break
                    except OSError: time.sleep(.1)
                if not ready: return {'id':item['id'],'kind':item['kind'],'ok':False,'error':'core_start'}
                checks=[];observed=None
                for url,expected_status in [('https://www.cloudflare.com/cdn-cgi/trace',200),('https://www.gstatic.com/generate_204',204)]:
                    r=subprocess.run(['curl','-sS','--max-time','15','--socks5-hostname',f'127.0.0.1:{port}','-w','\n%{http_code}',url],capture_output=True,text=True,timeout=20)
                    body,_,status=r.stdout.rpartition('\n')
                    connected=r.returncode==0 and status==str(expected_status)
                    if expected_status==200 and connected:
                        observed=next((line[3:] for line in body.splitlines() if line.startswith('ip=')),None)
                    checks.append(connected and (expected_status!=200 or observed==item['expected']))
                    if not item['allowed']:
                        return {'id':item['id'],'kind':item['kind'],'ok':r.returncode!=0,'rejected':r.returncode!=0}
                return {'id':item['id'],'kind':item['kind'],'ok':all(checks),'exit_ip':observed,'checks':checks}
            finally:
                core.terminate()
                try:core.wait(timeout=3)
                except subprocess.TimeoutExpired:core.kill();core.wait()


def check_all(targets):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(proxy,targets))
    # Retry only failed positive observations; a successful unauthorized connection is never excused.
    for index,result in enumerate(results):
        if not result['ok'] and targets[index]['allowed']:
            result['retry']=proxy(targets[index]);result['ok']=result['retry']['ok']
    print(json.dumps({'proxy_checks':results},ensure_ascii=False),flush=True)
    if not all(row['ok'] for row in results):raise RuntimeError('proxy_acceptance_failed')
    return results


def subscription_names(config):
    # Production enables the controller's protocol prefix; info rows clone the first VLESS node.
    names=[x['tag'].removeprefix('[vless]') for x in config['outbounds'] if x.get('type')=='vless']
    return [name for name in names if not name.startswith(('剩余流量：','套餐到期：','距离下次重置剩余：'))]


def subscriptions(rows):
    results=[]
    for row in rows:
        url=row['url']+('&' if '?' in row['url'] else '?')+'flag=sing-box'
        r=subprocess.run(['curl','-fsS','--max-time','25','-A','sing-box/1.12',url],capture_output=True,text=True,timeout=30)
        if r.returncode: raise RuntimeError('subscription_transport_failed')
        config=json.loads(r.stdout)
        names=subscription_names(config)
        if sorted(names)!=sorted(row['names']):
            print(json.dumps({'subscription_name_difference':{'group':row['group'],'actual':names,'expected':row['names']}},ensure_ascii=False),flush=True)
            raise RuntimeError('subscription_database_scope_mismatch')
        expected=['美国10｜2×｜家宽','香港01｜1×'] if row['group']==5 else ['美国01｜2×｜家宽','美国02｜2×｜家宽']
        if not all(name in names for name in expected) or len(names)!=len(set(names)):raise RuntimeError('subscription_content_failed')
        if row['group']!=5 and '美国10｜2×｜家宽' in names:raise RuntimeError('fixed_route_leaked')
        if row['group']==5 and sorted(names)!=sorted(expected):raise RuntimeError('fixed_subscription_scope_failed')
        results.append({'group':row['group'],'format':'sing-box','ok':True,'vless_count':len(names)})
    print(json.dumps({'https_subscriptions':results},ensure_ascii=False),flush=True)


def backup():
    BACKUP.mkdir(mode=0o700,parents=True,exist_ok=True)
    descriptor,name=tempfile.mkstemp(prefix='before-',suffix='.sqlite',dir=BACKUP);os.close(descriptor)
    with sqlite3.connect((ROOT/'.docker/.data/database.sqlite').as_uri()+'?mode=ro',uri=True,timeout=30) as live:
        with sqlite3.connect(name) as saved:
            live.backup(saved)
            if saved.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('backup_integrity_failed')
    print(json.dumps({'backup':name,'integrity_check':'ok'}),flush=True)


def invariants():
    snapshots=sorted(BACKUP.glob('before-*.sqlite'),key=lambda p:p.stat().st_mtime)
    if len(snapshots)!=1:raise RuntimeError('ambiguous_original_backup')
    result={}
    with sqlite3.connect(snapshots[0].as_uri()+'?mode=ro',uri=True) as before, sqlite3.connect((ROOT/'.docker/.data/database.sqlite').as_uri()+'?mode=ro',uri=True,timeout=30) as live:
        specs={
            'v2_user':['id','email','password','uuid','token','group_id','plan_id','transfer_enable','expired_at','balance','commission_balance','speed_limit','device_limit','banned'],
            'v2_plan':[row[1] for row in before.execute('PRAGMA table_info(v2_plan)') if row[1] not in ['allocation_version','updated_at']],
            'v2_order':[row[1] for row in before.execute('PRAGMA table_info(v2_order)') if row[1]!='updated_at'],
        }
        for table,columns in specs.items():
            select=','.join('"'+column+'"' for column in columns)
            old=before.execute('SELECT '+select+' FROM '+table).fetchall()
            changed=0
            for row in old:
                expected=list(row);identity=row[columns.index('id')]
                if table=='v2_plan' and identity==5:expected[columns.index('capacity_limit')]=5
                actual=live.execute('SELECT '+select+' FROM '+table+' WHERE id=?',(identity,)).fetchone()
                changed+=actual!=tuple(expected)
            result[table]={'existing_rows':len(old),'unexpected_changes':changed}
        if any(row['unexpected_changes'] for row in result.values()):raise RuntimeError('existing_customer_or_order_drift')
    return result


def start_qa():
    # Do not manufacture a healthy lease. Give the existing independent probe a bounded recovery window.
    for attempt in range(10):
        state=app('status')
        if state['target_healthy']:
            try:return app('qa-start')
            except RuntimeError as error:
                if 'qa_assignment_failed' not in str(error):raise
                app('qa-clean')
        print(json.dumps({'waiting_for_independent_health':attempt+1,'healthy':state['target_healthy']}),flush=True)
        time.sleep(30)
    raise RuntimeError('independent_health_did_not_recover')


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['preflight','apply','verify','status','cleanup'])
    operation=parser.parse_args().operation
    if operation=='status': print(json.dumps({'state':app('status'),'invariants':invariants()},ensure_ascii=False));return
    if operation=='cleanup':print(json.dumps(app('qa-clean')));return
    if not BINARY.is_file():raise RuntimeError('verified_test_binary_missing')
    if operation in ('preflight','apply'):
        pre=app('preflight');check_all(pre.pop('targets'));print(json.dumps({'preflight':pre}),flush=True)
        if operation=='preflight':return
        backup();print(json.dumps(app('apply')),flush=True)
    targets=[]
    try:
        print(json.dumps(start_qa()),flush=True)
        data=app('qa-targets');targets=data.pop('targets');urls=data.pop('urls')
        print(json.dumps(data,ensure_ascii=False),flush=True)
        subscriptions(urls)
        time.sleep(75) # Existing REST polling must observe the changed authorization.
        check_all(targets)
    finally:
        print(json.dumps({'qa_cleanup':app('qa-clean')}),flush=True)
    time.sleep(75)
    revoked=[dict(row,allowed=False,kind='qa-revoked') for row in targets if row['allowed'] and row['id'] in [322,323,324]]
    check_all(revoked)
    print(json.dumps({'late_qa_cleanup':app('qa-clean'),'final':app('status'),'invariants':invariants()},ensure_ascii=False),flush=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        if isinstance(error,RuntimeError):print(str(error),flush=True)
        else:
            import traceback
            frame=traceback.extract_tb(error.__traceback__)[-1]
            print('rotation_failed:'+type(error).__name__+':'+Path(frame.filename).name+':'+str(frame.lineno),flush=True)
        raise SystemExit(1)
