<?php
namespace Tests\Feature\ResidentialProxy;
use Tests\TestCase;
use App\Models\{Plan,User,Order,ResidentialProxyHost,ResidentialProxyEndpoint};
use App\Utils\Helper;
use Illuminate\Support\Facades\DB;
use Symfony\Component\Process\Process;
class ProxyConcurrencyTest extends TestCase {
    public function test_parallel_buyers_cannot_reserve_the_same_port(): void {
        $database=tempnam(sys_get_temp_dir(),'proxy-concurrency-');$original=config('database.connections.sqlite.database');
        try {
            config(['database.connections.sqlite.database'=>$database]);DB::purge('sqlite');
            $this->artisan('migrate',['--force'=>true])->assertSuccessful();DB::statement('PRAGMA journal_mode = WAL');
            Plan::forceCreate(['name'=>'Proxy','is_proxy'=>true,'transfer_enable'=>0,'prices'=>['monthly'=>39]]);
            $host=ResidentialProxyHost::create(['address'=>'216.36.108.173','token_hash'=>str_repeat('a',64),'enabled'=>true,'seen_at'=>time()]);
            foreach(range(20001,20003) as $port)ResidentialProxyEndpoint::create(['host_id'=>$host->id,'port'=>$port]);
            $processes=[];
            foreach(range(1,6) as $i){$u=User::create(['email'=>"concurrent$i@example.test",'password'=>'unused','uuid'=>Helper::guid(),'token'=>Helper::guid(),'balance'=>10000]);
                $processes[]=new Process([PHP_BINARY,base_path('tests/Fixtures/proxy-order-worker.php'),$u->id],base_path(),['APP_ENV'=>'testing','DB_CONNECTION'=>'sqlite','DB_DATABASE'=>':memory:','PROXY_TEST_DATABASE'=>$database,'CACHE_DRIVER'=>'array','SETTINGS_CACHE_STORE'=>'array','QUEUE_CONNECTION'=>'sync'],timeout:30);
            }
            foreach($processes as $p)$p->start();$results=[];
            foreach($processes as $p){$p->wait();$this->assertTrue($p->isSuccessful(),$p->getErrorOutput().$p->getOutput());$results[]=trim($p->getOutput());}
            $this->assertSame(3,count(array_filter($results,fn($s)=>$s==='reserved')),json_encode($results));
            $this->assertSame(3,Order::count());$this->assertSame(3,ResidentialProxyEndpoint::whereNotNull('reserved_order_id')->count());
            $this->assertEquals(60000-3*3900,User::sum('balance'));
        } finally {DB::disconnect('sqlite');config(['database.connections.sqlite.database'=>$original]);DB::purge('sqlite');foreach([$database,$database.'-wal',$database.'-shm'] as $p)if(is_file($p))unlink($p);}
    }
}
