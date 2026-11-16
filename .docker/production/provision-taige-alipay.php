<?php
// Dedicated, resumable provisioning; never print credentials or raw Stripe responses.
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;

function provisionTaigeAlipay(string $key): array
{
    $account = 'acct_1UGbyu1DvmJXrFlV';
    $pmc = 'pmc_1UGbzR1DvmJXrFlVLsBXHPnq';
    $marker = 'xboard-taige-alipay-v1';
    $base = 'https://api.stripe.com/v1/';
    $version = '2026-07-29.dahlia';
    if (!preg_match('/^rk_live_[A-Za-z0-9]+$/', $key)) throw new RuntimeException('Expected live restricted key');
    $api = fn () => Http::asForm()->withToken($key)->withHeaders(['Stripe-Version' => $version])->connectTimeout(10)->timeout(30);
    $check = function ($response, string $operation): array {
        if (!$response->successful()) {
            // Stripe messages can contain sensitive parameters. Only allow diagnostic codes.
            $code = preg_replace('/[^a-zA-Z0-9_]/', '', (string) $response->json('error.code'));
            throw new RuntimeException($operation . ': HTTP ' . $response->status() . ' code=' . $code);
        }
        return $response->json();
    };
    $config = $check($api()->get($base . 'payment_method_configurations/' . $pmc), 'Read target payment configuration');
    if (($config['id'] ?? '') !== $pmc || !($config['livemode'] ?? false) || !($config['active'] ?? false)
        || !($config['alipay']['available'] ?? false) || ($config['alipay']['display_preference']['value'] ?? '') !== 'on') {
        throw new RuntimeException('Target live Alipay configuration is not ready');
    }
    // A restricted key may not have Account read. Owning the exact live PMC is sufficient.
    $identity = $api()->get($base . 'account');
    if ($identity->successful() && $identity->json('id') !== $account) throw new RuntimeException('Wrong Stripe account');
    if (!$identity->successful() && $identity->status() !== 403) $check($identity, 'Read account identity');

    $all = DB::table('v2_payment')->orderBy('id')->get();
    $existing = null;
    foreach ($all as $row) {
        $c = json_decode($row->config, true) ?: [];
        if (($c['provisioning_marker'] ?? '') === $marker) {
            if ($existing) throw new RuntimeException('Duplicate managed channel');
            $existing = $row;
        } elseif (($c['payment_method_configuration'] ?? '') === $pmc) {
            throw new RuntimeException('Unmanaged target channel already exists; inspect before proceeding');
        }
    }
    $raymi = $all->firstWhere('id', 2);
    if (!$raymi || !$raymi->enable || $raymi->payment !== 'StripeCheckout'
        || (json_decode($raymi->config, true)['payment_method_configuration'] ?? '') !== 'pmc_1UOe6623UvHgD4dFh9FhQDvg') {
        throw new RuntimeException('Existing Raymi channel drift; abort');
    }
    $protected = $all->reject(fn ($row) => $existing && $row->id === $existing->id)->values()->toJson();
    $dir = storage_path('app/backups/taige-alipay-20261116');
    if (!is_dir($dir) && !mkdir($dir, 0700, true)) throw new RuntimeException('Backup directory failed');
    chmod($dir, 0700);
    $writePrivate = function (string $path, array $data) {
        $old = umask(0077);
        try {
            if (file_put_contents($path, json_encode($data, JSON_THROW_ON_ERROR), LOCK_EX) === false) throw new RuntimeException('Private backup failed');
            chmod($path, 0600);
        } finally { umask($old); }
    };
    $backup = $dir . '/payments-' . date('Ymd-His') . '-' . bin2hex(random_bytes(4)) . '.json';
    $writePrivate($backup, ['payments' => $all->all()]);
    $id = null;
    $enabledByRun = false;
    try {
        if (!$existing) {
            $uuid = bin2hex(random_bytes(8));
            $c = ['secret_key' => $key, 'webhook_secret' => '', 'currency' => 'cny',
                'cost_percent' => '0', 'cost_fixed_usd' => '0.00', 'payment_method_configuration' => $pmc,
                'provisioning_marker' => $marker, 'stripe_account_id' => $account];
            $id = DB::transaction(function () use ($all, $uuid, $c) {
                if (DB::table('v2_payment')->orderBy('id')->get()->toJson() !== $all->toJson()) throw new RuntimeException('Concurrent payment configuration change');
                return DB::table('v2_payment')->insertGetId(['uuid' => $uuid, 'payment' => 'StripeCheckout',
                    'name' => '支付宝（taige）', 'config' => json_encode($c, JSON_THROW_ON_ERROR),
                    'notify_domain' => 'https://taige.us', 'handling_fee_fixed' => 0, 'handling_fee_percent' => 0,
                    'enable' => 0, 'sort' => 1, 'created_at' => time(), 'updated_at' => time()]);
            });
        } else {
            $id = $existing->id;
            $uuid = $existing->uuid;
            $c = json_decode($existing->config, true, 512, JSON_THROW_ON_ERROR);
            if ($existing->payment !== 'StripeCheckout' || $existing->notify_domain !== 'https://taige.us'
                || $c['secret_key'] !== $key || $c['currency'] !== 'cny' || $c['payment_method_configuration'] !== $pmc
                || (float)$c['cost_percent'] !== 0.0 || (float)$c['cost_fixed_usd'] !== 0.0
                || $existing->handling_fee_fixed || $existing->handling_fee_percent) throw new RuntimeException('Managed channel drift; abort');
        }
        $callback = 'https://taige.us/api/v1/guest/payment/notify/StripeCheckout/' . $uuid;
        $events = ['checkout.session.completed', 'checkout.session.async_payment_succeeded'];
        if (empty($c['webhook_secret'])) {
            if ($existing && $existing->enable) throw new RuntimeException('Enabled channel has no webhook secret; inspect before proceeding');
            $journal = $dir . '/webhook-' . $uuid . '.json';
            if (is_file($journal)) {
                $webhook = json_decode(file_get_contents($journal), true, 512, JSON_THROW_ON_ERROR);
            } else {
                $webhook = $check($api()->withHeaders(['Idempotency-Key' => $marker . '-' . $uuid])->post($base . 'webhook_endpoints', [
                    'url' => $callback, 'enabled_events' => $events, 'api_version' => $version,
                    'description' => 'Xboard taige Alipay independent payment channel',
                    'metadata' => ['project' => 'xboard', 'payment_id' => (string)$id, 'site' => 'taige.us', 'provisioning_marker' => $marker],
                ]), 'Create independent webhook');
                $writePrivate($journal, $webhook);
            }
            if (!str_starts_with($webhook['secret'] ?? '', 'whsec_') || ($webhook['url'] ?? '') !== $callback) throw new RuntimeException('Webhook provisioning response invalid');
            $c['webhook_secret'] = $webhook['secret'];
            $c['webhook_endpoint_id'] = $webhook['id'];
            DB::table('v2_payment')->where('id', $id)->where('enable', 0)->update(['config' => json_encode($c, JSON_THROW_ON_ERROR), 'updated_at' => time()]);
        }
        $webhook = $check($api()->get($base . 'webhook_endpoints/' . $c['webhook_endpoint_id']), 'Verify webhook');
        if (($webhook['url'] ?? '') !== $callback || ($webhook['status'] ?? '') !== 'enabled'
            || !($webhook['livemode'] ?? false) || ($webhook['api_version'] ?? '') !== $version
            || array_diff($events, $webhook['enabled_events'] ?? []) || array_diff($webhook['enabled_events'] ?? [], $events)
            || (string)($webhook['metadata']['payment_id'] ?? '') !== (string)$id) throw new RuntimeException('Independent webhook mismatch');

        // Exercise the actual production plugin. No local order/customer/payment is created.
        Http::record();
        $service = new App\Services\PaymentService('StripeCheckout', $id);
        $probes = [];
        foreach ([990, 3200] as $amount) {
            $trade = 'verify-taige-' . bin2hex(random_bytes(8));
            $session = null;
            try {
                $service->pay(['trade_no' => $trade, 'total_amount' => $amount, 'user_id' => 0]);
                $pair = Http::recorded(fn ($request) => $request->url() === $base . 'checkout/sessions' && ($request['metadata']['trade_no'] ?? '') === $trade)->last();
                if (!$pair) throw new RuntimeException('No runtime Checkout response captured');
                [$request, $response] = $pair;
                $session = $response->json();
                parse_str($request->body(), $sent);
                if (($session['currency'] ?? '') !== 'cny' || (int)($session['amount_total'] ?? 0) !== $amount
                    || !($session['livemode'] ?? false) || !in_array('alipay', $session['payment_method_types'] ?? [], true)
                    || ($session['payment_method_configuration_details']['id'] ?? '') !== $pmc
                    || ($sent['adaptive_pricing']['enabled'] ?? '') !== 'false'
                    || (string)($session['metadata']['payment_id'] ?? '') !== (string)$id) throw new RuntimeException('Checkout currency, amount, account configuration or Alipay mismatch');
                $probes[] = ['currency' => 'cny', 'amount' => $amount, 'alipay' => true, 'session' => $session['id']];
            } finally {
                if (!empty($session['id'])) {
                    $expired = $check($api()->post($base . 'checkout/sessions/' . $session['id'] . '/expire'), 'Expire verification Checkout');
                    if (($expired['status'] ?? '') !== 'expired') throw new RuntimeException('Verification Checkout did not expire');
                }
            }
        }
        if (DB::table('v2_payment')->where('id', '!=', $id)->orderBy('id')->get()->toJson() !== $protected) throw new RuntimeException('Existing channel changed during provisioning');
        if (!$existing || !$existing->enable) {
            $updated = DB::table('v2_payment')->where('id', $id)->where('enable', 0)
                ->where('config', json_encode($c, JSON_THROW_ON_ERROR))->update(['enable' => 1, 'updated_at' => time()]);
            if ($updated !== 1) throw new RuntimeException('Concurrent channel change before enable');
            $enabledByRun = true;
        }
        // A signed foreign-project event is acknowledged without looking up/fulfilling an order.
        $payload = json_encode(['id' => 'evt_xboard_provisioning_probe', 'object' => 'event', 'livemode' => true,
            'type' => 'checkout.session.completed', 'data' => ['object' => ['id' => 'cs_provisioning_probe', 'object' => 'checkout.session',
                'metadata' => ['project' => 'xboard_provisioning_probe'], 'payment_status' => 'unpaid']]], JSON_THROW_ON_ERROR);
        $timestamp = time();
        $signature = hash_hmac('sha256', $timestamp . '.' . $payload, $c['webhook_secret']);
        $send = fn ($sig) => Http::withHeaders(['User-Agent' => 'Mozilla/5.0 Xboard-Provisioning', 'Stripe-Signature' => "t={$timestamp},v1={$sig}"])
            ->withBody($payload, 'application/json')->connectTimeout(10)->timeout(30)->post($callback);
        $valid = $send($signature);
        if (!$valid->successful() || trim($valid->body()) !== 'success') throw new RuntimeException('Public signed callback failed: HTTP ' . $valid->status());
        $invalid = $send(str_repeat('0', 64));
        if ($invalid->successful() && trim($invalid->body()) === 'success') throw new RuntimeException('Public callback accepted invalid signature');
        $readback = DB::table('v2_payment')->where('id', $id)->first();
        if (!$readback->enable || json_decode($readback->config, true) !== $c) throw new RuntimeException('Final channel readback failed');
        return ['account' => $account, 'payment_id' => $id, 'uuid' => $uuid, 'enabled' => true, 'pmc' => $pmc,
            'webhook_id' => $c['webhook_endpoint_id'], 'callback' => $callback, 'signed_callback_verified' => true,
            'invalid_signature_rejected' => true, 'raymi_unchanged' => true, 'backup' => $backup,
            'probes_expired' => $probes, 'real_payment_tested' => false];
    } catch (Throwable $e) {
        if ($enabledByRun && $id) DB::table('v2_payment')->where('id', $id)->update(['enable' => 0, 'updated_at' => time()]);
        throw $e;
    }
}

if (realpath($_SERVER['SCRIPT_FILENAME'] ?? '') === __FILE__) {
    require '/www/vendor/autoload.php';
    $app = require '/www/bootstrap/app.php';
    $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
    try {
        $key = trim(file_get_contents($argv[1] ?? '/dev/null'));
        echo json_encode(provisionTaigeAlipay($key), JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), "\n";
    } catch (Throwable $e) {
        // No exception trace: traces can contain method arguments, including credentials.
        $message = $e instanceof RuntimeException ? $e->getMessage() : 'Provisioning failed; inspect server securely';
        $message = preg_replace('/(?:[sr]k_(?:live|test)_|whsec_)[A-Za-z0-9]+/', '[REDACTED]', $message);
        fwrite(STDERR, $message . "\n");
        exit(1);
    }
}
