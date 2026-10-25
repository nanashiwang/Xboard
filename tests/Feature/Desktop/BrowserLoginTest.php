<?php

namespace Tests\Feature\Desktop;

use App\Models\User;
use App\Utils\Helper;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Tests\TestCase;

class BrowserLoginTest extends TestCase
{
    use RefreshDatabase;

    private const SECRET = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

    private function user(array $overrides = []): User
    {
        return User::query()->create(array_merge([
            'email' => Str::uuid() . '@example.com', 'password' => password_hash('test-only', PASSWORD_DEFAULT),
            'uuid' => Helper::guid(true), 'token' => Helper::guid(true),
            'created_at' => time(), 'updated_at' => time(),
        ], $overrides));
    }

    private function start(): array
    {
        return $this->postJson('/api/v1/auth/browser/start', [
            'secret' => self::SECRET,
            'device' => ['device_id' => (string) Str::uuid(), 'name' => '测试电脑', 'platform' => 'macos', 'app_version' => '0.1.0'],
        ])->assertOk()->assertJsonPath('data.expires_in', 300)->json('data');
    }

    private function approve(string $id, User $user, bool $approved = true, array $abilities = ['*'])
    {
        $this->app['auth']->forgetGuards();
        return $this->withToken($user->createToken('test-web', $abilities)->plainTextToken)
            ->postJson('/api/v1/auth/browser/approve', ['request_id' => $id, 'approved' => $approved]);
    }

    private function poll(string $id, string $secret = self::SECRET)
    {
        return $this->postJson('/api/v1/auth/browser/poll', ['request_id' => $id, 'secret' => $secret]);
    }

    public function test_browser_approval_exchanges_once_and_never_discloses_secrets(): void
    {
        $user = $this->user();
        $id = $this->start()['request_id'];
        $row = DB::table('client_browser_logins')->find($id);
        $this->assertSame(hash('sha256', self::SECRET), $row->secret_hash);
        $this->assertSame(['phase' => 'pending'], $this->poll($id)->assertOk()->json('data'));
        $this->assertDatabaseCount('client_refresh_tokens', 0);
        $context = $this->getJson('/api/v1/auth/browser/context?request_id=' . $id)->assertOk()->json('data');
        $this->assertEqualsCanonicalizing(['phase', 'device_name', 'platform', 'app_version', 'expires_at'], array_keys($context));
        $this->approve($id, $user)->assertOk()->assertJsonPath('data', true);
        $this->poll($id, str_repeat('b', 64))->assertStatus(401)->assertJsonPath('code', 'AUTH_BROWSER_INVALID');
        $this->assertDatabaseCount('client_refresh_tokens', 0);
        $tokens = $this->poll($id)->assertOk()->assertJsonPath('data.phase', 'complete')->json('data.tokens');
        $this->assertSame($user->id, $tokens['user']['id']);
        $this->assertNotEmpty($tokens['refresh_token']);
        $this->assertDatabaseCount('client_devices', 1);
        $this->assertDatabaseCount('client_refresh_tokens', 1);
        $this->poll($id)->assertStatus(410)->assertJsonPath('code', 'AUTH_BROWSER_EXPIRED');
        $this->getJson('/api/v1/auth/browser/context?request_id=' . $id)->assertStatus(410);
        $this->assertDatabaseCount('client_refresh_tokens', 1);
    }

    public function test_approval_requires_full_web_session_and_cannot_switch_accounts(): void
    {
        $id = $this->start()['request_id'];
        $this->postJson('/api/v1/auth/browser/approve', ['request_id' => $id, 'approved' => true])->assertStatus(401);
        $user = $this->user();
        $this->approve($id, $user, true, ['client'])->assertStatus(403)->assertJsonPath('code', 'AUTH_TOKEN_INVALID');
        $this->approve($id, $user)->assertOk();
        $this->approve($id, $user)->assertOk();
        $this->approve($id, $this->user())->assertStatus(409)->assertJsonPath('code', 'AUTH_BROWSER_ACCOUNT_MISMATCH');
    }

    public function test_cancel_and_expiry_prevent_token_creation(): void
    {
        $id = $this->start()['request_id'];
        $this->postJson('/api/v1/auth/browser/cancel', ['request_id' => $id, 'secret' => str_repeat('b', 64)])->assertStatus(401);
        $this->postJson('/api/v1/auth/browser/cancel', ['request_id' => $id, 'secret' => self::SECRET])->assertOk();
        $this->poll($id)->assertStatus(410)->assertJsonPath('code', 'AUTH_BROWSER_CANCELLED');
        $this->approve($id, $this->user())->assertStatus(410);
        $id = $this->start()['request_id'];
        $this->approve($id, $this->user(), false)->assertOk();
        $this->poll($id)->assertStatus(410);
        $id = $this->start()['request_id'];
        $this->travel(301)->seconds();
        $this->poll($id)->assertStatus(410)->assertJsonPath('code', 'AUTH_BROWSER_EXPIRED');
        $this->approve($id, $this->user())->assertStatus(410);
        $this->assertDatabaseCount('client_refresh_tokens', 0);
    }

    public function test_bans_are_checked_at_approval_and_exchange_and_device_limits_are_preserved(): void
    {
        $user = $this->user(['registered_device_limit' => 1]);
        $id = $this->start()['request_id'];
        $this->approve($id, $this->user(['banned' => 1]))->assertStatus(403)->assertJsonPath('code', 'ACCOUNT_BANNED');
        $this->approve($id, $user)->assertOk();
        $user->update(['banned' => 1]);
        $this->poll($id)->assertStatus(403)->assertJsonPath('code', 'ACCOUNT_BANNED');
        $user->update(['banned' => 0]);
        $this->poll($id)->assertOk();
        $next = $this->start()['request_id'];
        $this->approve($next, $user)->assertOk();
        $this->poll($next)->assertStatus(409)->assertJsonPath('code', 'DEVICE_LIMIT_REACHED');
        $this->assertDatabaseCount('client_refresh_tokens', 1);
        $this->assertDatabaseHas('client_browser_logins', ['id' => $next, 'state' => 'approved']);
    }

    public function test_validation_and_web_page_security(): void
    {
        $this->postJson('/api/v1/auth/browser/start', ['secret' => 'short'])->assertStatus(422);
        $this->getJson('/api/v1/auth/browser/context?request_id=../bad')->assertStatus(422);
        $this->postJson('/api/v1/auth/browser/poll', ['request_id' => (string) Str::ulid()])->assertStatus(422);
        $this->get('/desktop/login')->assertOk()->assertHeader('X-Frame-Options', 'DENY')
            ->assertHeader('Referrer-Policy', 'no-referrer')->assertSee('登录桌面客户端');
        admin_setting(['app_url' => 'https://trusted.example', 'safe_mode_enable' => 1]);
        $this->get('/desktop/login')->assertStatus(403);
    }
}
