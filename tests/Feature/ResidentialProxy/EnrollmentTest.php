<?php
namespace Tests\Feature\ResidentialProxy;

use App\Models\{Plan, ResidentialProxyEndpoint, ResidentialProxyHost};
use App\Services\{ResidentialEnrollment, ResidentialProxyService};
use Illuminate\Foundation\Testing\RefreshDatabase;
use Symfony\Component\HttpKernel\Exception\HttpException;
use Tests\TestCase;

class EnrollmentTest extends TestCase
{
    use RefreshDatabase;

    private ResidentialEnrollment $enroll;
    private array $data = ['label'=>'英国家宽','country'=>'英国','address'=>'8.8.4.4'];

    protected function setUp(): void
    {
        parent::setUp();
        Plan::forceCreate(['name'=>'家宽','is_proxy'=>true,'transfer_enable'=>0,'prices'=>['monthly'=>39]]);
        $this->enroll = app(ResidentialEnrollment::class);
    }

    private function denied(callable $action, int $code): void
    {
        try { $action(); $this->fail('Expected rejection'); }
        catch (HttpException $e) { $this->assertEquals($code, $e->getStatusCode()); }
    }

    public function test_rotating_install_code_and_full_revocation_before_sale(): void
    {
        $first = $this->enroll->register($this->data);
        $host = ResidentialProxyHost::sole();
        $this->assertSame(10, ResidentialProxyEndpoint::count());
        $this->denied(fn () => $this->enroll->register($this->data), 409);
        $second = $this->enroll->issue($host->id);
        preg_match('/[a-f0-9]{64}/', $first['command'], $a);
        preg_match('/[a-f0-9]{64}/', $second['command'], $b);
        $auth = bin2hex(random_bytes(32)); $digest = hash('sha256',$auth);
        $this->denied(fn () => $this->enroll->claim($host->id,$a[0],$digest),409);
        $this->enroll->claim($host->id,$b[0],$digest);
        $this->denied(fn () => $this->enroll->claim($host->id,$b[0],$digest),409);
        $this->denied(fn () => $this->enroll->issue($host->id),409);
        $host->update(['transport_cert'=>'fixture','seen_at'=>time()]);
        $this->enroll->start($host->id);
        $this->assertFalse(ResidentialProxyHost::acceptingOrders(time())->exists());
        $this->assertArrayNotHasKey('probe',$this->enroll->manifest()[0]);
        $host->refresh();
        $rows = app(ResidentialProxyService::class)->snapshot($host)['endpoints'];
        $this->assertCount(10, array_unique(array_column(array_column($rows,'credentials'),'password')));
        $reports = array_map(fn ($r) => ['id'=>$r['id'],'revision'=>$r['revision'],'running'=>true], $rows);
        $sync = fn ($reports) => $this->withHeader('Authorization','Bearer '.$auth)
            ->postJson('/api/v1/proxy-agent/sync',['reports'=>$reports])->assertOk();
        $sync($reports);
        $this->assertCount(10,$this->enroll->manifest()[0]['probe']['ports']);
        $this->denied(fn () => $this->enroll->finish($host->id, str_repeat('0',32), true, null),409);
        $this->enroll->finish($host->id, $host->probe_id, true, null);
        $res = $sync($reports);
        $withdrawn = $res->json('endpoints');
        $this->assertSame([],array_filter(array_column($withdrawn,'enabled')));
        $this->assertFalse($host->fresh()->enabled);
        $stopped = array_map(fn ($r) => ['id'=>$r['id'],'revision'=>$r['revision'],'running'=>false],$withdrawn);
        $sync(array_slice($stopped,0,9));
        $this->assertFalse($host->fresh()->enabled);
        $sync($stopped);
        $this->assertTrue($host->fresh()->enabled);
        $this->assertEquals('live',$host->fresh()->enrollment_state);
        $this->denied(fn () => $this->enroll->start($host->id),409);
        $this->assertEquals('英国', app(ResidentialProxyService::class)->describe(ResidentialProxyEndpoint::first())['country']);
    }

    public function test_admin_endpoints_generate_commands_but_never_expose_them_in_inventory(): void
    {
        $prefix = '/api/v2/'.admin_setting('secure_path', admin_setting('frontend_admin_path', hash('crc32b', config('app.key')))).'/stat/';
        $url = $prefix.'residential/register';
        $this->postJson($url,$this->data)->assertForbidden();
        $user = \App\Models\User::create(['email'=>'operator@example.test','uuid'=>\App\Utils\Helper::guid(),
            'password'=>'unused','token'=>\App\Utils\Helper::guid(),'is_admin'=>true]);
        \Laravel\Sanctum\Sanctum::actingAs($user);
        $command = $this->postJson($url,$this->data)->assertOk()->json('data.command');
        $this->assertStringContainsString('sudo python3', $command);
        preg_match('/[0-9a-f]{64}/', $command, $secret);
        $response = $this->getJson($prefix.'getResidentialCapacity')->assertOk();
        $this->assertStringNotContainsString($secret[0], $response->getContent());
        $this->assertSame(0,$response->json('data.proxy_inventory.totals.available'));
        $this->assertSame('registered',$response->json('data.proxy_inventory.hosts.0.enrollment'));
    }

    public function test_failed_expired_or_unauthorized_checks_leave_stock_offline(): void
    {
        foreach (['127.0.0.1','10.0.0.1','169.254.169.254','224.4.4.4'] as $ip) {
            $this->denied(fn () => $this->enroll->register(array_merge($this->data,['address'=>$ip])),422);
        }
        $this->enroll->register($this->data);
        $host = ResidentialProxyHost::sole();
        $this->denied(fn () => $this->enroll->start($host->id),409);
        $this->getJson('/api/v1/proxy-agent/ingress')->assertUnauthorized();
        $this->getJson('/api/v1/proxy-agent/installer')->assertOk();
        $host->update(['enrollment_state'=>'installed','transport_cert'=>'fixture','seen_at'=>time()]);
        $this->enroll->start($host->id);
        $host->refresh();
        $this->enroll->finish($host->id,$host->probe_id,false,'route');
        $this->assertSame('failed',$host->fresh()->enrollment_state);
        $this->assertFalse($host->fresh()->enabled);
        $this->enroll->start($host->id);
        $host->refresh()->update(['probe_until'=>time()-1]);
        $this->assertArrayNotHasKey('probe',$this->enroll->manifest()[0]);
        $this->denied(fn () => $this->enroll->finish($host->id,$host->probe_id,true,null),409);
        $this->assertEquals([], array_filter(array_column(app(ResidentialProxyService::class)->snapshot($host)['endpoints'],'enabled')));
    }
}
