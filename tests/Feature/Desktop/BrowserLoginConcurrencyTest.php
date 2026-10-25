<?php

namespace Tests\Feature\Desktop;

use App\Models\User;
use App\Services\Client\ClientBrowserLoginService;
use App\Utils\Helper;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use PDO;
use Tests\TestCase;

class BrowserLoginConcurrencyTest extends TestCase
{
    private string $database;
    private const SECRET = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

    protected function setUp(): void
    {
        parent::setUp();
        // Two independent connections to a real WAL file; no wrapping test transaction.
        $this->database = tempnam(sys_get_temp_dir(), 'capybara-wal-');
        config(['database.default' => 'sqlite', 'database.connections.sqlite.database' => $this->database]);
        DB::purge('sqlite');
        $this->artisan('migrate:fresh', ['--force' => true])->assertExitCode(0);
        DB::statement('CREATE TABLE concurrency_probe (id INTEGER PRIMARY KEY)');
    }

    protected function tearDown(): void
    {
        DB::disconnect('sqlite');
        foreach (['', '-wal', '-shm'] as $suffix) {
            if (is_file($this->database . $suffix)) unlink($this->database . $suffix);
        }
        parent::tearDown();
    }

    private function approved(): string
    {
        $user = User::query()->create([
            'email' => Str::uuid() . '@example.com', 'password' => password_hash('test-only', PASSWORD_DEFAULT),
            'uuid' => Helper::guid(true), 'token' => Helper::guid(true),
            'created_at' => time(), 'updated_at' => time(),
        ]);
        $service = app(ClientBrowserLoginService::class);
        $id = $service->start(['device_id' => (string) Str::uuid(), 'name' => 'test', 'platform' => 'macos'], self::SECRET)['request_id'];
        $user->withAccessToken($user->createToken('test-web', ['*'])->accessToken);
        $service->approve($id, $user, true);
        return $id;
    }

    private function poll(string $id)
    {
        return $this->postJson('/api/v1/auth/browser/poll', ['request_id' => $id, 'secret' => self::SECRET]);
    }

    public function test_stale_wal_snapshot_restarts_whole_exchange_and_issues_tokens_once(): void
    {
        $id = $this->approved();
        $writer = new PDO('sqlite:' . $this->database);
        $injected = false;
        DB::connection()->beforeExecuting(function ($sql) use ($writer, &$injected) {
            if (!$injected && str_starts_with($sql, 'insert into "client_devices"')) {
                $writer->exec('INSERT INTO concurrency_probe DEFAULT VALUES');
                $injected = true;
            }
        });
        $this->poll($id)->assertOk()->assertJsonPath('data.phase', 'complete');
        $this->assertTrue($injected);
        $this->assertDatabaseCount('client_devices', 1);
        $this->assertDatabaseCount('client_refresh_tokens', 1);
        $this->poll($id)->assertStatus(410);
        $this->assertDatabaseCount('client_refresh_tokens', 1);
    }

    public function test_exhausted_contention_rolls_back_and_keeps_approval_for_later_poll(): void
    {
        $id = $this->approved();
        $writer = new PDO('sqlite:' . $this->database);
        $writes = 0;
        $busy = true;
        DB::connection()->beforeExecuting(function ($sql) use ($writer, &$writes, &$busy) {
            if ($busy && str_starts_with($sql, 'insert into "client_devices"')) {
                $writer->exec('INSERT INTO concurrency_probe DEFAULT VALUES');
                $writes++;
            }
        });
        $this->poll($id)->assertStatus(503)->assertJsonPath('code', 'AUTH_BROWSER_BUSY');
        $this->assertSame(5, $writes);
        $this->assertSame(0, DB::transactionLevel());
        $this->assertDatabaseCount('client_devices', 0);
        $this->assertDatabaseCount('client_refresh_tokens', 0);
        $this->assertDatabaseHas('client_browser_logins', ['id' => $id, 'state' => 'approved']);
        $busy = false;
        $this->poll($id)->assertOk()->assertJsonPath('data.phase', 'complete');
        $this->assertDatabaseCount('client_refresh_tokens', 1);
    }

    public function test_non_concurrency_failure_is_not_retried(): void
    {
        $id = $this->approved();
        $calls = 0;
        DB::connection()->beforeExecuting(function ($sql) use (&$calls) {
            if (str_starts_with($sql, 'insert into "client_devices"')) {
                $calls++;
                throw new \RuntimeException('test-only failure');
            }
        });
        $this->poll($id)->assertStatus(500)->assertJsonPath('code', 'SERVER_ERROR');
        $this->assertSame(1, $calls);
        $this->assertDatabaseCount('client_refresh_tokens', 0);
    }
}
