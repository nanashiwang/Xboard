<?php
// Read-only reconciliation. No emails, UUIDs, tokens, IPs or raw error messages.
$hash = getenv('TRAFFIC_EMAIL_SHA256');
if (!is_string($hash) || !preg_match('/^[a-f0-9]{64}$/D', $hash)) {
    fwrite(STDERR, "Invalid account selector\n"); exit(2);
}
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
use Illuminate\Support\Facades\DB;

try {
    // The production SQLite connection refuses writes for this audit process.
    if (DB::connection()->getDriverName() !== 'sqlite') {
        throw new RuntimeException('unsupported driver');
    }
    DB::statement('PRAGMA query_only = ON');
    $result = DB::transaction(function () use ($hash) {
        $ids = DB::table('v2_user')->select(['id', 'email'])->get()->filter(
            fn ($u) => hash_equals($hash, hash('sha256', strtolower(trim($u->email))))
        )->pluck('id');
        if ($ids->count() !== 1) throw new RuntimeException('account not unique');
        $uid = $ids->first();
        $u = DB::table('v2_user')->where('id', $uid)->first([
            'u', 'd', 'transfer_enable', 'plan_id', 'created_at', 'updated_at',
            'expired_at', 't', 'last_reset_at', 'next_reset_at', 'reset_count',
        ]);
        $since = strtotime('-14 days', strtotime(date('Y-m-d')));
        $daily = DB::table('v2_stat_user')->where('user_id', $uid)
            ->where('record_type', 'd')->where('record_at', '>=', $since)
            ->orderBy('record_at')->orderBy('server_rate')
            ->get(['record_at', 'server_rate', 'u', 'd', 'created_at', 'updated_at'])
            ->map(function ($r) {
                $r->date = date('Y-m-d', $r->record_at);
                $r->billed_bytes = $r->u + $r->d;
                $r->reported_bytes_inferred = (float) $r->server_rate > 0
                    ? $r->billed_bytes / (float) $r->server_rate : null;
                return $r;
            });
        $lifetime = DB::table('v2_stat_user')->where('user_id', $uid)->where('record_type', 'd')
            ->selectRaw('SUM(u) AS u, SUM(d) AS d, MIN(record_at) AS first_day, MAX(record_at) AS last_day')->first();
        $resets = DB::table('v2_traffic_reset_logs')->where('user_id', $uid)
            ->orderByDesc('id')->limit(10)->get([
                'reset_time', 'reset_type', 'trigger_source', 'old_total', 'new_total',
            ]);
        $servers = DB::table('v2_server')->where('enabled', 1)->orderBy('id')
            ->get(['id', 'parent_id', 'type', 'rate', 'rate_time_enable', 'rate_time_ranges', 'show', 'machine_id']);
        $serverDaily = DB::table('v2_stat_server')->where('record_type', 'd')->where('record_at', '>=', $since)
            ->selectRaw('server_id, record_at, SUM(u) AS u, SUM(d) AS d')
            ->groupBy('server_id', 'record_at')->orderBy('record_at')->get();
        return [
            'at' => now()->toIso8601String(), 'timezone' => date_default_timezone_get(),
            'user' => $u, 'daily' => $daily, 'lifetime_daily' => $lifetime, 'recent_resets' => $resets,
            'enabled_servers' => $servers, 'server_daily_all_users' => $serverDaily,
            'enabled_plugin_codes' => DB::table('v2_plugins')->where('is_enabled', 1)->pluck('code'),
            'failed_jobs_by_queue' => DB::table('failed_jobs')->selectRaw('queue, COUNT(*) AS count')
                ->groupBy('queue')->get(),
        ];
    });
    $result['runtime_source_sha256'] = [];
    foreach (['app/Services/ServerService.php', 'app/Services/UserService.php', 'app/Jobs/TrafficFetchJob.php',
        'app/Jobs/StatUserJob.php', 'app/Jobs/StatServerJob.php', 'app/Models/Server.php'] as $file) {
        $result['runtime_source_sha256'][$file] = hash_file('sha256', '/www/'.$file);
    }
    $errors = [];
    $files = glob('/www/storage/logs/*.log') ?: [];
    usort($files, fn ($a, $b) => filemtime($b) <=> filemtime($a));
    foreach (array_slice($files, 0, 3) as $file) {
        $fh = fopen($file, 'rb'); fseek($fh, max(0, filesize($file) - 8 * 1024 * 1024));
        $contents = stream_get_contents($fh); fclose($fh);
        foreach (preg_split('/(?=\[\d{4}-\d{2}-\d{2} )/', $contents) as $entry) {
            if (!str_contains($entry, '.ERROR')) continue;
            foreach (['TrafficFetchJob', 'StatUserJob', 'StatServerJob'] as $job) {
                if (!str_contains($entry, $job)) continue;
                $kind = str_contains($entry, 'database is locked') ? 'database_locked' : 'other';
                $key = $job.':'.$kind;
                $errors[$key] = ($errors[$key] ?? 0) + 1;
            }
        }
    }
    $result['bounded_recent_log_error_counts'] = $errors;
    echo json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR).PHP_EOL;
} catch (Throwable $e) {
    // Exception messages can contain SQL or personal data; emit class only.
    fwrite(STDERR, 'Traffic audit failed: '.get_class($e).PHP_EOL); exit(1);
}
