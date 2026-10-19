<?php

namespace App\Console\Commands;

use App\Models\{DedicatedExit, NodeProbe, Plan, Server};
use App\Services\{DedicatedExitService, NodeSyncService};
use App\Services\Probes\NodeProbeService;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\{DB, Validator};

class AttachOwnedDedicatedExits extends Command
{
    protected $signature = 'dedicated:attach-owned {plan} {manifest} {--apply : Apply the validated inventory; otherwise preview only}';
    protected $description = '复用自建后端接入固定出口池，保留普通用户授权；默认只预览';

    public function handle(): int
    {
        $manifest = json_decode(file_get_contents($this->argument('manifest')), true, 512, JSON_THROW_ON_ERROR);
        Validator::make($manifest, [
            'probe_id' => 'required|integer|exists:v2_node_probe,id',
            'exits' => 'required|array|min:1|max:50',
            'exits.*.server_id' => 'required|integer|distinct|exists:v2_server,id',
            'exits.*.ip' => 'required|ipv4|distinct',
            'public_fallback_ids' => 'sometimes|array',
            'public_fallback_ids.*' => 'integer|distinct|exists:v2_server,id',
        ])->validate();
        $plan = Plan::findOrFail($this->argument('plan'));
        if (!$plan->dedicated || !$plan->group_id) throw new \RuntimeException('需要有独立权限组的专属套餐');
        if (Plan::where('group_id', $plan->group_id)->where('id', '<>', $plan->id)->exists()) {
            throw new \RuntimeException('专属权限组被其他套餐共用，拒绝改变访问范围');
        }
        $probe = NodeProbe::findOrFail($manifest['probe_id']);
        $eligible = $probe->enabled && $probe->user ? app(NodeProbeService::class)->eligible($probe->user)->keyBy('id') : collect();
        $sources = [];
        foreach ($manifest['exits'] as $row) {
            $source = $eligible->get($row['server_id']);
            $backend = $source?->parent;
            if (!$source || $source->type !== 'vless' || !$source->parent_id || !$backend?->machine_id
                || !$backend->enabled || $source->dedicated_exit_id || $backend->dedicated_exit_id
                || $source->getCurrentRate() != 1 || $backend->getCurrentRate() != 1
                || $source->rate_time_enable || $backend->rate_time_enable
                || !in_array($source->id, $probe->server_ids, true)
                || (isset($probe->expected_exits[$source->id]) && $probe->expected_exits[$source->id] !== $row['ip'])
                || (int) data_get($source->protocol_settings, 'tls') !== 1
                || data_get($source->protocol_settings, 'tls_settings.allow_insecure', false)
                || $source->machine_id) {
                throw new \RuntimeException('节点必须为有监控的 1 倍率普通自建 TLS 前端及有效后端');
            }
            $existing = DedicatedExit::where('public_ip', $row['ip'])
                ->orWhere('shared_server_id', $backend->id)->first();
            if ($existing && ($existing->plan_id !== $plan->id || $existing->public_ip !== $row['ip']
                || ($existing->shared_server_id && $existing->shared_server_id !== $backend->id))) {
                throw new \RuntimeException('出口 IP 或后端已绑定其他资源，拒绝覆盖');
            }
            if (in_array((string) $plan->group_id, $source->group_ids ?? [], true)) {
                throw new \RuntimeException('池内原公开节点已向专属组开放，需先解决绕过固定分配的权限');
            }
            $sources[] = [$source, $backend, $row['ip']];
        }
        $fallbacks = Server::whereIn('id', $manifest['public_fallback_ids'] ?? [])->get();
        $backendIds = array_map(fn ($pair) => $pair[1]->id, $sources);
        foreach ($fallbacks as $fallback) {
            if (!$eligible->has($fallback->id) || !$fallback->parent?->enabled
                || $fallback->dedicated_exit_id || $fallback->parent->dedicated_exit_id
                || in_array($fallback->parent_id, $backendIds, true)
                || DedicatedExit::where('shared_server_id', $fallback->parent_id)->exists()) {
                throw new \RuntimeException('公共备用必须与固定池后端分离且可由监控账号访问');
            }
        }
        $this->table(['原公开节点', '后端', '出口 IP'], array_map(fn ($pair) => [$pair[0]->id, $pair[1]->id, $pair[2]], $sources));
        if (!$this->option('apply')) {
            $this->info('仅预览；固定出口容量、价格和上架状态均未修改。');
            return self::SUCCESS;
        }
        $backup = storage_path('app/owned-fixed-' . date('Ymd-His') . '-' . bin2hex(random_bytes(4)) . '.json');
        $changedNodes = collect($sources)->pluck(1)->merge($fallbacks)->merge($fallbacks->map(fn ($s) => $s->parent))->unique('id');
        $snapshot = [
            'plan_id' => $plan->id, 'created_at' => time(),
            'probe' => $probe->only(['id', 'expected_exits']),
            'nodes' => $changedNodes->map(fn ($s) => $s->only(['id', 'group_ids'])),
            'exits' => DedicatedExit::where('plan_id', $plan->id)->get()->toArray(),
            'aliases' => Server::whereNotNull('dedicated_exit_id')->get(['id', 'dedicated_exit_id'])->toArray(),
        ];
        $oldMask = umask(0077);
        try {
            if (!is_dir(dirname($backup)) && !mkdir(dirname($backup), 0700, true) && !is_dir(dirname($backup))) {
                throw new \RuntimeException('备份目录创建失败');
            }
            if (file_put_contents($backup, json_encode($snapshot, JSON_THROW_ON_ERROR | JSON_PRETTY_PRINT)) === false) {
                throw new \RuntimeException('备份写入失败');
            }
        } finally { umask($oldMask); }
        DB::transaction(function () use ($plan, $probe, $sources, $fallbacks) {
            app(DedicatedExitService::class)->lock($plan);
            $probe = NodeProbe::lockForUpdate()->findOrFail($probe->id);
            $expected = $probe->expected_exits ?? [];
            foreach ($sources as [$source, $backend, $ip]) {
                if (isset($expected[$source->id]) && $expected[$source->id] !== $ip) {
                    throw new \RuntimeException('监控预期出口已变化，拒绝覆盖');
                }
                $expected[$source->id] = $ip;
                $exit = DedicatedExit::firstOrCreate(['public_ip' => $ip], [
                    'plan_id' => $plan->id, 'name' => '自建固定出口 · ' . $source->name,
                    'shared_server_id' => $backend->id, 'probe_id' => $probe->id,
                    'probe_server_id' => $source->id, 'enabled' => true, 'healthy' => false, 'standby' => false,
                ]);
                if ($exit->shared_server_id !== $backend->id || $exit->probe_id !== $probe->id || $exit->probe_server_id !== $source->id) {
                    throw new \RuntimeException('已有出口绑定不一致，拒绝改写');
                }
                if (!Server::where('dedicated_exit_id', $exit->id)->where('show', true)->exists()) {
                    $alias = $source->replicate(['code']);
                    $alias->fill([
                        'name' => '固定出口 · ' . $source->name, 'dedicated_exit_id' => $exit->id,
                        'group_ids' => [(string) $plan->group_id], 'tags' => ['owned-fixed-public'],
                        'u' => 0, 'd' => 0, 'sort' => -20, 'rate' => 1, 'enabled' => false,
                    ])->save();
                }
                $this->grant($backend, $plan);
            }
            $probe->update(['expected_exits' => $expected]);
            foreach ($fallbacks as $fallback) {
                $this->grant($fallback, $plan);
                $this->grant($fallback->parent, $plan);
            }
        }, 5);
        NodeSyncService::notifyUsersUpdatedByGroup((int) $plan->group_id);
        $this->info('已接入；出口须经两次独立监控成功后提供容量。备份：' . $backup);
        return self::SUCCESS;
    }

    private function grant(Server $server, Plan $plan): void
    {
        $server = Server::lockForUpdate()->findOrFail($server->id);
        $groups = $server->group_ids ?? [];
        if (!in_array((string) $plan->group_id, $groups, true)) {
            $server->group_ids = [...$groups, (string) $plan->group_id];
            $server->save();
        }
    }
}
