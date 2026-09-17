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
            && $r['metadata']['payment_id'] === '7' && !isset($r['payment_method_types'])
            && $r['adaptive_pricing']['enabled'] === 'false');
        $requests = Http::recorded();
        foreach ($requests as [$request]) {
            // Assert the encoded body: Laravel's array access retains the original
            // parameters and can hide Guzzle serializing a PHP false as "0".
            parse_str($request->body(), $form);
            $this->assertSame('false', $form['adaptive_pricing']['enabled']);
            $this->assertSame('cny', $form['line_items'][0]['price_data']['currency']);
            $this->assertSame('1050', $form['line_items'][0]['price_data']['unit_amount']);
        }
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
        $this->assertSame([['value' => 'usd', 'label' => '美元 USD'], ['value' => 'cny', 'label' => '人民币 CNY']], $form['currency']['options']);
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

    private function usdGateway(array $overrides = []): Plugin
    {
        $gateway = $this->gateway();
        $gateway->setConfig(array_replace($gateway->getConfig(), ['currency' => 'usd', 'exchange_rate' => '6.7075', 'cost_percent' => '4.4', 'cost_fixed_usd' => '0.30'], $overrides));
        return $gateway;
    }

    public function test_usd_formula_rounds_up_and_covers_the_configured_budget(): void
    {
        foreach ([990 => 186, 2000 => 344, 2990 => 498, 4990 => 810] as $cny => $usd) {
            $quote = \Plugin\Stripe\UsdPricing::calculate($cny, '6.7075', '4.4', '0.30');
            $this->assertSame($usd, $quote['amount']);
        }
        foreach (['0', '-1', 'NaN', '1e2', '6.1234567', '21'] as $rate) {
            try {
                \Plugin\Stripe\UsdPricing::calculate(990, $rate, '4.4', '0.30');
                $this->fail('Invalid rate accepted');
            } catch (ApiException $e) {
                $this->assertNotEmpty($e->getMessage());
            }
        }
    }

    public function test_usd_quote_is_persisted_and_rate_changes_do_not_change_an_existing_quote(): void
    {
        $this->order();
        Http::preventStrayRequests();
        Http::fake(['api.stripe.com/*' => Http::response(['url' => 'https://checkout.stripe.com/c/pay/cs_test_example'])]);
        $input = ['total_amount' => 1050, 'trade_no' => 'test-order', 'return_url' => 'https://board.example/#/order/test-order'];
        $this->usdGateway()->pay($input);
        $this->usdGateway(['exchange_rate' => '7.5', 'cost_percent' => '8'])->pay($input);
        $this->assertDatabaseCount('v2_stripe_quotes', 1);
        $requests = Http::recorded();
        $this->assertSame($requests[0][0]['line_items'], $requests[1][0]['line_items']);
        $this->assertSame('usd', $requests[0][0]['line_items'][0]['price_data']['currency']);
        $quote = \Illuminate\Support\Facades\DB::table('v2_stripe_quotes')->first();
        foreach ($requests as [$request]) {
            parse_str($request->body(), $form);
            $this->assertSame('false', $form['adaptive_pricing']['enabled']);
            $this->assertSame('usd', $form['line_items'][0]['price_data']['currency']);
            $this->assertSame((string) $quote->amount, $form['line_items'][0]['price_data']['unit_amount']);
        }
        $this->assertSame(1050, (int) $quote->cny_amount);
        $changes = ['currency' => 'usd', 'amount_total' => (int) $quote->amount,
            'metadata' => ['trade_no' => 'test-order', 'payment_id' => '7', 'quote_id' => $quote->id]];
        $this->assertIsArray($this->notify($this->usdGateway(['exchange_rate' => '8']), $this->event($changes)));
        $this->assertFalse($this->notify($this->usdGateway(), $this->event(array_replace($changes, ['amount_total' => 1050]))));
        $this->assertFalse($this->notify($this->usdGateway(), $this->event(array_replace($changes, ['currency' => 'cny']))));
        $this->assertFalse($this->notify($this->usdGateway(), $this->event(['currency' => 'usd', 'amount_total' => $quote->amount])));
        Order::where('trade_no', 'test-order')->update(['total_amount' => 900]);
        $this->assertFalse($this->notify($this->usdGateway(), $this->event($changes)));
    }

    public function test_usd_catalog_price_is_only_used_for_exact_amount_and_discount_uses_same_product(): void
    {
        $order = $this->order();
        $order->update(['period' => 'monthly', 'total_amount' => 990, 'handling_amount' => 0]);
        Http::preventStrayRequests();
        Http::fake(['api.stripe.com/*' => Http::response(['url' => 'https://checkout.stripe.com/c/pay/cs_test_example'])]);
        $gateway = $this->usdGateway(['catalog_usd' => ['1' => ['product' => 'prod_example', 'prices' => ['monthly' => ['id' => 'price_example', 'amount' => 186]]]]]);
        $input = ['total_amount' => 990, 'trade_no' => 'test-order', 'return_url' => 'https://board.example/#/order/test-order'];
        $gateway->pay($input);
        $order->update(['total_amount' => 700]);
        $gateway->pay(array_replace($input, ['total_amount' => 700]));
        $requests = Http::recorded();
        $this->assertSame('price_example', $requests[0][0]['line_items'][0]['price']);
        $this->assertSame('prod_example', $requests[1][0]['line_items'][0]['price_data']['product']);
        $this->assertArrayNotHasKey('product_data', $requests[1][0]['line_items'][0]['price_data']);
        $this->assertDatabaseCount('v2_stripe_quotes', 2);
    }

    public function test_restricted_api_key_accepts_a_signed_live_event(): void
    {
        $this->order();
        $gateway = $this->gateway();
        $gateway->setConfig(array_replace($gateway->getConfig(), ['secret_key' => 'rk_live_example']));
        $event = $this->event();
        $event['livemode'] = true;
        $this->assertIsArray($this->notify($gateway, $event));
    }

    public function test_usd_quote_rejects_invalid_fee_budget_and_tiny_payments(): void
    {
        foreach ([[1, '6.7075', '0', '0'], [990, '6.7075', '100', '0.30'], [990, '6.7075', '4.4', '-1'], [100000001, '6.7075', '4.4', '0.30']] as $args) {
            try {
                \Plugin\Stripe\UsdPricing::calculate(...$args);
                $this->fail('Invalid quote accepted');
            } catch (ApiException $e) {
                $this->assertNotEmpty($e->getMessage());
            }
        }
    }
}
