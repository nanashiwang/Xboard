<?php

namespace Tests\Feature\Dedicated;

use App\Models\{DedicatedAssignment, DedicatedExit, Order, Plan, Server, User};
use App\Services\ResidentialCapacityService;
use App\Utils\Helper;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Queue;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class ResidentialCapacityTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        Queue::fake();
    }

    private function plan(array $extra = []): Plan
    {
        return Plan::create($extra + ['name' => '独享家宽', 'group_id' => 5, 'dedicated' => true,
            'transfer_enable' => 200, 'prices' => ['monthly' => 5900], 'show' => true, 'sell' => true, 'capacity_limit' => 5]);
    }

    private function user(array $extra = []): User
    {
        return User::create($extra + ['email' => Helper::guid().'@example.test', 'password' => bcrypt('test'),
            'uuid' => Helper::guid(), 'token' => Helper::guid(), 'expired_at' => time()+3600, 'banned' => false]);
    }

    private function exit(Plan $plan, array $extra = []): DedicatedExit
    {
        return DedicatedExit::create($extra + ['plan_id' => $plan->id, 'name' => '家宽节点',
            'public_ip' => '203.0.113.'.(DedicatedExit::count()+1), 'enabled' => true, 'healthy' => true, 'checked_at' => time(), 'standby' => false]);
    }

    private function seat(Plan $plan, DedicatedExit $exit, User $user, int $slot, ?int $status = null, int $ttl = 600): void
    {
        $order = $status === null ? null : Order::create(['user_id' => $user->id, 'plan_id' => $plan->id,
            'period' => 'monthly', 'type' => 1, 'trade_no' => Helper::guid(), 'total_amount' => 5900, 'status' => $status]);
        DedicatedAssignment::create(['plan_id' => $plan->id, 'exit_id' => $exit->id, 'user_id' => $user->id,
            'slot' => $slot, 'order_id' => $order?->id, 'reserved_until' => time()+$ttl]);
    }

    private function url(): string
    {
        return '/api/v2/'.admin_setting('secure_path', admin_setting('frontend_admin_path', hash('crc32b', config('app.key')))).'/stat/getResidentialCapacity';
    }

    public function test_endpoint_requires_admin_and_returns_only_aggregate_data(): void
    {
        $this->getJson($this->url())->assertForbidden();
        Sanctum::actingAs($this->user());
        $this->getJson($this->url())->assertForbidden();
        Sanctum::actingAs($this->user(['is_admin' => true]));
        $this->getJson($this->url())->assertOk()->assertJsonPath('data.plans', [])->assertJsonPath('data.shared_nodes', [])
            ->assertHeader('Cache-Control', 'no-store, private');
    }

    public function test_subscriptions_reservations_renewals_and_stale_records_have_distinct_counts_without_writes(): void
    {
        $p = $this->plan(); $e = $this->exit($p); $standby = $this->exit($p, ['standby' => true]);
        $this->seat($p, $e, $this->user(['plan_id' => $p->id]), 1, Order::STATUS_PENDING);
        $this->seat($p, $e, $this->user(['plan_id' => $p->id, 'expired_at' => null, 'transfer_enable' => 0]), 2);
        $this->seat($p, $e, $this->user(), 3, Order::STATUS_PENDING);
        $this->seat($p, $e, $this->user(['plan_id' => $p->id, 'expired_at' => time()-1]), 4);
        $this->seat($p, $e, $this->user(['plan_id' => $p->id, 'banned' => true]), 5);
        $this->seat($p, $standby, $this->user(), 1, Order::STATUS_PROCESSING, -600);
        $this->seat($p, $standby, $this->user(), 2, Order::STATUS_PENDING, -600);
        $before = DedicatedAssignment::all()->toArray();
        $r = app(ResidentialCapacityService::class)->summary()['plans'][0];
        $this->assertSame(2, $r['subscribers']);
        $this->assertSame(2, $r['assigned_subscribers']);
        $this->assertSame(2, $r['reserved']);
        $this->assertSame(4, $r['occupied']);
        $this->assertSame(1, $r['available_slots']);
        $this->assertSame(5, $r['primary_capacity']);
        $this->assertSame(3, $r['exits'][0]['occupied']);
        $this->assertSame(2, $r['exits'][0]['allocatable_slots']);
        $this->assertSame(0, $r['exits'][1]['allocatable_slots']);
        $this->assertSame($before, DedicatedAssignment::all()->toArray());
    }

    public function test_health_sales_limit_and_unassigned_subscribers_do_not_overstate_capacity(): void
    {
        $p = $this->plan(['capacity_limit' => null]); $e = $this->exit($p, ['checked_at' => time()-301]);
        $this->user(['plan_id' => $p->id]);
        $r = app(ResidentialCapacityService::class)->summary()['plans'][0];
        $this->assertSame(1, $r['unassigned_subscribers']);
        $this->assertSame(0, $r['available_slots']);
        $this->assertFalse($r['exits'][0]['healthy']);
        $e->update(['checked_at' => time()]);
        $this->assertSame(5, app(ResidentialCapacityService::class)->summary()['plans'][0]['available_slots']);
        $p->update(['capacity_limit' => 2]);
        $this->assertSame(2, app(ResidentialCapacityService::class)->summary()['plans'][0]['available_slots']);
        $p->update(['sell' => false]);
        $this->assertSame(0, app(ResidentialCapacityService::class)->summary()['plans'][0]['available_slots']);
    }

    public function test_disabled_exit_with_occupancy_is_visible_but_cannot_offer_capacity(): void
    {
        $p = $this->plan(); $e = $this->exit($p, ['enabled' => false]);
        $this->seat($p, $e, $this->user(['plan_id' => $p->id]), 1);
        $this->exit($p, ['enabled' => false]);
        $r = app(ResidentialCapacityService::class)->summary()['plans'][0];
        $this->assertCount(1, $r['exits']);
        $this->assertSame(1, $r['exits'][0]['subscribers']);
        $this->assertSame(0, $r['available_slots']);
    }

    public function test_shared_aliases_deduplicate_users_and_exclude_dedicated_retired_and_expired_subscriptions(): void
    {
        $p = $this->plan(['dedicated' => false, 'group_id' => 1]);
        $q = $this->plan(['dedicated' => false, 'group_id' => 2]);
        $dedicated = $this->plan(['group_id' => 1]);
        foreach ([$p, $q, $dedicated] as $plan) $this->user(['plan_id' => $plan->id, 'group_id' => $plan->group_id]);
        $this->user(['plan_id' => $p->id, 'group_id' => 1, 'expired_at' => time()-1]);
        $backend = Server::create(['name' => '后端', 'type' => 'vless', 'host' => 'node.test', 'port' => 443, 'server_port' => 31001, 'rate' => 2, 'show' => false, 'group_ids' => ['1','2']]);
        foreach ([['1'], ['1','2']] as $groups) Server::create(['name' => '美国01｜家宽', 'type' => 'vless', 'host' => 'node.test', 'port' => 443,
            'server_port' => 31001, 'rate' => 2, 'show' => true, 'parent_id' => $backend->id, 'group_ids' => $groups]);
        $r = app(ResidentialCapacityService::class)->summary()['shared_nodes'];
        $this->assertCount(1, $r); $this->assertSame(2, $r[0]['subscribers']);
        Server::where('parent_id', $backend->id)->update(['show' => false]);
        $this->assertSame([], app(ResidentialCapacityService::class)->summary()['shared_nodes']);
    }
}
