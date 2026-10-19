<?php

namespace Tests\Feature\Dedicated;

use App\Exceptions\ApiException;
use App\Jobs\OrderHandleJob;
use App\Models\DedicatedAssignment;
use App\Models\DedicatedExit;
use App\Models\Order;
use App\Models\Plan;
use App\Models\Server;
use App\Models\ServerMachine;
use App\Models\User;
use App\Services\DedicatedExitService;
use App\Services\DedicatedExitHealthService;
use App\Services\NodeSyncService;
use App\Services\OrderService;
use App\Services\PlanService;
use App\Services\ServerService;
use App\Utils\Helper;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Facades\Queue;
use Illuminate\Support\Facades\Redis;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class DedicatedExitTest extends TestCase
{
    use RefreshDatabase;

    private Plan $plan;
    private DedicatedExit $exit;
    private Server $public;
    private Server $private;

    protected function setUp(): void
    {
        parent::setUp();
        Queue::fake();
        $this->plan = Plan::create([
            'name' => '美国独享家宽IP', 'group_id' => 5, 'dedicated' => true,
            'transfer_enable' => 200, 'prices' => ['monthly' => 59], 'speed_limit' => 10,
            'device_limit' => null, 'show' => true, 'sell' => true, 'renew' => true,
            'capacity_limit' => 15, 'reset_traffic_method' => Plan::RESET_TRAFFIC_MONTHLY,
        ]);
        $this->exit = $this->exit('203.0.113.1');
        $this->public = $this->node('公共线路');
        $this->private = $this->node('美国独享家宽IP', $this->exit->id);
    }

    private function exit(string $ip, bool $standby = false): DedicatedExit
    {
        return DedicatedExit::create([
            'name' => $ip, 'plan_id' => $this->plan->id, 'public_ip' => $ip,
            'enabled' => true, 'healthy' => true, 'checked_at' => time(), 'standby' => $standby,
        ]);
    }

    private function node(string $name, ?int $exitId = null): Server
    {
        return Server::create([
            'name' => $name, 'type' => 'vless', 'host' => 'test.example', 'port' => '443',
            'server_port' => 31001, 'group_ids' => ['5'], 'rate' => 1, 'show' => true,
            'enabled' => true, 'dedicated_exit_id' => $exitId, 'protocol_settings' => [],
        ]);
    }

    private function user(bool $active = false): User
    {
        return User::create([
            'email' => Helper::guid() . '@example.test', 'password' => bcrypt('test-password'),
            'uuid' => Helper::guid(), 'token' => Helper::guid(), 'banned' => false,
            'plan_id' => $active ? $this->plan->id : null, 'group_id' => $active ? 5 : null,
            'transfer_enable' => $active ? 200 * 1073741824 : 0,
            'expired_at' => $active ? time() + 86400 : 0, 'u' => 0, 'd' => 0,
        ]);
    }

    private function order(User $user): Order
    {
        return OrderService::createFromRequest($user, $this->plan, 'month_price');
    }

    private function complete(Order $order): void
    {
        $order->update(['status' => Order::STATUS_PROCESSING]);
        (new OrderService($order))->open();
    }

    private function assignAsAdmin(User $user, Plan $plan, string $period = 'half_year_price')
    {
        $admin = $this->user();
        $admin->update(['is_admin' => true]);
        Sanctum::actingAs($admin);
        $path = admin_setting('secure_path', admin_setting('frontend_admin_path', hash('crc32b', config('app.key'))));
        return $this->postJson('/api/v2/' . $path . '/order/assign', [
            'email' => $user->email, 'plan_id' => $plan->id,
            'period' => $period, 'total_amount' => 0,
        ]);
    }

    public function test_admin_zero_amount_assignment_rejects_unavailable_exit_without_leaving_an_order(): void
    {
        $user = $this->user();
        $this->exit->update(['healthy' => false]);
        $this->assignAsAdmin($user, $this->plan)->assertStatus(400);
        $this->assertSame(0, Order::count());
        $this->assertSame(0, DedicatedAssignment::count());
        $this->assertNull($user->fresh()->plan_id);
    }

    public function test_admin_assignment_cannot_overbook_a_full_dedicated_exit(): void
    {
        for ($i = 0; $i < DedicatedExit::CAPACITY; $i++) {
            $this->order($this->user());
        }
        $this->assignAsAdmin($this->user(), $this->plan)->assertStatus(400);
        $this->assertSame(5, Order::count());
        $this->assertSame(5, DedicatedAssignment::count());
    }

    public function test_admin_assignment_reserves_a_seat_and_can_complete(): void
    {
        $user = $this->user();
        $tradeNo = $this->assignAsAdmin($user, $this->plan)->assertOk()->json('data');
        $order = Order::where('trade_no', $tradeNo)->firstOrFail();
        $this->assertSame(Plan::PERIOD_HALF_YEARLY, $order->period);
        $this->assertSame($order->id, DedicatedAssignment::sole()->order_id);
        $this->assertSame(0, $order->total_amount);
        $this->complete($order);
        $this->assertSame(Order::STATUS_COMPLETED, $order->fresh()->status);
        $this->assertSame($this->plan->id, $user->fresh()->plan_id);
        $this->assertNull(DedicatedAssignment::sole()->reserved_until);
    }

    public function test_admin_renewal_retains_existing_seat_when_exit_is_temporarily_unhealthy(): void
    {
        $user = $this->user();
        $this->complete($this->order($user));
        $assignment = DedicatedAssignment::sole();
        $this->exit->update(['healthy' => false]);
        $this->assignAsAdmin($user->fresh(), $this->plan)->assertOk();
        $this->assertSame(1, DedicatedAssignment::count());
        $this->assertSame($assignment->id, DedicatedAssignment::sole()->id);
    }

    public function test_admin_ordinary_plan_and_traffic_reset_do_not_require_new_exit_capacity(): void
    {
        $this->exit->update(['healthy' => false]);
        $ordinary = Plan::create(['name' => '普通套餐', 'group_id' => 1, 'transfer_enable' => 25, 'prices' => ['monthly' => 10]]);
        $this->assignAsAdmin($this->user(), $ordinary)->assertOk();
        $this->assignAsAdmin($this->user(true), $this->plan, 'reset_price')->assertOk();
        $this->assertSame(2, Order::count());
        $this->assertSame(0, DedicatedAssignment::count());
    }

    private function ordinarySubscriber(int $paidAmount = 12000, int $creditedAmount = 2000): array
    {
        $this->freezeTime();
        admin_setting(['surplus_enable' => 1, 'plan_change_enable' => 1, 'change_order_event_id' => 0]);
        $oldPlan = Plan::create([
            'name' => '普通套餐', 'group_id' => 1, 'transfer_enable' => 100,
            'prices' => ['monthly' => 120], 'show' => true, 'sell' => true, 'renew' => true,
        ]);
        $user = $this->user();
        $user->update([
            'plan_id' => $oldPlan->id, 'group_id' => 1, 'balance' => 0,
            'transfer_enable' => 100 * 1073741824, 'expired_at' => now()->addMonth()->timestamp,
        ]);
        $previous = Order::create([
            'user_id' => $user->id, 'plan_id' => $oldPlan->id, 'period' => Plan::PERIOD_MONTHLY,
            'trade_no' => Helper::generateOrderNo(), 'total_amount' => $paidAmount,
            'surplus_credit' => $creditedAmount, 'type' => Order::TYPE_UPGRADE,
            'status' => Order::STATUS_COMPLETED,
        ]);

        return [$user, $previous];
    }

    public function test_upgrade_with_excess_surplus_creates_and_completes_without_gateway_payment(): void
    {
        Queue::fake()->except([OrderHandleJob::class]);
        [$user, $previous] = $this->ordinarySubscriber();
        Sanctum::actingAs($user);
        $tradeNo = $this->postJson('/api/v1/user/order/save', [
            'plan_id' => $this->plan->id, 'period' => 'month_price',
        ])->assertOk()->json('data');

        $order = Order::where('trade_no', $tradeNo)->firstOrFail();
        $this->assertSame(0, $order->total_amount);
        $this->assertSame(10000, $order->surplus_amount);
        $this->assertSame(4100, $order->surplus_credit);
        $this->assertEquals(0, $user->fresh()->balance);
        $this->assertSame(Order::STATUS_COMPLETED, $previous->fresh()->status);
        $this->assertSame($order->id, DedicatedAssignment::sole()->order_id);
        $this->getJson('/api/v1/user/order/detail?trade_no=' . $tradeNo)->assertOk()
            ->assertJsonPath('data.surplus_credit', 4100)
            ->assertJsonPath('data.refund_amount', 4100);

        $this->postJson('/api/v1/user/order/checkout', ['trade_no' => $tradeNo])
            ->assertOk()->assertJsonPath('type', -1)->assertJsonPath('data', true);
        $this->assertSame(Order::STATUS_COMPLETED, $order->fresh()->status);
        $this->assertSame(Order::STATUS_DISCOUNTED, $previous->fresh()->status);
        $this->assertEquals(4100, $user->fresh()->balance);
        $this->assertSame($this->plan->id, $user->fresh()->plan_id);
        $this->assertSame(200 * 1073741824, $user->fresh()->transfer_enable);
        $this->assertNull(DedicatedAssignment::sole()->reserved_until);
        $expiry = $user->fresh()->expired_at;
        (new OrderService($order->fresh()))->open();
        $this->assertEquals(4100, $user->fresh()->balance);
        $this->assertSame($expiry, $user->fresh()->expired_at);
        $this->assertSame(1, DedicatedAssignment::count());
    }

    public function test_cancelled_upgrade_does_not_credit_balance_or_consume_previous_subscription(): void
    {
        [$user, $previous] = $this->ordinarySubscriber();
        $order = $this->order($user);
        $this->assertSame(4100, $order->surplus_credit);
        $this->assertTrue((new OrderService($order))->cancel());
        $this->assertEquals(0, $user->fresh()->balance);
        $this->assertSame($previous->plan_id, $user->fresh()->plan_id);
        $this->assertSame(Order::STATUS_COMPLETED, $previous->fresh()->status);
        $this->assertTrue((new PlanService($this->plan))->hasCapacity($this->plan));
        $this->assertSame(0, app(DedicatedExitService::class)->occupied($this->plan->id)->count());
    }

    public function test_upgrade_deducts_previous_credit_before_calculating_amount_still_due(): void
    {
        [$user] = $this->ordinarySubscriber(5000, 2000);
        $order = $this->order($user);
        $this->assertSame(3000, $order->surplus_amount);
        $this->assertSame(2900, $order->total_amount);
        $this->assertNull($order->surplus_credit);
        $this->assertEquals(0, $user->fresh()->balance);
    }

    public function test_five_pending_orders_fill_an_exit_and_hide_the_plan_without_authorizing_unpaid_users(): void
    {
        for ($i = 0; $i < 5; $i++) {
            $this->order($this->user());
        }
        $this->assertSame(5, DedicatedAssignment::count());
        $this->assertSame([1, 2, 3, 4, 5], DedicatedAssignment::orderBy('slot')->pluck('slot')->all());
        $this->assertFalse((new PlanService($this->plan))->hasCapacity($this->plan));
        $this->getJson('/api/v1/guest/plan/fetch')->assertOk()->assertJsonCount(0, 'data');
        $this->assertCount(0, ServerService::getAvailableUsers($this->private));
        try {
            $this->order($this->user());
            $this->fail('A sixth account must not purchase the full exit');
        } catch (ApiException $e) {
            $this->assertSame(5, Order::count());
        }
    }

    public function test_paid_activation_has_200gb_no_ip_limit_and_only_its_assigned_exit(): void
    {
        $other = $this->exit('203.0.113.2');
        $otherNode = $this->node('别人的出口', $other->id);
        $user = $this->user();
        $order = $this->order($user);
        $this->assertSame(5900, $order->total_amount);
        $this->complete($order);
        $user->refresh();
        $this->assertSame(200 * 1073741824, $user->transfer_enable);
        $this->assertNull($user->device_limit);
        $this->assertEquals(10, $user->speed_limit);
        $this->assertSame([$this->public->id, $this->private->id], array_column(ServerService::getAvailableServers($user), 'id'));
        $this->assertEquals([$user->id], ServerService::getAvailableUsers($this->private)->pluck('id')->all());
        $this->assertCount(0, ServerService::getAvailableUsers($otherNode));
        $this->assertNull(DedicatedAssignment::first()->reserved_until);
    }

    public function test_full_exit_renewal_keeps_one_seat_and_paid_order_is_idempotent(): void
    {
        $users = [];
        for ($i = 0; $i < 5; $i++) {
            $users[] = $u = $this->user();
            $this->complete($this->order($u));
        }
        $user = $users[0]->fresh();
        $assignment = DedicatedAssignment::where('user_id', $user->id)->first();
        $order = $this->order($user);
        $this->complete($order);
        $expiry = $user->fresh()->expired_at;
        (new OrderService($order->fresh()))->open();
        $this->assertSame($expiry, $user->fresh()->expired_at);
        $this->assertSame(5, DedicatedAssignment::count());
        $this->assertSame($assignment->id, DedicatedAssignment::where('user_id', $user->id)->value('id'));
    }

    public function test_cancelled_and_expired_reservations_return_capacity(): void
    {
        for ($i = 0; $i < 5; $i++) {
            $order = $this->order($this->user());
        }
        (new OrderService($order))->cancel();
        $this->assertTrue((new PlanService($this->plan))->hasCapacity($this->plan));
        $new = $this->order($this->user());
        $this->assertSame(5, DedicatedAssignment::count());
        DedicatedAssignment::where('order_id', $new->id)->update(['reserved_until' => time() - 1]);
        $this->assertTrue((new PlanService($this->plan))->hasCapacity($this->plan));
        $this->order($this->user());
        $this->assertSame(5, DedicatedAssignment::count());
    }

    public function test_processing_payment_does_not_expire_its_reservation(): void
    {
        for ($i = 0; $i < 5; $i++) {
            $order = $this->order($this->user());
        }
        $order->update(['status' => Order::STATUS_PROCESSING]);
        DedicatedAssignment::where('order_id', $order->id)->update(['reserved_until' => time() - 1]);
        $this->assertFalse((new PlanService($this->plan))->hasCapacity($this->plan));
    }

    public function test_failure_migrates_to_standby_on_subscription_update_and_recovery_does_not_move_it_back(): void
    {
        $standby = $this->exit('203.0.113.2', true);
        $backup = $this->node('备用出口', $standby->id);
        $user = $this->user();
        $this->complete($this->order($user));
        $user->refresh();
        $this->exit->update(['healthy' => false]);
        $this->assertSame([$this->public->id, $backup->id], array_column(ServerService::getAvailableServers($user), 'id'));
        $this->assertCount(0, ServerService::getAvailableUsers($this->private));
        $this->assertEquals([$user->id], ServerService::getAvailableUsers($backup)->pluck('id')->all());
        $this->exit->update(['healthy' => true]);
        $this->assertSame($standby->id, app(DedicatedExitService::class)->assignedExit($user));
        $this->assertDatabaseHas('v2_dedicated_assignment_log', ['user_id' => $user->id, 'reason' => 'exit_failed']);
    }

    public function test_exhausted_failover_capacity_never_overallocates_and_public_routes_survive(): void
    {
        $standby = $this->exit('203.0.113.2', true);
        $this->node('备用出口', $standby->id);
        for ($i = 1; $i <= 5; $i++) {
            DedicatedAssignment::create(['user_id' => $this->user(true)->id, 'plan_id' => $this->plan->id, 'exit_id' => $standby->id, 'slot' => $i]);
        }
        $user = $this->user();
        $this->complete($this->order($user));
        $this->exit->update(['healthy' => false]);
        $this->assertSame([$this->public->id], array_column(ServerService::getAvailableServers($user->fresh()), 'id'));
        $this->assertSame(5, DedicatedAssignment::where('exit_id', $standby->id)->count());
        $this->assertSame($this->exit->id, DedicatedAssignment::where('user_id', $user->id)->value('exit_id'));
    }

    public function test_standby_is_not_sold_and_stale_health_stops_new_sales(): void
    {
        $this->exit('203.0.113.2', true);
        $this->exit->update(['checked_at' => time() - 301]);
        $this->assertFalse((new PlanService($this->plan))->hasCapacity($this->plan));
    }

    public function test_exhausted_traffic_retains_seat_but_expired_account_releases_it(): void
    {
        $user = $this->user();
        $this->complete($this->order($user));
        $user->refresh()->update(['u' => 200 * 1073741824]);
        $this->assertSame(1, app(DedicatedExitService::class)->occupied($this->plan->id)->count());
        $this->assertCount(0, ServerService::getAvailableUsers($this->private));
        $user->update(['expired_at' => time() - 1]);
        $this->assertSame(0, app(DedicatedExitService::class)->occupied($this->plan->id)->count());
    }

    public function test_regular_plan_cannot_see_or_authenticate_to_private_nodes_even_with_same_group(): void
    {
        $regular = Plan::create(['name' => '普通套餐', 'group_id' => 5, 'transfer_enable' => 200]);
        $user = $this->user(true);
        $user->update(['plan_id' => $regular->id]);
        $this->assertSame([$this->public->id], array_column(ServerService::getAvailableServers($user), 'id'));
        $this->assertCount(0, ServerService::getAvailableUsers($this->private));
    }

    public function test_child_nodes_inherit_private_authorization_from_parent(): void
    {
        $child = $this->node('前端显示节点');
        $child->update(['parent_id' => $this->private->id]);
        $user = $this->user(true);
        $this->assertCount(0, ServerService::getAvailableUsers($child));
        app(DedicatedExitService::class)->assignedExit($user);
        $this->assertEquals([$user->id], ServerService::getAvailableUsers($child)->pluck('id')->all());
    }

    public function test_websocket_delta_removes_unassigned_accounts_instead_of_granting_all_group_members(): void
    {
        $user = $this->user(true);
        Cache::put('node_ws_alive:' . $this->private->id, true);
        $messages = [];
        Redis::shouldReceive('publish')->andReturnUsing(function ($channel, $payload) use (&$messages) {
            $messages[] = json_decode($payload, true);
            return 1;
        });
        NodeSyncService::notifyUserChanged($user);
        $this->assertSame('remove', $messages[0]['data']['action']);
        $this->assertSame($this->private->id, $messages[0]['node_id']);
    }

    public function test_plan_limit_caps_total_sales_across_exits(): void
    {
        $this->exit('203.0.113.2');
        $this->plan->update(['capacity_limit' => 3]);
        for ($i = 0; $i < 3; $i++) {
            $this->order($this->user());
        }
        $this->assertFalse((new PlanService($this->plan))->hasCapacity($this->plan));
    }

    public function test_health_requires_three_failures_and_two_recovery_checks(): void
    {
        $health = new class extends DedicatedExitHealthService {
            public bool $result = false;
            protected function probe(DedicatedExit $exit): bool { return $this->result; }
        };
        $health->check($this->exit);
        $health->check($this->exit);
        $this->assertTrue($this->exit->healthy);
        $health->check($this->exit);
        $this->assertFalse($this->exit->healthy);
        $health->result = true;
        $health->check($this->exit);
        $this->assertFalse($this->exit->healthy);
        $health->check($this->exit);
        $this->assertTrue($this->exit->healthy);
    }

    public function test_paid_activation_waits_without_granting_entitlement_when_no_exit_is_usable(): void
    {
        $user = $this->user();
        $order = $this->order($user);
        $this->exit->update(['healthy' => false]);
        try {
            $this->complete($order);
            $this->fail('Must retain processing order until an exit is usable');
        } catch (ApiException $e) {
            $this->assertSame(Order::STATUS_PROCESSING, $order->fresh()->status);
            $this->assertNull($user->fresh()->plan_id);
            $this->assertSame(1, DedicatedAssignment::count());
        }
    }

    public function test_unavailable_legacy_order_waits_then_recovers_without_duplicate_entitlement(): void
    {
        Queue::fake()->except([OrderHandleJob::class]);
        Log::spy();
        $user = $this->user();
        $order = $this->order($user);
        // Legacy administrator orders did not reserve an exit before payment.
        DedicatedAssignment::query()->delete();
        $user->update(['balance' => 989]);
        $order->update(['total_amount' => 0, 'surplus_credit' => 100]);
        $this->exit->update(['healthy' => false]);

        $this->assertTrue((new OrderService($order->fresh()))->paid('manual_operation'));
        $this->assertSame(Order::STATUS_PROCESSING, $order->fresh()->status);
        $this->assertSame('manual_operation', $order->fresh()->callback_no);
        $this->assertNull($user->fresh()->plan_id);
        $this->assertEquals(989, $user->fresh()->balance);
        $this->assertSame(0, DedicatedAssignment::count());
        $this->assertTrue(OrderHandleJob::isWaitingForDedicatedExit($order->id));

        $this->exit->update(['healthy' => true]);
        (new OrderHandleJob($order->trade_no))->handle();
        $this->assertSame(Order::STATUS_PROCESSING, $order->fresh()->status);
        Log::shouldHaveReceived('warning')->once();

        $this->travel(OrderHandleJob::DEDICATED_EXIT_RETRY_SECONDS + 1)->seconds();
        $this->assertFalse(OrderHandleJob::isWaitingForDedicatedExit($order->id));
        (new OrderHandleJob($order->trade_no))->handle();
        $this->assertSame(Order::STATUS_COMPLETED, $order->fresh()->status);
        $this->assertSame($this->plan->id, $user->fresh()->plan_id);
        $this->assertEquals(1089, $user->fresh()->balance);
        $this->assertSame(1, DedicatedAssignment::count());
        $expiry = $user->fresh()->expired_at;
        (new OrderHandleJob($order->trade_no))->handle();
        $this->assertEquals(1089, $user->fresh()->balance);
        $this->assertSame($expiry, $user->fresh()->expired_at);
    }

    public function test_scheduler_skips_waiting_order_and_retries_when_cooldown_expires(): void
    {
        $order = $this->order($this->user());
        $order->update(['status' => Order::STATUS_PROCESSING]);
        $this->exit->update(['healthy' => false]);
        (new OrderHandleJob($order->trade_no))->handle();
        $this->artisan('check:order')->assertExitCode(0);
        Queue::assertNotPushed(OrderHandleJob::class);

        $this->travel(OrderHandleJob::DEDICATED_EXIT_RETRY_SECONDS + 1)->seconds();
        $this->artisan('check:order')->assertExitCode(0);
        Queue::assertPushed(OrderHandleJob::class, 1);
    }

    public function test_unrelated_activation_errors_still_fail_the_job(): void
    {
        $user = $this->user();
        $order = $this->order($user);
        $order->update(['status' => Order::STATUS_PROCESSING]);
        $this->partialMock(DedicatedExitService::class, function ($mock) {
            $mock->shouldReceive('activate')->once()->andThrow(new ApiException('other activation error'));
        });

        try {
            (new OrderHandleJob($order->trade_no))->handle();
            $this->fail('Unrelated errors must remain visible to the queue worker');
        } catch (ApiException $e) {
            $this->assertSame('other activation error', $e->getMessage());
            $this->assertSame(Order::STATUS_PROCESSING, $order->fresh()->status);
            $this->assertNull($user->fresh()->plan_id);
            $this->assertFalse(OrderHandleJob::isWaitingForDedicatedExit($order->id));
        }
    }

    public function test_dedicated_wait_does_not_block_expired_pending_order_cancellation(): void
    {
        $order = $this->order($this->user());
        $order->update(['status' => Order::STATUS_PROCESSING]);
        $this->exit->update(['healthy' => false]);
        (new OrderHandleJob($order->trade_no))->handle();
        $order->update(['status' => Order::STATUS_PENDING, 'created_at' => time() - 7201]);
        $this->artisan('check:order')->assertExitCode(0);
        Queue::assertPushed(OrderHandleJob::class, 1);
        (new OrderHandleJob($order->trade_no))->handle();
        $this->assertSame(Order::STATUS_CANCELLED, $order->fresh()->status);
    }

    public function test_switching_back_to_public_plan_releases_the_dedicated_seat(): void
    {
        $user = $this->user();
        $this->complete($this->order($user));
        $regular = Plan::create(['name' => '普通套餐', 'group_id' => 5, 'transfer_enable' => 200]);
        $user->refresh()->update(['plan_id' => $regular->id]);
        app(DedicatedExitService::class)->activate($user, $regular);
        $this->assertSame(0, DedicatedAssignment::count());
        $this->assertCount(0, ServerService::getAvailableUsers($this->private));
    }

    public function test_prepare_is_idempotent_and_does_not_publish_or_change_existing_prices(): void
    {
        $this->plan->update(['name' => 'Existing plan']);
        $machine = ServerMachine::create(['name' => 'Test entry', 'token' => Helper::guid()]);
        $this->public->update(['machine_id' => $machine->id, 'protocol_settings' => ['network' => 'ws', 'network_settings' => ['path' => '/template']]]);
        $front = $this->node('Template front');
        $front->update(['parent_id' => $this->public->id, 'protocol_settings' => ['tls' => 1, 'network' => 'ws', 'network_settings' => ['path' => '/template']]]);
        $manifest = tempnam(sys_get_temp_dir(), 'dedicated-manifest-');
        try {
            file_put_contents($manifest, json_encode([
                'backend_template_id' => $this->public->id, 'frontend_template_id' => $front->id, 'port_start' => 31200,
                'exits' => [
                    ['ip' => '203.0.113.10', 'port' => 1080, 'username' => 'test', 'password' => 'test-secret', 'standby' => false],
                    ['ip' => '203.0.113.11', 'port' => 1080, 'username' => 'test', 'password' => 'test-secret', 'standby' => true],
                ],
            ]));
            $this->artisan('dedicated:prepare', ['manifest' => $manifest])->assertSuccessful();
            $plan = Plan::where('name', '美国独享家宽IP')->firstOrFail();
            $this->assertFalse($plan->show);
            $this->assertEquals(59, $plan->prices['monthly']);
            $this->assertTrue($this->plan->fresh()->show);
            $nodes = Server::whereJsonContains('tags', 'dedicated-public')->get();
            $this->assertCount(2, $nodes);
            $this->assertSame([(string) $plan->group_id], $nodes[0]->group_ids);
            $this->assertSame('socks', $nodes[0]->parent->custom_outbounds[0]['protocol']);
            $this->artisan('dedicated:prepare', ['manifest' => $manifest])->assertSuccessful();
            $this->assertSame(2, Plan::count());
            $this->assertSame(2, Server::whereJsonContains('tags', 'dedicated-public')->count());
        } finally {
            unlink($manifest);
        }
    }
}
