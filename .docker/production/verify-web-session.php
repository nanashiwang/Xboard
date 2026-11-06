<?php
// Read-only runtime check. Do not output account data, tokens or the private admin path.
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$manifest = json_decode(file_get_contents(public_path('assets/admin/manifest.json')), true, 512, JSON_THROW_ON_ERROR);
$entry = $manifest['index.html']['file'];
$admin = file_get_contents(public_path('assets/admin/' . $entry));
$user = file_get_contents(base_path('theme/Xboard/assets/umi.js'));
$checks = [
    'user_retention_30_days' => str_contains($user, 'sd.set("access_token",e,2592000)'),
    'user_network_error_keeps_session' => str_contains($user, 'return next(expired ? {path: "/login"} : false)'),
    'admin_retention_30_days' => str_contains($admin, 'Mf.set(Af,e,2592000)'),
    'admin_content_hash' => $entry === 'assets/index-session-' . substr(hash('sha256', $admin), 0, 16) . '.js',
    'server_no_short_global_expiry' => config('sanctum.expiration') === null,
];
echo json_encode(['version' => app(App\Services\UpdateService::class)->getCurrentVersion(), 'checks' => $checks,
    'panel_sha256' => hash('sha256', $user), 'admin_entry' => $entry], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . PHP_EOL;
exit(in_array(false, $checks, true) ? 1 : 0);
