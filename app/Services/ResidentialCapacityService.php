<?php

namespace App\Services;

use App\Models\DedicatedExit;
use App\Models\Plan;
use App\Models\Server;
use App\Models\User;
use Illuminate\Database\Eloquent\Builder;

class ResidentialCapacityService
{
    private function subscribers(): Builder
    {
        return User::where('banned', 0)
            ->where(fn ($q) => $q->whereNull('expired_at')->orWhere('expired_at', '>', time()));
    }

    private function sharedNodes(): array
    {
        $dedicatedBackends = DedicatedExit::pluck('shared_server_id')->filter()->all();
        $nodes = Server::where('show', true)->where('name', 'like', '%家宽%')
            ->whereNull('dedicated_exit_id')->with('parent')->get()
            ->filter(fn ($node) => !app(DedicatedExitService::class)->nodeExitId($node)
                && !in_array($node->parent_id ?: $node->id, $dedicatedBackends));
        return $nodes->groupBy(fn ($node) => $node->parent_id ?: $node->id)->map(function ($aliases, $backendId) {
            $groups = $aliases->flatMap(fn ($node) => $node->group_ids ?? [])->unique()->values();
            $plans = Plan::where('dedicated', false)->whereIn('group_id', $groups)->pluck('id');
            return [
                'id' => (int) $backendId, 'name' => $aliases->pluck('name')->unique()->implode(' / '),
                'subscribers' => $this->subscribers()->whereIn('plan_id', $plans)->whereIn('group_id', $groups)->count(),
            ];
        })->values()->all();
    }

    public function summary(): array
    {
        $allocator = app(DedicatedExitService::class);
        $plans = Plan::where('dedicated', true)->orderBy('sort')->orderBy('id')->get()->map(function (Plan $plan) use ($allocator) {
            $subscribers = $this->subscribers()->where('plan_id', $plan->id)->pluck('id');
            $occupied = $allocator->occupied($plan->id)->get();
            $assigned = $occupied->whereIn('user_id', $subscribers)->count();
            $exits = DedicatedExit::where('plan_id', $plan->id)->orderBy('id')->get()
                ->filter(fn ($exit) => $exit->enabled || $occupied->contains('exit_id', $exit->id))
                ->map(function (DedicatedExit $exit) use ($occupied, $subscribers) {
                    $seats = $occupied->where('exit_id', $exit->id);
                    $assigned = $seats->whereIn('user_id', $subscribers)->count();
                    $free = max(0, DedicatedExit::CAPACITY - $seats->count());
                    return [
                        'id' => $exit->id, 'name' => $exit->name, 'public_ip' => $exit->public_ip,
                        'enabled' => $exit->enabled, 'standby' => $exit->standby,
                        'healthy' => $exit->isHealthy(), 'checked_at' => $exit->checked_at,
                        'capacity' => DedicatedExit::CAPACITY, 'subscribers' => $assigned,
                        'reserved' => $seats->count() - $assigned, 'occupied' => $seats->count(),
                        'free_slots' => $exit->enabled ? $free : 0,
                        'allocatable_slots' => $exit->isHealthy() && !$exit->standby ? $free : 0,
                    ];
                })->values();
            $limit = $plan->capacity_limit === null ? null : (int) $plan->capacity_limit;
            $available = min($exits->sum('allocatable_slots'), $limit === null ? PHP_INT_MAX : max(0, $limit - $occupied->count()));
            return [
                'id' => $plan->id, 'name' => $plan->name, 'selling' => (bool) $plan->sell,
                'subscribers' => $subscribers->count(), 'assigned_subscribers' => $assigned,
                'unassigned_subscribers' => max(0, $subscribers->count() - $assigned),
                'reserved' => $occupied->count() - $assigned, 'occupied' => $occupied->count(),
                'capacity_limit' => $limit,
                'primary_capacity' => $exits->where('enabled', true)->where('standby', false)->sum('capacity'),
                'healthy_free_slots' => $exits->sum('allocatable_slots'),
                'available_slots' => $plan->sell ? $available : 0, 'exits' => $exits->all(),
            ];
        });
        return ['checked_at' => time(), 'plans' => $plans->all(), 'shared_nodes' => $this->sharedNodes()];
    }
}
