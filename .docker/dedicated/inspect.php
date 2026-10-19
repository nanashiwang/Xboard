<?php
// Read-only production inventory. Never print credentials or user identities.
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

$nodes = App\Models\Server::orderBy('id')->get();
$probes = App\Models\NodeProbe::where('enabled', true)->get();
echo json_encode([
    'version' => config('app.version'),
    'plans' => App\Models\Plan::where('dedicated', true)->get()->map(fn ($p) => $p->only([
        'id', 'name', 'group_id', 'dedicated', 'capacity_limit', 'show', 'sell', 'renew',
    ])),
    'exits' => App\Models\DedicatedExit::orderBy('id')->get()->map(fn ($e) => $e->only([
        'id', 'plan_id', 'name', 'public_ip', 'enabled', 'standby', 'healthy', 'checked_at',
        'shared_server_id', 'probe_id', 'probe_server_id',
    ])),
    'assignments' => App\Models\DedicatedAssignment::selectRaw('plan_id, exit_id, count(*) as occupied')
        ->groupBy('plan_id', 'exit_id')->get(),
    'nodes' => $nodes->map(fn ($s) => [...$s->only([
        'id', 'name', 'host', 'type', 'parent_id', 'machine_id', 'group_ids', 'show', 'enabled',
        'dedicated_exit_id', 'tags', 'rate', 'server_port',
    ]), 'heartbeat' => $s->last_check_at]),
    'probes' => $probes->map(fn ($p) => $p->only(['id', 'server_ids', 'expected_exits', 'last_seen_at'])),
    'probe_states' => Illuminate\Support\Facades\DB::table('v2_node_probe_state')
        ->whereIn('probe_id', $probes->pluck('id'))->get(['probe_id', 'server_id', 'status', 'checked_at', 'exit_ip', 'successes']),
    'processing_dedicated_orders' => App\Models\Order::where('status', App\Models\Order::STATUS_PROCESSING)
        ->whereIn('plan_id', App\Models\Plan::where('dedicated', true)->pluck('id'))->count(),
], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . PHP_EOL;
