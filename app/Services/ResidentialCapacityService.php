<?php

namespace App\Services;

use App\Models\DedicatedExit;
use App\Models\Plan;
use App\Models\ResidentialProxyHost;
use App\Models\Server;
use App\Models\User;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Support\Facades\DB;

class ResidentialCapacityService
{
    private function subscribers(): Builder
    {
        return User::where('banned', 0)
            ->where(fn ($q) => $q->whereNull('expired_at')->orWhere('expired_at', '>', time()));
    }

    private function sharedNodes(): array
    {
        $nodes = Server::where('show', true)->where('name', 'like', '%家宽%')
            ->whereNull('dedicated_exit_id')->with('parent')->get()
            ->filter(fn ($node) => !app(DedicatedExitService::class)->nodeExitId($node));
        return $nodes->groupBy(fn ($node) => $node->parent_id ?: $node->id)->map(function ($aliases, $backendId) {
            $groups = $aliases->flatMap(fn ($node) => $node->group_ids ?? [])->unique()->values();
            $plans = Plan::where('dedicated', false)->whereIn('group_id', $groups)->pluck('id');
            // A shared backend may also have a current or retired dedicated-pool
            // record. Public access comes from ordinary plan groups, not pool history.
            if ($plans->isEmpty()) return null;
            return [
                'id' => (int) $backendId, 'name' => $aliases->pluck('name')->unique()->implode(' / '),
                'subscribers' => $this->subscribers()->whereIn('plan_id', $plans)->whereIn('group_id', $groups)->count(),
            ];
        })->filter()->values()->all();
    }

    private function proxyInventory(int $now): array
    {
        // One read captures host eligibility, reservations and ownership at the same instant.
        $rows = DB::table('residential_proxy_hosts as h')
            ->leftJoin('residential_proxy_endpoints as e', 'e.host_id', '=', 'h.id')
            ->leftJoin('v2_user as u', 'u.id', '=', 'e.user_id')
            ->select('h.id as host_id', 'h.address', 'h.enabled', 'h.seen_at', 'e.id as endpoint_id',
                'e.user_id', 'e.expires_at', 'e.reserved_order_id', 'u.banned')
            ->selectSub(ResidentialProxyHost::acceptingOrders($now)->selectRaw('1')
                ->whereColumn('residential_proxy_hosts.id', 'h.id'), 'accepting_orders')
            ->orderBy('h.id')->cursor();

        $empty = array_fill_keys(['ports', 'active', 'expired', 'restricted', 'reserved', 'available', 'unavailable'], 0);
        $hosts = $buyers = [];
        foreach ($rows as $row) {
            $hosts[$row->host_id] ??= $empty + [
                'address' => $row->address, 'seen_at' => $row->seen_at,
                'status' => !$row->enabled ? 'disabled' : ($row->accepting_orders ? 'online' : 'stale'),
            ];
            if ($row->endpoint_id === null) continue;

            if ($row->user_id !== null) {
                if ($row->expires_at <= $now) {
                    $bucket = 'expired';
                } elseif ($row->banned === null || $row->banned) {
                    $bucket = 'restricted';
                } else {
                    $bucket = 'active';
                    $buyers[$row->user_id] = true;
                }
            } elseif ($row->reserved_order_id !== null) {
                $bucket = 'reserved';
            } else {
                $bucket = $row->accepting_orders ? 'available' : 'unavailable';
            }
            $hosts[$row->host_id]['ports']++;
            $hosts[$row->host_id][$bucket]++;
        }

        $totals = $empty;
        foreach (array_keys($totals) as $key) {
            $totals[$key] = array_sum(array_column($hosts, $key));
        }
        return ['buyers' => count($buyers), 'totals' => $totals, 'hosts' => array_values($hosts)];
    }

    public function summary(): array
    {
        $allocator = app(DedicatedExitService::class);
        $plans = Plan::where('dedicated', true)->orderBy('sort')->orderBy('id')->get()->map(function (Plan $plan) use ($allocator) {
            $subscribers = $this->subscribers()->where('plan_id', $plan->id)->pluck('id');
            $occupied = $allocator->occupied($plan->id)->get();
            if (!$plan->show && !$plan->sell && !$plan->renew && $subscribers->isEmpty() && $occupied->isEmpty()) {
                return null;
            }
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
        })->filter()->values();
        $now = time();
        return ['checked_at' => $now, 'plans' => $plans->all(), 'shared_nodes' => $this->sharedNodes(),
            'proxy_inventory' => $this->proxyInventory($now)];
    }
}
