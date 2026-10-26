<?php
declare(strict_types=1);
require dirname(__DIR__, 2).'/vendor/autoload.php';
define('XBOARD_UPSTREAM_GUARD_APPLY_LIBRARY_ONLY',true);
require dirname(__DIR__, 2).'/.docker/upstream/guard-apply.php';
use Illuminate\Container\Container;
use Illuminate\Database\Capsule\Manager as Capsule;
use Illuminate\Events\Dispatcher;
use Illuminate\Support\Facades\Facade;
use App\Models\Server;
use XboardUpstreamGuard\Rejected;
use function XboardUpstreamGuard\{validate,withdraw};
$container=new Container();Container::setInstance($container);
$capsule=new Capsule($container);$capsule->addConnection(['driver'=>'sqlite','database'=>':memory:','prefix'=>'']);
$capsule->setEventDispatcher(new Dispatcher($container));$capsule->setAsGlobal();$capsule->bootEloquent();
$container->instance('db',$capsule->getDatabaseManager());Facade::setFacadeApplication($container);
Capsule::schema()->create('v2_server',function($t){$t->integer('id')->primary();foreach(['machine_id','parent_id','enabled','show'] as $f)$t->integer($f)->nullable();foreach(['type','tags','group_ids','rate','custom_outbounds','custom_routes','protocol_settings','created_at','updated_at'] as $f)$t->text($f)->nullable();});
$manifest=['machine_id'=>21,'routes'=>array_map(fn($n)=>['key'=>sprintf('U%02d',$n),'backend_id'=>357+2*$n,'public_id'=>358+2*$n],range(1,41))];$passed=0;
function check(bool $ok,string $why):void{if(!$ok)throw new RuntimeException($why);}
function request(array $numbers=[1]):array{return ['schema'=>1,'machine_id'=>21,'routes'=>array_map(fn($n)=>['key'=>sprintf('U%02d',$n),'backend_id'=>357+2*$n,'public_id'=>358+2*$n,'reason'=>'runtime_public_key_mismatch'],$numbers)];}
function fixture(int $n=1):void{$common=['machine_id'=>null,'parent_id'=>null,'enabled'=>1,'show'=>1,'type'=>'vless','tags'=>'[]','group_ids'=>'[1,2]','rate'=>'2.0000','custom_outbounds'=>'[{"secret":"test-only-secret"}]','custom_routes'=>'[{"tag":"keep"}]','protocol_settings'=>'{"keep":true}','created_at'=>'1','updated_at'=>'1'];Capsule::table('v2_server')->insert(array_replace($common,['id'=>357+2*$n,'machine_id'=>21,'show'=>0,'tags'=>'["upstream-extension-backend"]']));Capsule::table('v2_server')->insert(array_replace($common,['id'=>358+2*$n,'parent_id'=>357+2*$n,'tags'=>'["upstream-extension-public"]']));}
function state(int $id):array{return Server::findOrFail($id)->getRawOriginal();}
function rejects(callable $fn):void{try{$fn();}catch(Rejected $e){return;}throw new RuntimeException('not rejected');}
function test(string $name,callable $fn):void{global $passed;Capsule::table('v2_server')->delete();try{$fn();$passed++;echo "PASS $name\n";}catch(Throwable $e){echo 'FAIL '.$name.' '.get_class($e).' '.$e->getMessage().PHP_EOL;exit(1);}}

test('bounded_withdraw_preserves_configuration_and_unrelated_nodes',function()use($manifest){fixture();fixture(2);$before=state(359);$other=state(361);$result=withdraw($manifest,request());check($result===['withdrawn'=>['U01']],'receipt');check(!state(359)['enabled']&&!state(360)['show'],'closed');foreach(['group_ids','rate','custom_outbounds','custom_routes','protocol_settings','type','machine_id'] as $field)check(state(359)[$field]===$before[$field],'preserved');check(state(361)===$other,'other node unchanged');check(!str_contains(json_encode($result),'test-only-secret'),'redacted');});
test('repeat_withdraw_never_reenables',function()use($manifest){fixture();withdraw($manifest,request());check(withdraw($manifest,request())===['withdrawn'=>[]],'idempotent');check(!state(359)['enabled']&&!state(360)['show'],'remains closed');});
test('mixed_batch_parent_drift_rolls_back_first_row',function()use($manifest){fixture();fixture(2);Capsule::table('v2_server')->where('id',362)->update(['parent_id'=>148]);$before=state(359);rejects(fn()=>withdraw($manifest,request([1,2])));check(state(359)===$before&&state(360)['show']===1,'whole batch rollback');});
test('machine_and_both_tags_keep_original_boundaries',function()use($manifest){foreach([[359,'machine_id',22],[359,'tags','[]'],[360,'tags','[]']] as [$id,$field,$value]){Capsule::table('v2_server')->delete();fixture();Capsule::table('v2_server')->where('id',$id)->update([$field=>$value]);rejects(fn()=>withdraw($manifest,request()));check(state(359)['enabled']===1&&state(360)['show']===1,'not mutated');}});
test('manifest_requires_complete_fixed_scope_and_unique_keys',function()use($manifest){$bad=$manifest;array_pop($bad['routes']);rejects(fn()=>validate($bad,request()));$bad=$manifest;$bad['routes'][40]=$bad['routes'][0];rejects(fn()=>validate($bad,request()));$bad=$manifest;$bad['routes'][0]['backend_id']=148;rejects(fn()=>validate($bad,request()));$bad=$manifest;$bad['machine_id']=22;rejects(fn()=>validate($bad,request()));});
test('strict_request_schema_rejects_new_fields_and_missing_version',function()use($manifest){$bad=request();$bad['password']='test-only';rejects(fn()=>validate($manifest,$bad));$bad=request();unset($bad['schema']);rejects(fn()=>validate($manifest,$bad));$bad=request();$bad['routes'][0]['enabled']=true;rejects(fn()=>validate($manifest,$bad));$bad=request();$bad['machine_id']=22;rejects(fn()=>validate($manifest,$bad));});
test('request_ids_types_reason_and_duplicates_are_rejected',function()use($manifest){foreach([['backend_id',148],['backend_id','359'],['public_id',true],['key','U42'],['reason','enable']] as [$field,$value]){$bad=request();$bad['routes'][0][$field]=$value;rejects(fn()=>validate($manifest,$bad));}$bad=request([1,1]);rejects(fn()=>validate($manifest,$bad));});
test('empty_request_cannot_be_mistaken_for_valid_recovery',function()use($manifest){rejects(fn()=>validate($manifest,request([])));});
echo json_encode(['passed'=>$passed,'failed'=>0,'database'=>':memory:','production_bootstrap'=>false],JSON_THROW_ON_ERROR).PHP_EOL;
