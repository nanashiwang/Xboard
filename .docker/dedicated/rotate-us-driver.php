<?php
// App is bootstrapped and RotateOwnedUs20261028 is loaded by rotate-us.py.
use App\Models\User;
use App\Services\ServerService;
use App\Services\Probes\ProbeOutbound;
use App\Utils\Helper;

function rotationOutbound(int $id, User $user): array {
    $node=Server::findOrFail($id); $row=$node->toArray(); $row['port']=(int)$node->port;
    $row['password']=$node->generateServerPassword($user);
    return (new ProbeOutbound($user->toArray(),[]))->build($row);
}
function rotationTarget(int $id, User $user, bool $allowed, string $kind): array {
    $ip=RotateOwnedUs20261028::IPS[$id]??($id===148?'192.204.56.29':Server::findOrFail($id)->parent->host);
    return ['id'=>$id,'kind'=>$kind,'allowed'=>$allowed,'expected'=>$ip,'outbound'=>rotationOutbound($id,$user)];
}
function rotationPrivate(string $file,array $data): void {
    $tmp=$file.'.tmp'; file_put_contents($tmp,json_encode($data,JSON_THROW_ON_ERROR),LOCK_EX);
    chmod($tmp,0600); rename($tmp,$file);
}
$directory=storage_path('app/backups/us-retirement-20261028');
if(!is_dir($directory)) mkdir($directory,0700,true);
$qaFile=$directory.'/qa.json';
try {
    if($mode==='preflight') {
        RotateOwnedUs20261028::validate();
        $monitor=NodeProbe::findOrFail(1)->user;
        RotateOwnedUs20261028::demand($monitor && !$monitor->banned && $monitor->u+$monitor->d<$monitor->transfer_enable && (!$monitor->expired_at||$monitor->expired_at>time()),'monitor_unavailable');
        $targets=[];
        foreach([322,323,324,325] as $id) {
            RotateOwnedUs20261028::demand(ServerService::getAvailableUsers(Server::findOrFail($id)->parent)->contains('id',$monitor->id),'monitor_not_authorized');
            $targets[]=rotationTarget($id,$monitor,true,'monitor');
        }
        $out=['targets'=>$targets,'occupied'=>DedicatedAssignment::where('plan_id',5)->count(),'target_healthy'=>DedicatedExit::findOrFail(14)->isHealthy()];
    } elseif($mode==='apply') {
        RotateOwnedUs20261028::demand(!file_exists($directory.'/applied.json'),'already_applied');
        $result=RotateOwnedUs20261028::apply(fn($before)=>rotationPrivate($directory.'/before.json',$before));
        rotationPrivate($directory.'/applied.json',$result);
        $out=['applied'=>true,'moved'=>$result['moved'],'pool'=>[14],'capacity'=>5];
    } elseif($mode==='qa-start') {
        if(file_exists($qaFile)) {
            $previous=json_decode(file_get_contents($qaFile),true,512,JSON_THROW_ON_ERROR)['ids'];
            RotateOwnedUs20261028::demand(!User::whereIn('id',$previous)->exists(),'qa_already_exists');
            rename($qaFile,$qaFile.'.'.time());
        }
        $ids=DB::transaction(function() use($qaFile) {
            app(DedicatedExitService::class)->lock(Plan::findOrFail(5));
            RotateOwnedUs20261028::demand(DedicatedAssignment::where('plan_id',5)->count()<5,'no_test_slot');
            $ids=[];
            foreach([1,2,3,4,5] as $group) {
                $plan=Plan::where('group_id',$group)->sole();
                $user=User::create(['email'=>'us-retirement-'.Helper::guid().'@example.test','password'=>password_hash(Helper::guid(),PASSWORD_DEFAULT),
                    'uuid'=>Helper::guid(),'token'=>Helper::guid(),'group_id'=>$group,'plan_id'=>$plan->id,'banned'=>false,
                    'transfer_enable'=>1073741824,'u'=>0,'d'=>0,'expired_at'=>time()+3600,'remind_expire'=>false,'remind_traffic'=>false]);
                $ids[]=$user->id;
                if($group===5) RotateOwnedUs20261028::demand(app(DedicatedExitService::class)->assignedExit($user)===14,'qa_assignment_failed');
            }
            rotationPrivate($qaFile,['ids'=>$ids]);
            return $ids;
        });
        foreach([1,2,3,4,5] as $group) NodeSyncService::notifyUsersUpdatedByGroup($group);
        $out=['created'=>count($ids)];
    } elseif($mode==='qa-targets') {
        $ids=json_decode(file_get_contents($qaFile),true,512,JSON_THROW_ON_ERROR)['ids'];
        $targets=[];$subscriptions=[];$urls=[];
        foreach($ids as $id) {
            $user=User::findOrFail($id); $group=(int)$user->group_id;
            DB::beginTransaction();
            try { $available=ServerService::getAvailableServers($user); } finally {DB::rollBack();}
            $owned=array_values(array_filter($available,fn($s)=>!in_array('upstream-extension-public',$s['tags']??[],true)));
            $actual=array_column($owned,'id');sort($actual);$expected=$group===5?[325,348]:[323,324,325,354,356,358];sort($expected);
            RotateOwnedUs20261028::demand($actual===$expected,'subscription_scope_mismatch');
            $names=array_column($available,'name');RotateOwnedUs20261028::demand(count($names)===count(array_unique($names)),'duplicate_subscription_name');
            $subscriptions[$group]=['count'=>count($available),'owned'=>$actual];
            $urls[]=['group'=>$group,'url'=>Helper::getSubscribeUrl($user->token,'https://taige.us'),'names'=>$names];
            foreach([322,323,324] as $sourceId) {
                $allowed=$group===5?$sourceId===322:$sourceId!==322;
                $authorized=ServerService::getAvailableUsers(Server::findOrFail($sourceId)->parent)->contains('id',$user->id);
                RotateOwnedUs20261028::demand($allowed===$authorized,'backend_authorization_mismatch');
                $targets[]=rotationTarget($sourceId,$user,$allowed,'group-'.$group);
            }
            if(in_array($group,[1,5],true)) {
                foreach(array_diff(RotateOwnedUs20261028::SOURCES,RotateOwnedUs20261028::KEEP) as $sourceId)
                    $targets[]=rotationTarget($sourceId,$user,false,'retired-group-'.$group);
                $targets[]=rotationTarget(325,$user,true,'fallback-group-'.$group);
            }
        }
        $out=['targets'=>$targets,'subscriptions'=>$subscriptions,'urls'=>$urls];
    } elseif($mode==='qa-clean') {
        $ids=file_exists($qaFile)?json_decode(file_get_contents($qaFile),true,512,JSON_THROW_ON_ERROR)['ids']:[];
        foreach($ids as $id) {
            $user=User::find($id);
            if($user) {
                RotateOwnedUs20261028::demand(str_starts_with($user->email,'us-retirement-') && str_ends_with($user->email,'@example.test'),'qa_identity_changed');
                app(DedicatedExitService::class)->release($id,'qa_cleanup'); $user->delete();
            }
        }
        foreach(['v2_stat_user','v2_dedicated_assignment_log'] as $table) DB::table($table)->whereIn('user_id',$ids)->delete();
        foreach([1,2,3,4,5] as $group) NodeSyncService::notifyUsersUpdatedByGroup($group);
        $out=['remaining'=>User::whereIn('id',$ids)->count(),'assignments'=>DedicatedAssignment::whereIn('user_id',$ids)->count()];
    } elseif($mode==='status') {
        $s=RotateOwnedUs20261028::snapshot();
        $out=['nodes'=>$s['nodes'],'pool'=>DedicatedExit::where('plan_id',5)->where('enabled',true)->pluck('id'),
            'capacity'=>$s['plan']['capacity_limit'],'probe'=>$s['probe'],
            'assignments'=>DedicatedAssignment::where('plan_id',5)->selectRaw('exit_id,count(*) as occupied')->groupBy('exit_id')->get(),
            'target_healthy'=>DedicatedExit::findOrFail(14)->isHealthy()];
    } else throw new RuntimeException('unknown_operation');
    echo json_encode($out,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE);
} catch(Throwable $error) {
    // Never include SQL bindings, proxy credentials, customer data or raw transport exceptions.
    fwrite(fopen('php://stderr','w'),'rotation_failed:'.(in_array($error->getMessage(),[
        'already_applied','target_not_healthy','too_many_assignments','pool_changed','no_test_slot','qa_already_exists',
        'subscription_scope_mismatch','backend_authorization_mismatch','duplicate_subscription_name'
    ],true)?$error->getMessage():get_class($error)).PHP_EOL);
    exit(1);
}
