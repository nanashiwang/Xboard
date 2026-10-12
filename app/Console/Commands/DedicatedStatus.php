<?php

namespace App\Console\Commands;

use App\Models\DedicatedExit;
use App\Models\Plan;
use App\Services\DedicatedExitService;
use Illuminate\Console\Command;

class DedicatedStatus extends Command
{
    protected $signature = 'dedicated:status';
    protected $description = '显示专属套餐容量、出口健康和占用，不输出账号或代理凭据';

    public function handle(DedicatedExitService $service): int
    {
        foreach (Plan::where('dedicated', true)->get() as $plan) {
            $occupied = $service->occupied($plan->id)->get();
            $this->info("套餐 {$plan->id} {$plan->name}：上架=" . (int) $plan->show
                . '，可新购=' . (int) $service->hasCapacity($plan) . "，占用={$occupied->count()}/{$plan->capacity_limit}");
            $this->table(['出口 ID', '名称', '用途', '健康', '占用', '最近检查'],
                DedicatedExit::where('plan_id', $plan->id)->get()->map(fn ($e) => [
                    $e->id, $e->name, $e->standby ? '备用' : '销售', $e->isHealthy() ? '正常' : '不可分配',
                    $occupied->where('exit_id', $e->id)->count() . '/5', $e->checked_at,
                ]));
        }
        return self::SUCCESS;
    }
}
