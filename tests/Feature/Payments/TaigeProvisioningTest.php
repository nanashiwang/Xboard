<?php

namespace Tests\Feature\Payments;

use App\Models\Payment;
use App\Services\Plugin\PluginManager;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class TaigeProvisioningTest extends TestCase
{
    use RefreshDatabase;

    private array $endpoints = [];
    private bool $failCallback = false;
    private bool $allowAlipay = true;
    private bool $wrongAmount = false;
    private int $created = 0;
    private int $expired = 0;

    protected function setUp(): void
    {
        parent::setUp();
        $this->app->useStoragePath(sys_get_temp_dir() . '/xboard-taige-test-' . bin2hex(random_bytes(8)));
        require_once base_path('.docker/production/provision-taige-alipay.php');
        admin_setting(['currency' => 'CNY', 'app_url' => 'https://taige.us']);
        Payment::create(['id' => 1, 'uuid' => 'old', 'payment' => 'EPay', 'name' => 'Old', 'config' => [], 'enable' => false]);
        // guarded id is allocated sequentially, matching the production guard.
        Payment::create(['uuid' => 'raymi', 'payment' => 'StripeCheckout', 'name' => 'Raymi', 'enable' => true,
            'config' => ['payment_method_configuration' => 'pmc_1UOe6623UvHgD4dFh9FhQDvg']]);
        $manager = app(PluginManager::class);
        $manager->install('stripe');
        $manager->enable('stripe');
        $manager->initializeEnabledPlugins();
        Http::preventStrayRequests();
        Http::fake(function ($request) {
            $url = $request->url();
            if (str_contains($url, 'payment_method_configurations/')) return Http::response([
                'id' => 'pmc_1UGbzR1DvmJXrFlVLsBXHPnq', 'active' => true, 'livemode' => true,
                'alipay' => ['available' => $this->allowAlipay, 'display_preference' => ['value' => 'on']],
            ]);
            if (str_ends_with($url, '/account')) return Http::response([], 403);
            if (str_ends_with($url, '/webhook_endpoints')) {
                $id = 'we_test_' . ++$this->created;
                $this->endpoints[$id] = array_merge($request->data(), ['id' => $id, 'secret' => 'whsec_example', 'livemode' => true, 'status' => 'enabled']);
                return Http::response($this->endpoints[$id]);
            }
            if (str_contains($url, '/webhook_endpoints/')) return Http::response($this->endpoints[basename($url)]);
            if (str_ends_with($url, '/checkout/sessions')) return Http::response([
                'id' => 'cs_live_probe_' . $request['line_items'][0]['price_data']['unit_amount'],
                'url' => 'https://checkout.stripe.com/c/pay/test', 'livemode' => true,
                'currency' => $request['line_items'][0]['price_data']['currency'],
                'amount_total' => $request['line_items'][0]['price_data']['unit_amount'] + ($this->wrongAmount ? 1 : 0),
                'metadata' => $request['metadata'], 'payment_method_types' => ['card', 'alipay'],
                'payment_method_configuration_details' => ['id' => $request['payment_method_configuration']],
            ]);
            if (str_ends_with($url, '/expire')) { $this->expired++; return Http::response(['status' => 'expired']); }
            if (str_contains($url, '/payment/notify/')) {
                $sig = $request->header('Stripe-Signature')[0];
                preg_match('/t=(\d+),v1=(.+)/', $sig, $matches);
                $valid = hash_equals(hash_hmac('sha256', $matches[1] . '.' . $request->body(), 'whsec_example'), $matches[2]);
                return Http::response($valid && !$this->failCallback ? 'success' : 'verify error', $valid && !$this->failCallback ? 200 : 422);
            }
            throw new \RuntimeException('Unexpected test HTTP request');
        });
    }

    protected function tearDown(): void
    {
        \Illuminate\Support\Facades\File::deleteDirectory(storage_path());
        parent::tearDown();
    }

    public function test_provision_is_isolated_and_resumable_with_expired_probes(): void
    {
        $old = Payment::orderBy('id')->get()->toJson();
        $result = \provisionTaigeAlipay('rk_live_example');
        $this->assertTrue($result['enabled']);
        $this->assertSame(4, count(Http::recorded(fn ($r) => str_contains($r->url(), '/checkout/sessions'))));
        $this->assertSame(2, $this->expired);
        $this->assertSame($old, Payment::whereIn('id', [1, 2])->orderBy('id')->get()->toJson());
        $again = \provisionTaigeAlipay('rk_live_example');
        $this->assertSame($result['payment_id'], $again['payment_id']);
        $this->assertSame(1, $this->created);
        $this->assertSame(3, Payment::count());
        $this->assertTrue($again['invalid_signature_rejected']);
    }

    public function test_callback_failure_disables_only_new_channel(): void
    {
        $this->failCallback = true;
        try { \provisionTaigeAlipay('rk_live_example'); $this->fail('Expected callback failure'); }
        catch (\RuntimeException $e) { $this->assertStringContainsString('Public signed callback failed', $e->getMessage()); }
        $this->assertTrue(Payment::find(2)->enable);
        $this->assertFalse(Payment::find(3)->enable);
        $this->assertSame(2, $this->expired);
    }

    public function test_unavailable_alipay_does_not_change_channels(): void
    {
        $this->allowAlipay = false;
        try { \provisionTaigeAlipay('rk_live_example'); $this->fail('Expected capability failure'); }
        catch (\RuntimeException $e) { $this->assertStringContainsString('not ready', $e->getMessage()); }
        $this->assertSame(2, Payment::count());
        $this->assertSame(0, $this->created);
    }

    public function test_checkout_mismatch_expires_probe_and_keeps_channel_disabled(): void
    {
        $this->wrongAmount = true;
        try { \provisionTaigeAlipay('rk_live_example'); $this->fail('Expected Checkout validation failure'); }
        catch (\RuntimeException $e) { $this->assertStringContainsString('Checkout currency', $e->getMessage()); }
        $this->assertSame(1, $this->expired);
        $this->assertFalse(Payment::find(3)->enable);
        $this->assertTrue(Payment::find(2)->enable);
    }
}
