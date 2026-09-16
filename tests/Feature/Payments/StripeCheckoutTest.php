<?php

namespace Tests\Feature\Payments;

use App\Exceptions\ApiException;
use App\Models\Order;
use App\Models\Payment;
use App\Models\Plugin as PluginModel;
use App\Services\PaymentService;
use App\Services\Plugin\PluginManager;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;
use Plugin\Stripe\Plugin;
use Tests\TestCase;

class StripeCheckoutTest extends TestCase
{
    use RefreshDatabase;

    private function gateway(): Plugin
    {
        admin_setting(['currency' => 'CNY']);
        $plugin = new Plugin('stripe');
        $plugin->setConfig(['id' => 7, 'uuid' => 'channel7', 'secret_key' => 'sk_test_example', 'webhook_secret' => 'whsec_example', 'currency' => 'cny']);
        return $plugin;
    }

    private function event(array $changes = [], string $type = 'checkout.session.completed'): array
    {
        return ['id' => 'evt_example', 'object' => 'event', 'type' => $type, 'livemode' => false, 'data' => ['object' => array_replace([
            'id' => 'cs_test_example', 'object' => 'checkout.session', 'mode' => 'payment',
            'payment_status' => 'paid', 'currency' => 'cny', 'amount_total' => 1050,
            'client_reference_id' => 'test-order', 'metadata' => ['trade_no' => 'test-order', 'payment_id' => '7'],
            'payment_intent' => 'pi_example',
        ], $changes)]];
    }

    private function notify(Plugin $plugin, array $event, string $secret = 'whsec_example', ?int $timestamp = null): array|bool
    {
        $body = json_encode($event);
        $timestamp ??= time();
        $signature = hash_hmac('sha256', $timestamp . '.' . $body, $secret);
        $request = Request::create('/notify', 'POST', [], [], [], ['CONTENT_TYPE' => 'application/json', 'HTTP_STRIPE_SIGNATURE' => "t={$timestamp},v1={$signature}"], $body);
        $this->app->instance('request', $request);
        return $plugin->notify([]);
    }

    private function order(): Order
    {
        return Order::create(['user_id' => 1, 'plan_id' => 1, 'payment_id' => 7, 'type' => 1, 'period' => 'month_price', 'trade_no' => 'test-order', 'total_amount' => 1000, 'handling_amount' => 50]);
    }

    public function test_checkout_uses_cny_minor_units_metadata_and_idempotency(): void
    {
        Http::preventStrayRequests();
        Http::fake(['api.stripe.com/*' => Http::response(['url' => 'https://checkout.stripe.com/c/pay/cs_test_example'])]);
        $gateway = $this->gateway();
        $order = ['total_amount' => 1050, 'trade_no' => 'test-order', 'return_url' => 'https://board.example/#/order/test-order'];
        $result = $gateway->pay($order);
        $gateway->pay($order);
        $this->assertSame(1, $result['type']);
        Http::assertSent(fn ($r) => $r['line_items'][0]['price_data']['unit_amount'] === 1050
            && $r['line_items'][0]['price_data']['currency'] === 'cny'
            && $r['metadata']['payment_id'] === '7' && $r['payment_method_types'] === ['card']);
        $requests = Http::recorded();
        $this->assertSame($requests[0][0]->header('Idempotency-Key'), $requests[1][0]->header('Idempotency-Key'));
    }

    public function test_valid_paid_event_matches_order_and_includes_handling_fee(): void
    {
        $this->order();
        $this->assertSame(['trade_no' => 'test-order', 'callback_no' => 'pi_example'], $this->notify($this->gateway(), $this->event()));
    }

    public function test_wrong_signature_and_expired_signature_are_rejected(): void
    {
        $plugin = $this->gateway();
        $this->assertFalse($this->notify($plugin, $this->event(), 'whsec_wrong'));
        $this->assertFalse($this->notify($plugin, $this->event(), timestamp: time() - 600));
    }

    public function test_mismatched_amount_currency_channel_reference_or_mode_are_rejected(): void
    {
        $this->order();
        $plugin = $this->gateway();
        foreach ([['amount_total' => 1000], ['currency' => 'usd'], ['metadata' => ['trade_no' => 'test-order', 'payment_id' => '8']], ['client_reference_id' => 'another-order'], ['mode' => 'subscription']] as $change) {
            $this->assertFalse($this->notify($plugin, $this->event($change)));
        }
        $event = $this->event();
        $event['livemode'] = true;
        $this->assertFalse($this->notify($plugin, $event));
    }

    public function test_unknown_order_or_changed_payment_channel_is_rejected(): void
    {
        $plugin = $this->gateway();
        $this->assertFalse($this->notify($plugin, $this->event()));
        $this->order()->update(['payment_id' => 8]);
        $this->assertFalse($this->notify($plugin, $this->event()));
    }

    public function test_signed_unpaid_and_unrelated_events_are_acknowledged_without_fulfilment(): void
    {
        $plugin = $this->gateway();
        $this->assertSame(['skip_order' => true], $this->notify($plugin, $this->event(['payment_status' => 'unpaid'])));
        $this->assertSame(['skip_order' => true], $this->notify($plugin, $this->event(type: 'payment_intent.created')));
    }

    public function test_missing_plugin_preserves_database_configuration(): void
    {
        PluginModel::create(['code' => 'missing_test_gateway', 'name' => 'Missing', 'version' => '1.0.0', 'type' => 'payment', 'is_enabled' => true, 'config' => '{}']);
        app(PluginManager::class)->initializeEnabledPlugins();
        $this->assertDatabaseHas('v2_plugins', ['code' => 'missing_test_gateway', 'is_enabled' => true]);
    }

    public function test_missing_payment_method_returns_controlled_error(): void
    {
        $this->expectException(ApiException::class);
        new PaymentService('MissingGateway');
    }

    public function test_enabled_stripe_plugin_populates_dropdown_and_form(): void
    {
        $manager = app(PluginManager::class);
        $manager->install('stripe');
        $manager->enable('stripe');
        $this->assertContains('StripeCheckout', PaymentService::getAllPaymentMethodNames());
        $form = (new PaymentService('StripeCheckout'))->form();
        $this->assertArrayHasKey('webhook_secret', $form);
        $this->assertSame([['value' => 'cny', 'label' => '人民币 CNY']], $form['currency']['options']);
    }

    public function test_duplicate_callback_does_not_reprocess_completed_order(): void
    {
        $gateway = $this->gateway();
        $manager = app(PluginManager::class);
        $manager->install('stripe');
        $manager->enable('stripe');
        $manager->initializeEnabledPlugins();
        Payment::forceCreate(['id' => 7, 'uuid' => 'channel7', 'name' => 'Stripe test', 'payment' => 'StripeCheckout', 'config' => $gateway->getConfig(), 'enable' => true]);
        $order = $this->order();
        $order->update(['status' => Order::STATUS_COMPLETED, 'callback_no' => 'pi_example']);
        $this->notify($gateway, $this->event());
        $controller = new \App\Http\Controllers\V1\Guest\PaymentController();
        $this->assertSame('success', $controller->notify('StripeCheckout', 'channel7', request()));
        $this->assertSame('success', $controller->notify('StripeCheckout', 'channel7', request()));
        $this->assertSame(Order::STATUS_COMPLETED, $order->fresh()->status);
        $this->assertSame('pi_example', $order->fresh()->callback_no);
    }

    public function test_incomplete_credentials_never_call_stripe(): void
    {
        Http::preventStrayRequests();
        $gateway = new Plugin('stripe');
        $gateway->setConfig(['secret_key' => 'sk_test_example']);
        $this->expectException(ApiException::class);
        $gateway->pay(['total_amount' => 1000]);
    }
}
