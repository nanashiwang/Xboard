<?php
namespace App\Console\Commands;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;
use App\Models\{Plan,ResidentialProxyHost,ResidentialProxyEndpoint};
class ResidentialProxyInventory extends Command {
    protected $signature='proxy:inventory {action : init, enable, disable, status} {--address=} {--output=}';
    protected $description='管理独立家宽代理库存；令牌只写入受限文件';
    public function handle(): int {
        $action=$this->argument('action'); $address=$this->option('address');
        if (!in_array($action,['init','enable','disable','status'],true)) return self::FAILURE;
        if ($action==='status') {
            $this->line(json_encode(['hosts'=>ResidentialProxyHost::all()->toArray(),'total'=>ResidentialProxyEndpoint::count(),'assigned'=>ResidentialProxyEndpoint::whereNotNull('user_id')->count()],JSON_UNESCAPED_UNICODE));return self::SUCCESS;
        }
        if (!in_array($address,['216.36.108.173','192.204.56.29'],true)) { $this->error('地址不在已授权库存中'); return self::FAILURE; }
        if ($action==='init') {
            $output=$this->option('output');
            if (!$output || file_exists($output)) { $this->error('必须指定尚不存在的受限输出文件'); return self::FAILURE; }
            $token=bin2hex(random_bytes(32));
            $old=umask(0077); $f=fopen($output,'x'); umask($old);
            if (!$f) return self::FAILURE;
            try {
                DB::transaction(function() use($address,$token) {
                    if (ResidentialProxyHost::where('address',$address)->exists()) throw new \RuntimeException('库存已存在，禁止重复初始化');
                    if (!Plan::where('is_proxy',true)->exists()) Plan::forceCreate(['name'=>'家宽固定代理 · 100 Mbps','is_proxy'=>true,'show'=>false,'sell'=>false,'renew'=>false,'transfer_enable'=>0,'speed_limit'=>100,'prices'=>['monthly'=>39],'capacity_limit'=>null]);
                    $host=ResidentialProxyHost::create(['address'=>$address,'token_hash'=>hash('sha256',$token),'enabled'=>false]);
                    foreach(range(20001,20010) as $port) ResidentialProxyEndpoint::create(['host_id'=>$host->id,'port'=>$port]);
                });
                fwrite($f,json_encode(['url'=>'https://capybarago.uk/api/v1/proxy-agent/sync','token'=>$token,'address'=>$address],JSON_UNESCAPED_SLASHES)); fclose($f);
            } catch(\Throwable $e) { fclose($f); unlink($output); throw $e; }
            $this->info('库存已初始化且暂停售卖；令牌已写入指定文件'); return self::SUCCESS;
        }
        $host=ResidentialProxyHost::where('address',$address)->firstOrFail();
        if ($action==='enable' && $host->seen_at<time()-60) { $this->error('代理未取得健康心跳'); return self::FAILURE; }
        $host->enabled=$action==='enable';$host->save();$this->info('库存状态已更新');return self::SUCCESS;
    }
}
