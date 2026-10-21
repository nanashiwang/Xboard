"""Production proxy acceptance. Credentials stay in a private, removed temp directory."""
import argparse
import concurrent.futures
import json
import os
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--baseline', action='store_true')
args = parser.parse_args()
os.umask(0o077)
binary = Path('/root/Xboard/backups/fleet-20261017/sing-box')
if not binary.is_file():
    raise SystemExit('Verified proxy test binary is missing; no downloads or changes performed.')
php = r'''
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$probe=App\Models\NodeProbe::findOrFail(1); $monitor=$probe->user;
if (!$monitor || $monitor->banned || $monitor->u+$monitor->d >= $monitor->transfer_enable
    || ($monitor->expired_at && $monitor->expired_at <= time())) throw new RuntimeException('Monitor unavailable');
$ids=[314,315,316,317,318,319,320,321,322,323,324,326,148]; // Includes two public exits for monitoring only.
$targets=[]; $authorization=[];
function outbound($node,$user) {
    $row=$node->toArray(); $row['port']=(int)$node->port;
    $row['password']=$node->generateServerPassword($user);
    return (new App\Services\Probes\ProbeOutbound($user->toArray(),[]))->build($row);
}
foreach ($ids as $id) {
    $node=App\Models\Server::findOrFail($id);
    $expected=$id===148?'192.204.56.29':$node->parent->host;
    $authorization[$id]=App\Services\ServerService::getAvailableUsers($node->parent)->contains('id',$monitor->id);
    $targets[]=['kind'=>'monitor','id'=>$id,'expected'=>$expected,'outbound'=>outbound($node,$monitor)];
}
$result=['targets'=>$targets,'monitor_authorized'=>$authorization];
// Read-only ordinary scope must not be inferred from the privileged monitoring group.
$ordinary=App\Models\User::whereIn('group_id',[1,2,3,4])->where('banned',false)
    ->whereRaw('u+d < transfer_enable')->where(fn($q)=>$q->whereNull('expired_at')->orWhere('expired_at','>',time()))->firstOrFail();
$publicIds=[148,319,325,354,356,358];
foreach([1,2,3,4] as $group) {
    $viewer=clone $ordinary; $viewer->group_id=$group; $viewer->plan_id=null;
    $available=App\Services\ServerService::getAvailableServers($viewer);
    // Extension routes have their own allocation/acceptance; verify the retained owned scope here.
    $owned=array_values(array_filter($available,fn($s)=>!in_array('upstream-extension-public',$s['tags']??[],true)));
    $availableIds=array_column($owned,'id');
    sort($availableIds); $expectedIds=$publicIds; sort($expectedIds);
    $result['ordinary_scope'][$group]=$availableIds===$expectedIds;
}
foreach(array_unique([...$ids,...$publicIds]) as $id) {
    $source=App\Models\Server::findOrFail($id);
    $allowed=App\Services\ServerService::getAvailableUsers($source->parent)->contains('id',$ordinary->id);
    $expected=in_array($id,$publicIds,true);
    $result['ordinary_authorization'][$id]=$allowed===$expected;
    $result['targets'][]=['kind'=>$expected?'ordinary':'unassigned','id'=>$id,
        'expected'=>$id===148?'192.204.56.29':$source->parent->host,'outbound'=>outbound($source,$ordinary)];
}
foreach([150,156,158] as $id) {
    $source=App\Models\Server::findOrFail($id);
    $result['retired_duplicates'][$id]=!$source->show && !$source->parent->enabled
        && !App\Services\ServerService::getAvailableUsers($source->parent)->contains('id',$ordinary->id);
    $result['targets'][]=['kind'=>'unassigned','id'=>$id,'expected'=>null,'outbound'=>outbound($source,$ordinary)];
}
if (OWNED_POST_CHECK) {
    $user=App\Models\User::findOrFail(8);
    $order=App\Models\Order::where('user_id',8)->where('plan_id',5)->where('trade_no','like','%e920')->sole();
    $assignment=App\Models\DedicatedAssignment::where('user_id',8)->first();
    $result['order']=['status'=>$order->status,'plan_id'=>$order->plan_id,'total_amount'=>$order->total_amount,
        'expired_at'=>$user->expired_at,'transfer_enable'=>$user->transfer_enable,'assignment_exit_id'=>$assignment?->exit_id,
        'updated_at'=>$order->updated_at];
    $ready=$order->status===App\Models\Order::STATUS_COMPLETED && $assignment && $user->plan_id===5
        && App\Models\DedicatedExit::find($assignment->exit_id)?->isHealthy();
    $result['ready']=(bool)$ready;
    $result['pool']=App\Models\DedicatedExit::whereNotNull('shared_server_id')->where('enabled',true)->get()->map(fn($e)=>[
        'id'=>$e->id,'healthy'=>$e->isHealthy(),'occupied'=>App\Models\DedicatedAssignment::where('exit_id',$e->id)->count()]);
    if ($ready) {
        // Subscription getters can migrate unhealthy bindings. Acceptance must be read-only.
        Illuminate\Support\Facades\DB::beginTransaction();
        try {
            $available=App\Services\ServerService::getAvailableServers($user);
            $unchanged=App\Models\DedicatedAssignment::where('user_id',$user->id)->value('exit_id')===$assignment->exit_id;
        } finally { Illuminate\Support\Facades\DB::rollBack(); }
        if (!$unchanged) throw new RuntimeException('Fixed binding health changed during acceptance; retry without migrating it.');
        $result['subscription_ids']=array_column($available,'id');
        $result['fixed_subscription_count']=count(array_filter($available,fn($s)=>!empty($s['dedicated_exit_id'])));
        $fallback=App\Models\Server::findOrFail(325);
        $result['fallback_authorized']=in_array(325,$result['subscription_ids'],true)
            && App\Services\ServerService::getAvailableUsers($fallback->parent)->contains('id',$user->id);
        $result['targets'][]=['kind'=>'fallback','id'=>325,'expected'=>$fallback->parent->host,'outbound'=>outbound($fallback,$user)];
        foreach (App\Models\DedicatedExit::whereNotNull('shared_server_id')->where('enabled',true)->get() as $exit) {
            $node=App\Models\Server::findOrFail($exit->probe_server_id);
            $allowed=App\Services\ServerService::getAvailableUsers($node->parent)->contains('id',$user->id);
            $assigned=$exit->id===$assignment->exit_id;
            $result['fixed_authorization'][$node->id]=['assigned'=>$assigned,'allowed'=>$allowed];
            $result['targets'][]=['kind'=>$assigned?'fixed':'unassigned','id'=>$node->id,
                'expected'=>$exit->public_ip,'outbound'=>outbound($node,$user)];
        }
        foreach([148,319] as $id) {
            $node=App\Models\Server::findOrFail($id);
            $result['public_fixed_exclusion'][$id]=!App\Services\ServerService::getAvailableUsers($node->parent)->contains('id',$user->id);
            $result['targets'][]=['kind'=>'unassigned','id'=>$id,'expected'=>null,'outbound'=>outbound($node,$user)];
        }
    }
}
echo json_encode($result,JSON_THROW_ON_ERROR);
'''.replace('OWNED_POST_CHECK', 'false' if args.baseline else 'true')
proc = subprocess.run(['docker','compose','exec','-T','xboard','php','-r',php], capture_output=True, text=True, timeout=60)
if proc.returncode:
    raise SystemExit('Application acceptance query failed; credentials were not printed.')
data = json.loads(proc.stdout)
targets = data.pop('targets')
invalid = json.loads(json.dumps(next(t for t in targets if t['kind'] == 'ordinary' and t['id'] == 319)))
invalid['kind'] = 'invalid'
invalid['outbound']['uuid'] = str(uuid.uuid4())
targets.append(invalid)

def check(item):
    with tempfile.TemporaryDirectory(prefix='owned-fixed-probe-') as directory:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        config = {'log':{'level':'error'}, 'inbounds':[{'type':'socks','tag':'local','listen':'127.0.0.1','listen_port':port}],
                  'outbounds':[item['outbound']], 'route':{'final':'node'}}
        path = Path(directory)/'client.json'; path.write_text(json.dumps(config)); path.chmod(0o600)
        with open(Path(directory)/'core.log','w') as log:
            core = subprocess.Popen([str(binary),'run','-c',str(path)], stdout=log, stderr=log)
            try:
                for _ in range(40):
                    if core.poll() is not None:
                        return {'kind':item['kind'],'id':item['id'],'ok':False,'error':'core_start'}
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.1): break
                    except OSError: time.sleep(.1)
                result = subprocess.run(['curl','--silent','--show-error','--fail','--max-time','12',
                    '--socks5-hostname',f'127.0.0.1:{port}','https://api.ipify.org'],capture_output=True,text=True,timeout=15)
                connected = result.returncode == 0
                ok = (not connected) if item['kind'] in ('unassigned', 'invalid') else connected and result.stdout.strip()==item['expected']
                return {'kind':item['kind'],'id':item['id'],'ok':ok,'connected':connected,
                        'exit_matches':connected and result.stdout.strip()==item['expected']}
            finally:
                core.terminate()
                try: core.wait(timeout=3)
                except subprocess.TimeoutExpired: core.kill(); core.wait()

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results = list(pool.map(check, targets))
data['proxy_checks']=results
print(json.dumps(data,ensure_ascii=False,indent=2))
assert all(data['monitor_authorized'].values()), 'Monitoring authorization regression'
assert all(data['ordinary_scope'].values()), 'Ordinary subscription must have exactly two US and four non-US routes'
assert all(data['ordinary_authorization'].values()), 'Ordinary backend scope mismatch'
assert all(data['retired_duplicates'].values()), 'Duplicate CF route still available'
assert all(x['ok'] for x in results), 'Proxy or negative-auth check failed'
if not args.baseline:
    assert data['ready'], 'Fixed entitlement or current assigned-exit health is unavailable'
    assert data['fixed_subscription_count']==1, 'Fixed subscription must contain one assigned exit'
    assert data['fallback_authorized'], 'Hong Kong fallback authorization missing'
    assert all(data['public_fixed_exclusion'].values()), 'Fixed user must not authenticate the two ordinary US exits'
    assert all(v['assigned']==v['allowed'] for v in data['fixed_authorization'].values()), 'Fixed authorization mismatch'
    assert all(x['ok'] for x in results if x['kind'] in ('fixed','unassigned','fallback')), 'Fixed proxy, fallback or unauthorized-route check failed'
    assert all(p['occupied']<=5 for p in data['pool']), 'Exit capacity exceeded'
