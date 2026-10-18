<?php
namespace App\Console\Commands;

use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;

class PruneNodeProbes extends Command
{
    protected $signature = 'probes:prune';
    protected $description = '清理节点探针 24 小时明细及 30 天统计和事件';
    public function handle(): int
    {
        foreach (['sample' => ['checked_at', 86400], 'ingress_sample' => ['checked_at', 86400], 'hour' => ['hour', 30 * 86400], 'event' => ['created_at', 30 * 86400]] as $table => [$column, $age]) {
            do {
                $ids = DB::table('v2_node_probe_' . $table)->where($column, '<', time() - $age)->limit(1000)->pluck('id');
                if ($ids->isNotEmpty()) DB::table('v2_node_probe_' . $table)->whereIn('id', $ids)->delete();
            } while ($ids->count() === 1000);
        }
        return self::SUCCESS;
    }
}
