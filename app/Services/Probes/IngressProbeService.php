<?php
namespace App\Services\Probes;

use App\Models\{NodeProbe, NodeProbeIngress, Server};
use Illuminate\Support\Facades\DB;

class IngressProbeService
{
    public function scoped(NodeProbe $probe)
    {
        $servers = Server::whereIn('id', $probe->server_ids)->where('show', true)->get()->keyBy('id');
        return NodeProbeIngress::with('machine')->where('enabled', true)->get()->filter(function ($entry) use ($servers) {
            return collect($entry->server_tunnels)->keys()->contains(fn ($id) => $servers->get($id)?->host === $entry->host);
        });
    }

    public function configuration(NodeProbe $probe): array
    {
        return $this->scoped($probe)->map(fn ($e) => ['id' => $e->id,
            'url' => 'https://' . $e->host . $e->health_path, 'expected_body' => $e->expected_body])->values()->all();
    }

    public function report(NodeProbe $probe, array $sample): bool
    {
        return DB::transaction(function () use ($probe, $sample) {
            $hash = $probe->token_hash;
            $probe = NodeProbe::lockForUpdate()->findOrFail($probe->id);
            abort_unless(hash_equals($hash, $probe->token_hash), 401);
            abort_unless($probe->enabled && $this->scoped($probe)->contains('id', $sample['ingress_id']), 403);
            $query = DB::table('v2_node_probe_ingress_sample')->where('probe_id', $probe->id);
            if ((clone $query)->where('sample_id', $sample['sample_id'])->exists() ||
                (clone $query)->where('ingress_id', $sample['ingress_id'])->where('checked_at', '>=', $sample['checked_at'])->exists()) return false;
            $measurement = $sample['measurement'];
            $ok = $measurement['status'] === 200 && $measurement['body_ok'] && empty($measurement['error']);
            DB::table('v2_node_probe_ingress_sample')->insert([
                'probe_id' => $probe->id, 'ingress_id' => $sample['ingress_id'], 'sample_id' => $sample['sample_id'],
                'checked_at' => $sample['checked_at'], 'ok' => $ok, 'measurement' => json_encode($measurement),
            ]);
            return true;
        });
    }

    public function overview(NodeProbe $probe): array
    {
        $hosts = Server::whereIn('id', $probe->server_ids)->pluck('host', 'id');
        return $this->scoped($probe)->map(function ($entry) use ($probe, $hosts) {
            $q = DB::table('v2_node_probe_ingress_sample')->where(['probe_id' => $probe->id, 'ingress_id' => $entry->id])->where('checked_at', '>=', time() - 86400);
            $latest = (clone $q)->orderByDesc('checked_at')->first();
            $stats = (clone $q)->selectRaw('COUNT(*) AS samples, SUM(ok) AS successes')->first();
            $fresh = $probe->enabled && $probe->last_seen_at >= time() - $probe->staleAfter() && $latest && $latest->checked_at >= time() - $probe->staleAfter();
            $machine = $entry->machine;
            // Resource freshness is based on a status report, never a mere machine nodes poll.
            $load = $machine?->load_status;
            $machineFresh = $machine?->is_active && ($load['updated_at'] ?? 0) >= time() - 180;
            $mapping = array_filter($entry->server_tunnels, fn ($ip, $id) => $hosts->get($id) === $entry->host, ARRAY_FILTER_USE_BOTH);
            return ['id' => $entry->id, 'name' => $entry->name, 'host' => $entry->host, 'server_tunnels' => (object) $mapping,
                'status' => !$probe->enabled ? 'disabled' : (!$latest ? 'unknown' : (!$fresh ? 'stale' : ($latest->ok ? 'healthy' : 'degraded'))),
                'checked_at' => $latest?->checked_at, 'measurement' => $latest ? json_decode($latest->measurement, true) : null,
                'samples' => (int) $stats->samples, 'successes' => (int) $stats->successes,
                'availability' => $stats->samples ? round(100 * $stats->successes / $stats->samples, 2) : null,
                'machine' => ['name' => $machine?->name, 'fresh' => (bool) $machineFresh, 'load' => $load],
            ];
        })->values()->all();
    }

    public function history(NodeProbe $probe, int $id): array
    {
        $entry = $this->scoped($probe)->firstWhere('id', $id);
        abort_unless($entry, 404);
        return ['samples' => DB::table('v2_node_probe_ingress_sample')->where(['probe_id' => $probe->id, 'ingress_id' => $id])
            ->where('checked_at', '>=', time() - 86400)->orderByDesc('checked_at')->limit(200)->get()->map(function ($s) {
                $s->measurement = json_decode($s->measurement, true); return $s;
            }), 'resources' => DB::table('v2_server_machine_load_history')->where('machine_id', $entry->machine_id)
                ->where('recorded_at', '>=', time() - 86400)->orderByDesc('recorded_at')->limit(200)->get(['cpu', 'mem_total', 'mem_used', 'net_in_speed', 'net_out_speed', 'recorded_at'])];
    }
}
