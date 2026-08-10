<?php

namespace App\Console\Commands;

use App\Models\ClientRefreshToken;
use Illuminate\Console\Command;

class PruneClientAuthTokens extends Command
{
    protected $signature = 'client-auth:prune {--days=30 : 保留已失效凭证的天数}';
    protected $description = '清理过期、已使用或已撤销的桌面客户端 Refresh Token';

    public function handle(): int
    {
        $days = max(1, (int) $this->option('days'));
        $cutoff = now()->subDays($days);
        $deleted = ClientRefreshToken::query()
            ->where(function ($query) use ($cutoff): void {
                $query->where('expires_at', '<', $cutoff)
                    ->orWhere('used_at', '<', $cutoff)
                    ->orWhere('revoked_at', '<', $cutoff);
            })
            ->delete();

        $this->info("已清理 {$deleted} 条客户端续期凭证。");
        return self::SUCCESS;
    }
}
