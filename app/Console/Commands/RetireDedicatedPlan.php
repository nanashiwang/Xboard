<?php

namespace App\Console\Commands;

use App\Models\Order;
use App\Models\Plan;
use App\Models\User;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;

class RetireDedicatedPlan extends Command
{
    protected $signature = 'dedicated:retire {plan} {name}';
    protected $description = '核对独享套餐身份、有效订阅及未完成订单后关闭展示、新购和续费';

    public function handle(): int
    {
        return DB::transaction(function () {
            $plan = Plan::whereKey($this->argument('plan'))->where('name', $this->argument('name'))
                ->where('dedicated', true)->where('is_proxy', false)->lockForUpdate()->firstOrFail();

            $active = User::where('plan_id', $plan->id)->where('banned', false)
                ->where(fn ($q) => $q->whereNull('expired_at')->orWhere('expired_at', '>', time()))->count();
            $orders = Order::where('plan_id', $plan->id);
            $pending = (clone $orders)->where('status', Order::STATUS_PENDING)->count();
            $processing = (clone $orders)->where('status', Order::STATUS_PROCESSING)->count();
            $this->info("plan={$plan->id} active={$active} pending={$pending} processing={$processing} orders=".$orders->count());
            if ($active || $pending || $processing) {
                $this->error('套餐仍有有效订阅或未完成订单');
                return self::FAILURE;
            }

            $plan->fill(['show' => false, 'sell' => false, 'renew' => false]);
            if ($plan->isDirty()) $plan->saveOrFail();
            $this->info('展示、新购与续费均已关闭');
            return self::SUCCESS;
        }, 5);
    }
}
