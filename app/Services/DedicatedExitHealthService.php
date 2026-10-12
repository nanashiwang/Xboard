<?php

namespace App\Services;

use App\Models\DedicatedExit;
use App\Models\Plan;
use App\Models\Server;

class DedicatedExitHealthService
{
    public function check(DedicatedExit $exit): bool
    {
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
