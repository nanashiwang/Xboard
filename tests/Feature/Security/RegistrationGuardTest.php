<?php
namespace Tests\Feature\Security;

use App\Exceptions\ApiException;
use App\Jobs\SendEmailJob;
use App\Models\User;
use App\Services\Auth\RegistrationGuard;
use App\Utils\CacheKey;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\{Cache, File, Queue};
use Illuminate\Support\Str;
use Tests\TestCase;

class RegistrationGuardTest extends TestCase
{
    use RefreshDatabase;
    protected function setUp(): void
    {
        parent::setUp(); Cache::flush(); Queue::fake();
        admin_setting(['registration_guard_enable' => 1, 'email_verify' => 1, 'captcha_enable' => 0,
            'registration_blocked_email_domains' => ['fldubai.com'], 'register_limit_by_ip_enable' => 1,
            'register_limit_count' => 3, 'register_limit_expire' => 60, 'register_limit_daily_count' => 10]);
    }
    private function user(string $email): User
    {
        return User::create(['email' => $email, 'password' => password_hash('old-password', PASSWORD_DEFAULT), 'uuid' => (string) Str::uuid(), 'token' => Str::random(32)]);
    }
    private function code(string $email): void
    {
        Cache::put(CacheKey::get('EMAIL_VERIFY_CODE', $email), '123456', 300);
    }
    private function signup(string $email, string $code = '123456')
    {
        return $this->postJson('/api/v1/passport/auth/register', ['email' => $email, 'password' => 'test-password', 'email_code' => $code]);
    }
    public function test_form_requests_preserve_captcha_reason_and_created_user_in_audit(): void
    {
        $events = [];
        $logger = \Mockery::mock(\Psr\Log\LoggerInterface::class);
        $logger->shouldReceive('info')->andReturnUsing(function ($message, $context) use (&$events) { $events[] = $context; });
        \Illuminate\Support\Facades\Log::shouldReceive('channel')->with('registration')->andReturn($logger);
        admin_setting(['captcha_enable' => 1, 'captcha_type' => 'turnstile']);
        $this->postJson('/api/v1/passport/comm/sendEmailVerify', ['email' => 'audit-missing@example.com'])->assertStatus(400);
        $this->assertSame('captcha_missing_token', $events[0]['reason']);
        $this->assertNull($events[0]['user_id']);
        admin_setting(['captcha_enable' => 0]);
        $this->code('audit-ok@example.com');
        $this->signup('audit-ok@example.com')->assertOk();
        $this->assertSame(User::byEmail('audit-ok@example.com')->value('id'), $events[1]['user_id']);
        $this->assertSame('accepted', $events[1]['reason']);
        $this->assertNotSame($events[0]['request_id'], $events[1]['request_id']);
        Queue::assertNotPushed(SendEmailJob::class);
    }
    public function test_blocked_domain_rejects_signup_and_new_mail_before_dispatch(): void
    {
        $this->signup('Random@FLDUBAI.COM')->assertStatus(403);
        $this->postJson('/api/v1/passport/comm/sendEmailVerify', ['email' => 'other@FLDUBAI.COM'])->assertStatus(403);
        Queue::assertNothingPushed(); $this->assertDatabaseCount('v2_user', 0);
    }
    public function test_existing_user_in_blocked_domain_keeps_login_and_recovery(): void
    {
        $user = $this->user('existing@fldubai.com');
        $this->postJson('/api/v1/passport/auth/login', ['email' => $user->email, 'password' => 'old-password'])->assertOk();
        admin_setting(['stop_register' => 1]);
        $this->postJson('/api/v1/passport/comm/sendEmailVerify', ['email' => $user->email])->assertOk();
        Queue::assertPushed(SendEmailJob::class, 1);
        $this->code($user->email);
        $this->postJson('/api/v1/passport/auth/forget', ['email' => strtoupper($user->email), 'email_code' => '123456', 'password' => 'new-password'])->assertOk();
        $this->assertTrue(password_verify('new-password', $user->fresh()->password));
        $this->postJson('/api/v1/passport/comm/sendEmailVerify', ['email' => 'new@example.com'])->assertStatus(403);
    }
    public function test_email_exception_does_not_allow_other_addresses(): void
    {
        admin_setting(['registration_allowed_emails' => ['exception@fldubai.com']]);
        $this->code('exception@fldubai.com');
        $this->signup('Exception@FLDUBAI.COM')->assertOk();
        $this->signup('another@fldubai.com')->assertStatus(403);
    }
    public function test_switching_emails_cannot_evade_ip_send_quota(): void
    {
        for ($i=0; $i<5; $i++) $this->postJson('/api/v1/passport/comm/sendEmailVerify', ['email' => "mail$i@example.com"])->assertOk();
        $this->postJson('/api/v1/passport/comm/sendEmailVerify', ['email' => 'mail6@example.com'])->assertStatus(429);
        Queue::assertPushed(SendEmailJob::class, 5);
    }
    public function test_switching_ips_and_case_cannot_evade_email_cooldown(): void
    {
        $this->withServerVariables(['REMOTE_ADDR' => '203.0.113.1'])->postJson('/api/v1/passport/comm/sendEmailVerify', ['email' => 'Mailbox@example.com'])->assertOk();
        $this->withServerVariables(['REMOTE_ADDR' => '203.0.113.2'])->postJson('/api/v1/passport/comm/sendEmailVerify', ['email' => 'mailbox@EXAMPLE.COM'])->assertStatus(429);
        Queue::assertPushed(SendEmailJob::class, 1);
    }
    public function test_success_quota_and_window_expiry(): void
    {
        for ($i=0; $i<3; $i++) { $this->code("ok$i@example.com"); $this->signup("ok$i@example.com")->assertOk(); }
        $this->code('over@example.com'); $this->signup('over@example.com')->assertStatus(429);
        $this->assertDatabaseCount('v2_user', 3);
        $this->travel(3601)->seconds(); $this->code('later@example.com'); $this->signup('later@example.com')->assertOk();
    }
    public function test_daily_quota_survives_short_window_expiry(): void
    {
        admin_setting(['register_limit_daily_count' => 2]);
        for ($i=0; $i<2; $i++) { $this->code("ok$i@example.com"); $this->signup("ok$i@example.com")->assertOk(); }
        $this->travel(3601)->seconds(); $this->code('over@example.com'); $this->signup('over@example.com')->assertStatus(429);
        $this->assertDatabaseCount('v2_user', 2);
    }
    public function test_wrong_codes_are_limited_across_source_changes_and_resends(): void
    {
        $guard = app(RegistrationGuard::class); $this->code('guess@example.com');
        for ($i=0; $i<5; $i++) $this->assertFalse($guard->consumeEmailCode('guess@example.com', '999999'));
        $this->code('guess@example.com');
        $this->expectException(ApiException::class); $this->expectExceptionCode(429);
        $guard->consumeEmailCode('guess@example.com', '123456');
    }
    public function test_code_expires_and_cannot_be_replayed_between_register_and_reset(): void
    {
        $guard = app(RegistrationGuard::class); $this->code('once@example.com');
        $this->assertTrue($guard->consumeEmailCode('ONCE@example.com', '123456'));
        $this->assertFalse($guard->consumeEmailCode('once@example.com', '123456'));
        $this->code('expired@example.com'); $this->travel(301)->seconds();
        $this->assertFalse($guard->consumeEmailCode('expired@example.com', '123456'));
        $this->assertFalse($guard->consumeEmailCode('missing@example.com', ''));
    }
    public function test_malformed_email_is_rejected_without_dispatch(): void
    {
        $this->postJson('/api/v1/passport/comm/sendEmailVerify', ['email' => ['bad']])->assertStatus(422);
        Queue::assertNothingPushed();
    }
    public function test_parallel_workers_share_atomic_quota_and_one_time_code(): void
    {
        if (!function_exists('pcntl_fork')) $this->markTestSkipped('pcntl required for independent worker regression');
        $directory = sys_get_temp_dir() . '/registration-guard-' . Str::random(10);
        mkdir($directory, 0700, true);
        $driver = getenv('GUARD_CONCURRENCY_STORE') ?: 'file';
        config(['cache.stores.file.path' => $directory, 'cache.prefix' => 'guard-test-' . Str::random(12)]);
        Cache::purge($driver); Cache::setDefaultDriver($driver);
        try {
            $this->code('parallel@example.com'); $pids=[];
            for ($i=0; $i<8; $i++) {
                $pid=pcntl_fork();
                if ($pid===0) {
                    // Forked workers must not reuse the parent's Redis socket.
                    if ($driver === 'redis') { app('redis')->purge('cache'); app('redis')->purge('default'); Cache::purge('redis'); }
                    $g=app(RegistrationGuard::class); $accepted=false; $consumed=false;
                    try { $g->consume('parallel', 'same-ip', 3, 3600); $accepted=true; } catch (ApiException) {}
                    try { $consumed=$g->consumeEmailCode('parallel@example.com', '123456'); } catch (ApiException) {}
                    file_put_contents($directory.'/result-'.$i,json_encode([$accepted,$consumed])); exit(0);
                }
                $this->assertGreaterThan(0,$pid); $pids[]=$pid;
            }
            foreach ($pids as $pid) { pcntl_waitpid($pid,$status); $this->assertSame(0,pcntl_wexitstatus($status)); }
            $results=array_map(fn($file)=>json_decode(file_get_contents($file),true),glob($directory.'/result-*'));
            $this->assertCount(8,$results); $this->assertSame(3,array_sum(array_column($results,0))); $this->assertSame(1,array_sum(array_column($results,1)));
        } finally { Cache::setDefaultDriver('array'); File::deleteDirectory($directory); }
    }
}
