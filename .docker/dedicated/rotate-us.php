<?php
// Fixed, reviewed production scope. Loaded by the private operations harness and regression tests.
use App\Models\{DedicatedAssignment, DedicatedExit, NodeProbe, Plan, Server};
use App\Services\{DedicatedExitService, NodeSyncService};
use Illuminate\Support\Facades\DB;

final class RotateOwnedUs20261028
{
    public const SOURCES = [314,315,316,317,318,319,320,321,322,323,324,326,148];
    public const KEEP = [322,323,324];
    public const IPS = [322=>'216.36.108.173',323=>'192.220.24.147',324=>'216.36.108.128'];
    public const BACKENDS = [314=>327,315=>328,316=>329,317=>330,318=>331,319=>332,320=>333,321=>334,322=>335,323=>336,324=>337,326=>339,148=>147];
    public const NODE_FIELDS = ['group_ids','show','enabled','name'];
    public const EXIT_FIELDS = ['enabled','standby'];

    public static function demand(bool $ok, string $reason): void
    {
        if (!$ok) throw new RuntimeException($reason);
    }

    public static function snapshot(): array
    {
        $exitIds=DedicatedExit::where('plan_id',5)->pluck('id');
        $aliases=Server::whereIn('dedicated_exit_id',$exitIds)->pluck('id')->all();
        $ids = array_values(array_unique([...self::SOURCES,...array_values(self::BACKENDS),...$aliases]));
        return [
            'nodes'=>Server::whereIn('id',$ids)->orderBy('id')->get()->mapWithKeys(fn($s)=>[$s->id=>$s->only(self::NODE_FIELDS)])->all(),
            'exits'=>DedicatedExit::where('plan_id',5)->orderBy('id')->get()->mapWithKeys(fn($e)=>[$e->id=>$e->only(self::EXIT_FIELDS)])->all(),
            'plan'=>Plan::findOrFail(5)->only(['capacity_limit']),
            'probe'=>NodeProbe::findOrFail(1)->only(['server_ids','expected_exits']),
            'assignments'=>DedicatedAssignment::where('plan_id',5)->orderBy('id')->get()->map(fn($a)=>$a->only(['id','user_id','exit_id','slot','order_id','reserved_until']))->all(),
        ];
    }

    public static function validate(): void
    {
        $plan=Plan::findOrFail(5);
        self::demand($plan->dedicated && (int)$plan->group_id===5,'plan_mapping_changed');
        self::demand(in_array((int)$plan->capacity_limit,[5,15],true),'capacity_changed');
        $probe=NodeProbe::findOrFail(1);
        self::demand($probe->enabled && (int)$probe->user?->group_id===6,'monitor_changed');
        foreach(self::BACKENDS as $sourceId=>$backendId) {
            $source=Server::findOrFail($sourceId); $backend=Server::findOrFail($backendId);
            self::demand((int)$source->parent_id===$backendId && !$source->dedicated_exit_id && !$backend->dedicated_exit_id,'node_mapping_changed');
            self::demand((float)$source->rate===2.0 && (float)$backend->rate===2.0,'rate_changed');
            if(isset(self::IPS[$sourceId])) {
                self::demand($backend->host===self::IPS[$sourceId] && $backend->enabled,'target_backend_changed');
                self::demand(($probe->expected_exits[$sourceId]??null)===self::IPS[$sourceId],'probe_mapping_changed');
            }
        }
        $target=DedicatedExit::findOrFail(14);
        self::demand($target->public_ip===self::IPS[322] && $target->shared_server_id===335 && $target->probe_server_id===322 && $target->isHealthy(),'target_not_healthy');
        $alias=Server::findOrFail(348);
        self::demand((int)$alias->dedicated_exit_id===14 && (int)$alias->parent_id===335 && $alias->show,'alias_changed');
        self::demand(DedicatedAssignment::where('plan_id',5)->count()<=DedicatedExit::CAPACITY,'too_many_assignments');
        // Refuse an unexpected new pool member rather than silently retiring it.
        self::demand(DedicatedExit::where('plan_id',5)->pluck('id')->sort()->values()->all()===range(1,18),'pool_changed');
    }

    public static function apply(?callable $saveBefore = null): array
    {
        DB::statement('PRAGMA busy_timeout=15000');
        return DB::transaction(function() use ($saveBefore) {
            $plan=Plan::findOrFail(5);
            app(DedicatedExitService::class)->lock($plan); // Acquire SQLite write lock before reading scope.
            self::validate();
            $before=self::snapshot();
            if ($saveBefore) $saveBefore($before);
            $used=DedicatedAssignment::where('plan_id',5)->where('exit_id',14)->pluck('slot')->all();
            $moved=0;
            foreach(DedicatedAssignment::where('plan_id',5)->where('exit_id','<>',14)->orderBy('id')->get() as $assignment) {
                $free=array_values(array_diff(range(1,DedicatedExit::CAPACITY),$used));
                self::demand(count($free)>0,'target_full');
                $old=$assignment->exit_id; $slot=$free[0]; $used[]=$slot;
                $assignment->update(['exit_id'=>14,'slot'=>$slot]);
                DB::table('v2_dedicated_assignment_log')->insert(['user_id'=>$assignment->user_id,'from_exit_id'=>$old,'to_exit_id'=>14,'reason'=>'operator_exit_retirement','created_at'=>time()]);
                $moved++;
            }
            foreach(self::BACKENDS as $sourceId=>$backendId) {
                $source=Server::findOrFail($sourceId); $backend=Server::findOrFail($backendId);
                if(in_array($sourceId,[323,324],true)) {
                    $groups=['1','2','3','4','6'];
                    $source->update(['group_ids'=>$groups,'show'=>true,'name'=>$sourceId===324?'美国01｜2×｜家宽':'美国02｜2×｜家宽']);
                    $backend->update(['group_ids'=>$groups]);
                } elseif($sourceId===322) {
                    $source->update(['group_ids'=>['6'],'show'=>true]);
                    $backend->update(['group_ids'=>['5','6']]);
                } else {
                    $source->update(['group_ids'=>[],'show'=>false,'enabled'=>false]);
                    $backend->update(['group_ids'=>[],'enabled'=>false]);
                }
            }
            foreach(DedicatedExit::where('plan_id',5)->get() as $exit) {
                $exit->update($exit->id===14?['enabled'=>true,'standby'=>false]:['enabled'=>false]);
                foreach(Server::where('dedicated_exit_id',$exit->id)->get() as $alias) {
                    $alias->update(['show'=>$exit->id===14,'group_ids'=>$exit->id===14?['5']:[]]);
                }
            }
            $plan->update(['capacity_limit'=>5]);
            $probe=NodeProbe::findOrFail(1);
            $retired=array_values(array_diff(self::SOURCES,self::KEEP));
            $probe->update([
                'server_ids'=>array_values(array_diff($probe->server_ids,$retired)),
                'expected_exits'=>array_diff_key($probe->expected_exits,array_flip($retired)),
            ]);
            $after=self::snapshot();
            DB::afterCommit(function() {
                foreach(self::BACKENDS as $id) NodeSyncService::notifyFullSync($id);
                NodeSyncService::notifyUsersUpdatedByGroup(5);
            });
            return ['before'=>$before,'after'=>$after,'moved'=>$moved];
        },5);
    }
}
