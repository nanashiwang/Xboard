<?php

namespace App\Console\Commands;

use App\Models\DedicatedExit;
use App\Models\Plan;
use App\Models\User;
use App\Services\DedicatedExitHealthService;
use App\Services\DedicatedExitService;
use Illuminate\Console\Command;

class CheckDedicatedExits extends Command
{
    protected $signature = 'dedicated:check';
    protected $description = '检查专属出口，保留健康绑定并迁移故障出口账号';

    public function handle(DedicatedExitHealthService $health, DedicatedExitService $assignments): int
    {
        $passed = 0;
        $exits = DedicatedExit::where('enabled', true)->get();
        foreach ($exits as $exit) {
            $passed += (int) $health->check($exit);
        }
        $waiting = 0;
        User::whereIn('plan_id', Plan::where('dedicated', true)->select('id'))->where('banned', 0)
            ->where(fn ($q) => $q->whereNull('expired_at')->orWhere('expired_at', '>', time()))
            ->eachById(function ($user) use ($assignments, &$waiting) {
                $waiting += (int) ($assignments->assignedExit($user) === null);
            });
        $this->info("出口检查通过 {$passed}/{$exits->count()}，等待可用出口的账号 {$waiting}");
        return self::SUCCESS;
    }
}
