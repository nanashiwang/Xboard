<?php
// Read-only inventory. No credentials, webhook secrets, customer data or raw responses in output.
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;
DB::statement('PRAGMA query_only = ON');
$channels = [];
foreach (DB::table('v2_payment')->get() as $row) {
    $c = json_decode($row->config, true) ?: [];
    $item = ['id' => $row->id, 'name' => $row->name, 'payment' => $row->payment, 'enabled' => (bool)$row->enable];
    if ($row->payment === 'StripeCheckout') {
        $item += ['uuid' => $row->uuid, 'notify_domain' => $row->notify_domain,
            'currency' => $c['currency'] ?? null, 'pmc' => $c['payment_method_configuration'] ?? null,
            'has_key' => !empty($c['secret_key']), 'has_webhook_secret' => !empty($c['webhook_secret']),
            'fixed_fee' => $row->handling_fee_fixed, 'percent_fee' => $row->handling_fee_percent];
        if (!empty($c['secret_key'])) {
            try {
                $r = Http::withToken($c['secret_key'])->connectTimeout(10)->timeout(20)->get('https://api.stripe.com/v1/account');
                $item['account_http_status'] = $r->status();
                if ($r->successful()) $item['account_id'] = $r->json('id');
            } catch (Throwable $e) { $item['account_request_failed'] = true; }
        }
    }
    $channels[] = $item;
}
$backups = [];
$root = storage_path('app/backups');
if (is_dir($root)) {
    $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS));
    foreach ($it as $file) {
        if (!$file->isFile() || $file->isLink()) continue;
        $relative = substr($file->getPathname(), strlen($root) + 1);
        if (preg_match('/stripe|payment|checkout/i', $relative)) $backups[] = $relative;
        if (count($backups) >= 100) break;
    }
}
echo json_encode(['at' => now()->toIso8601String(), 'read_only' => true, 'channels' => $channels, 'payment_backup_paths' => $backups], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), "\n";
