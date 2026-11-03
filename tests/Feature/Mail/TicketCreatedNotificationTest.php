<?php

namespace Tests\Feature\Mail;

use App\Exceptions\ApiException;
use App\Jobs\SendEmailJob;
use App\Models\{MailTemplate, Ticket, TicketMessage, User};
use App\Services\TicketService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Mail\Transport\ArrayTransport;
use Illuminate\Support\Facades\{Bus, DB, Log, Mail, Queue};
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class TicketCreatedNotificationTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        config(['mail.driver' => 'array']);
        admin_setting(['app_name' => '测试站点', 'app_url' => 'https://example.test']);
        $this->assertInstanceOf(ArrayTransport::class, Mail::mailer()->getSymfonyTransport());
    }

    private function user(array $overrides = []): User
    {
        return User::withoutEvents(fn () => User::create(array_replace([
            'email' => Str::random(8) . '@example.test', 'password' => 'test-only',
            'uuid' => (string) Str::uuid(), 'token' => Str::random(32),
            'banned' => false, 'is_admin' => false, 'is_staff' => false,
        ], $overrides)));
    }

    private function createTicket(?User $user = null): Ticket
    {
        return app(TicketService::class)->createTicket(($user ?? $this->user())->id, '无法连接', 1, '请协助检查');
    }

    private function messages()
    {
        return Mail::mailer()->getSymfonyTransport()->messages()
            ->map(fn ($sent) => $sent->getOriginalMessage())->values();
    }

    public function test_customer_endpoint_notifies_each_active_admin_and_no_other_accounts(): void
    {
        $admin = $this->user(['is_admin' => true]);
        $second = $this->user(['is_admin' => true]);
        $this->user(['is_admin' => true, 'banned' => true]);
        $this->user(['is_staff' => true]);
        $this->user(['is_admin' => true, 'email' => '']);
        $this->user(['is_admin' => true, 'email' => 'invalid']);
        $customer = $this->user();
        Sanctum::actingAs($customer);
        $this->postJson('/api/v1/user/ticket/save', [
            'subject' => '无法连接', 'level' => 1, 'message' => '请协助检查',
        ])->assertOk()->assertJsonPath('data', true);
        $ticket = Ticket::sole();
        $messages = $this->messages();
        $this->assertCount(2, $messages);
        $this->assertEqualsCanonicalizing([$admin->email, $second->email], $messages->map(fn ($m) => $m->getTo()[0]->getAddress())->all());
        foreach ($messages as $message) {
            $this->assertCount(1, $message->getTo());
            $this->assertSame([], $message->getCc());
            $this->assertSame('测试站点 收到新工单 #' . $ticket->id, $message->getSubject());
            foreach ([$customer->email, '无法连接', '请协助检查', 'https://example.test'] as $text) {
                $this->assertStringContainsString($text, $message->getHtmlBody());
            }
        }
        $this->postJson('/api/v1/user/ticket/reply', ['id' => $ticket->id, 'message' => '补充信息'])->assertOk();
        $this->assertCount(2, $this->messages());
    }

    public function test_creation_uses_existing_email_queue_and_normalizes_duplicate_recipients(): void
    {
        Queue::fake();
        $this->user(['is_admin' => true, 'email' => 'admin@example.test']);
        $duplicate = $this->user(['is_admin' => true]);
        DB::table('v2_user')->where('id', $duplicate->id)->update(['email' => ' ADMIN@example.test ']);
        $this->createTicket();
        Queue::assertPushedOn('send_email', SendEmailJob::class);
        Queue::assertPushed(SendEmailJob::class, 1);
    }

    public function test_failed_or_outer_rolled_back_creation_does_not_notify(): void
    {
        Queue::fake();
        $this->user(['is_admin' => true]);
        DB::beginTransaction();
        $this->createTicket();
        Queue::assertNothingPushed();
        DB::rollBack();
        $this->assertDatabaseCount('v2_ticket', 0);
        Queue::assertNothingPushed();

        TicketMessage::creating(function () {
            throw new \RuntimeException('simulated ticket message failure');
        });
        try {
            $this->createTicket();
            $this->fail('Creation must fail.');
        } catch (\RuntimeException $e) {
            $this->assertSame('simulated ticket message failure', $e->getMessage());
        } finally {
            TicketMessage::flushEventListeners();
        }
        $this->assertDatabaseCount('v2_ticket', 0);
        Queue::assertNothingPushed();
    }

    public function test_outer_commit_delays_notification_until_ticket_is_committed(): void
    {
        Queue::fake();
        $this->user(['is_admin' => true]);
        DB::beginTransaction();
        $ticket = $this->createTicket();
        Queue::assertNothingPushed();
        DB::commit();
        $this->assertDatabaseHas('v2_ticket', ['id' => $ticket->id]);
        Queue::assertPushed(SendEmailJob::class, 1);
    }

    public function test_duplicate_request_is_rejected_but_next_new_ticket_is_not_throttled(): void
    {
        Queue::fake();
        $this->user(['is_admin' => true]);
        $customer = $this->user();
        $ticket = $this->createTicket($customer);
        $transactionLevel = DB::transactionLevel();
        try {
            $this->createTicket($customer);
            $this->fail('A second open ticket must be rejected.');
        } catch (ApiException $e) {
            $this->assertSame('存在未关闭的工单', $e->getMessage());
        }
        $this->assertSame($transactionLevel, DB::transactionLevel());
        Queue::assertPushed(SendEmailJob::class, 1);
        $ticket->update(['status' => Ticket::STATUS_CLOSED]);
        $this->createTicket($customer);
        Queue::assertPushed(SendEmailJob::class, 2);
    }

    public function test_unavailable_queue_does_not_fail_committed_ticket_or_skip_remaining_admins(): void
    {
        $this->user(['is_admin' => true]);
        $this->user(['is_admin' => true]);
        $attempts = 0;
        Bus::shouldReceive('dispatch')->twice()->andReturnUsing(function ($job) use (&$attempts) {
            $this->assertInstanceOf(SendEmailJob::class, $job);
            if (++$attempts === 1) {
                throw new \RuntimeException('simulated queue failure with sensitive details');
            }
        });
        Log::shouldReceive('warning')->once()->with('新工单管理员邮件入队失败', \Mockery::on(function ($context) {
            return array_keys($context) === ['ticket_id', 'admin_id', 'exception_type']
                && $context['exception_type'] === \RuntimeException::class;
        }));
        $ticket = $this->createTicket();
        $this->assertDatabaseHas('v2_ticket', ['id' => $ticket->id]);
        $this->assertDatabaseHas('v2_ticket_message', ['ticket_id' => $ticket->id]);
        $this->assertSame(2, $attempts);
    }

    public function test_no_eligible_admin_does_not_prevent_ticket_creation(): void
    {
        Queue::fake();
        Log::shouldReceive('warning')->once()->with('新工单通知没有可用的管理员邮箱', \Mockery::type('array'));
        $ticket = $this->createTicket();
        $this->assertDatabaseHas('v2_ticket', ['id' => $ticket->id]);
        Queue::assertNothingPushed();
    }

    public function test_customer_content_is_escaped_in_default_and_custom_templates(): void
    {
        $this->user(['is_admin' => true]);
        foreach ([false, true] as $custom) {
            if ($custom) {
                MailTemplate::create(['name' => 'notify', 'subject' => '{{name}} - 通知', 'content' => '<p>{{content}}</p>']);
                \Illuminate\Support\Facades\Cache::forget('mail_template:notify');
            }
            app(TicketService::class)->createTicket($this->user()->id, '<img src=x onerror=alert(1)>', 1, "<script>alert(1)</script>\n第二行 & 内容");
            $html = $this->messages()->last()->getHtmlBody();
            $this->assertStringNotContainsString('<img', $html);
            $this->assertStringNotContainsString('<script>', $html);
            $this->assertStringContainsString('&lt;img', $html);
            $this->assertStringContainsString('&lt;script&gt;', $html);
            $this->assertStringContainsString('第二行 &amp; 内容', $html);
            $this->assertStringContainsString('<br', $html);
        }
    }

    public function test_original_admin_reply_email_retains_its_thirty_minute_limit(): void
    {
        $admin = $this->user(['is_admin' => true]);
        $customer = $this->user();
        $ticket = $this->createTicket($customer);
        app(TicketService::class)->replyByAdmin($ticket->id, '已经处理', $admin->id);
        app(TicketService::class)->replyByAdmin($ticket->id, '请再试一次', $admin->id);
        $this->assertCount(2, $this->messages());
        $this->assertSame($customer->email, $this->messages()->last()->getTo()[0]->getAddress());
        $this->assertStringContainsString('已经处理', $this->messages()->last()->getHtmlBody());
        $this->assertSame(Ticket::REPLY_STATUS_REPLIED, $ticket->fresh()->reply_status);
    }
}
