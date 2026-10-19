<?php

namespace App\Services;

use App\Models\DedicatedExit;
use App\Models\Plan;
use App\Models\Server;
use App\Models\NodeProbe;
use App\Services\Probes\NodeProbeService;
use Illuminate\Support\Facades\DB;

class DedicatedExitHealthService
{
    public function check(DedicatedExit $exit): bool
    {
        if ($exit->shared_server_id) {
            return $this->checkShared($exit);
        }
        $passed = $this->probe($exit);
        $previouslyHealthy = $exit->healthy;
        $exit->checked_at = time();
        $exit->failures = $passed ? 0 : $exit->failures + 1;
        $exit->successes = $passed ? $exit->successes + 1 : 0;
        if ($exit->failures >= 3) {
            $exit->healthy = false;
        } elseif ($exit->successes >= 2) {
            $exit->healthy = true;
        }
        $exit->save();
        if ($exit->healthy !== $previouslyHealthy) {
            $groupId = Plan::whereKey($exit->plan_id)->value('group_id');
            if ($groupId) {
                NodeSyncService::notifyUsersUpdatedByGroup($groupId);
            }
        }
        return $passed;
    }

    private function checkShared(DedicatedExit $exit): bool
    {
        $probe = NodeProbe::find($exit->probe_id);
        $source = Server::find($exit->probe_server_id);
        $backend = Server::find($exit->shared_server_id);
        $state = DB::table('v2_node_probe_state')->where('probe_id', $exit->probe_id)
            ->where('server_id', $exit->probe_server_id)->first();
        $aliases = Server::where('dedicated_exit_id', $exit->id)->where('show', true)->get();
        $valid = $probe?->enabled && $probe->user && $source && $backend?->enabled
            && $source->parent_id === $backend->id && $backend->last_check_at >= time() - DedicatedExit::HEALTH_TTL
            && in_array($source->id, $probe->server_ids, true)
            && ($probe->expected_exits[$source->id] ?? null) === $exit->public_ip
            && app(NodeProbeService::class)->eligible($probe->user)->contains('id', $source->id)
            && $state && $state->checked_at >= time() - DedicatedExit::HEALTH_TTL
            && $state->checked_at <= time() + 30
            && $aliases->isNotEmpty()
            && $aliases->every(fn ($alias) => $alias->parent_id === $backend->id
                && $alias->host === $source->host && (string) $alias->port === (string) $source->port
                && $alias->type === $source->type && $alias->protocol_settings === $source->protocol_settings);
        $previouslyHealthy = $exit->healthy;
        if (!$valid) {
            // Missing/stale/configuration evidence must not renew the five-minute lease.
            $exit->healthy = false;
            $exit->checked_at = null;
            $exit->successes = 0;
            $passed = false;
        } else {
            $checks = json_decode($state->checks, true) ?: [];
            $connect = collect($checks['checks'] ?? [])->whereIn('id', ['google', 'cloudflare']);
            $passed = empty($checks['error']) && $state->exit_ip === $exit->public_ip
                && $connect->pluck('id')->unique()->count() === 2 && $connect->every(fn ($c) => $c['ok'] ?? false);
            if ($exit->checked_at && $state->checked_at <= $exit->checked_at) {
                return $passed; // Re-reading the same observation cannot manufacture a success streak.
            }
            $fresh = $exit->checked_at && $state->checked_at - $exit->checked_at <= DedicatedExit::HEALTH_TTL;
            $exit->checked_at = $state->checked_at;
            $exit->successes = $passed ? ($fresh ? $exit->successes : 0) + 1 : 0;
            $exit->failures = $passed ? 0 : ($fresh ? $exit->failures : 0) + 1;
            if ($state->exit_ip !== $exit->public_ip || $exit->failures >= 3) {
                $exit->healthy = false;
            } elseif ($exit->successes >= 2) {
                $exit->healthy = true;
            }
        }
        $exit->save();
        if ($exit->healthy !== $previouslyHealthy) {
            $group = Plan::whereKey($exit->plan_id)->value('group_id');
            if ($group) NodeSyncService::notifyUsersUpdatedByGroup((int) $group);
        }
        return $passed;
    }

    protected function probe(DedicatedExit $exit): bool
    {
        $nodes = Server::where('dedicated_exit_id', $exit->id)->where('enabled', true)->get();
        foreach ($nodes as $node) {
            if (!$node->machine_id || $node->last_check_at < time() - DedicatedExit::HEALTH_TTL) {
                continue;
            }
            foreach ($node->custom_outbounds ?? [] as $outbound) {
                $settings = $outbound['settings'] ?? [];
                if (($outbound['protocol'] ?? '') !== 'socks' || ($settings['server'] ?? '') !== $exit->public_ip) {
                    continue;
                }
                foreach (['https://api.ipify.org', 'https://checkip.amazonaws.com'] as $url) {
                    $curl = curl_init($url);
                    curl_setopt_array($curl, [
                        CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 3, CURLOPT_TIMEOUT => 5,
                        CURLOPT_PROXY => $settings['server'], CURLOPT_PROXYPORT => (int) $settings['server_port'],
                        CURLOPT_PROXYTYPE => CURLPROXY_SOCKS5_HOSTNAME,
                        CURLOPT_PROXYUSERPWD => ($settings['username'] ?? '') . ':' . ($settings['password'] ?? ''),
                        CURLOPT_SSL_VERIFYPEER => true, CURLOPT_SSL_VERIFYHOST => 2,
                    ]);
                    $body = curl_exec($curl);
                    $status = curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
                    curl_close($curl);
                    if ($status === 200 && is_string($body) && trim($body) === $exit->public_ip) {
                        return true;
                    }
                }
            }
        }
        return false;
    }
}
