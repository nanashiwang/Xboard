<?php

namespace Tests\Feature\Operations;

use App\Jobs\{StatServerJob, StatUserJob};
use App\Models\Server;
use Illuminate\Foundation\Testing\RefreshDatabase;
use PHPUnit\Framework\Attributes\DataProvider;
use RuntimeException;
use Tests\TestCase;

class TrafficStatRetryTest extends TestCase
{
    use RefreshDatabase;

    public static function rates(): array
    {
        return [[1], [2], [5]];
    }

    #[DataProvider('rates')]
    public function test_partial_user_batch_is_rolled_back_before_retry(int $rate): void
    {
        $job = new class(['rate' => $rate], [101 => [10, 100], 102 => [20, 200]], 'vless') extends StatUserJob {
            public bool $fail = true;
            protected function processUserStat(int $uid, array $v, int $recordAt): void
            {
                if ($uid === 102 && $this->fail) throw new RuntimeException('injected write failure');
                parent::processUserStat($uid, $v, $recordAt);
            }
        };
        try {
            $job->handle();
            $this->fail('Expected injected failure');
        } catch (RuntimeException $e) {
            $this->assertSame('injected write failure', $e->getMessage());
        }
        $this->assertDatabaseCount('v2_stat_user', 0);
        $job->fail = false;
        $job->handle();
        $this->assertDatabaseHas('v2_stat_user', ['user_id' => 101, 'u' => 10 * $rate, 'd' => 100 * $rate]);
        $this->assertDatabaseHas('v2_stat_user', ['user_id' => 102, 'u' => 20 * $rate, 'd' => 200 * $rate]);
        // A genuinely new identical increment must still be counted.
        (new StatUserJob(['rate' => $rate], [101 => [10, 100]], 'vless'))->handle();
        $this->assertDatabaseHas('v2_stat_user', ['user_id' => 101, 'u' => 20 * $rate, 'd' => 200 * $rate]);
    }

    public function test_node_daily_and_lifetime_counters_rollback_together(): void
    {
        $server = Server::create(['name' => 'test', 'type' => 'vless', 'host' => 'example.test',
            'port' => '443', 'server_port' => 31443, 'rate' => 2, 'u' => 0, 'd' => 0]);
        $job = new class($server->toArray(), [101 => [10, 100]], 'vless') extends StatServerJob {
            public bool $fail = true;
            protected function updateServerTraffic(int $u, int $d): void
            {
                if ($this->fail) throw new RuntimeException('injected node failure');
                parent::updateServerTraffic($u, $d);
            }
        };
        try {
            $job->handle();
            $this->fail('Expected injected failure');
        } catch (RuntimeException $e) {
            $this->assertSame('injected node failure', $e->getMessage());
        }
        $this->assertDatabaseCount('v2_stat_server', 0);
        $this->assertSame(0, (int) $server->fresh()->u);
        $job->fail = false;
        $job->handle();
        $this->assertDatabaseHas('v2_stat_server', ['server_id' => $server->id, 'u' => 10, 'd' => 100]);
        $this->assertSame(100, (int) $server->fresh()->d);
        (new StatServerJob($server->toArray(), [101 => [10, 100]], 'vless'))->handle();
        $this->assertDatabaseHas('v2_stat_server', ['server_id' => $server->id, 'u' => 20, 'd' => 200]);
        $this->assertSame(200, (int) $server->fresh()->d);
    }
}
