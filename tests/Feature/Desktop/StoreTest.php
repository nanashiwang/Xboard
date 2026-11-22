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

    public function test_wallet_history_only_lists_the_ten_latest_subscription_orders_using_own_balance(): void
    {
        $trade = $this->save()->assertOk()->json('data.trade_no');
        $original = Order::where('trade_no', $trade)->firstOrFail();
        foreach (range(1, 11) as $n) {
            $copy = $original->replicate();
            $copy->trade_no = "wallet-own-$n";
            $copy->save();
        }
        foreach (['balance_amount' => 0, 'product_type' => 'proxy', 'user_id' => $this->user->id + 1] as $field => $value) {
            $copy = $original->replicate();
            $copy->trade_no = "excluded-$field";
            $copy->$field = $value;
            $copy->save();
        }
        $this->getJson('/api/v1/client/store', $this->headers)->assertJsonMissingPath('data.wallet_orders');
        $rows = $this->getJson('/api/v1/client/store?wallet=1', $this->headers)->assertOk()->json('data.wallet_orders');
        $this->assertSame(array_map(fn ($n) => "wallet-own-$n", range(11, 2)), array_column($rows, 'trade_no'));
    }

    public function test_web_and_desktop_wallet_share_subscription_deductions_and_returns(): void
    {
        $web = ['Authorization' => (new \App\Services\AuthService($this->user))->generateAuthData()['auth_data']];
        $payload = ['plan_id' => $this->plan->id, 'period' => 'month_price'];
        $this->app['auth']->forgetGuards();
        $trade = $this->postJson('/api/v1/user/order/save', $payload, $web)->assertOk()->json('data');

        $this->app['auth']->forgetGuards();
        $this->getJson('/api/v1/client/store?wallet=1', $this->headers)->assertOk()
            ->assertJsonPath('data.balance', 0)->assertJsonCount(1, 'data.wallet_orders')
            ->assertJsonPath('data.wallet_orders.0.trade_no', $trade)
            ->assertJsonPath('data.wallet_orders.0.balance_amount', 234)
            ->assertJsonPath('data.order.total_amount', 1000);
        $this->postJson('/api/v1/client/store/cancel', ['trade_no' => $trade], $this->headers)
            ->assertOk()->assertJsonPath('data.account_balance', 234);
        $this->getJson('/api/v1/client/store?wallet=1', $this->headers)->assertJsonPath('data.wallet_orders.0.status', 2);

        $this->app['auth']->forgetGuards();
        $this->getJson('/api/v1/user/info', $web)->assertOk()->assertJsonPath('data.balance', 234);
        $this->user->update(['balance' => 1500]);
        $this->app['auth']->forgetGuards();
        $second = $this->save()->assertOk()->assertJsonPath('data.balance_amount', 1234)
            ->assertJsonPath('data.total_amount', 0)->assertJsonPath('data.account_balance', 266)->json('data.trade_no');
        $this->app['auth']->forgetGuards();
        $this->getJson('/api/v1/user/info', $web)->assertOk()->assertJsonPath('data.balance', 266);
        $this->postJson('/api/v1/user/order/cancel', ['trade_no' => $second], $web)->assertOk();
        $this->app['auth']->forgetGuards();
        $this->getJson('/api/v1/client/store?wallet=1', $this->headers)->assertOk()
            ->assertJsonPath('data.balance', 1500)->assertJsonCount(2, 'data.wallet_orders')
            ->assertJsonPath('data.wallet_orders.0.trade_no', $second)->assertJsonPath('data.wallet_orders.0.status', 2);
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

    public function test_wallet_topup_requires_verified_payment_and_credits_principal_once_even_after_cancel(): void
    {
        $payment = \App\Models\Payment::create(['name' => '测试充值', 'payment' => 'EPay',
            'uuid' => str_repeat('a', 32), 'enable' => 1, 'handling_fee_fixed' => 50,
            'config' => ['pid' => 'fixture', 'key' => 'fixture-key', 'url' => 'https://example.test']]);
        $plugin = new \Plugin\Epay\Plugin('epay');
        $plugin->boot();
        $this->partialMock(\App\Services\Plugin\PluginManager::class)
            ->shouldReceive('getEnabledPaymentPlugins')->andReturn([$plugin]);
        $other = $payment->replicate();
        $other->uuid = str_repeat('b', 32);
        $other->save();
        $user = $this->user->fresh();
        $save = fn ($amount) => $this->postJson('/api/v1/client/store/topup', ['amount' => $amount, 'method' => $payment->id], $this->headers);
        $save(0)->assertStatus(422);
        $save(30.55)->assertStatus(422);
        $trade = $save(3000)->assertOk()->assertJsonPath('data.plan_name', '钱包充值')
            ->assertJsonPath('data.balance_amount', 0)->assertJsonPath('data.handling_amount', 50)
            ->assertJsonPath('data.total_amount', 3000)->json('data.trade_no');
        $save(3000)->assertStatus(409);
        $this->getJson('/api/v1/client/store?wallet=1', $this->headers)->assertOk()
            ->assertJsonPath('data.order.trade_no', $trade)->assertJsonPath('data.topups.0.status', 0)
            ->assertJsonPath('data.balance', 234);
        $this->postJson('/api/v1/client/store/checkout', ['trade_no' => $trade, 'method' => $other->id], $this->headers)
            ->assertJsonPath('code', 'STORE_PAYMENT_FAILED');
        $checkout = $this->postJson('/api/v1/client/store/checkout', ['trade_no' => $trade, 'method' => $payment->id], $this->headers)
            ->assertOk()->assertJsonPath('data.kind', 'url')->json('data.data');
        parse_str(parse_url($checkout, PHP_URL_QUERY), $query);
        $this->assertEquals('30.5', $query['money']);
        $this->postJson('/api/v1/client/store/cancel', ['trade_no' => $trade], $this->headers)->assertOk();
        $order = Order::where('trade_no', $trade)->firstOrFail();
        $notify = function ($status, $amount, $uuid, $key = 'fixture-key') use ($trade) {
            $params = ['pid' => 'fixture', 'trade_no' => 'paid-fixture', 'out_trade_no' => $trade,
                'trade_status' => $status, 'money' => $amount];
            ksort($params);
            $params['sign'] = md5(stripslashes(urldecode(http_build_query($params))) . $key);
            $params['sign_type'] = 'MD5';
            return $this->postJson('/api/v1/guest/payment/notify/EPay/' . $uuid, $params);
        };
        $notify('TRADE_SUCCESS', '30.50', $payment->uuid, 'invalid-fixture')->assertStatus(422);
        $notify('WAIT_BUYER_PAY', '30.50', $payment->uuid)->assertStatus(400);
        $notify('TRADE_SUCCESS', '30.00', $payment->uuid)->assertStatus(400);
        $notify('TRADE_SUCCESS', '30.50', $other->uuid)->assertStatus(400);
        $this->assertEquals(234, $user->fresh()->balance);
        $notify('TRADE_SUCCESS', '30.50', $payment->uuid)->assertOk()->assertContent('success');
        $notify('TRADE_SUCCESS', '30.50', $payment->uuid)->assertOk()->assertContent('success');
        $this->assertSame(Order::STATUS_COMPLETED, $order->fresh()->status);
        $this->assertEquals(3234, $user->fresh()->balance);
        $this->assertEquals($user->plan_id, $user->fresh()->plan_id);
        $this->assertFalse((new \App\Services\OrderService($order))->cancel());
        $this->getJson('/api/v1/client/store?wallet=1', $this->headers)->assertOk()
            ->assertJsonPath('data.balance', 3234)->assertJsonPath('data.topups.0.status', 3);
    }

    private function save(array $payload = [])
    {
        return $this->withHeaders($this->headers)->postJson('/api/v1/client/store/save', array_merge([
            'plan_id' => $this->plan->id, 'period' => 'month_price',
        ], $payload));
    }
}
