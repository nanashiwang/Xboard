<?php

namespace App\Services;

final class TrafficBilling
{
    public const DOWNLOAD_ONLY = 'download_only';

    /**
     * Select billable directions before applying the node's rate. Missing mode
     * means an older queued report; preserve its original bidirectional policy.
     * The original report is retained for node statistics and diagnostics.
     */
    public static function forUser(array $traffic, array $server): array
    {
        return [
            ($server['traffic_billing_mode'] ?? null) === self::DOWNLOAD_ONLY ? 0 : $traffic[0],
            $traffic[1],
        ];
    }
}
