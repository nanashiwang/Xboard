<?php

namespace Tests\Feature\Dedicated;

use App\Models\DedicatedAssignment;
use App\Models\DedicatedExit;
use App\Models\Order;
use App\Models\Plan;
use App\Models\User;
use App\Utils\Helper;
use Illuminate\Support\Facades\DB;
use Symfony\Component\Process\Process;
use Tests\TestCase;

class DedicatedConcurrencyTest extends TestCase
{
    public function test_eight_concurrent_buyers_cannot_oversell_the_last_five_seats(): void
    {
        $database = tempnam(sys_get_temp_dir(), 'dedicated-concurrency-');
        $original = config('database.connections.sqlite.database');
        try {
            config(['database.connections.sqlite.database' => $database]);
            DB::purge('sqlite');
            $this->artisan('migrate', ['--force' => true])->assertSuccessful();
            DB::statement('PRAGMA journal_mode = WAL');
            $plan = Plan::create(['name' => 'Concurrent', 'group_id' => 1, 'dedicated' => true,
                'transfer_enable' => 200, 'prices' => ['monthly' => 59], 'show' => true,
                'sell' => true, 'renew' => true, 'capacity_limit' => 15]);
            DedicatedExit::create(['plan_id' => $plan->id, 'name' => 'Test', 'public_ip' => '203.0.113.1',
                'enabled' => true, 'healthy' => true, 'checked_at' => time()]);
            $processes = [];
            for ($i = 0; $i < 8; $i++) {
                $user = User::withoutEvents(fn () => User::create(['email' => "buyer{$i}@example.test",
                    'password' => 'unused', 'uuid' => Helper::guid(), 'token' => Helper::guid(),
                    'expired_at' => 0, 'transfer_enable' => 0, 'u' => 0, 'd' => 0]));
                $processes[] = new Process([PHP_BINARY, base_path('tests/Fixtures/dedicated-order-worker.php'), $user->id, $plan->id],
                    base_path(), ['APP_ENV' => 'testing', 'DB_CONNECTION' => 'sqlite', 'DB_DATABASE' => ':memory:', 'DEDICATED_TEST_DATABASE' => $database,
                        'CACHE_STORE' => 'array', 'CACHE_DRIVER' => 'array', 'SETTINGS_CACHE_STORE' => 'array',
                        'QUEUE_CONNECTION' => 'sync'], timeout: 30);
            }
            foreach ($processes as $process) {
                $process->start();
            }
            $results = [];
            foreach ($processes as $process) {
                $process->wait();
                $this->assertTrue($process->isSuccessful(), $process->getErrorOutput() . $process->getOutput());
                $results[] = trim($process->getOutput());
            }
            $this->assertSame(5, count(array_filter($results, fn ($r) => $r === 'reserved')), json_encode($results));
            $this->assertSame(3, count(array_filter($results, fn ($r) => $r === 'sold_out')));
            $this->assertSame(5, DedicatedAssignment::count());
            $this->assertSame(5, Order::count());
            $this->assertSame([1, 2, 3, 4, 5], DedicatedAssignment::orderBy('slot')->pluck('slot')->all());
        } finally {
            DB::disconnect('sqlite');
            config(['database.connections.sqlite.database' => $original]);
            DB::purge('sqlite');
            foreach ([$database, $database . '-wal', $database . '-shm'] as $file) {
                if (is_file($file)) {
                    unlink($file);
                }
            }
        }
    }
}
