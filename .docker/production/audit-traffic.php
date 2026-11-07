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
use Illuminate\Support\Facades\Redis;

try {
    // The production SQLite connection refuses writes for this audit process.
    if (DB::connection()->getDriverName() !== 'sqlite') {
        throw new RuntimeException('unsupported driver');
    }
    DB::statement('PRAGMA query_only = ON');
    $targetId = null;
    $result = DB::transaction(function () use ($hash, &$targetId) {
        $ids = DB::table('v2_user')->select(['id', 'email'])->get()->filter(
            fn ($u) => hash_equals($hash, hash('sha256', strtolower(trim($u->email))))
        )->pluck('id');
        if ($ids->count() !== 1) throw new RuntimeException('account not unique');
        $uid = $ids->first();
        $targetId = $uid;
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
    // Horizon retains only a short window. Decode objects without instantiating
    // job classes; never execute or print a serialized job or its server config.
    try {
        $redis = Redis::connection('horizon');
        $ids = $redis->zrange('recent_jobs', 0, 9999);
        $history = ['available' => true, 'scanned_jobs' => count($ids), 'limit' => 10000,
            'retention_minutes' => config('horizon.trim.recent'), 'matched_reports' => 0,
            'first_at' => null, 'last_at' => null, 'nodes' => [], 'five_minute_buckets' => []];
        foreach (array_chunk($ids, 100) as $chunk) {
            $rows = $redis->pipeline(function ($pipe) use ($chunk) {
                foreach ($chunk as $id) $pipe->hmget($id, ['name', 'status', 'created_at', 'payload']);
            });
            foreach ($rows as $row) {
                [$name, $status, $created, $raw] = array_values($row);
                if ($name !== App\Jobs\TrafficFetchJob::class || $status !== 'completed'
                    || !is_string($raw) || strlen($raw) > 2 * 1024 * 1024) continue;
                $payload = json_decode($raw, true);
                $command = $payload['data']['command'] ?? null;
                if (!is_string($command)) continue;
                $object = @unserialize($command, ['allowed_classes' => false]);
                if (!is_object($object)) continue;
                $values = (array) $object;
                $data = $values["\0*\0data"] ?? null;
                $server = $values["\0*\0server"] ?? null;
                if (!is_array($data) || !isset($data[$targetId]) || !is_array($server)) continue;
                $traffic = $data[$targetId];
                if (!is_array($traffic) || count($traffic) !== 2 || !is_numeric($traffic[0]) || !is_numeric($traffic[1])) continue;
                $at = (int) ((float) $created);
                $nodeId = (int) ($server['id'] ?? 0);
                $rate = (float) ($server['rate'] ?? 0);
                $history['matched_reports']++;
                $history['first_at'] = min($history['first_at'] ?? $at, $at);
                $history['last_at'] = max($history['last_at'] ?? $at, $at);
                $key = $nodeId.':'.$rate;
                $history['nodes'][$key] ??= ['node_id' => $nodeId, 'rate' => $rate, 'reports' => 0, 'u' => 0, 'd' => 0];
                $history['nodes'][$key]['reports']++;
                $history['nodes'][$key]['u'] += $traffic[0];
                $history['nodes'][$key]['d'] += $traffic[1];
                $bucket = (int) (floor($at / 300) * 300);
                $history['five_minute_buckets'][$bucket] ??= ['reported_bytes' => 0, 'billed_bytes' => 0, 'reports' => 0];
                $history['five_minute_buckets'][$bucket]['reported_bytes'] += $traffic[0] + $traffic[1];
                $history['five_minute_buckets'][$bucket]['billed_bytes'] += ($traffic[0] + $traffic[1]) * $rate;
                $history['five_minute_buckets'][$bucket]['reports']++;
            }
        }
        $history['nodes'] = array_values($history['nodes']);
        ksort($history['five_minute_buckets']);
        $result['recent_user_reports'] = $history;
        $devices = Redis::hgetall('user_devices:'.$targetId);
        $activeNodes = [];
        foreach ($devices as $field => $at) {
            if (time() - (int) $at > 300) continue;
            $node = (int) explode(':', $field, 2)[0];
            $activeNodes[$node] = ($activeNodes[$node] ?? 0) + 1;
        }
        $result['active_node_device_counts'] = $activeNodes;
    } catch (Throwable $e) {
        $result['recent_user_reports'] = ['available' => false, 'error_class' => get_class($e)];
    }
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
