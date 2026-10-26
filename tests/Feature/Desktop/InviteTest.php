<?php

namespace Tests\Feature\Desktop;

use App\Http\Controllers\V1\User\InviteController as WebsiteInvites;
use App\Models\CommissionLog;
use App\Models\InviteCode;
use App\Models\Order;
use App\Models\User;
use App\Services\Auth\RegisterService;
use App\Utils\Helper;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Request;
use Tests\TestCase;

class InviteTest extends TestCase
{
    use RefreshDatabase;
    private User $user;
    private array $headers;

    protected function setUp(): void
    {
        parent::setUp();
        admin_setting(['password_limit_enable' => 0, 'stop_register' => 0, 'invite_gen_limit' => 2,
            'invite_never_expire' => 1, 'invite_commission' => 10, 'commission_distribution_enable' => 0]);
        $this->user = $this->makeUser('invite@example.com');
        $device = '9dfc6298-69c4-4f4d-a42e-0ca109b76440';
        $token = $this->postJson('/api/v1/auth/login', [
            'email' => $this->user->email, 'password' => 'password123',
            'device' => ['device_id' => $device, 'name' => 'Invite test', 'platform' => 'macos', 'architecture' => 'arm64', 'app_version' => '0.1.2'],
        ])->assertOk()->json('data.access_token');
        $this->headers = ['Authorization' => 'Bearer ' . $token, 'X-Device-ID' => $device];
    }

    private function makeUser(string $email): User
    {
        return User::create(['email' => $email, 'password' => password_hash('password123', PASSWORD_DEFAULT),
            'uuid' => Helper::guid(true), 'token' => Helper::guid(true)]);
    }

    private function code(User $user, string $code, bool $used = false): void
    {
        $invite = new InviteCode(); $invite->user_id = $user->id; $invite->code = $code; $invite->status = $used; $invite->save();
    }

    public function test_invites_require_desktop_device_and_non_banned_account(): void
    {
        $this->getJson('/api/v1/client/invite')->assertUnauthorized();
        $this->app['auth']->forgetGuards();
        $this->withHeaders([...$this->headers, 'X-Device-ID' => 'wrong'])->getJson('/api/v1/client/invite')->assertUnauthorized();
        $this->user->update(['banned' => 1]); $this->app['auth']->forgetGuards();
        foreach (['', '/details'] as $path) $this->withHeaders($this->headers)->getJson('/api/v1/client/invite' . $path)->assertForbidden();
        $this->withHeaders($this->headers)->postJson('/api/v1/client/invite/generate')->assertForbidden();
        $this->assertSame(0, InviteCode::count());
    }

    public function test_no_subscription_required_and_only_current_users_codes_and_stats_are_returned(): void
    {
        $other = $this->makeUser('other@example.com');
        $this->code($this->user, 'OWN12345'); $this->code($this->user, 'USED1234', true); $this->code($other, 'OTHER123');
        $other->update(['invite_user_id' => $this->user->id]);
        $this->user->update(['commission_balance' => 1234, 'commission_rate' => 25]);
        $this->withHeaders($this->headers)->getJson('/api/v1/client/invite?user_id=' . $other->id)->assertOk()
            ->assertJsonCount(1, 'data.codes')->assertJsonPath('data.codes.0.code', 'OWN12345')
            ->assertJsonPath('data.stats.registered', 1)->assertJsonPath('data.stats.available_commission', 1234)
            ->assertJsonPath('data.rules.commission_rates', [25])->assertJsonPath('data.rules.reusable', true)
            ->assertJsonMissingPath('data.codes.0.user_id');
    }

    public function test_generate_is_explicit_and_web_and_desktop_share_quota(): void
    {
        $this->withHeaders($this->headers)->getJson('/api/v1/client/invite')->assertOk();
        $this->assertSame(0, InviteCode::count());
        $request = Request::create('/user/invite/save'); $request->setUserResolver(fn() => $this->user);
        $this->assertTrue(json_decode(app(WebsiteInvites::class)->save($request)->getContent(), true)['data']);
        $response = $this->withHeaders($this->headers)->postJson('/api/v1/client/invite/generate', ['user_id' => 999])->assertOk();
        $response->assertJsonCount(2, 'data.codes')->assertJsonPath('data.rules.can_generate', false);
        $this->withHeaders($this->headers)->postJson('/api/v1/client/invite/generate')->assertStatus(409)->assertJsonPath('code', 'INVITE_LIMIT_REACHED');
        $this->assertSame(400, app(WebsiteInvites::class)->save($request)->getStatusCode());
        $this->assertSame(2, InviteCode::where('user_id', $this->user->id)->count());
    }

    public function test_closed_registration_blocks_generation_without_consuming_quota(): void
    {
        admin_setting(['stop_register' => 1]);
        $this->withHeaders($this->headers)->getJson('/api/v1/client/invite')->assertOk()->assertJsonPath('data.rules.registration_open', false)->assertJsonPath('data.rules.can_generate', false);
        $this->withHeaders($this->headers)->postJson('/api/v1/client/invite/generate')->assertStatus(409);
        $this->assertSame(0, InviteCode::count());
    }

    public function test_generated_code_uses_existing_registration_attribution_and_expiry_rules(): void
    {
        admin_setting(['invite_never_expire' => 0]);
        $code = $this->withHeaders($this->headers)->postJson('/api/v1/client/invite/generate')->assertOk()->json('data.codes.0.code');
        $this->assertSame($this->user->id, app(RegisterService::class)->handleInviteCode($code));
        $this->assertNull(app(RegisterService::class)->handleInviteCode($code));
        $this->withHeaders($this->headers)->getJson('/api/v1/client/invite')->assertOk()->assertJsonCount(0, 'data.codes');
    }

    public function test_distribution_rates_match_website_semantics(): void
    {
        admin_setting(['commission_distribution_enable' => 1, 'commission_distribution_l1' => 70,
            'commission_distribution_l2' => 20, 'commission_distribution_l3' => 10]);
        $this->withHeaders($this->headers)->getJson('/api/v1/client/invite')->assertOk()->assertJsonPath('data.rules.commission_rates', [7, 2, 1]);
    }

    public function test_pending_commission_excludes_unpaid_or_already_processed_orders(): void
    {
        foreach ([[3, 0, 800], [0, 0, 2000], [3, 2, 1000]] as $i => [$status, $commissionStatus, $amount]) {
            Order::create(['user_id' => $this->user->id + 1, 'invite_user_id' => $this->user->id,
                'plan_id' => 1, 'type' => 1, 'period' => 'monthly', 'trade_no' => 'pending-invite-' . $i,
                'total_amount' => 8000, 'status' => $status, 'commission_status' => $commissionStatus, 'commission_balance' => $amount]);
        }
        $this->withHeaders($this->headers)->getJson('/api/v1/client/invite')->assertOk()->assertJsonPath('data.stats.pending_commission', 800);
        admin_setting(['commission_distribution_enable' => 1, 'commission_distribution_l1' => 70]);
        $this->withHeaders($this->headers)->getJson('/api/v1/client/invite')->assertOk()->assertJsonPath('data.stats.pending_commission', 560);
    }

    public function test_history_is_bounded_private_and_totals_use_existing_commission_records(): void
    {
        $other = $this->makeUser('history@example.com');
        foreach (range(1, 12) as $i) CommissionLog::create(['invite_user_id' => $this->user->id, 'user_id' => $other->id,
            'trade_no' => 'invite-test-' . $i, 'order_amount' => 1000, 'get_amount' => 100]);
        CommissionLog::create(['invite_user_id' => $other->id, 'user_id' => $this->user->id,
            'trade_no' => 'private-other', 'order_amount' => 9999, 'get_amount' => 999]);
        $this->withHeaders($this->headers)->getJson('/api/v1/client/invite/details?page=1&page_size=999&current=2&user_id=' . $other->id)
            ->assertOk()->assertJsonCount(10, 'data.items')->assertJsonPath('data.total', 12)->assertJsonPath('data.page', 1)
            ->assertJsonMissingPath('data.items.0.trade_no')->assertJsonMissingPath('data.items.0.user_id');
        $this->withHeaders($this->headers)->getJson('/api/v1/client/invite/details?page=2')->assertOk()->assertJsonCount(2, 'data.items');
        $this->withHeaders($this->headers)->getJson('/api/v1/client/invite')->assertOk()->assertJsonPath('data.stats.total_commission', 1200);
        foreach (['0', '-1', '100001', '1.5', 'bad'] as $page) $this->withHeaders($this->headers)->getJson('/api/v1/client/invite/details?page=' . $page)->assertStatus(422);
    }
}
