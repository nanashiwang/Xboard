<?php

namespace Tests\Feature\Mail;

use App\Jobs\SendTrafficExhaustedEmailJob;
use App\Models\{MailLog, MailTemplate, User};
use App\Services\{MailService, TrafficExhaustedReminderService, TrafficResetService};
use App\Utils\CacheKey;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Mail\Events\MessageSending;
use Illuminate\Mail\Transport\ArrayTransport;
use Illuminate\Support\Facades\{Cache, DB, Event, Mail, Queue};
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class TrafficExhaustedReminderTest extends TestCase
{
    use RefreshDatabase;

    private const TABLE = 'v2_traffic_exhausted_reminders';

    protected function setUp(): void
    {
        parent::setUp();
        config(['mail.driver' => 'array']);
        admin_setting(['remind_mail_enable' => true, 'app_name' => '测试站点', 'app_url' => 'https://example.test']);
        $this->assertInstanceOf(ArrayTransport::class, Mail::mailer()->getSymfonyTransport());
    }

    private function user(array $overrides = []): User
    {
        return User::withoutEvents(fn () => User::create(array_replace([
            'email' => Str::random(8) . '@example.test', 'password' => 'test-only',
            'uuid' => (string) Str::uuid(), 'token' => Str::random(32),
            'transfer_enable' => 1000, 'u' => 200, 'd' => 800,
            'banned' => false, 'remind_traffic' => true, 'remind_expire' => false, 'reset_count' => 0,
        ], $overrides)));
    }

    private function service(): TrafficExhaustedReminderService
    {
        return app(TrafficExhaustedReminderService::class);
    }

    private function messageCount(): int
    {
        return Mail::mailer()->getSymfonyTransport()->messages()->count();
    }

    public function test_exactly_full_and_over_quota_send_but_below_full_does_not(): void
    {
        $this->user();
        $this->user(['d' => 801]);
        $this->user(['d' => 799]);
        $this->assertSame(2, $this->service()->queuePending());
        $this->assertSame(2, $this->messageCount());
        $this->assertSame(2, DB::table(self::TABLE)->whereNotNull('sent_at')->count());
        $this->assertDatabaseHas('v2_mail_log', ['template_name' => 'mail.default.remindTrafficExhausted', 'error' => null]);
        $html = Mail::mailer()->getSymfonyTransport()->messages()->first()->getOriginalMessage()->getHtmlBody();
        $this->assertStringContainsString('全部用完', $html);
        $this->assertStringNotContainsString('80%', $html);
    }

    public function test_success_is_once_per_cycle_even_after_cache_clear_and_next_day(): void
    {
        $user = $this->user();
        $this->service()->queuePending();
        Cache::flush();
        $this->travel(1)->days();
        $this->assertSame(0, $this->service()->queuePending());
        (new SendTrafficExhaustedEmailJob($user->id, 0))->handle($this->service());
        $this->assertSame(1, $this->messageCount());
    }

    public function test_eighty_percent_warning_and_exhausted_template_are_independent(): void
    {
        $user = $this->user(['d' => 600]);
        MailTemplate::create(['name' => 'remindTraffic', 'subject' => '80% 预警', 'content' => '<p>80% 预警</p>']);
        app(MailService::class)->remindTraffic($user);
        $this->assertNotNull(Cache::get(CacheKey::get('LAST_SEND_EMAIL_REMIND_TRAFFIC', $user->id)));
        $this->assertSame(0, $this->service()->queuePending());
        $user->updateQuietly(['d' => 800]);
        $this->assertSame(1, $this->service()->queuePending());
        $this->assertSame(2, $this->messageCount());
        $this->assertSame(['db:remindTraffic', 'mail.default.remindTrafficExhausted'], MailLog::orderBy('id')->pluck('template_name')->all());
    }

    public function test_real_traffic_reset_rearms_next_cycle_and_stale_job_is_ignored(): void
    {
        $user = $this->user();
        $this->service()->queuePending();
        $this->assertTrue(app(TrafficResetService::class)->performReset($user));
        $user->refresh();
        $this->assertSame(1, (int) $user->reset_count);
        $this->assertSame(0, $this->service()->queuePending());
        $user->updateQuietly(['d' => 1000]);
        (new SendTrafficExhaustedEmailJob($user->id, 0))->handle($this->service());
        $this->assertSame(1, $this->messageCount());
        $this->assertSame(1, $this->service()->queuePending());
        $this->assertSame(2, $this->messageCount());
        $this->assertDatabaseCount(self::TABLE, 2);
    }

    public function test_disabled_preferences_banned_empty_email_and_zero_quota_are_excluded(): void
    {
        foreach ([['remind_traffic' => false], ['banned' => true], ['email' => ''], ['transfer_enable' => 0]] as $overrides) {
            $user = $this->user($overrides);
            (new SendTrafficExhaustedEmailJob($user->id, 0))->handle($this->service());
        }
        $this->assertSame(0, $this->service()->queuePending());
        $this->assertSame(0, $this->messageCount());
        $this->assertDatabaseCount(self::TABLE, 0);
    }

    public function test_global_switch_is_checked_during_scan_and_again_in_worker(): void
    {
        $user = $this->user();
        admin_setting(['remind_mail_enable' => false]);
        $this->assertSame(0, $this->service()->queuePending());
        (new SendTrafficExhaustedEmailJob($user->id, 0))->handle($this->service());
        $this->assertSame(0, $this->messageCount());
        $this->assertDatabaseCount(self::TABLE, 0);
    }

    public function test_worker_rechecks_preferences_and_quota_after_enqueue(): void
    {
        Queue::fake();
        $user = $this->user();
        $this->service()->queuePending();
        Queue::assertPushedOn('send_email', SendTrafficExhaustedEmailJob::class);
        $user->updateQuietly(['remind_traffic' => false]);
        (new SendTrafficExhaustedEmailJob($user->id, 0))->handle($this->service());
        $user->updateQuietly(['remind_traffic' => true, 'transfer_enable' => 2000]);
        (new SendTrafficExhaustedEmailJob($user->id, 0))->handle($this->service());
        $this->assertSame(0, $this->messageCount());
    }

    public function test_smtp_failure_is_logged_and_retried_after_cooldown_without_marking_sent(): void
    {
        $this->freezeTime();
        $user = $this->user();
        $fail = true;
        Event::listen(MessageSending::class, function () use (&$fail) {
            if ($fail) {
                throw new \RuntimeException('simulated SMTP unavailable');
            }
        });
        try {
            (new SendTrafficExhaustedEmailJob($user->id, 0))->handle($this->service());
            $this->fail('SMTP failure must reach the queue retry mechanism.');
        } catch (\RuntimeException $e) {
            $this->assertStringContainsString('see the mail log', $e->getMessage());
        }
        $this->assertDatabaseHas(self::TABLE, ['user_id' => $user->id, 'sent_at' => null]);
        $this->assertDatabaseHas('v2_mail_log', ['error' => 'simulated SMTP unavailable']);
        $this->assertSame(0, $this->service()->queuePending());
        $fail = false;
        $this->travel(TrafficExhaustedReminderService::RETRY_SECONDS)->seconds();
        $this->assertSame(1, $this->service()->queuePending());
        $this->assertSame(1, $this->messageCount());
        $this->assertSame(0, $this->service()->queuePending());
    }

    public function test_atomic_claim_prevents_a_second_worker_from_sending_during_delivery(): void
    {
        $user = $this->user();
        Event::listen(MessageSending::class, function () use ($user) {
            $this->service()->send($user->id, 0);
        });
        $this->service()->send($user->id, 0);
        $this->assertSame(1, $this->messageCount());
        $this->assertDatabaseCount(self::TABLE, 1);
    }

    public function test_abandoned_claim_is_recovered_after_lease_expires(): void
    {
        $this->freezeTime();
        $user = $this->user();
        DB::table(self::TABLE)->insert(['user_id' => $user->id, 'reset_count' => 0, 'retry_after' => now()->timestamp + 900]);
        $this->assertSame(0, $this->service()->queuePending());
        $this->travel(901)->seconds();
        $this->assertSame(1, $this->service()->queuePending());
        $this->assertSame(1, $this->messageCount());
    }

    public function test_duplicate_scans_do_not_accumulate_identical_queued_jobs(): void
    {
        Queue::fake();
        $this->user();
        $this->service()->queuePending();
        $this->service()->queuePending();
        Queue::assertPushed(SendTrafficExhaustedEmailJob::class, 1);
    }

    public function test_command_queues_only_exhausted_mail_and_schedule_keeps_expiry_daily(): void
    {
        $this->user(['remind_expire' => true, 'expired_at' => time() + 1000]);
        $this->artisan('send:traffic-exhausted')->expectsOutputToContain('候选用户：1')->assertSuccessful();
        $this->assertSame(['mail.default.remindTrafficExhausted'], MailLog::pluck('template_name')->all());
        $events = collect(app(\Illuminate\Contracts\Console\Kernel::class)->resolveConsoleSchedule()->events());
        $this->assertSame('*/5 * * * *', $events->first(fn ($e) => str_contains($e->command ?? '', 'send:traffic-exhausted'))->expression);
        $this->assertSame('30 11 * * *', $events->first(fn ($e) => str_contains($e->command ?? '', 'send:remindMail'))->expression);
    }

    public function test_admin_can_read_and_customize_the_new_template_only_with_admin_access(): void
    {
        $path = '/api/v2/' . admin_setting('secure_path', admin_setting('frontend_admin_path', hash('crc32b', config('app.key')))) . '/mail/template';
        $this->getJson($path . '/get?name=remindTrafficExhausted')->assertForbidden();
        $user = $this->user(['is_admin' => true]);
        Sanctum::actingAs($user);
        $this->getJson($path . '/list')->assertOk()->assertJsonFragment(['name' => 'remindTrafficExhausted', 'label' => '流量耗尽提醒']);
        $this->getJson($path . '/get?name=remindTrafficExhausted')->assertOk()
            ->assertJsonPath('data.subject', '测试站点 - 套餐流量已用完');
        $this->postJson($path . '/save', ['name' => 'remindTrafficExhausted', 'subject' => '{{name}} - 耗尽', 'content' => '<p>{{name}} 流量已用完 <a href="{{url}}">查看</a></p>'])->assertOk();
        $this->service()->queuePending();
        $message = Mail::mailer()->getSymfonyTransport()->messages()->first()->getOriginalMessage();
        $this->assertSame('测试站点 - 耗尽', $message->getSubject());
        $this->assertStringContainsString('https://example.test', $message->getHtmlBody());
        $this->assertDatabaseHas('v2_mail_log', ['template_name' => 'db:remindTrafficExhausted', 'error' => null]);
    }
}
