<?php
namespace Tests\Feature\Probes;

use App\Models\{NodeProbe, NodeProbeIngress, Server, ServerMachine, User};
use App\Services\Probes\{IngressProbeService, NodeProbeService};
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Tests\TestCase;

class IngressProbeTest extends TestCase
{
    use RefreshDatabase;
    private $probe; private $entry; private $machine; private $server; private $token;
    protected function setUp(): void
    {
        parent::setUp();
        $u=User::create(['email'=>'ingress@test.invalid','password'=>bcrypt('test'),'uuid'=>(string)Str::uuid(),'token'=>Str::random(32),'group_id'=>1,'transfer_enable'=>1000000,'u'=>0,'d'=>0,'banned'=>false,'expired_at'=>null]);
        $this->server=Server::create(['name'=>'入口','host'=>'ingress.test','type'=>'vless','port'=>443,'server_port'=>31443,'show'=>true,'enabled'=>false,'group_ids'=>['1'],'rate'=>1]);
        [$this->probe,$this->token]=app(NodeProbeService::class)->create(['name'=>'NAS','location'=>'home','user_id'=>$u->id,'server_ids'=>[$this->server->id]]);
        $this->probe->refresh();
        $this->machine=ServerMachine::create(['name'=>'入口','token'=>Str::random(32),'is_active'=>true]);
        $this->entry=NodeProbeIngress::create(['name'=>'第一段','host'=>'ingress.test','health_path'=>'/healthz','expected_body'=>'ready','machine_id'=>$this->machine->id,'server_tunnels'=>[$this->server->id=>'10.1.0.2']]);
    }
    private function sample($offset=0): array
    {
        return ['sample_id'=>(string)Str::uuid(),'ingress_id'=>$this->entry->id,'checked_at'=>time()-100+$offset,'measurement'=>['status'=>200,'body_ok'=>true,'error'=>null,'total_ms'=>240,'dns_ms'=>5,'tcp_ms'=>80,'tls_ms'=>90,'ttfb_ms'=>230]];
    }
    private function report($s) { return $this->withHeader('Authorization','Bearer '.$this->token)->postJson('/api/v2/probe/ingress-report',$s); }
    public function test_scoped_reports_deduplicate_and_never_change_proxy_statistics(): void
    {
        $s=$this->sample();
        $this->postJson('/api/v2/probe/ingress-report',$s)->assertUnauthorized();
        $this->report([...$s,'ingress_id'=>999])->assertForbidden();
        $this->report($s)->assertOk()->assertJsonPath('data.accepted',true);
        $this->report($s)->assertJsonPath('data.accepted',false);
        $this->report($this->sample(-1))->assertJsonPath('data.accepted',false);
        $this->assertDatabaseCount('v2_node_probe_ingress_sample',1);
        $this->assertDatabaseCount('v2_node_probe_hour',0);
        $this->server->update(['host'=>'different.test']);
        $this->report($this->sample(1))->assertForbidden();
        $this->assertSame([],app(IngressProbeService::class)->configuration($this->probe));
    }
    public function test_body_mismatch_stale_heartbeat_and_revocation_cannot_be_healthy(): void
    {
        $s=$this->sample();$s['measurement']['body_ok']=false;
        $this->report($s)->assertOk();
        $this->probe->update(['last_seen_at'=>time()]);
        $service=app(IngressProbeService::class);
        $this->assertSame('degraded',$service->overview($this->probe)[0]['status']);
        $this->report($this->sample(1))->assertOk();
        $this->assertSame('healthy',$service->overview($this->probe)[0]['status']);
        $this->probe->update(['last_seen_at'=>time()-1000]);
        $this->assertSame('stale',$service->overview($this->probe)[0]['status']);
        $this->machine->update(['last_seen_at'=>time(),'load_status'=>['updated_at'=>time()-1000,'cpu'=>2]]);
        $this->assertFalse($service->overview($this->probe)[0]['machine']['fresh']);
        $this->probe->update(['enabled'=>false]);
        $this->report($this->sample(2))->assertUnauthorized();
        $this->assertSame('disabled',$service->overview($this->probe)[0]['status']);
    }
    public function test_machine_report_keeps_tunnels_scoped_and_bytes_per_second(): void
    {
        $body=['machine_id'=>$this->machine->id,'token'=>$this->machine->token,'cpu'=>3,'mem'=>['total'=>1000,'used'=>200],
            'net'=>['in_speed'=>125000,'out_speed'=>250000], 'ingress'=>['interface'=>'ens3','nginx'=>true,'wireguard'=>true,
            'peers'=>[['ip'=>'10.1.0.2','handshake_at'=>time()-30,'loss_percent'=>0,'rtt_ms'=>45]]]];
        $this->postJson('/api/v2/server/machine/status',[...$body,'token'=>'invalid'])->assertForbidden();
        $this->postJson('/api/v2/server/machine/status',$body)->assertOk();
        $view=app(IngressProbeService::class)->overview($this->probe)[0];
        $this->assertTrue($view['machine']['fresh']);
        $this->assertEquals(125000,$view['machine']['load']['net']['in_speed']);
        $this->assertEquals(45,$view['machine']['load']['ingress']['peers'][0]['rtt_ms']);
        $this->assertArrayNotHasKey('token',$view['machine']);
        $this->postJson('/api/v2/server/machine/status',[...$body,'ingress'=>[...$body['ingress'],'unknown'=>'secret']])->assertUnprocessable();
    }
    public function test_ingress_details_require_admin_and_retention_prunes_only_old_samples(): void
    {
        $this->report($this->sample())->assertOk();
        $path='/api/v2/'.admin_setting('secure_path',admin_setting('frontend_admin_path',hash('crc32b',config('app.key')))).'/node-probes/'.$this->probe->id.'/ingress-history/'.$this->entry->id;
        $this->getJson($path)->assertForbidden();
        $h=app(IngressProbeService::class)->history($this->probe,$this->entry->id);
        $this->assertCount(1,$h['samples']);
        DB::table('v2_node_probe_ingress_sample')->update(['checked_at'=>time()-90000]);
        $this->artisan('probes:prune')->assertSuccessful();
        $this->assertDatabaseCount('v2_node_probe_ingress_sample',0);
    }
    public function test_cli_rejects_unrelated_nodes_and_exports_only_to_private_file(): void
    {
        $path=tempnam(sys_get_temp_dir(),'ingress');
        $data=['name'=>'第一段','host'=>'ingress.test','health_path'=>'/healthz','expected_body'=>'ready','network_interface'=>'ens3','wireguard_interface'=>'wg-test','server_tunnels'=>[$this->server->id=>'10.1.0.2']];
        try {
            file_put_contents($path,json_encode($data));
            $this->artisan('probes:ingress',['config'=>$path])->assertSuccessful();
            $private=storage_path('app/private/node-probes/ingress-'.$this->entry->id.'.json');
            $this->assertSame(0600,fileperms($private)&0777);
            $this->assertSame($this->machine->token,json_decode(file_get_contents($private),true)['token']);
            unlink($private);
            $data['server_tunnels']=[999=>'10.1.0.2'];file_put_contents($path,json_encode($data));
            $this->artisan('probes:ingress',['config'=>$path])->assertFailed();
            $this->assertDatabaseCount('v2_server_machine',1);
        } finally { unlink($path); }
    }
}
