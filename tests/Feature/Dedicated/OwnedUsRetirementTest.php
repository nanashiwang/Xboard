<?php
namespace Tests\Feature\Dedicated;

use App\Models\{DedicatedAssignment,DedicatedExit,NodeProbe,Plan,Server,ServerMachine,User};
use App\Services\ServerService;
use App\Utils\Helper;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Queue;
use Tests\TestCase;

require_once dirname(__DIR__,3).'/.docker/dedicated/rotate-us.php';

class OwnedUsRetirementTest extends TestCase
{
    use RefreshDatabase;
    private User $customer;

    protected function setUp(): void
    {
        parent::setUp(); Queue::fake();
        Plan::forceCreate(['id'=>5,'name'=>'Fixed','group_id'=>5,'dedicated'=>true,'capacity_limit'=>15,'prices'=>['monthly'=>59],'transfer_enable'=>200]);
        $monitor=User::create(['email'=>Helper::guid().'@example.test','password'=>'test','uuid'=>Helper::guid(),'token'=>Helper::guid(),
            'group_id'=>6,'transfer_enable'=>1073741824,'u'=>0,'d'=>0,'expired_at'=>time()+86400]);
        $machine=ServerMachine::create(['name'=>'test','token'=>Helper::guid()]);
        foreach(\RotateOwnedUs20261028::BACKENDS as $source=>$backend) {
            $groups=in_array($source,[148,319],true)?['1','2','3','4','6']:['5','6'];
            Server::forceCreate(['id'=>$backend,'name'=>'backend-'.$backend,'type'=>'vless','host'=>\RotateOwnedUs20261028::IPS[$source]??'203.0.113.1',
                'port'=>'31443','server_port'=>31443,'machine_id'=>$machine->id,'group_ids'=>$groups,'show'=>false,'enabled'=>true,'rate'=>2]);
            Server::forceCreate(['id'=>$source,'name'=>'source-'.$source,'type'=>'vless','host'=>'node.example','port'=>'443','server_port'=>443,
                'parent_id'=>$backend,'group_ids'=>in_array($source,[148,319],true)?$groups:['6'],'show'=>true,'enabled'=>false,'rate'=>2]);
        }
        for($id=1;$id<=18;$id++) {
            $source=$id>=6?\RotateOwnedUs20261028::SOURCES[$id-6]:null;
            DedicatedExit::forceCreate(['id'=>$id,'plan_id'=>5,'name'=>'exit-'.$id,'public_ip'=>$id===14?'216.36.108.173':'203.0.113.'.$id,
                'enabled'=>!in_array($id,[1,2,3,4,5,11,18],true),'healthy'=>true,'checked_at'=>time(),
                'shared_server_id'=>$source?\RotateOwnedUs20261028::BACKENDS[$source]:null,'probe_id'=>$source?1:null,'probe_server_id'=>$source]);
            if($source) Server::forceCreate(['id'=>$id+334,'name'=>'alias-'.$id,'type'=>'vless','host'=>'node.example','port'=>'443','server_port'=>443,
                'parent_id'=>\RotateOwnedUs20261028::BACKENDS[$source],'group_ids'=>['5'],'show'=>!in_array($id,[11,18],true),'enabled'=>false,'rate'=>2,'dedicated_exit_id'=>$id]);
        }
        NodeProbe::forceCreate(['id'=>1,'name'=>'monitor','location'=>'test','token_hash'=>hash('sha256','test'),'user_id'=>$monitor->id,'enabled'=>true,
            'server_ids'=>\RotateOwnedUs20261028::SOURCES,'expected_exits'=>\RotateOwnedUs20261028::IPS]);
        $this->customer=User::create(['email'=>Helper::guid().'@example.test','password'=>'test','uuid'=>Helper::guid(),'token'=>Helper::guid(),
            'plan_id'=>5,'group_id'=>5,'transfer_enable'=>1073741824,'u'=>1,'d'=>2,'balance'=>123,'expired_at'=>time()+86400]);
        DedicatedAssignment::create(['plan_id'=>5,'user_id'=>$this->customer->id,'exit_id'=>17,'slot'=>1]);
    }

    public function test_rotation_preserves_customer_and_reservation_and_separates_authorization(): void
    {
        $before=$this->customer->fresh()->getAttributes();
        $reservation=DedicatedAssignment::create(['plan_id'=>5,'user_id'=>999,'exit_id'=>15,'slot'=>2,'order_id'=>777,'reserved_until'=>time()+120]);
        $saved=null;
        $result=\RotateOwnedUs20261028::apply(function($snapshot)use(&$saved){$saved=$snapshot;});
        $this->assertSame(2,$result['moved']);
        $this->assertSame($before,$this->customer->fresh()->getAttributes());
        $this->assertSame(17,$saved['assignments'][0]['exit_id']);
        $this->assertSame([14],DedicatedExit::where('enabled',true)->pluck('id')->all());
        $this->assertSame(5,Plan::find(5)->capacity_limit);
        $this->assertSame(777,$reservation->fresh()->order_id);
        $this->assertSame(14,$reservation->fresh()->exit_id);
        $this->assertCount(2,DedicatedAssignment::pluck('slot')->unique());
        $this->assertSame([322,323,324],NodeProbe::find(1)->server_ids);
        $ordinary=User::create(['email'=>Helper::guid().'@example.test','password'=>'test','uuid'=>Helper::guid(),'token'=>Helper::guid(),
            'group_id'=>1,'transfer_enable'=>1073741824,'u'=>0,'d'=>0,'expired_at'=>time()+86400]);
        foreach([336,337] as $backend) {
            $users=ServerService::getAvailableUsers(Server::find($backend))->pluck('id')->all();
            $this->assertContains($ordinary->id,$users);$this->assertNotContains($this->customer->id,$users);
        }
        $users=ServerService::getAvailableUsers(Server::find(335))->pluck('id')->all();
        $this->assertContains($this->customer->id,$users);$this->assertNotContains($ordinary->id,$users);
        foreach(array_diff(\RotateOwnedUs20261028::SOURCES,[322,323,324]) as $id) {
            $node=Server::find($id);$this->assertFalse($node->show);$this->assertSame([],$node->group_ids);
            $this->assertFalse($node->parent->enabled);$this->assertCount(0,ServerService::getAvailableUsers($node->parent));
        }
    }

    public function test_stale_target_rolls_back_all_changes(): void
    {
        DedicatedExit::find(14)->update(['checked_at'=>time()-301]);
        $before=\RotateOwnedUs20261028::snapshot();
        try {\RotateOwnedUs20261028::apply();$this->fail('Must refuse stale evidence');}
        catch(\RuntimeException $e){$this->assertSame('target_not_healthy',$e->getMessage());}
        $this->assertSame($before,\RotateOwnedUs20261028::snapshot());
    }

    public function test_over_capacity_does_not_displace_any_assignment(): void
    {
        foreach(range(1,5) as $n) DedicatedAssignment::create(['plan_id'=>5,'user_id'=>100+$n,'exit_id'=>6,'slot'=>$n]);
        $before=\RotateOwnedUs20261028::snapshot();
        try {\RotateOwnedUs20261028::apply();$this->fail('Must refuse excess occupancy');}
        catch(\RuntimeException $e){$this->assertSame('too_many_assignments',$e->getMessage());}
        $this->assertSame($before,\RotateOwnedUs20261028::snapshot());
    }

    public function test_backup_failure_prevents_mutation(): void
    {
        $before=\RotateOwnedUs20261028::snapshot();
        try {\RotateOwnedUs20261028::apply(fn()=>throw new \RuntimeException('backup_failed'));$this->fail('Backup must succeed first');}
        catch(\RuntimeException $e){$this->assertSame('backup_failed',$e->getMessage());}
        $this->assertSame($before,\RotateOwnedUs20261028::snapshot());
    }
}
