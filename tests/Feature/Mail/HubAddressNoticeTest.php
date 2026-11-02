<?php
namespace Tests\Feature\Mail;

use App\Models\{User, MailLog};
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\{Mail, File};
use Illuminate\Support\Str;
use Tests\TestCase;

require_once __DIR__ . '/../../../.docker/mail/hub-address-notice.php';

class HubAddressNoticeTest extends TestCase
{
    use RefreshDatabase;
    private string $directory;
    protected function setUp(): void
    {
        parent::setUp();
        config(['mail.driver' => 'array']);
        $this->directory = storage_path('framework/testing/hub-notice-' . Str::random(12));
    }
    protected function tearDown(): void
    {
        File::deleteDirectory($this->directory);
        parent::tearDown();
    }
    private function user(string $email): User
    {
        return User::withoutEvents(fn () => User::create(['email' => $email, 'password' => 'test-only', 'uuid' => (string) Str::uuid(), 'token' => Str::random(32)]));
    }
    public function test_notice_links_point_to_hub_and_success_is_not_sent_twice(): void
    {
        $this->user('a@example.test'); $this->user('b@example.test');
        $notice = new \HubAddressNotice($this->directory, 0);
        $this->assertSame(2, $notice->status()['eligible_unique_addresses']);
        $this->assertFalse(is_dir($this->directory));
        $result = $notice->sendBatch(1); $this->assertSame(1, $result['counts']->sent);
        $notice->sendBatch(25); $notice->sendBatch(25);
        $this->assertCount(2, Mail::mailer()->getSymfonyTransport()->messages());
        $this->assertSame(2, MailLog::whereNull('error')->count());
        $html = Mail::mailer()->getSymfonyTransport()->messages()->first()->getOriginalMessage()->getHtmlBody();
        $this->assertStringContainsString('href="https://capybarahub.fyi/"', $html);
        $this->assertStringContainsString('无需重新注册', $html);
        $this->assertStringNotContainsString('taige.us', $html);
        $this->assertStringNotContainsString('@example.test', file_get_contents($this->directory.'/hub-address-notice-20261103.json'));
    }
    public function test_interrupted_attempt_is_not_blindly_resent(): void
    {
        $this->user('a@example.test');
        $notice = new \HubAddressNotice($this->directory, 0); $notice->sendBatch();
        $path = $this->directory.'/hub-address-notice-20261103.json';
        $state = json_decode(file_get_contents($path), true);
        foreach ($state['targets'] as &$target) $target['status'] = 'attempting';
        unset($target); file_put_contents($path, json_encode($state));
        MailLog::query()->delete();
        $result = $notice->sendBatch();
        $this->assertSame(1, $result['counts']->uncertain);
        $this->assertCount(1, Mail::mailer()->getSymfonyTransport()->messages());
    }
    public function test_changed_content_fails_closed(): void
    {
        $this->user('a@example.test');
        $notice = new \HubAddressNotice($this->directory, 0); $notice->sendBatch();
        $path = $this->directory.'/hub-address-notice-20261103.json';
        $state = json_decode(file_get_contents($path), true); $state['fingerprint'] = 'changed'; file_put_contents($path, json_encode($state));
        $this->expectException(\RuntimeException::class); $notice->sendBatch();
    }

    public function test_failed_recipient_stops_batch_and_only_safe_diagnostics_are_exposed(): void
    {
        $this->user('a@example.test'); $this->user('b@example.test');
        Mail::shouldReceive('send')->once()->andThrow(new \RuntimeException('550 5.1.1 User unknown a@example.test private-detail'));
        $notice = new \HubAddressNotice($this->directory, 0);
        $result = $notice->sendBatch();
        $this->assertSame(1, $result['counts']->failed);
        $this->assertSame(1, $result['counts']->pending);
        $this->assertSame(1, $result['smtp_error_summary']->{'recipient_rejected:550'});
        $this->assertStringNotContainsString('a@example.test', json_encode($result));
        $this->assertStringNotContainsString('private-detail', json_encode($result));
        Mail::shouldReceive('send')->once()->andReturn(null);
        $result = $notice->sendBatch();
        $this->assertSame(1, $result['counts']->sent);
        $this->assertSame(1, $result['counts']->failed);
        $this->assertSame(2, MailLog::count());
    }

    public function test_explicit_rate_rejection_can_be_retried_once_but_daily_quota_cannot(): void
    {
        $this->user('rate@example.test');
        Mail::shouldReceive('send')->once()->andThrow(new \RuntimeException('Expected response code "250" but got code "454", with message "454 Throttling failure: Rate exceeded"'));
        $notice = new \HubAddressNotice($this->directory, 0);
        $result = $notice->sendBatch();
        $this->assertSame(1, $result['smtp_error_summary']->{'sending_rate:454'});
        Mail::shouldReceive('send')->once()->andReturn(null);
        $result = $notice->sendBatch();
        $this->assertSame(1, $result['counts']->sent);
        $notice->sendBatch();
        $this->assertSame(2, MailLog::count());
        $this->user('daily@example.test');
        $daily = new \HubAddressNotice($this->directory.'-daily', 0);
        Mail::shouldReceive('send')->once()->andThrow(new \RuntimeException('Expected response code "250" but got code "454", with message "454 Daily message quota exceeded"'));
        try {
            $result = $daily->sendBatch();
            $this->assertSame(1, $result['smtp_error_summary']->{'daily_quota:454'});
            $result = $daily->sendBatch();
            $this->assertSame(1, $result['counts']->failed);
            $this->assertSame(3, MailLog::count());
        } finally { File::deleteDirectory($this->directory.'-daily'); }
    }
}
