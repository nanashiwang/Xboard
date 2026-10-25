<?php

namespace Tests\Feature\Desktop;

use App\Http\Controllers\V1\User\OrderController;
use App\Models\Order;
use App\Models\Plan;
use App\Models\User;
use App\Utils\Helper;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class StoreTest extends TestCase
{
    use RefreshDatabase;
    private User $user;
    private Plan $plan;
    private array $headers;

    protected function setUp(): void
    {
        parent::setUp();
        admin_setting(['password_limit_enable' => 0]);
        $this->plan = Plan::create(['name' => '测试套餐', 'group_id' => 1, 'show' => 1, 'sell' => 1, 'renew' => 1,
            'transfer_enable' => 100, 'capacity_limit' => null, 'prices' => ['monthly' => 12.34, 'yearly' => 100],
            'content' => '<p>每月 {{transfer}} GB</p><img src=x onerror=alert(1)>',
        ]);
        $this->user = User::create(['email' => 'shop@example.com', 'password' => password_hash('password123', PASSWORD_DEFAULT),
            'uuid' => Helper::guid(true), 'token' => Helper::guid(true), 'balance' => 234]);
        $deviceId = '9dfc6298-69c4-4f4d-a42e-0ca109b76440';
        $token = $this->postJson('/api/v1/auth/login', [
            'email' => $this->user->email, 'password' => 'password123',
            'device' => ['device_id' => $deviceId, 'name' => 'Store test', 'platform' => 'macos', 'architecture' => 'arm64', 'app_version' => '1.0.0'],
        ])->assertOk()->json('data.access_token');
        $this->headers = ['Authorization' => 'Bearer ' . $token, 'X-Device-ID' => $deviceId];
    }

    public function test_public_catalog_uses_real_prices_and_filters_hidden_unsellable_and_sold_out_plans(): void
    {
        foreach (['show' => 0, 'sell' => 0, 'capacity_limit' => 0] as $field => $value) {
            $copy = $this->plan->replicate(); $copy->$field = $value; $copy->save();
        }
        $this->getJson('/api/v1/client/plans')->assertOk()->assertJsonCount(1, 'data')
            ->assertJsonPath('data.0.periods.0.amount', 1234)
            ->assertJsonPath('data.0.periods.1.amount', 10000);
        $this->assertStringNotContainsString('<', $this->getJson('/api/v1/client/plans')->json('data.0.description'));
    }

    public function test_store_requires_bound_device_and_rejects_banned_account(): void
    {
        $this->getJson('/api/v1/client/store')->assertUnauthorized();
        $this->app['auth']->forgetGuards();
        $this->withHeaders([...$this->headers, 'X-Device-ID' => 'wrong-device'])->getJson('/api/v1/client/store')->assertUnauthorized();
        $this->user->update(['banned' => 1]); $this->app['auth']->forgetGuards();
        $this->withHeaders($this->headers)->getJson('/api/v1/client/store')->assertForbidden()->assertJsonPath('code', 'ACCOUNT_BANNED');
    }

    public function test_order_uses_balance_prevents_duplicate_and_recovers_pending_order(): void
    {
        $order = $this->save()->assertOk()->assertJsonPath('data.total_amount', 1000)->assertJsonPath('data.balance_amount', 234)->json('data');
        $this->save()->assertStatus(409)->assertJsonPath('code', 'STORE_PENDING_ORDER');
        $this->assertSame(1, Order::count());
        $this->withHeaders($this->headers)->getJson('/api/v1/client/store')->assertOk()->assertJsonPath('data.order.trade_no', $order['trade_no']);
        $this->withHeaders($this->headers)->postJson('/api/v1/client/store/cancel', ['trade_no' => $order['trade_no']])->assertOk()->assertJsonPath('data.status', 2);
        $this->assertEquals(234, $this->user->fresh()->balance);
    }

    public function test_other_users_cannot_read_pay_or_cancel_order(): void
    {
        $order = $this->save()->assertOk()->json('data');
        Order::where('trade_no', $order['trade_no'])->update(['user_id' => $this->user->id + 999]);
        $this->withHeaders($this->headers)->getJson('/api/v1/client/store/order?trade_no=' . $order['trade_no'])->assertNotFound();
        foreach (['checkout', 'cancel'] as $action) {
            $this->withHeaders($this->headers)->postJson('/api/v1/client/store/' . $action, ['trade_no' => $order['trade_no']])->assertNotFound();
        }
    }

    public function test_invalid_period_hidden_or_unsellable_plan_never_creates_order(): void
    {
        $this->save(['period' => 'invalid'])->assertStatus(422);
        $this->save(['period' => 'quarter_price'])->assertStatus(400)->assertJsonPath('code', 'STORE_ORDER_REJECTED');
        $this->plan->update(['sell' => 0]);
        $this->save()->assertStatus(400)->assertJsonPath('code', 'STORE_PLAN_UNAVAILABLE');
        $this->plan->update(['sell' => 1, 'show' => 0]);
        $this->save()->assertStatus(400);
        $this->assertSame(0, Order::count());
        $this->assertEquals(234, $this->user->fresh()->balance);
    }

    public function test_existing_users_can_renew_hidden_plan_but_cannot_renew_when_disabled(): void
    {
        $this->user->update(['plan_id' => $this->plan->id, 'expired_at' => time() + 86400, 'transfer_enable' => 100 * 1073741824]);
        $this->plan->update(['show' => 0, 'sell' => 0]);
        $this->withHeaders($this->headers)->getJson('/api/v1/client/store')->assertOk()->assertJsonPath('data.plans.0.current', true);
        $order = $this->save()->assertOk()->json('data');
        $this->withHeaders($this->headers)->postJson('/api/v1/client/store/cancel', ['trade_no' => $order['trade_no']])->assertOk();
        $this->plan->update(['show' => 1, 'sell' => 1, 'renew' => 0]);
        $this->save()->assertStatus(400)->assertJsonPath('code', 'STORE_PLAN_UNAVAILABLE');
    }

    public function test_zero_due_order_uses_existing_payment_and_activation_flow(): void
    {
        $this->user->update(['balance' => 1234]);
        $order = $this->save()->assertOk()->assertJsonPath('data.total_amount', 0)->json('data');
        $this->withHeaders($this->headers)->postJson('/api/v1/client/store/checkout', ['trade_no' => $order['trade_no']])
            ->assertOk()->assertJsonPath('data.kind', 'submitted');
        $status = Order::where('trade_no', $order['trade_no'])->value('status');
        $this->assertContains($status, [Order::STATUS_PROCESSING, Order::STATUS_COMPLETED]);
        if ($status === Order::STATUS_PROCESSING) {
            (new \App\Services\OrderService(Order::where('trade_no', $order['trade_no'])->first()))->open();
        }
        $this->withHeaders($this->headers)->getJson('/api/v1/client/store/order?trade_no=' . $order['trade_no'])->assertOk()->assertJsonPath('data.status', 3);
        $this->assertEquals($this->plan->id, $this->user->fresh()->plan_id);
    }

    public function test_payment_projection_accepts_url_and_qr_but_rejects_html_and_unsafe_urls(): void
    {
        $order = $this->save()->assertOk()->json('data');
        foreach ([[1, 'https://pay.example.com/session', 'url'], [0, 'alipays://qr/test', 'qr'], [1, 'javascript:alert(1)', null], [2, '<form>secret</form>', null]] as [$type, $data, $kind]) {
            $controller = \Mockery::mock(OrderController::class);
            $controller->shouldReceive('checkout')->once()->andReturn(response(['type' => $type, 'data' => $data]));
            $this->app->instance(OrderController::class, $controller);
            $response = $this->withHeaders($this->headers)->postJson('/api/v1/client/store/checkout', ['trade_no' => $order['trade_no'], 'method' => 1]);
            if ($kind) $response->assertOk()->assertJsonPath('data.kind', $kind)->assertJsonPath('data.data', $data);
            else $response->assertStatus(400)->assertJsonPath('code', 'STORE_PAYMENT_UNSUPPORTED');
        }
    }

    private function save(array $payload = [])
    {
        return $this->withHeaders($this->headers)->postJson('/api/v1/client/store/save', array_merge([
            'plan_id' => $this->plan->id, 'period' => 'month_price',
        ], $payload));
    }
}
