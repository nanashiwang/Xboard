<?php

namespace Tests\Feature\Dedicated;

use App\Jobs\OrderHandleJob;
use App\Models\{DedicatedAssignment, DedicatedExit, NodeProbe, Order, Plan, Server, ServerMachine, User};
use App\Services\{DedicatedExitHealthService, DedicatedExitService, NodeSyncService, OrderService, ServerService};
use App\Services\Probes\NodeProbeService;
use App\Utils\{CacheKey, Helper};
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\{Cache, DB, Queue, Redis};
use Tests\TestCase;

class OwnedDedicatedExitTest extends TestCase
{
    use RefreshDatabase;

    private Plan $plan;
    private User $monitor;
    private NodeProbe $probe;
    private array $sources = [];
    private string $manifest;
    private array $existingBackups = [];

    protected function setUp(): void
    {
        parent::setUp();
        $this->existingBackups = glob(storage_path('app/owned-fixed-*.json'));
        Queue::fake();
        $this->plan = Plan::create(['name' => '固定出口', 'group_id' => 5, 'dedicated' => true,
            'transfer_enable' => 200, 'prices' => ['monthly' => 59], 'capacity_limit' => 15,
            'show' => false, 'sell' => true, 'renew' => true, 'speed_limit' => 10]);
        $ordinaryPlan = Plan::create(['name' => '普通套餐', 'group_id' => 1, 'transfer_enable' => 200]);
        $this->monitor = $this->user(false);
        $this->monitor->update(['plan_id' => $ordinaryPlan->id]);
        $machine = ServerMachine::create(['name' => 'test', 'token' => Helper::guid()]);
        foreach ([1, 2] as $i) {
            $backend = Server::create(['name' => '后端' . $i, 'type' => 'vless', 'host' => '203.0.113.' . $i,
                'port' => '31443', 'server_port' => 31443, 'machine_id' => $machine->id, 'group_ids' => ['1'],
                'show' => false, 'enabled' => true, 'rate' => 1, 'protocol_settings' => ['network' => 'ws']]);
            Cache::put(CacheKey::get('SERVER_VLESS_LAST_CHECK_AT', $backend->id), time(), 600);
            $source = Server::create(['name' => '公开' . $i, 'type' => 'vless', 'host' => 'ingress.example',
                'port' => '443', 'server_port' => 443, 'parent_id' => $backend->id, 'group_ids' => ['1'],
                'show' => true, 'enabled' => false, 'rate' => 1,
                'protocol_settings' => ['tls' => 1, 'network' => 'ws', 'network_settings' => ['path' => '/node-' . $i]]]);
            $this->sources[] = $source;
        }
        [$this->probe] = app(NodeProbeService::class)->create(['name' => 'test', 'location' => 'test',
            'user_id' => $this->monitor->id, 'server_ids' => array_map(fn ($s) => $s->id, $this->sources),
            'expected_exits' => [$this->sources[0]->id => '203.0.113.1', $this->sources[1]->id => '203.0.113.2']]);
        $this->manifest = tempnam(sys_get_temp_dir(), 'owned-exits-');
        file_put_contents($this->manifest, json_encode(['probe_id' => $this->probe->id, 'exits' => [
            ['server_id' => $this->sources[0]->id, 'ip' => '203.0.113.1'],
            ['server_id' => $this->sources[1]->id, 'ip' => '203.0.113.2'],
        ]]));
    }

    protected function tearDown(): void
    {
        @unlink($this->manifest);
        foreach (array_diff(glob(storage_path('app/owned-fixed-*.json')), $this->existingBackups) as $path) unlink($path);
        parent::tearDown();
    }

    private function user(bool $dedicated = true): User
    {
        return User::create(['email' => Helper::guid() . '@example.test', 'password' => 'test',
            'uuid' => Helper::guid(), 'token' => Helper::guid(), 'banned' => false,
            'group_id' => $dedicated ? 5 : 1, 'plan_id' => $dedicated ? $this->plan->id : null,
            'expired_at' => time() + 86400, 'transfer_enable' => 214748364800, 'u' => 0, 'd' => 0]);
    }

    private function attach(bool $apply = true): void
    {
        $this->artisan('dedicated:attach-owned', ['plan' => $this->plan->id, 'manifest' => $this->manifest, '--apply' => $apply])->assertSuccessful();
    }

    private function observation(Server $source, int $when, ?string $ip = null, bool $ok = true): void
    {
        DB::table('v2_node_probe_state')->updateOrInsert(['probe_id' => $this->probe->id, 'server_id' => $source->id], [
            'checked_at' => $when, 'status' => $ok ? 'healthy' : 'down', 'exit_ip' => $ip ?? $source->parent->host,
            'checks' => json_encode(['error' => null, 'checks' => [
                ['id' => 'cloudflare', 'ok' => $ok], ['id' => 'google', 'ok' => $ok],
            ]]),
        ]);
    }

    private function healthy(): void
    {
        foreach (DedicatedExit::all() as $exit) {
            $source = Server::find($exit->probe_server_id);
            $this->observation($source, time() - 60);
            app(DedicatedExitHealthService::class)->check($exit);
            $this->observation($source, time());
            app(DedicatedExitHealthService::class)->check($exit);
            $this->assertTrue($exit->fresh()->isHealthy());
        }
    }

    public function test_preview_and_repeat_apply_preserve_public_nodes_and_plan_terms(): void
    {
        $before = Server::where('show', true)->get()->toArray();
        $terms = $this->plan->fresh()->only(['prices', 'capacity_limit', 'show', 'sell', 'renew']);
        $this->attach(false);
        $this->assertDatabaseCount('v2_dedicated_exit', 0);
        $this->attach();
        $this->attach();
        $this->assertDatabaseCount('v2_dedicated_exit', 2);
        $this->assertDatabaseCount('v2_server', 6);
        $this->assertSame($terms, $this->plan->fresh()->only(array_keys($terms)));
        $this->assertSame($before, Server::whereIn('id', array_column($before, 'id'))->get()->toArray());
        $this->assertCount(2, app(NodeProbeService::class)->eligible($this->monitor));
        $this->assertCount(2, ServerService::getAvailableServers($this->monitor));
        $this->assertFalse(app(DedicatedExitService::class)->hasCapacity($this->plan));
    }

    public function test_fixed_users_cannot_authenticate_other_pool_backends_and_public_users_remain(): void
    {
        $this->attach(); $this->healthy();
        $user = $this->user();
        $nodes = ServerService::getAvailableServers($user);
        $this->assertCount(1, $nodes);
        $first = $this->sources[0]->parent->fresh();
        $second = $this->sources[1]->parent->fresh();
        $this->assertContains($user->id, ServerService::getAvailableUsers($first)->pluck('id')->all());
        $this->assertNotContains($user->id, ServerService::getAvailableUsers($second)->pluck('id')->all());
        foreach ([$first, $second] as $backend) $this->assertContains($this->monitor->id, ServerService::getAvailableUsers($backend)->pluck('id')->all());
        $unassigned = $this->user();
        $this->assertNotContains($unassigned->id, ServerService::getAvailableUsers($first)->pluck('id')->all());
        $this->assertSame($nodes[0]['id'], ServerService::getAvailableServers($user)[0]['id']);
    }

    public function test_repeated_observation_does_not_fake_recovery_and_stale_or_mismatched_exit_stops_capacity(): void
    {
        $this->attach();
        $exit = DedicatedExit::first(); $health = app(DedicatedExitHealthService::class);
        $this->observation($this->sources[0], time() - 60);
        $health->check($exit); $health->check($exit);
        $this->assertSame(1, $exit->fresh()->successes);
        $this->assertFalse($exit->fresh()->isHealthy());
        $this->observation($this->sources[0], time()); $health->check($exit);
        $this->assertTrue($exit->fresh()->isHealthy());
        $this->observation($this->sources[0], time() + 1, '203.0.113.99'); $health->check($exit);
        $this->assertFalse($exit->fresh()->isHealthy());
        $exit->update(['healthy' => true, 'checked_at' => time() - 301]);
        $this->observation($this->sources[0], time() - 301); $health->check($exit->fresh());
        $this->assertFalse($exit->fresh()->isHealthy());
    }

    public function test_probe_disabled_exhausted_account_or_alias_drift_invalidates_health(): void
    {
        $this->attach(); $this->healthy();
        $exit = DedicatedExit::first();
        $this->probe->update(['enabled' => false]);
        app(DedicatedExitHealthService::class)->check($exit);
        $this->assertFalse($exit->fresh()->isHealthy());
        $this->probe->update(['enabled' => true]); $this->healthy();
        $this->monitor->update(['u' => $this->monitor->transfer_enable]);
        app(DedicatedExitHealthService::class)->check($exit->fresh());
        $this->assertFalse($exit->fresh()->isHealthy());
        $this->monitor->update(['u' => 0]); $this->healthy();
        Server::where('dedicated_exit_id', $exit->id)->first()->update(['host' => 'other.example']);
        app(DedicatedExitHealthService::class)->check($exit->fresh());
        $this->assertFalse($exit->fresh()->isHealthy());
    }

    public function test_five_slots_then_next_exit_and_failure_migrates_without_blocking_public_users(): void
    {
        $this->attach(); $this->healthy();
        $users = [];
        for ($i = 0; $i < 6; $i++) { $users[] = $u = $this->user(); ServerService::getAvailableServers($u); }
        $first = DedicatedExit::first();
        $this->assertSame(5, DedicatedAssignment::where('exit_id', $first->id)->count());
        $first->update(['healthy' => false]);
        ServerService::getAvailableServers($users[0]);
        $this->assertNotEquals($first->id, DedicatedAssignment::where('user_id', $users[0]->id)->value('exit_id'));
        $this->assertContains($this->monitor->id, ServerService::getAvailableUsers($this->sources[0]->parent->fresh())->pluck('id')->all());
        $this->assertNotContains($users[1]->id, ServerService::getAvailableUsers($this->sources[0]->parent->fresh())->pluck('id')->all());
    }

    public function test_historical_processing_order_completes_once_after_pool_becomes_healthy(): void
    {
        $this->attach();
        $user = $this->user(false);
        $order = Order::create(['user_id' => $user->id, 'plan_id' => $this->plan->id, 'period' => Plan::PERIOD_MONTHLY,
            'type' => Order::TYPE_NEW_PURCHASE, 'trade_no' => Helper::guid(), 'total_amount' => 0, 'status' => Order::STATUS_PROCESSING]);
        (new OrderHandleJob($order->trade_no))->handle();
        $this->assertEquals(Order::STATUS_PROCESSING, $order->fresh()->status);
        $this->healthy();
        (new OrderService($order->fresh()))->open();
        $expiry = $user->fresh()->expired_at;
        (new OrderService($order->fresh()))->open();
        $this->assertEquals(Order::STATUS_COMPLETED, $order->fresh()->status);
        $this->assertEquals($expiry, $user->fresh()->expired_at);
        $this->assertDatabaseCount('v2_dedicated_assignment', 1);
    }

    public function test_incremental_sync_only_adds_fixed_user_to_assigned_backend(): void
    {
        $this->attach(); $this->healthy();
        $user = $this->user(); ServerService::getAvailableServers($user);
        foreach ($this->sources as $source) Cache::put('node_ws_alive:' . $source->parent_id, true);
        $messages = [];
        Redis::shouldReceive('publish')->andReturnUsing(function ($channel, $payload) use (&$messages) {
            $messages[] = json_decode($payload, true); return 1;
        });
        NodeSyncService::notifyUserChanged($user);
        $actions = collect($messages)->keyBy('node_id');
        $this->assertSame('add', $actions[$this->sources[0]->parent_id]['data']['action']);
        $this->assertSame('remove', $actions[$this->sources[1]->parent_id]['data']['action']);
        $messages = []; NodeSyncService::notifyUserChanged($this->monitor);
        $this->assertCount(2, $messages);
        $this->assertSame(['add', 'add'], array_column(array_column($messages, 'data'), 'action'));
    }

    public function test_new_alias_and_ordinary_backend_still_enforce_quota_expiry_and_ban(): void
    {
        $this->attach(); $this->healthy();
        $user = $this->user(); ServerService::getAvailableServers($user);
        foreach ([['u' => $user->transfer_enable], ['expired_at' => time() - 1], ['banned' => true]] as $change) {
            $user->update(['u' => 0, 'expired_at' => time() + 86400, 'banned' => false, ...$change]);
            $this->assertNotContains($user->id, ServerService::getAvailableUsers($this->sources[0]->parent->fresh())->pluck('id')->all());
        }
    }

    public function test_three_distinct_failed_observations_stop_a_previously_healthy_exit(): void
    {
        $this->attach(); $this->healthy();
        $exit = DedicatedExit::first();
        foreach ([1, 2, 3] as $offset) {
            $this->observation($this->sources[0], time() + $offset, null, false);
            app(DedicatedExitHealthService::class)->check($exit);
            $this->assertSame($offset < 3, $exit->fresh()->isHealthy());
        }
    }

    public function test_rejects_public_access_bypass_before_mutating_inventory(): void
    {
        $this->sources[0]->update(['group_ids' => ['1', '5']]);
        try {
            $this->attach();
            $this->fail('Public fixed-pool bypass must be rejected');
        } catch (\RuntimeException $e) {
            $this->assertStringContainsString('绕过固定分配', $e->getMessage());
        }
        $this->assertDatabaseCount('v2_dedicated_exit', 0);
        $this->assertDatabaseCount('v2_server', 4);
    }

    public function test_clean_install_creates_private_backup_directory_before_applying(): void
    {
        $original = storage_path();
        $temporary = sys_get_temp_dir() . '/owned-storage-' . bin2hex(random_bytes(6));
        $this->app->useStoragePath($temporary);
        try {
            $this->attach();
            $files = glob($temporary . '/app/owned-fixed-*.json');
            $this->assertCount(1, $files);
            $this->assertSame(0600, fileperms($files[0]) & 0777);
            $this->assertSame(0700, fileperms($temporary . '/app') & 0777);
            $this->assertSame($this->plan->id, json_decode(file_get_contents($files[0]), true)['plan_id']);
        } finally {
            foreach (glob($temporary . '/app/owned-fixed-*.json') as $file) unlink($file);
            if (is_dir($temporary . '/app')) rmdir($temporary . '/app');
            if (is_dir($temporary)) rmdir($temporary);
            $this->app->useStoragePath($original);
        }
    }
}
