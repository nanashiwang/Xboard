<?php
namespace App\Console\Commands;

use App\Models\{NodeProbeIngress, Server, ServerMachine};
use Illuminate\Console\Command;
use Illuminate\Support\Facades\{DB, Validator};

class ConfigureProbeIngress extends Command
{
    protected $signature = 'probes:ingress {config : 本机 JSON 配置文件}';
    protected $description = '登记第一段入口与隧道映射，生成私有只读采集器配置';

    public function handle(): int
    {
        $data = json_decode(file_get_contents($this->argument('config')), true, 512, JSON_THROW_ON_ERROR);
        $data = Validator::make($data, [
            'name' => 'required|string|max:80', 'host' => ['required', 'string', 'max:253', 'regex:/^(?:[a-zA-Z0-9][a-zA-Z0-9-]*\.)+[a-zA-Z]{2,63}$/'],
            'health_path' => ['required', 'string', 'max:200', 'regex:#^/[a-zA-Z0-9/_-]*$#'],
            'expected_body' => 'required|string|max:200', 'server_tunnels' => 'required|array|min:1|max:50',
            'server_tunnels.*' => 'required|ip', 'network_interface' => ['required','regex:/^[a-zA-Z0-9_.-]{1,30}$/'],
            'wireguard_interface' => ['required','regex:/^[a-zA-Z0-9_.-]{1,30}$/'],
        ])->validate();
        foreach ($data['server_tunnels'] as $id => $ip) {
            if (!ctype_digit((string) $id) || !Server::where('id', $id)->where('host', $data['host'])->where('show', true)->exists()) {
                $this->error('节点必须是此入口域名下的公开节点。'); return self::FAILURE;
            }
        }
        $entry = DB::transaction(function () use ($data) {
            $entry = NodeProbeIngress::firstOrNew(['host' => $data['host']]);
            $machine = $entry->machine ?? ServerMachine::create([
                'name' => $data['name'], 'notes' => '第一段入口只读监控，不承载面板分配的代理节点',
                'is_active' => true, 'token' => ServerMachine::generateToken(),
            ]);
            $entry->fill(collect($data)->only(['name', 'host', 'health_path', 'expected_body', 'server_tunnels'])->all());
            $entry->machine_id = $machine->id; $entry->enabled = true; $entry->save(); return $entry;
        });
        $folder = storage_path('app/private/node-probes');
        if (!is_dir($folder)) mkdir($folder, 0700, true);
        $path = $folder . '/ingress-' . $entry->id . '.json';
        $oldMask = umask(0077);
        try {
            file_put_contents($path, json_encode(['panel_url' => rtrim(config('app.url'), '/'), 'machine_id' => $entry->machine_id,
                'token' => $entry->machine->token, 'network_interface' => $data['network_interface'],
                'wireguard_interface' => $data['wireguard_interface'], 'peers' => array_values(array_unique($data['server_tunnels']))], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
            chmod($path, 0600);
        } finally { umask($oldMask); }
        $this->info('入口 #' . $entry->id . '，私有采集器配置：' . $path);
        return self::SUCCESS;
    }
}
