<?php

namespace App\Console\Commands;

use App\Models\DedicatedExit;
use App\Models\Plan;
use App\Models\Server;
use App\Models\ServerGroup;
use App\Services\NodeSyncService;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Validator;

class PrepareDedicatedPlan extends Command
{
    protected $signature = 'dedicated:prepare {manifest : 服务器本地的私密 JSON 清单}';
    protected $description = '建立待上架套餐和独立出口节点，不自动开放销售';

    public function handle(): int
    {
        $manifest = json_decode(file_get_contents($this->argument('manifest')), true, 512, JSON_THROW_ON_ERROR);
        Validator::make($manifest, [
            'backend_template_id' => 'required|integer|exists:v2_server,id',
            'frontend_template_id' => 'required|integer|exists:v2_server,id',
            'port_start' => 'required|integer|min:1024|max:65000',
            'exits' => 'required|array|min:2|max:50',
            'exits.*.ip' => 'required|ipv4|distinct', 'exits.*.port' => 'required|integer|min:1|max:65535',
            'exits.*.username' => 'required|string', 'exits.*.password' => 'required|string',
            'exits.*.standby' => 'required|boolean',
        ])->validate();
        $definition = json_decode(file_get_contents(base_path('.docker/dedicated/plan.json')), true, 512, JSON_THROW_ON_ERROR);
        $backendTemplate = Server::findOrFail($manifest['backend_template_id']);
        $frontendTemplate = Server::findOrFail($manifest['frontend_template_id']);
        if (!$backendTemplate->machine_id || $backendTemplate->type !== 'vless'
            || $frontendTemplate->parent_id !== $backendTemplate->id
            || data_get($backendTemplate->protocol_settings, 'network') !== 'ws') {
            $this->error('必须指定同一 VLESS WebSocket 入口的后端与公开节点模板');
            return self::FAILURE;
        }
        $plan = DB::transaction(function () use ($manifest, $definition, $backendTemplate, $frontendTemplate) {
            $plan = Plan::where('name', $definition['name'])->first();
            if ($plan && !$plan->dedicated) {
                throw new \RuntimeException('同名普通套餐已存在，拒绝覆盖');
            }
            if (!$plan) {
                $group = new ServerGroup();
                $group->name = $definition['name'];
                $group->save();
                $plan = Plan::create([...$definition, 'dedicated' => true, 'group_id' => $group->id,
                    'show' => false, 'sell' => false, 'renew' => true]);
            }
            foreach ($manifest['exits'] as $i => $source) {
                $exit = DedicatedExit::firstOrCreate(['public_ip' => $source['ip']], [
                    'plan_id' => $plan->id, 'name' => '美国固定出口 ' . ($i + 1),
                    'standby' => $source['standby'], 'enabled' => true,
                ]);
                if ($exit->plan_id !== $plan->id) {
                    throw new \RuntimeException('出口 IP 已用于另一个套餐');
                }
                $backend = Server::where('dedicated_exit_id', $exit->id)->where('machine_id', $backendTemplate->machine_id)->first();
                if (!$backend) {
                    $port = $manifest['port_start'] + $i;
                    if (Server::where('machine_id', $backendTemplate->machine_id)->where('server_port', $port)->exists()) {
                        throw new \RuntimeException('入口后端端口已被使用');
                    }
                    $path = '/dedicated/' . bin2hex(random_bytes(20));
                    $backend = $backendTemplate->replicate(['code']);
                    $backend->fill([
                        'name' => '__专属后端|' . $exit->name, 'dedicated_exit_id' => $exit->id,
                        'parent_id' => 0, 'port' => (string) $port, 'server_port' => $port,
                        'group_ids' => [(string) $plan->group_id], 'show' => false, 'enabled' => true,
                        'tags' => ['dedicated-backend'], 'rate' => 1, 'u' => 0, 'd' => 0, 'transfer_enable' => null,
                        'custom_outbounds' => [[
                            'tag' => 'upstream', 'protocol' => 'socks', 'settings' => [
                                'server' => $source['ip'], 'server_port' => $source['port'], 'version' => '5',
                                'username' => $source['username'], 'password' => $source['password'],
                            ],
                        ]],
                    ]);
                    $settings = $backend->protocol_settings;
                    $settings['network_settings']['path'] = $path;
                    $backend->protocol_settings = $settings;
                    $backend->save();
                    $front = $frontendTemplate->replicate(['code']);
                    $settings = $front->protocol_settings;
                    $settings['network_settings']['path'] = $path;
                    $front->fill([
                        'name' => $definition['name'] . ' · ' . str_pad((string) ($i + 1), 2, '0', STR_PAD_LEFT),
                        'dedicated_exit_id' => $exit->id, 'parent_id' => $backend->id,
                        'group_ids' => [(string) $plan->group_id], 'show' => true, 'enabled' => true,
                        'tags' => ['dedicated-public'], 'rate' => 1, 'sort' => -10,
                        'u' => 0, 'd' => 0, 'transfer_enable' => null, 'protocol_settings' => $settings,
                    ]);
                    $front->save();
                }
            }
            // Grant the new plan public routes through the same existing authorization groups.
            Server::whereNull('dedicated_exit_id')->whereJsonContains('group_ids', (string) $backendTemplate->group_ids[0])
                ->get()->each(function ($server) use ($plan) {
                    $groups = $server->group_ids ?? [];
                    if (!in_array((string) $plan->group_id, $groups, true)) {
                        $server->group_ids = [...$groups, (string) $plan->group_id];
                        $server->save();
                    }
                });
            return $plan;
        }, 5);
        NodeSyncService::notifyMachineNodesChanged($backendTemplate->machine_id);
        $this->info("套餐 {$plan->id} 已准备；销售状态未自动更改。完成入口转发、健康与真实代理验收后再上架。");
        return self::SUCCESS;
    }
}
