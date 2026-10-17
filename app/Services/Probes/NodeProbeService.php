<?php
namespace App\Services\Probes;

use App\Models\{NodeProbe, Server, User};
use App\Services\DedicatedExitService;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Illuminate\Validation\ValidationException;

class NodeProbeService
{
    public const ERRORS = ['timeout', 'dns', 'connect', 'tls', 'http', 'incomplete', 'proxy', 'unknown'];
    public const CONFIG_ERRORS = ['account_unavailable', 'node_unavailable', 'unsupported_protocol', 'insecure_tls', 'core_unavailable', 'core_config'];

    public function eligible(User $user)
    {
        // Read-only subscription scope: never allocate or migrate dedicated exits during monitoring.
        if ($user->banned || !$user->group_id || ($user->expired_at !== null && $user->expired_at <= time())
            || $user->u + $user->d >= $user->transfer_enable || $user->plan?->dedicated) return collect();
        return Server::where('show', true)->whereJsonContains('group_ids', (string) $user->group_id)
            ->where(fn ($q) => $q->whereNull('transfer_enable')->orWhere('transfer_enable', 0)->orWhereRaw('u + d < transfer_enable'))
            ->orderBy('sort')->get()->filter(fn ($s) => !app(DedicatedExitService::class)->nodeExitId($s));
    }

    public function create(array $data): array
    {
        $user = User::findOrFail($data['user_id']);
        $ids = array_map('intval', $data['server_ids']);
        if (count(array_diff($ids, $this->eligible($user)->pluck('id')->all()))) {
            throw ValidationException::withMessages(['server_ids' => '节点必须在有效监控账号的普通订阅范围内。请检查账号额度、权限组和有效期。']);
        }
        $token = Str::random(64);
        $probe = NodeProbe::create([...$data, 'server_ids' => $ids, 'token_hash' => hash('sha256', $token)]);
        return [$probe, $token];
    }

    public function configuration(NodeProbe $probe): array
    {
        $user = $probe->user;
        $available = $user ? $this->eligible($user)->keyBy('id') : collect();
        $builder = $user ? new ProbeOutbound($user->toArray(), []) : null;
        $nodes = [];
        foreach ($probe->server_ids as $id) {
            $node = ['id' => $id];
            $server = $available->get($id);
            if (!$server) {
                $node['error'] = $available->isEmpty() ? 'account_unavailable' : 'node_unavailable';
            } else {
                try {
                    $data = $server->toArray();
                    // Stable port selection avoids conflating hopping with the same probe path.
                    $data['port'] = (int) explode('-', (string) $server->port)[0];
                    $data['password'] = $server->generateServerPassword($user);
                    $node['outbound'] = $builder->build($data);
                } catch (\InvalidArgumentException $e) {
                    $node['error'] = in_array($e->getMessage(), self::CONFIG_ERRORS) ? $e->getMessage() : 'unsupported_protocol';
                }
            }
            $nodes[] = $node;
        }
        return [
            'version' => 1, 'interval_seconds' => $probe->interval_seconds,
            'transfer_interval_seconds' => $probe->transfer_interval_seconds, 'transfer_bytes' => $probe->transfer_bytes,
            'targets' => config('node_probe.targets'), 'upload_url' => config('node_probe.upload_url'),
            'download_url' => config('node_probe.download_url'), 'nodes' => $nodes,
        ];
    }

    public function report(NodeProbe $probe, array $sample): bool
    {
        return DB::transaction(function () use ($probe, $sample) {
            $authorizedHash = $probe->token_hash;
            $probe = NodeProbe::lockForUpdate()->findOrFail($probe->id);
            abort_unless(hash_equals($authorizedHash, $probe->token_hash), 401);
            abort_unless($probe->enabled && in_array((int) $sample['server_id'], $probe->server_ids, true), 403);
            $scope = ['probe_id' => $probe->id, 'server_id' => $sample['server_id']];
            if (DB::table('v2_node_probe_sample')->where('probe_id', $probe->id)->where('sample_id', $sample['sample_id'])->exists()) return false;
            $state = DB::table('v2_node_probe_state')->where($scope)->first();
            // Old samples cannot change current health or manufacture consecutive successes.
            if ($state && $sample['checked_at'] <= $state->checked_at) return false;
            $checks = [];
            $error = $sample['error'] ?? null;
            foreach ($sample['checks'] ?? [] as $check) {
                $expectedStatus = $check['id'] === 'google' ? 204 : 200;
                $transfer = in_array($check['id'], ['upload', 'download']);
                $ok = !$error && empty($check['error']) && $check['status'] === $expectedStatus;
                if ($transfer) $ok = $ok && $check['bytes'] === $probe->transfer_bytes;
                $checks[] = [
                    'id' => $check['id'], 'ok' => $ok, 'status' => $check['status'], 'ms' => $check['ms'],
                    'bytes' => $check['bytes'], 'error' => $ok ? null : ($check['error'] ?? ($check['status'] !== $expectedStatus ? 'http' : 'incomplete')),
                    'mbps' => $transfer && $ok && $check['ms'] > 0 ? round($check['bytes'] * 8 / $check['ms'] / 1000, 3) : null,
                ];
            }
            $connect = array_values(array_filter($checks, fn ($c) => in_array($c['id'], ['cloudflare', 'google'])));
            $successes = count(array_filter($connect, fn ($c) => $c['ok']));
            $exit = $sample['exit_ip'] ?? null;
            $expected = $probe->expected_exits[$sample['server_id']] ?? null;
            $exitMismatch = $expected && $exit !== $expected;
            $transferChecks = array_values(array_filter($checks, fn ($c) => in_array($c['id'], ['upload', 'download'])));
            $lastTransfers = $transferChecks ?: ($state?->transfers ? json_decode($state->transfers, true) : []);
            // A lightweight round cannot prove that a failed upload/download has recovered.
            $transferHealthy = count(array_filter($lastTransfers, fn ($c) => !$c['ok'])) === 0;
            $allGood = !$error && !$exitMismatch && $transferHealthy && count($checks) >= 2 && count(array_filter($checks, fn ($c) => !$c['ok'])) === 0;
            // A long gap breaks consecutive streaks; the missing period is not evidence of recovery.
            $fresh = $state && $sample['checked_at'] - $state->checked_at <= $probe->staleAfter();
            $failures = !$error && $successes === 0 ? ($fresh ? $state->failures : 0) + 1 : 0;
            $goods = $allGood ? ($fresh ? $state->successes : 0) + 1 : 0;
            $status = $error ? 'config_error' : ($failures >= 3 ? 'down' : ($goods >= 2 ? 'healthy' : 'degraded'));
            $payload = ['checks' => $checks, 'error' => $error, 'exit_mismatch' => (bool) $exitMismatch];
            $encoded = json_encode($payload);
            DB::table('v2_node_probe_sample')->insert([...$scope, 'sample_id' => $sample['sample_id'], 'checked_at' => $sample['checked_at'], 'checks' => $encoded, 'exit_ip' => $exit]);
            $stateUpdate = ['status' => $status, 'failures' => $failures, 'successes' => $goods, 'checked_at' => $sample['checked_at'], 'checks' => $encoded, 'exit_ip' => $exit];
            if ($transferChecks) $stateUpdate += ['transfers' => json_encode($transferChecks), 'transfer_checked_at' => $sample['checked_at']];
            DB::table('v2_node_probe_state')->updateOrInsert($scope, $stateUpdate);
            if ($status !== ($state->status ?? 'unknown')) DB::table('v2_node_probe_event')->insert([...$scope, 'from_status' => $state->status ?? 'unknown', 'to_status' => $status, 'created_at' => $sample['checked_at']]);
            // Config failures have no HTTP observations, so never count as successful requests.
            $hourScope = [...$scope, 'hour' => intdiv($sample['checked_at'], 3600) * 3600];
            DB::table('v2_node_probe_hour')->insertOrIgnore($hourScope);
            $latencies = array_column(array_filter($connect, fn ($c) => $c['ok']), 'ms');
            $increments = ['rounds' => 1, 'healthy_rounds' => (int) $allGood, 'requests' => count($connect), 'successes' => $successes, 'latency_sum_ms' => array_sum($latencies)];
            foreach (['upload', 'download'] as $kind) {
                $items = array_filter($checks, fn ($c) => $c['id'] === $kind);
                $increments[$kind . 's'] = count($items);
                $increments[$kind . '_successes'] = count(array_filter($items, fn ($c) => $c['ok']));
            }
            $hour = DB::table('v2_node_probe_hour')->where($hourScope)->first();
            $updates = ['latency_max_ms' => max($hour->latency_max_ms, max($latencies ?: [0]))];
            foreach ($increments as $key => $value) $updates[$key] = $hour->$key + $value;
            DB::table('v2_node_probe_hour')->where($hourScope)->update($updates);
            return true;
        }, 3);
    }

    public function overview(NodeProbe $probe): array
    {
        $states = DB::table('v2_node_probe_state')->where('probe_id', $probe->id)->get()->keyBy('server_id');
        $servers = Server::whereIn('id', $probe->server_ids)->get()->keyBy('id');
        $hours = DB::table('v2_node_probe_hour')->where('probe_id', $probe->id)->where('hour', '>=', intdiv(time(), 3600) * 3600 - 23 * 3600)->get()->groupBy('server_id');
        $online = $probe->enabled && $probe->last_seen_at && time() - $probe->last_seen_at <= $probe->staleAfter();
        $nodes = [];
        foreach ($probe->server_ids as $id) {
            $state = $states->get($id);
            $rows = $hours->get($id, collect());
            $status = !$probe->enabled ? 'disabled' : (!$online ? ($probe->last_seen_at ? 'stale' : 'unknown') : (!$state ? 'unknown' : (time() - $state->checked_at > $probe->staleAfter() ? 'stale' : $state->status)));
            $requests = $rows->sum('requests');
            $successes = $rows->sum('successes');
            $nodes[] = ['id' => $id, 'name' => $servers->get($id)?->name ?? "已删除节点 #$id", 'host' => $servers->get($id)?->host,
                'status' => $status, 'checked_at' => $state?->checked_at, 'exit_ip' => $state?->exit_ip,
                'latest' => $state ? json_decode($state->checks, true) : null,
                'transfers' => $state?->transfers ? json_decode($state->transfers, true) : [], 'transfer_checked_at' => $state?->transfer_checked_at,
                'transfers_stale' => !$online || !$state?->transfer_checked_at || time() - $state->transfer_checked_at > $probe->transfer_interval_seconds * 2 + $probe->staleAfter(), 'requests' => $requests, 'successes' => $successes,
                'availability' => $requests ? round($successes / $requests * 100, 2) : null,
                'latency_ms' => $successes ? round($rows->sum('latency_sum_ms') / $successes, 1) : null,
                'uploads' => $rows->sum('uploads'), 'upload_successes' => $rows->sum('upload_successes'),
                'downloads' => $rows->sum('downloads'), 'download_successes' => $rows->sum('download_successes'),
            ];
        }
        $user = $probe->user;
        return [...$probe->toArray(), 'user' => null, 'online' => (bool) $online, 'nodes' => $nodes,
            'account' => ['speed_limit_mbps' => $user?->speed_limit, 'remaining_bytes' => $user ? max(0, $user->transfer_enable - $user->u - $user->d) : 0],
        ];
    }
}
