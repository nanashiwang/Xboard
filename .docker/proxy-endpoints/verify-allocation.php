<?php

use App\Models\User;
use App\Services\ResidentialProxyService;
use App\Utils\Helper;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Support\Facades\DB;

require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Kernel::class)->bootstrap();

// Use the deployed service and today's sale inventory. Other sessions never
// see the temporary owner, orders or grants, even if this process is stopped.
$email = 'px-allocation-' . bin2hex(random_bytes(12)) . '@example.invalid';
$service = app(ResidentialProxyService::class);
$addresses = [];
DB::beginTransaction();
try {
    $buyer = User::create([
        'email' => $email, 'password' => password_hash(bin2hex(random_bytes(24)), PASSWORD_DEFAULT),
        'uuid' => Helper::guid(), 'token' => Helper::guid(), 'balance' => 3 * ResidentialProxyService::PRICE,
    ]);
    for ($i = 0; $i < 2; $i++) {
        $order = $service->create($buyer);
        if ($order->total_amount != 0 || !$service->paid($order, 'allocation-check')) {
            throw new RuntimeException('Test balance purchase failed');
        }
        $asset = $service->owned($buyer, $order->proxy_endpoint_id);
        $addresses[] = $asset->host->address;
        if ($i === 0) {
            $firstId = $asset->id;
        }
    }
    if ($addresses[0] === $addresses[1]) {
        throw new RuntimeException('Distinct-IP check requires free ports on two healthy IPs');
    }
    $renewal = $service->create($buyer, $firstId);
    if ((int) $renewal->proxy_endpoint_id !== $firstId) {
        throw new RuntimeException('Renewal selected another endpoint');
    }
} finally {
    DB::rollBack();
}
if (User::where('email', $email)->exists()) {
    throw new RuntimeException('Test transaction was not rolled back');
}
echo json_encode(['purchase_ips' => $addresses, 'renewed_original_port' => true, 'rolled_back' => true]);
