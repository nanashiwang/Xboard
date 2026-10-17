<?php
namespace Tests\Feature\Probes;

use App\Models\{NodeProbe, Server, User};
use App\Services\Probes\NodeProbeService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class NodeProbeTest extends TestCase
{
    use RefreshDatabase;
    private User $user;
    private Server $server;
    private NodeProbe $probe;
    private string $token;
    private string $adminPath;
    protected function setUp(): void
    {
        parent::setUp();
        $this->user = User::create(['email'=>'monitor@example.test','password'=>bcrypt('test'),'uuid'=>(string) Str::uuid(),'token'=>Str::random(32),'group_id'=>1,'transfer_enable'=>1073741824,'u'=>0,'d'=>0,'banned'=>false,'expired_at'=>null]);
        $this->server = Server::create(['name'=>'公开入口','type'=>'vless','host'=>'example.test','port'=>'443','server_port'=>31443,'group_ids'=>['1'],'show'=>true,'enabled'=>false,'rate'=>1,'protocol_settings'=>['network'=>'ws','tls'=>1,'tls_settings'=>['server_name'=>'example.test'],'network_settings'=>['path'=>'/test']]]);
        [$this->probe, $this->token] = app(NodeProbeService::class)->create(['name'=>'nas','location'=>'家庭网络','user_id'=>$this->user->id,'server_ids'=>[$this->server->id]]);
        $this->probe->refresh();
        $this->adminPath = '/api/v2/' . admin_setting('secure_path', admin_setting('frontend_admin_path', hash('crc32b', config('app.key')))) . '/node-probes';
    }
    private function sample(int $offset = 0, bool $ok = true): array
    {
        return ['sample_id'=>(string) Str::uuid(),'server_id'=>$this->server->id,'checked_at'=>time()-200+$offset,'checks'=>[
            ['id'=>'cloudflare','status'=>$ok?200:0,'ms'=>100,'bytes'=>64,'error'=>$ok?null:'timeout'],
            ['id'=>'google','status'=>$ok?204:0,'ms'=>200,'bytes'=>0,'error'=>$ok?null:'timeout'],
        ]];
    }
    private function report(array $s) { return $this->withHeader('Authorization', 'Bearer '.$this->token)->postJson('/api/v2/probe/report', $s); }
    public function test_admin_and_agent_authorization_are_separate(): void
    {
        $this->getJson($this->adminPath)->assertForbidden();
        Sanctum::actingAs($this->user);
        $this->getJson($this->adminPath)->assertForbidden();
        $this->postJson('/api/v2/probe/config',['agent_version'=>'test'])->assertUnauthorized();
        $this->user->update(['is_admin'=>true]);
        Sanctum::actingAs($this->user->fresh());
        $this->getJson($this->adminPath)->assertOk()->assertJsonMissing(['token_hash'=>$this->probe->token_hash])->assertJsonMissing(['uuid'=>$this->user->uuid]);
    }
    public function test_public_disabled_backend_alias_is_probed_and_credentials_are_scoped(): void
    {
        $r=$this->withHeader('Authorization','Bearer '.$this->token)->postJson('/api/v2/probe/config',['agent_version'=>'test'])->assertOk();
        $r->assertJsonPath('data.nodes.0.outbound.type','vless')->assertJsonPath('data.nodes.0.outbound.tag','node')->assertJsonPath('data.nodes.0.outbound.server','example.test');
        $this->assertStringContainsString('no-store',$r->headers->get('Cache-Control'));
        $this->user->update(['transfer_enable'=>0]);
        $this->postJson('/api/v2/probe/config',['agent_version'=>'test'])->assertJsonPath('data.nodes.0.error','account_unavailable')->assertJsonMissingPath('data.nodes.0.outbound');
    }
    public function test_unknown_scope_duplicate_and_old_reports_do_not_change_statistics(): void
    {
        $s=$this->sample();
        $this->report([...$s,'server_id'=>999])->assertForbidden();
        $this->report($s)->assertOk()->assertJsonPath('data.accepted',true);
        $this->report($s)->assertJsonPath('data.accepted',false);
        $this->report($this->sample(-1))->assertJsonPath('data.accepted',false);
        $this->assertDatabaseCount('v2_node_probe_sample',1);
        $this->assertDatabaseHas('v2_node_probe_hour',['requests'=>2,'successes'=>2,'rounds'=>1]);
        $this->report([...$this->sample(1),'checked_at'=>time()+1000])->assertUnprocessable();
    }
    public function test_failure_recovery_and_staleness(): void
    {
        foreach ([0,1,2] as $i) $this->report($this->sample($i,false))->assertOk();
        $this->assertDatabaseHas('v2_node_probe_state',['status'=>'down','failures'=>3]);
        foreach ([3,4] as $i) $this->report($this->sample($i))->assertOk();
        $this->assertDatabaseHas('v2_node_probe_state',['status'=>'healthy','successes'=>2]);
        $this->assertDatabaseHas('v2_node_probe_event',['to_status'=>'down']);
        $this->assertDatabaseHas('v2_node_probe_event',['to_status'=>'healthy']);
        $this->probe->update(['last_seen_at'=>time()]);
        $this->assertSame('healthy',app(NodeProbeService::class)->overview($this->probe)['nodes'][0]['status']);
        $this->probe->update(['last_seen_at'=>time()-1000]);
        $this->assertSame('stale',app(NodeProbeService::class)->overview($this->probe)['nodes'][0]['status']);
    }
    public function test_upload_requires_acknowledged_http_and_full_bytes(): void
    {
        $s=$this->sample();
        $s['checks'][]=['id'=>'upload','status'=>0,'ms'=>1000,'bytes'=>262144,'error'=>'timeout'];
        $s['checks'][]=['id'=>'download','status'=>200,'ms'=>1000,'bytes'=>1000,'error'=>null];
        $this->report($s)->assertOk();
        $this->assertDatabaseHas('v2_node_probe_hour',['uploads'=>1,'upload_successes'=>0,'downloads'=>1,'download_successes'=>0]);
        $s=$this->sample(1); foreach (['upload','download'] as $id) $s['checks'][]=['id'=>$id,'status'=>200,'ms'=>1000,'bytes'=>262144,'error'=>null];
        $this->report($s)->assertOk();
        $this->assertDatabaseHas('v2_node_probe_hour',['uploads'=>2,'upload_successes'=>1,'downloads'=>2,'download_successes'=>1]);
        $state=DB::table('v2_node_probe_state')->first();
        $this->assertSame(2.097,json_decode($state->checks,true)['checks'][2]['mbps']);
    }
    public function test_configuration_errors_are_not_node_outages_and_missing_checks_rejected(): void
    {
        $this->report([...$this->sample(),'checks'=>[]])->assertUnprocessable();
        foreach ([0,1,2] as $i) $this->report([...$this->sample($i),'checks'=>[],'error'=>'core_config'])->assertOk();
        $this->assertDatabaseHas('v2_node_probe_state',['status'=>'config_error','failures'=>0]);
        $this->assertDatabaseHas('v2_node_probe_hour',['requests'=>0,'successes'=>0,'rounds'=>3]);
    }
    public function test_disable_and_rotation_revoke_agent_token(): void
    {
        $this->user->update(['is_admin'=>true]); Sanctum::actingAs($this->user->fresh());
        $this->postJson($this->adminPath.'/'.$this->probe->id.'/rotate')->assertOk();
        $this->withHeader('Authorization','Bearer '.$this->token)->postJson('/api/v2/probe/config',['agent_version'=>'test'])->assertUnauthorized();
        $this->probe->update(['token_hash'=>hash('sha256',$this->token),'enabled'=>false]);
        $this->postJson('/api/v2/probe/config',['agent_version'=>'test'])->assertUnauthorized();
    }
    public function test_scope_cannot_include_unavailable_nodes_and_insecure_tls_rejected(): void
    {
        $this->server->update(['group_ids'=>['2']]);
        $this->expectException(\Illuminate\Validation\ValidationException::class);
        app(NodeProbeService::class)->create(['name'=>'bad','location'=>'bad','user_id'=>$this->user->id,'server_ids'=>[$this->server->id]]);
    }
    public function test_history_and_pruning_keep_hourly_totals(): void
    {
        $this->report($this->sample())->assertOk();
        $this->user->update(['is_admin'=>true]); Sanctum::actingAs($this->user->fresh());
        $this->getJson($this->adminPath.'/'.$this->probe->id.'/history/'.$this->server->id)->assertOk()->assertJsonPath('data.latency_p95_ms',200);
        DB::table('v2_node_probe_sample')->update(['checked_at'=>time()-90000]);
        $this->artisan('probes:prune')->assertSuccessful();
        $this->assertDatabaseCount('v2_node_probe_sample',0); $this->assertDatabaseCount('v2_node_probe_hour',1);
    }
    public function test_transfer_result_survives_connectivity_only_rounds(): void
    {
        $s=$this->sample(); foreach (['upload','download'] as $id) $s['checks'][]=['id'=>$id,'status'=>200,'ms'=>1000,'bytes'=>262144,'error'=>null];
        $this->report($s)->assertOk(); $this->report($this->sample(1))->assertOk();
        $state=DB::table('v2_node_probe_state')->first();
        $this->assertCount(2,json_decode($state->transfers,true));
        $this->assertSame($s['checked_at'],(int)$state->transfer_checked_at);
    }
    public function test_successful_small_requests_do_not_clear_a_failed_upload(): void
    {
        $s=$this->sample();
        $s['checks'][]=['id'=>'upload','status'=>0,'ms'=>8000,'bytes'=>0,'error'=>'timeout'];
        $s['checks'][]=['id'=>'download','status'=>200,'ms'=>1000,'bytes'=>262144,'error'=>null];
        $this->report($s)->assertOk();
        $this->report($this->sample(1))->assertOk(); $this->report($this->sample(2))->assertOk();
        $this->assertDatabaseHas('v2_node_probe_state',['status'=>'degraded','successes'=>0]);
        $s=$this->sample(3); foreach (['upload','download'] as $id) $s['checks'][]=['id'=>$id,'status'=>200,'ms'=>1000,'bytes'=>262144,'error'=>null];
        $this->report($s)->assertOk(); $this->report($this->sample(4))->assertOk();
        $this->assertDatabaseHas('v2_node_probe_state',['status'=>'healthy']);
    }
    public function test_cli_keeps_credentials_private_and_does_not_reuse_a_customer(): void
    {
        config(['app.url'=>'https://panel.example.test']);
        $this->artisan('probes:create',['name'=>'cli-test','--location'=>'NAS','--user'=>$this->user->id,'--nodes'=>(string)$this->server->id])->assertSuccessful();
        $probe=NodeProbe::orderByDesc('id')->first();
        $path=storage_path('app/private/node-probes/'.$probe->id.'.json');
        try {
            $this->assertFileExists($path);
            $config=json_decode(file_get_contents($path),true);
            $this->assertSame(hash('sha256',$config['token']),$probe->token_hash);
            $this->assertSame(0600,fileperms($path)&0777);
            $this->assertDatabaseCount('v2_user',1);
        } finally { @unlink($path); }
    }
    public function test_rejected_tls_and_protocol_are_explicit_configuration_errors(): void
    {
        $this->server->update(['protocol_settings'=>['network'=>'xhttp','tls'=>1]]);
        $this->assertSame('unsupported_protocol',app(NodeProbeService::class)->configuration($this->probe)['nodes'][0]['error']);
        $this->server->update(['protocol_settings'=>['network'=>'ws','tls'=>1,'tls_settings'=>['allow_insecure'=>true]]]);
        $this->assertSame('insecure_tls',app(NodeProbeService::class)->configuration($this->probe)['nodes'][0]['error']);
    }

}
