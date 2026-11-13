<?php
// Apply the authorized CNY/no-surcharge policy. Never print secrets or customer identifiers.
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;

$payment = DB::table('v2_payment')->where('id', 2)->first();
if (!$payment || !$payment->enable || $payment->payment !== 'StripeCheckout') throw new RuntimeException('Unexpected payment channel');
$config = json_decode($payment->config, true, 512, JSON_THROW_ON_ERROR);
$api = fn () => Http::asForm()->withToken($config['secret_key'])->withHeaders(['Stripe-Version' => '2026-07-29.dahlia'])->connectTimeout(10)->timeout(30);
$list = function () use ($api) {
    $items = []; $after = null;
    do {
        $query = ['status' => 'open', 'limit' => 100];
        if ($after) $query['starting_after'] = $after;
        $r = $api()->get('https://api.stripe.com/v1/checkout/sessions', $query);
        if (!$r->successful()) throw new RuntimeException('Cannot enumerate open sessions: HTTP ' . $r->status());
        $data = $r->json('data');
        foreach ($data as $s) {
            $m = $s['metadata'] ?? [];
            if (($m['project'] ?? '') !== 'xboard' || (string) ($m['payment_id'] ?? '') !== '2' || $s['currency'] !== 'usd') continue;
            if (!DB::table('v2_order')->where('trade_no', $m['trade_no'] ?? '')->where('payment_id', 2)->exists()) continue;
            $items[] = $s['id'];
        }
        $after = $data ? end($data)['id'] : null;
        if ($r->json('has_more') && !$after) throw new RuntimeException('Invalid pagination');
    } while ($r->json('has_more'));
    return $items;
};
$oldSessions = $list();
$dir = '/www/storage/app/backups/checkout-no-surcharge-20261113';
if (!is_dir($dir) && !mkdir($dir, 0700, true)) throw new RuntimeException('Backup directory failed');
chmod($dir, 0700);
$backup = $dir . '/payment-' . date('Ymd-His') . '-' . bin2hex(random_bytes(4)) . '.json';
$oldUmask = umask(0077);
if (file_put_contents($backup, json_encode(['payment' => $payment, 'old_open_sessions' => $oldSessions], JSON_THROW_ON_ERROR)) === false) throw new RuntimeException('Backup failed');
umask($oldUmask);
$new = $config;
$new['currency'] = 'cny';
$new['cost_percent'] = '0';
$new['cost_fixed_usd'] = '0.00';
DB::transaction(function () use ($payment, $new) {
    $updated = DB::table('v2_payment')->where('id', 2)->where('config', $payment->config)->update([
        'config' => json_encode($new, JSON_THROW_ON_ERROR), 'handling_fee_fixed' => 0, 'handling_fee_percent' => 0, 'updated_at' => time(),
    ]);
    if ($updated !== 1) throw new RuntimeException('Concurrent configuration change; abort');
});
$expired = 0; $completedDuringSwitch = 0;
foreach ($oldSessions as $id) {
    $r = $api()->post('https://api.stripe.com/v1/checkout/sessions/' . $id . '/expire');
    if ($r->successful() && $r->json('status') === 'expired') { $expired++; continue; }
    $state = $api()->get('https://api.stripe.com/v1/checkout/sessions/' . $id);
    if (!$state->successful() || !in_array($state->json('status'), ['complete', 'expired'], true)) throw new RuntimeException('Old session expiration failed');
    if ($state->json('status') === 'complete') $completedDuringSwitch++;
}
$remaining = count($list());
if ($remaining) throw new RuntimeException('Old USD sessions remain open');
$readback = DB::table('v2_payment')->where('id', 2)->first();
$actual = json_decode($readback->config, true);
if ($actual['currency'] !== 'cny' || (float)$actual['cost_percent'] !== 0.0 || (float)$actual['cost_fixed_usd'] !== 0.0 || $readback->handling_fee_fixed || $readback->handling_fee_percent) throw new RuntimeException('Readback mismatch');
// Exercise the actual plugin in this CLI process without creating an order or payment.
Http::preventStrayRequests();
Http::fake(['api.stripe.com/*' => Http::response(['url' => 'https://checkout.stripe.com/c/pay/verification'])]);
$service = new App\Services\PaymentService('StripeCheckout', 2);
foreach ([990, 3200] as $amount) $service->pay(['trade_no' => 'verification-no-payment', 'total_amount' => $amount, 'user_id' => 0]);
$sent = [];
foreach (Http::recorded() as [$request]) {
    parse_str($request->body(), $body);
    $sent[] = ['currency' => $body['line_items'][0]['price_data']['currency'], 'amount' => (int)$body['line_items'][0]['price_data']['unit_amount'], 'adaptive_pricing' => $body['adaptive_pricing']['enabled']];
}
if ($sent !== [['currency'=>'cny','amount'=>990,'adaptive_pricing'=>'false'],['currency'=>'cny','amount'=>3200,'adaptive_pricing'=>'false']]) throw new RuntimeException('Runtime request verification failed');
echo json_encode(['at'=>now()->toIso8601String(),'backup'=>$backup,'currency'=>$actual['currency'],'cost_percent'=>$actual['cost_percent'],'cost_fixed_usd'=>$actual['cost_fixed_usd'],'handling_fee_fixed'=>$readback->handling_fee_fixed,'handling_fee_percent'=>$readback->handling_fee_percent,'old_open_usd'=>count($oldSessions),'expired'=>$expired,'completed_during_switch'=>$completedDuringSwitch,'remaining_open_usd'=>$remaining,'runtime_requests'=>$sent], JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE), "\n";
