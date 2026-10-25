<?php

// Read-only, bounded diagnostics. Never print identities, SQL, secrets or raw log lines.
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$db = Illuminate\Support\Facades\DB::class;
$recent = $db::table('client_browser_logins')->where('created_at', '>=', now()->subHours(3))->get(['state', 'created_at', 'updated_at', 'device']);
$attempts = $recent->map(function ($row) {
    $version = json_decode($row->device, true)['app_version'] ?? '';
    return ['state' => $row->state, 'created_at' => $row->created_at, 'updated_at' => $row->updated_at,
        'version' => preg_match('/^[0-9A-Za-z.+-]{1,40}$/D', $version) ? $version : 'unknown'];
})->take(-30)->values()->all();
$files = glob(storage_path('logs/*.log')) ?: [];
usort($files, fn ($a, $b) => filemtime($b) <=> filemtime($a));
$errors = [];
foreach (array_slice($files, 0, 2) as $file) {
    $handle = fopen($file, 'rb');
    fseek($handle, max(0, filesize($file) - 4 * 1024 * 1024));
    $contents = stream_get_contents($handle); fclose($handle);
    foreach (preg_split('/(?=\[\d{4}-\d{2}-\d{2} )/', $contents) as $entry) {
        if (!str_contains($entry, 'ClientBrowserLogin') || !preg_match('/^\[([0-9 :+-]+)\].*?\.ERROR:/', $entry, $match)) continue;
        $kind = 'other';
        foreach (['database is locked', 'database table is locked', 'no such column', 'no such table', 'UNIQUE constraint failed', 'NOT NULL constraint failed', 'Call to undefined method', 'TypeError', 'RedisException'] as $candidate) {
            if (str_contains($entry, $candidate)) { $kind = $candidate; break; }
        }
        preg_match('/SQLSTATE\[([A-Z0-9]+)\]/', $entry, $sqlstate);
        preg_match('/ClientBrowserLoginService\.php\((\d+)\)/', $entry, $line);
        $errors[] = ['time' => $match[1], 'kind' => $kind, 'sqlstate' => $sqlstate[1] ?? null, 'service_line' => $line[1] ?? null];
    }
}
echo json_encode(['at' => now()->toIso8601String(), 'attempts' => $attempts, 'errors' => array_slice($errors, -30)], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . PHP_EOL;
