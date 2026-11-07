<?php

namespace Tests\Feature\Operations;

use App\Jobs\{StatServerJob, StatUserJob, TrafficFetchJob};
use App\Models\{Server, User};
use App\Services\UserService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\{Bus, Redis};
use Illuminate\Support\Str;
use PHPUnit\Framework\Attributes\DataProvider;
use Tests\TestCase;

class DirectionalTrafficBillingTest extends TestCase
{
    use RefreshDatabase;

    public static function reports(): array
    {
        return [
            'upload only' => [1, 1000, 0],
            'download only' => [1, 0, 2000],
            'bidirectional 1x' => [1, 1000, 2000],
            'bidirectional 2x' => [2, 1000, 2000],
            'bidirectional 5x' => [5, 1000, 2000],
        ];
    }

    private function user(): User
    {
        return User::withoutEvents(fn () => User::create([
            'email' => Str::random(12).'@example.test', 'password' => 'test-only',
            'uuid' => (string) Str::uuid(), 'token' => Str::random(32),
            'transfer_enable' => 100000, 'u' => 12, 'd' => 34,
        ]));
    }

    private function server(int $rate): Server
    {
        return Server::create(['name' => 'test', 'type' => 'vless', 'host' => 'example.test',
            'port' => '443', 'server_port' => 31443, 'rate' => $rate, 'u' => 0, 'd' => 0]);
    }

    #[DataProvider('reports')]
    public function test_new_reports_only_charge_upload_but_keep_node_downloads(int $rate, int $up, int $down): void
    {
        $user = $this->user();
        $server = $this->server($rate);
        Bus::fake();
        (new UserService())->trafficFetch($server, 'vless', [$user->id => [$up, $down]]);
        Redis::shouldReceive('sadd')->once()->with('traffic:pending_check', $user->id);
        foreach ([TrafficFetchJob::class, StatUserJob::class, StatServerJob::class] as $type) {
            Bus::assertDispatchedTimes($type, 1);
            // Exercise the same serialized policy snapshot consumed by workers.
            unserialize(serialize(Bus::dispatched($type)->first()))->handle();
        }
        $this->assertSame(12 + $up * $rate, (int) $user->fresh()->u);
        $this->assertSame(34, (int) $user->fresh()->d, 'Historical download charges must remain unchanged');
        $this->assertDatabaseHas('v2_stat_user', ['user_id' => $user->id, 'u' => $up * $rate, 'd' => 0]);
        $this->assertDatabaseHas('v2_stat_server', ['server_id' => $server->id, 'u' => $up, 'd' => $down]);
        $this->assertSame($up, (int) $server->fresh()->u);
        $this->assertSame($down, (int) $server->fresh()->d);
    }

    public static function queuedPolicies(): array
    {
        return [
            'legacy bidirectional' => [null, 200, 400],
            'previous download only' => ['download_only', 0, 400],
            'upload only retry' => ['upload_only', 200, 0],
        ];
    }

    #[DataProvider('queuedPolicies')]
    public function test_pre_cutover_jobs_keep_their_original_policy(?string $mode, int $up, int $down): void
    {
        $user = $this->user();
        $server = $this->server(2)->toArray();
        if ($mode !== null) $server['traffic_billing_mode'] = $mode;
        Redis::shouldReceive('sadd')->once()->with('traffic:pending_check', $user->id);
        $data = [$user->id => [100, 200]];
        unserialize(serialize(new TrafficFetchJob($server, $data, 'vless', time())))->handle();
        unserialize(serialize(new StatUserJob($server, $data, 'vless')))->handle();
        $this->assertSame(12 + $up, (int) $user->fresh()->u);
        $this->assertSame(34 + $down, (int) $user->fresh()->d);
        $this->assertDatabaseHas('v2_stat_user', ['user_id' => $user->id, 'u' => $up, 'd' => $down]);
    }

    public function test_no_report_does_not_dispatch_accounting(): void
    {
        Bus::fake();
        (new UserService())->trafficFetch($this->server(2), 'vless', []);
        Bus::assertNothingDispatched();
    }
}
