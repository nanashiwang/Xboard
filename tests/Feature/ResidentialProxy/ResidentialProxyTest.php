<?php
namespace Tests\Feature\ResidentialProxy;
use Tests\TestCase;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use App\Models\{User,Plan,Order,ResidentialProxyHost,ResidentialProxyEndpoint};
use App\Services\{OrderService,ResidentialProxyService};
use App\Utils\Helper;
use App\Exceptions\ApiException;

class ResidentialProxyTest extends TestCase {
    use RefreshDatabase;
    private User $buyer; private ResidentialProxyHost $host; private ResidentialProxyEndpoint $endpoint; private ResidentialProxyService $service;
    protected function setUp(): void {
        parent::setUp();
        Plan::forceCreate(['name'=>'Proxy','is_proxy'=>true,'show'=>false,'sell'=>false,'transfer_enable'=>0,'prices'=>['monthly'=>39]]);
        $this->buyer=User::create(['email'=>'proxy@example.test','password'=>'unused','uuid'=>Helper::guid(),'token'=>Helper::guid(),'balance'=>10000,'plan_id'=>888,'group_id'=>7,'u'=>123,'d'=>456,'transfer_enable'=>999,'expired_at'=>time()+86400]);
        $this->host=ResidentialProxyHost::create(['address'=>'216.36.108.173','token_hash'=>hash('sha256',str_repeat('a',64)),'enabled'=>true,'seen_at'=>time()]);
        $this->endpoint=ResidentialProxyEndpoint::create(['host_id'=>$this->host->id,'port'=>20001]);
        $this->service=app(ResidentialProxyService::class);
    }
    public function test_purchase_and_duplicate_payment_never_change_vpn_or_extend_twice(): void {
        $before=$this->buyer->only(['plan_id','group_id','u','d','transfer_enable','expired_at']);
        $order=$this->service->create($this->buyer);
        $this->assertSame(0,$order->total_amount);$this->assertSame(3900,$order->balance_amount);
        (new OrderService($order))->paid('test');
        $expiry=$this->endpoint->fresh()->expires_at;
        (new OrderService($order))->paid('duplicate');
        $this->assertSame($expiry,$this->endpoint->fresh()->expires_at);
        $this->assertSame($before,$this->buyer->fresh()->only(array_keys($before)));
        $this->assertEquals(6100,$this->buyer->fresh()->balance);
        $this->assertSame(3,$order->fresh()->status);
        $raw=DB::table('residential_proxy_endpoints')->value('credentials');
        $this->assertStringNotContainsString($this->endpoint->fresh()->credentials['password'],$raw);
        $this->assertArrayNotHasKey('credentials',$this->service->index($this->buyer)['items'][0]);
    }

    private function secondHost(): ResidentialProxyHost {
        return ResidentialProxyHost::create([
            'address' => '192.204.56.29', 'token_hash' => str_repeat('b', 64),
            'enabled' => true, 'seen_at' => time(),
        ]);
    }

    public function test_successive_purchases_use_distinct_ips_then_the_least_owned_available_ip(): void {
        $this->buyer->update(['balance' => 5 * ResidentialProxyService::PRICE]);
        $a2 = ResidentialProxyEndpoint::create(['host_id' => $this->host->id, 'port' => 20002]);
        ResidentialProxyEndpoint::create(['host_id' => $this->host->id, 'port' => 20003]);
        $otherHost = $this->secondHost();
        $b1 = ResidentialProxyEndpoint::create(['host_id' => $otherHost->id, 'port' => 20001]);
        $b2 = ResidentialProxyEndpoint::create(['host_id' => $otherHost->id, 'port' => 20002]);
        ResidentialProxyEndpoint::create(['host_id' => $otherHost->id, 'port' => 20003, 'user_id' => 999]);

        foreach ([$this->endpoint, $b1, $a2, $b2] as $expected) {
            $order = $this->service->create($this->buyer);
            $this->assertEquals($expected->id, $order->proxy_endpoint_id);
            $this->assertEquals($order->id, $expected->fresh()->reserved_order_id);
            $this->service->paid($order, 'test');
        }
    }

    public function test_retained_expired_asset_counts_for_new_purchases_and_renewal_keeps_its_port(): void {
        $this->endpoint->update(['user_id' => $this->buyer->id, 'expires_at' => time() - 1]);
        ResidentialProxyEndpoint::create(['host_id' => $this->host->id, 'port' => 20002]);
        $newIp = ResidentialProxyEndpoint::create(['host_id' => $this->secondHost()->id, 'port' => 20001]);
        $order = $this->service->create($this->buyer);
        $this->assertEquals($newIp->id, $order->proxy_endpoint_id);
        $this->service->cancel($order);
        $renew = $this->service->create($this->buyer, $this->endpoint->id);
        $this->assertEquals($this->endpoint->id, $renew->proxy_endpoint_id);
    }

    #[\PHPUnit\Framework\Attributes\DataProvider('unavailableInventory')]
    public function test_new_purchase_reuses_owned_ip_if_other_ip_has_no_sellable_port(array $hostState, array $portState): void {
        $this->endpoint->update(['user_id' => $this->buyer->id]);
        $otherHost = $this->secondHost();
        $otherHost->update($hostState);
        ResidentialProxyEndpoint::create($portState + ['host_id' => $otherHost->id, 'port' => 20001]);
        $available = ResidentialProxyEndpoint::create(['host_id' => $this->host->id, 'port' => 20002]);
        $this->assertEquals($available->id, $this->service->create($this->buyer)->proxy_endpoint_id);
    }

    public static function unavailableInventory(): array {
        return [
            'disabled host' => [['enabled' => false], []],
            'stale heartbeat' => [['seen_at' => 1], []],
            'reserved port' => [[], ['reserved_order_id' => 999]],
            'owned by another user' => [[], ['user_id' => 999]],
        ];
    }
    public function test_reservation_prevents_oversell_and_cancel_refunds_once(): void {
        $order=$this->service->create($this->buyer);
        $other=$this->buyer->replicate();$other->email='other@example.test';$other->uuid=Helper::guid();$other->token=Helper::guid();$other->save();
        try {$this->service->create($other);$this->fail('oversold');}catch(ApiException $e){$this->assertStringContainsString('库存',$e->getMessage());}
        $this->service->cancel($order);$this->service->cancel($order);
        $this->assertEquals(10000,$this->buyer->fresh()->balance);$this->assertNull($this->endpoint->fresh()->reserved_order_id);
        $this->service->create($other);$this->assertSame(2,Order::count());
    }
    public function test_late_payment_after_cancel_credits_balance_and_cannot_steal_inventory(): void {
        $this->buyer->update(['balance'=>100]);$order=$this->service->create($this->buyer);
        $this->service->cancel($order);$this->service->paid($order,'late');$this->service->paid($order,'duplicate');
        $this->assertEquals(3900,$this->buyer->fresh()->balance);$this->assertNull($this->endpoint->fresh()->user_id);
        $this->assertSame(2,$order->fresh()->status);
    }
    public function test_cancel_after_payment_does_not_refund_or_revoke(): void {
        $o=$this->service->create($this->buyer);$this->service->paid($o,'paid');
        $this->assertFalse($this->service->cancel($o));$this->assertEquals(6100,$this->buyer->fresh()->balance);
        $this->assertEquals($this->buyer->id,$this->endpoint->fresh()->user_id);
    }
    public function test_renewal_uses_calendar_month_and_expiry_disables_both_protocols(): void {
        $o=$this->service->create($this->buyer);$this->service->paid($o,'paid');
        $expiry=\Carbon\Carbon::parse('2028-01-31 12:00:00')->timestamp;
        $this->endpoint->update(['expires_at'=>$expiry]);
        $renew=$this->service->create($this->buyer,$this->endpoint->id);$this->service->paid($renew,'renew');
        $this->assertSame(\Carbon\Carbon::parse('2028-02-29 12:00:00')->timestamp,$this->endpoint->fresh()->expires_at);
        $this->endpoint->update(['expires_at'=>time()-1]);
        $row=$this->service->snapshot($this->host)['endpoints'][0];
        $this->assertFalse($row['enabled']);$this->assertNull($row['credentials']);
        $this->assertArrayNotHasKey('credentials',$this->service->describe($this->endpoint->fresh('host'),true));
    }
    public function test_credentials_owner_isolation_reset_revision_and_host_reports(): void {
        $o=$this->service->create($this->buyer);$this->service->paid($o,'paid');
        $before=$this->endpoint->fresh();
        $this->actingAs($this->buyer,'sanctum');
        $this->getJson('/api/v1/user/proxies/detail?id='.$before->id)->assertOk()->assertHeader('Cache-Control','no-store, private')->assertJsonPath('data.credentials.username',$before->credentials['username']);
        $result=$this->service->update($this->buyer,$before->id,['reset'=>true,'name'=>'My endpoint']);
        $this->assertNotEquals($before->credentials['password'],$result['credentials']['password']);
        $this->assertSame($before->revision+1,$result['revision']);
        $this->withHeader('Authorization','Bearer '.str_repeat('a',64))->postJson('/api/v1/proxy-agent/sync',['reports'=>[['id'=>$before->id,'revision'=>$result['revision'],'running'=>true]]])->assertOk()->assertJsonPath('endpoints.0.credentials.password',$result['credentials']['password']);
        $this->assertSame('active',$this->service->describe($before->fresh('host'))['status']);
        $other=$this->buyer->replicate();$other->email='other@example.test';$other->uuid=Helper::guid();$other->save();
        $this->actingAs($other,'sanctum')->getJson('/api/v1/user/proxies/detail?id='.$before->id)->assertNotFound();
        $this->postJson('/api/v1/user/proxies/update',['id'=>$before->id,'reset'=>true])->assertNotFound();
    }
    public function test_disabled_stale_hosts_and_vpn_store_cannot_sell_proxy_plan(): void {
        $this->host->update(['seen_at'=>time()-61]);$this->assertSame(0,$this->service->index($this->buyer)['available']);
        $this->expectException(ApiException::class);
        OrderService::createFromRequest($this->buyer,Plan::where('is_proxy',true)->first(),'month_price');
    }
    public function test_agent_cannot_acknowledge_another_hosts_endpoint_or_stale_revision(): void {
        $this->postJson('/api/v1/proxy-agent/sync',['reports'=>[]])->assertUnauthorized();
        $this->withHeader('Authorization','Bearer '.str_repeat('a',64))->postJson('/api/v1/proxy-agent/sync',['reports'=>[['id'=>$this->endpoint->id,'revision'=>99,'running'=>true]]])->assertOk();
        $this->assertSame(0,$this->endpoint->fresh()->applied_revision);
    }
}
