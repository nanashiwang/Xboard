<?php

namespace App\Services;

use App\Exceptions\ApiException;
use App\Exceptions\DedicatedExitUnavailableException;
use App\Models\DedicatedAssignment;
use App\Models\DedicatedExit;
use App\Models\Order;
use App\Models\Plan;
use App\Models\Server;
use App\Models\User;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Support\Facades\DB;

class DedicatedExitService
{
    /** Serialize allocation for this plan on both SQLite and MySQL. Caller owns the transaction. */
    public function lock(Plan $plan): void
    {
        Plan::whereKey($plan->id)->increment('allocation_version');
    }

    public function occupied(int $planId): Builder
    {
        return DedicatedAssignment::where('plan_id', $planId)->where(function ($query) {
            $query->whereExists(function ($users) {
                $users->selectRaw('1')->from('v2_user')
                    ->whereColumn('v2_user.id', 'v2_dedicated_assignment.user_id')
                    ->whereColumn('v2_user.plan_id', 'v2_dedicated_assignment.plan_id')
                    ->where('banned', 0)
                    ->where(fn ($q) => $q->whereNull('expired_at')->orWhere('expired_at', '>', time()));
            })->orWhereExists(function ($orders) {
                $orders->selectRaw('1')->from('v2_order')
                    ->whereColumn('v2_order.id', 'v2_dedicated_assignment.order_id')
                    ->where(function ($q) {
                        $q->where('status', Order::STATUS_PROCESSING)
                            ->orWhere(fn ($pending) => $pending->where('status', Order::STATUS_PENDING)
                                ->where('v2_dedicated_assignment.reserved_until', '>', time()));
                    });
            });
        });
    }

    private function healthyExits(int $planId, bool $includeStandby = false)
    {
        return DedicatedExit::where('plan_id', $planId)->where('enabled', true)->where('healthy', true)
            ->where('checked_at', '>=', time() - DedicatedExit::HEALTH_TTL)
            ->when(!$includeStandby, fn ($q) => $q->where('standby', false))
            ->orderBy('standby')->orderBy('id')->get();
    }

    public function hasCapacity(Plan $plan): bool
    {
        $occupied = $this->occupied($plan->id)->get();
        if ($plan->capacity_limit !== null && $occupied->count() >= $plan->capacity_limit) {
            return false;
        }
        foreach ($this->healthyExits($plan->id) as $exit) {
            if ($occupied->where('exit_id', $exit->id)->count() < DedicatedExit::CAPACITY) {
                return true;
            }
        }
        return false;
    }

    private function prune(int $planId): void
    {
        $keep = $this->occupied($planId)->pluck('id');
        DedicatedAssignment::where('plan_id', $planId)->whereNotIn('id', $keep)->get()->each(function ($assignment) {
            $this->record($assignment->user_id, $assignment->exit_id, null, 'expired_or_cancelled');
            $assignment->delete();
        });
    }

    /** Reserve before checkout, not after payment: concurrent purchases cannot sell the same seat. */
    public function reserve(Order $order, User $user, Plan $plan): void
    {
        $this->lock($plan);
        $this->prune($plan->id);
        $assignment = DedicatedAssignment::where('user_id', $user->id)->first();
        if ($assignment && $assignment->plan_id === $plan->id) {
            // Active renewals retain their seat, including while the exit is being repaired.
            return;
        }
        if (!$this->hasCapacity($plan)) {
            throw new ApiException(__('Current product is sold out'));
        }
        $slot = $this->freeSlot($plan->id);
        if (!$slot) {
            throw new ApiException(__('Current product is sold out'));
        }
        DedicatedAssignment::create([
            'plan_id' => $plan->id, 'user_id' => $user->id, ...$slot,
            'order_id' => $order->id, 'reserved_until' => time() + 7200,
        ]);
        $this->record($user->id, null, $slot['exit_id'], 'order_reserved');
    }

    private function freeSlot(int $planId, bool $includeStandby = false): ?array
    {
        $used = DedicatedAssignment::where('plan_id', $planId)->get()->groupBy('exit_id');
        // Fill one exit before using another; unused standby exits remain available for failures.
        foreach ($this->healthyExits($planId, $includeStandby) as $exit) {
            $slots = ($used[$exit->id] ?? collect())->pluck('slot')->all();
            for ($slot = 1; $slot <= DedicatedExit::CAPACITY; $slot++) {
                if (!in_array($slot, $slots, true)) {
                    return ['exit_id' => $exit->id, 'slot' => $slot];
                }
            }
        }
        return null;
    }

    /** Called after the paid user's entitlement is saved, within the order transaction. */
    public function activate(User $user, Plan $plan): void
    {
        if (!$plan->dedicated) {
            $this->release($user->id, 'plan_changed');
            return;
        }
        $exit = $this->assignedExit($user);
        if (!$exit) {
            throw new DedicatedExitUnavailableException();
        }
        DedicatedAssignment::where('user_id', $user->id)->update(['order_id' => null, 'reserved_until' => null]);
    }

    /** Reuse a healthy allocation; migrate only on failure and never exceed five accounts per exit. */
    public function assignedExit(User $user): ?int
    {
        $plan = $user->plan_id ? Plan::find($user->plan_id) : null;
        if (!$plan?->dedicated || $user->banned || ($user->expired_at !== null && $user->expired_at <= time())) {
            return null;
        }
        return DB::transaction(function () use ($user, $plan) {
            $this->lock($plan);
            $user = User::lockForUpdate()->find($user->id);
            if (!$user || $user->plan_id !== $plan->id || $user->banned
                || ($user->expired_at !== null && $user->expired_at <= time())) {
                return null;
            }
            $this->prune($plan->id);
            $assignment = DedicatedAssignment::where('user_id', $user->id)->first();
            $exit = $assignment ? DedicatedExit::find($assignment->exit_id) : null;
            if ($assignment?->plan_id === $plan->id && $exit?->isHealthy()) {
                return $exit->id;
            }
            $slot = $this->freeSlot($plan->id, true);
            if (!$slot) {
                // Keep the old reservation for recovery. Public routes remain usable meanwhile.
                return null;
            }
            $oldExit = $assignment?->exit_id;
            DedicatedAssignment::updateOrCreate(['user_id' => $user->id], [
                'plan_id' => $plan->id, ...$slot, 'order_id' => null, 'reserved_until' => null,
            ]);
            $this->record($user->id, $oldExit, $slot['exit_id'], $oldExit ? 'exit_failed' : 'subscription_assigned');
            DB::afterCommit(fn () => NodeSyncService::notifyUsersUpdatedByGroup((int) $user->group_id));
            return $slot['exit_id'];
        }, 5);
    }

    public function release(int $userId, string $reason): void
    {
        $assignment = DedicatedAssignment::where('user_id', $userId)->first();
        if ($assignment) {
            $this->record($userId, $assignment->exit_id, null, $reason);
            $assignment->delete();
        }
    }

    public function nodeExitId(Server $server): ?int
    {
        return $server->dedicated_exit_id ?: ($server->parent_id ? $server->parent?->dedicated_exit_id : null);
    }

    public function authorizedUserIds(Server $server): ?array
    {
        $exitId = $this->nodeExitId($server);
        // A pooled backend keeps its public authorization. Only accounts on this
        // fixed-exit plan require an allocation; do not mark the shared node exclusive.
        $shared = !$exitId ? DedicatedExit::where('shared_server_id', $server->id)->first() : null;
        if ($shared) {
            $assigned = $shared->isHealthy() ? DedicatedAssignment::where('exit_id', $shared->id)
                ->where('plan_id', $shared->plan_id)->pluck('user_id')->all() : [];
            return User::whereIn('group_id', $server->group_ids ?? [])
                ->where(function ($q) use ($shared, $assigned) {
                    $q->whereNull('plan_id')->orWhere('plan_id', '<>', $shared->plan_id)
                        ->orWhereIn('id', $assigned);
                })->pluck('id')->all();
        }
        if (!$exitId) {
            return null; // Public node: keep the existing group authorization.
        }
        $exit = DedicatedExit::find($exitId);
        if (!$exit?->isHealthy()) {
            return [];
        }
        return DedicatedAssignment::where('exit_id', $exitId)
            ->whereExists(fn ($q) => $q->selectRaw('1')->from('v2_user')
                ->whereColumn('v2_user.id', 'v2_dedicated_assignment.user_id')
                ->whereColumn('v2_user.plan_id', 'v2_dedicated_assignment.plan_id'))
            ->pluck('user_id')->all();
    }

    private function record(int $userId, ?int $from, ?int $to, string $reason): void
    {
        DB::table('v2_dedicated_assignment_log')->insert([
            'user_id' => $userId, 'from_exit_id' => $from, 'to_exit_id' => $to,
            'reason' => $reason, 'created_at' => time(),
        ]);
    }
}
