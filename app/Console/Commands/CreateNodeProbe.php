<?php
namespace App\Console\Commands;

use App\Models\User;
use App\Services\Probes\NodeProbeService;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;

class CreateNodeProbe extends Command
{
    protected $signature = 'probes:create {name} {--location=} {--user= : 已有普通监控账号 ID} {--group= : 创建独立监控账号时使用的权限组 ID} {--nodes= : 逗号分隔的公开节点 ID}';
    protected $description = '创建节点探针，配置仅写入 storage/app/private/node-probes（不会输出令牌）';

    public function handle(NodeProbeService $service): int
    {
        $ids = array_values(array_unique(array_map('intval', explode(',', (string) $this->option('nodes')))));
        if (!$this->option('location') || count($ids) > 50 || min($ids) < 1 || (bool) $this->option('user') === (bool) $this->option('group')) {
            $this->error('指定 --location、1–50 个 --nodes，并选择 --user 或 --group 之一。'); return self::FAILURE;
        }
        if (strlen($this->argument('name')) > 80 || strlen($this->option('location')) > 120) return self::FAILURE;
        if (parse_url(config('app.url'), PHP_URL_SCHEME) !== 'https') { $this->error('APP_URL 必须为 HTTPS 地址。'); return self::FAILURE; }
        $folder = storage_path('app/private/node-probes');
        if (!is_dir($folder) && !mkdir($folder, 0700, true)) return self::FAILURE;
        try {
            $probe = DB::transaction(function () use ($service, $ids, $folder) {
                $user = $this->option('user') ? User::findOrFail((int) $this->option('user')) : null;
                if (!$user) {
                    abort_unless(DB::table('v2_server_group')->where('id', (int) $this->option('group'))->exists(), 422, '权限组不存在');
                    // Dedicated, non-admin monitoring identity; no subscription emails or real balance.
                    $user = User::create(['email'=>'probe-'.Str::lower(Str::random(16)).'@monitor.invalid', 'password'=>bcrypt(Str::random(64)),
                        'uuid'=>(string) Str::uuid(), 'token'=>Str::random(32), 'group_id'=>(int) $this->option('group'),
                        'transfer_enable'=>30 * 1073741824, 'expired_at'=>time()+365*86400, 'u'=>0, 'd'=>0,
                        'speed_limit'=>100, 'device_limit'=>null, 'banned'=>false, 'is_admin'=>false, 'is_staff'=>false,
                        'remind_expire'=>false, 'remind_traffic'=>false]);
                }
                [$probe, $token] = $service->create(['name'=>$this->argument('name'), 'location'=>$this->option('location'), 'user_id'=>$user->id, 'server_ids'=>$ids]);
                $path = $folder.'/'.$probe->id.'.json';
                $oldMask = umask(0077);
                try {
                    $file = fopen($path, 'x');
                    if (!$file) throw new \RuntimeException('配置文件已存在或无法写入');
                    $json = json_encode(['panel_url'=>rtrim(config('app.url'), '/'), 'token'=>$token], JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES);
                    try { if (fwrite($file, $json) !== strlen($json)) { unlink($path); throw new \RuntimeException('配置写入不完整'); } }
                    finally { fclose($file); }
                } finally { umask($oldMask); }
                return $probe;
            });
            $this->info('已创建探针 #'.$probe->id.'，监控账号 #'.$probe->user_id.'。配置文件：'.$folder.'/'.$probe->id.'.json');
            return self::SUCCESS;
        } catch (\Throwable $e) { $this->error('创建失败：请检查账号/节点权限、APP_URL 及私有目录写权限。'); return self::FAILURE; }
    }
}
