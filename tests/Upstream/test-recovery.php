<?php
declare(strict_types=1);
// Real Illuminate transactions, isolated SQLite :memory:, no Laravel app bootstrap.
$repository = dirname(__DIR__, 2);
$tools = $repository.'/.docker/upstream';
require $repository.'/vendor/autoload.php';
define('XBOARD_UPSTREAM_RECOVERY_LIBRARY_ONLY', true);
require $tools.'/recovery.php';

use Illuminate\Container\Container;
use Illuminate\Database\Capsule\Manager as Capsule;
use Illuminate\Events\Dispatcher;
use Illuminate\Support\Facades\Facade;
use App\Models\Server;
use XboardUpstreamRecovery\Recovery;
use XboardUpstreamRecovery\Rejected;
use function XboardUpstreamRecovery\{canonical, digest, decode, copyObject};

$container = new Container(); Container::setInstance($container);
$capsule = new Capsule($container); $capsule->addConnection(['driver'=>'sqlite','database'=>':memory:','prefix'=>'']);
$capsule->setEventDispatcher(new Dispatcher($container)); $capsule->setAsGlobal(); $capsule->bootEloquent();
$container->instance('db', $capsule->getDatabaseManager()); Facade::setFacadeApplication($container);
Capsule::schema()->create('v2_server', function($table) {
    $table->integer('id')->primary();
    foreach (['machine_id','parent_id','enabled','show','port','server_port','u','d'] as $field) $table->integer($field)->nullable();
    foreach (['type','name','host','rate','tags','group_ids','route_ids','custom_outbounds','custom_routes','protocol_settings','cert_config','created_at','updated_at'] as $field) $table->text($field)->nullable();
});
$allocation = decode(file_get_contents($GLOBALS['tools'].'/allocation.json'));
$manifest = (object)['machine_id'=>21,'routes'=>array_map(fn($r)=>(object)['key'=>$r->key,'backend_id'=>$r->backend_id,'public_id'=>$r->public_id],$allocation->routes)];
$engine = new Recovery($GLOBALS['tools'].'/allocation.json',$manifest); $passed = 0;
function check(bool $value, string $reason): void { if (!$value) throw new RuntimeException($reason); }
function fixture(string $key='U01', bool $stringSettings=false, bool $visible=true): object {
    global $allocation;
    $scope = array_values(array_filter($allocation->routes,fn($r)=>$r->key===$key))[0];
    $tls = (object)['enabled'=>true,'insecure'=>false,'server_name'=>'approved.test.invalid','utls'=>(object)['enabled'=>true,'fingerprint'=>'chrome']];
    if ($scope->upstream_type !== 'vless') $tls->certificate_public_key_sha256=[base64_encode(str_repeat('a',32))];
    $settings=(object)['type'=>$scope->upstream_type,'server'=>'192.0.2.1','server_port'=>443,'password'=>'test-only-secret','tls'=>$tls,'transport'=>(object)['type'=>'ws','headers'=>(object)[]]];
    $outbound=[(object)['tag'=>'bounded','protocol'=>$scope->upstream_type,'settings'=>$stringSettings?canonical($settings):$settings]];
    $common=['machine_id'=>null,'parent_id'=>null,'enabled'=>1,'show'=>1,'port'=>443,'server_port'=>443,'type'=>'vless','name'=>'fixture','host'=>'ingress.invalid','rate'=>'2.0000', 'group_ids'=>'[1,2,6]','route_ids'=>'[]','custom_routes'=>'[{"outbound":"bounded"}]','protocol_settings'=>'{"inbound":"must-stay"}','cert_config'=>'{}','u'=>100,'d'=>200,'created_at'=>'1','updated_at'=>'1'];
    Capsule::table('v2_server')->insert(array_replace($common,['id'=>$scope->backend_id,'machine_id'=>21,'show'=>0,'tags'=>'["upstream-extension-backend"]','custom_outbounds'=>json_encode($outbound,JSON_THROW_ON_ERROR)]));
    Capsule::table('v2_server')->insert(array_replace($common,['id'=>$scope->public_id,'parent_id'=>$scope->backend_id,'show'=>(int)$visible,'tags'=>'["upstream-extension-public"]','custom_outbounds'=>null]));
    return (object)['key'=>$key,'backend_id'=>$scope->backend_id,'public_id'=>$scope->public_id];
}
function row(object $ids): object {
    $state=Recovery::state(Server::findOrFail($ids->backend_id),Server::findOrFail($ids->public_id));
    $identity=(object)['key'=>$ids->key,'ip'=>'8.8.8.8','port'=>443,'sni'=>'approved.test.invalid','pin'=>$ids->key==='U06'?null:base64_encode(str_repeat('b',32))];
    return (object)['key'=>$ids->key,'backend_id'=>$ids->backend_id,'public_id'=>$ids->public_id,'original_state'=>$state,'original_state_sha256'=>digest($state),'identity'=>$identity,'candidate_digest'=>digest($identity),'expected_sha256'=>digest($state)];
}
function request(array $rows,string $action): object { return (object)['schema'=>1,'action'=>$action,'plan_id'=>Recovery::planDigest($rows),'routes'=>$rows]; }
function routeState(object $r): object { return Recovery::state(Server::findOrFail($r->backend_id),Server::findOrFail($r->public_id)); }
function callAction(object $r,string $action): object { global $engine; $r->expected_sha256=digest(routeState($r)); return $engine->execute(request([$r],$action)); }
function rejected(callable $fn,string $reason): void {
    try {$fn();} catch(Rejected $e) {check($e->getMessage()===$reason,'unexpected rejection '.$e->getMessage().' expected '.$reason);return;}
    throw new RuntimeException('expected rejection '.$reason);
}
function test(string $name,callable $fn): void {
    global $passed; Capsule::table('v2_server')->delete();
    try {$fn();$passed++;echo 'PASS '.$name.PHP_EOL;} catch(Throwable $e) {echo 'FAIL '.$name.' '.get_class($e).' '.$e->getMessage().PHP_EOL;exit(1);}
}

test('full_lifecycle_strict_mutations_and_fail_closed_rollback', function(){
    $r=row(fixture());$old=$r->original_state;
    callAction($r,'withdraw'); check(!routeState($r)->backend->enabled&&!routeState($r)->public->show,'withdraw');
    $answer=callAction($r,'apply_hidden');$new=routeState($r);
    check((bool)$new->backend->enabled&&!$new->public->show,'hidden');
    $before=decode($old->backend->custom_outbounds);$after=decode($new->backend->custom_outbounds);
    $before[0]->settings->server=$r->identity->ip;$before[0]->settings->tls->certificate_public_key_sha256=[$r->identity->pin];
    check(canonical($before)===canonical($after),'only approved server/pin changed');
    foreach(['custom_routes','protocol_settings','group_ids','rate','host','port','type','cert_config'] as $field) check($old->backend->$field===$new->backend->$field,'preserved '.$field);
    check(!str_contains(canonical($answer),'test-only-secret')&&!str_contains(canonical($answer),'approved.test.invalid'),'redacted output');
    callAction($r,'publish');check((bool)routeState($r)->public->show,'publish');
    callAction($r,'rollback');check(routeState($r)->backend->custom_outbounds===$old->backend->custom_outbounds&&!routeState($r)->backend->enabled&&!routeState($r)->public->show,'rollback keeps withdrawn');
});
test('serialized_settings_and_empty_objects_preserved',function(){
    $r=row(fixture('U01',true));callAction($r,'withdraw');callAction($r,'apply_hidden');
    $entry=decode(routeState($r)->backend->custom_outbounds)[0];check(is_string($entry->settings),'settings string');
    check(is_object(decode($entry->settings)->transport->headers),'empty object kept');
});
test('ca_vless_changes_ip_without_adding_pin',function(){
    $r=row(fixture('U06'));callAction($r,'withdraw');callAction($r,'apply_hidden');
    $tls=decode(routeState($r)->backend->custom_outbounds)[0]->settings->tls;
    check($tls->insecure===false&&!property_exists($tls,'certificate_public_key_sha256'),'CA remains');
});
test('ca_pin_injection_rejected',function(){global $engine;
    $r=row(fixture('U06'));$r->identity->pin=base64_encode(str_repeat('c',32));$r->candidate_digest=digest($r->identity);
    rejected(fn()=>$engine->execute(request([$r],'withdraw')),'ca_boundary_changed');
});
test('omitted_insecure_preserves_strict_default_for_pinned_and_ca',function(){
    foreach (['U01','U06'] as $key) {
        $ids=fixture($key);$stored=Server::findOrFail($ids->backend_id);
        $outbound=decode($stored->getRawOriginal('custom_outbounds'));unset($outbound[0]->settings->tls->insecure);
        Capsule::table('v2_server')->where('id',$ids->backend_id)->update(['custom_outbounds'=>canonical($outbound)]);
        $r=row($ids);callAction($r,'withdraw');callAction($r,'apply_hidden');callAction($r,'publish');
        $tls=decode(routeState($r)->backend->custom_outbounds)[0]->settings->tls;
        check(!property_exists($tls,'insecure'),'preserve omitted strict default');
        check($key!=='U06'||!property_exists($tls,'certificate_public_key_sha256'),'CA policy preserved');
    }
});
test('null_or_non_boolean_insecure_never_uses_omitted_default',function(){global $engine;
    $r=row(fixture());
    foreach ([null,true,0,1,'false','true',[],(object)[]] as $unsafe) {
        $outbound=decode($r->original_state->backend->custom_outbounds);$outbound[0]->settings->tls->insecure=$unsafe;
        $r->original_state->backend->custom_outbounds=canonical($outbound);$r->original_state_sha256=digest($r->original_state);
        rejected(fn()=>$engine->execute(request([$r],'withdraw')),'tls_boundary_changed');
    }
});
test('mixed_batch_hash_drift_rolls_back_prior_update',function(){global $engine;
    $a=row(fixture('U01'));$b=row(fixture('U02'));$before=digest(routeState($a));$b->expected_sha256=str_repeat('0',64);
    rejected(fn()=>$engine->execute(request([$a,$b],'withdraw')),'concurrent_config_drift');check(digest(routeState($a))===$before,'whole batch rolled back');
});
test('concurrent_inbound_or_group_change_is_not_overwritten',function(){global $engine;
    $r=row(fixture());Capsule::table('v2_server')->where('id',$r->backend_id)->update(['protocol_settings'=>'{"new":"concurrent"}']);
    rejected(fn()=>$engine->execute(request([$r],'withdraw')),'concurrent_config_drift');
    check(routeState($r)->backend->protocol_settings==='{"new":"concurrent"}','concurrent field preserved');
});
test('runtime_traffic_changes_do_not_block_or_get_restored',function(){
    $r=row(fixture());Capsule::table('v2_server')->where('id',$r->backend_id)->update(['u'=>901,'d'=>902]);
    callAction($r,'withdraw');callAction($r,'apply_hidden');callAction($r,'rollback');
    $raw=Server::findOrFail($r->backend_id)->getRawOriginal();check($raw['u']===901&&$raw['d']===902,'traffic retained');
});
test('unknown_request_and_identity_fields_rejected',function(){global $engine;
    $r=row(fixture());$q=request([$r],'withdraw');$q->insecure=true;
    rejected(fn()=>$engine->execute($q),'unexpected_fields');
    $r->identity->password='replacement-not-allowed';$r->candidate_digest=digest($r->identity);
    rejected(fn()=>$engine->execute(request([$r],'withdraw')),'unexpected_fields');
});
test('unapproved_scope_ids_and_duplicates_rejected',function(){global $engine;
    $r=row(fixture());$unknown=copyObject($r);$unknown->key='U42';
    rejected(fn()=>$engine->execute(request([$unknown],'withdraw')),'unapproved_key');
    $wrong=copyObject($r);$wrong->backend_id=148;
    rejected(fn()=>$engine->execute(request([$wrong],'withdraw')),'mapping_changed');
    rejected(fn()=>$engine->execute(request([$r,$r],'withdraw')),'route_invalid');
});
test('candidate_and_plan_digest_tampering_rejected',function(){global $engine;
    $r=row(fixture());$r->candidate_digest=str_repeat('0',64);
    rejected(fn()=>$engine->execute(request([$r],'withdraw')),'candidate_digest_mismatch');
    $r->candidate_digest=digest($r->identity);$q=request([$r],'withdraw');$q->plan_id=str_repeat('0',64);
    rejected(fn()=>$engine->execute($q),'plan_digest_mismatch');
});
test('sni_hostname_and_malformed_pin_rejected',function(){global $engine;
    $r=row(fixture());$r->identity->sni='different.invalid';$r->candidate_digest=digest($r->identity);
    rejected(fn()=>$engine->execute(request([$r],'withdraw')),'tls_boundary_changed');
    $r->identity->sni='approved.test.invalid';$r->identity->ip='dns-rotation.invalid';$r->candidate_digest=digest($r->identity);
    rejected(fn()=>$engine->execute(request([$r],'withdraw')),'invalid_identity');
    $r->identity->ip='8.8.8.8';$r->identity->pin='not-a-pin';$r->candidate_digest=digest($r->identity);
    rejected(fn()=>$engine->execute(request([$r],'withdraw')),'pin_shape_invalid');
});
test('unsafe_existing_tls_and_multiple_pins_rejected',function(){global $engine;
    $r=row(fixture());$o=decode($r->original_state->backend->custom_outbounds);$o[0]->settings->tls->insecure=true;
    $r->original_state->backend->custom_outbounds=canonical($o);$r->original_state_sha256=digest($r->original_state);
    rejected(fn()=>$engine->execute(request([$r],'withdraw')),'tls_boundary_changed');
    $o[0]->settings->tls->insecure=false;$o[0]->settings->tls->certificate_public_key_sha256[]=base64_encode(str_repeat('z',32));
    $r->original_state->backend->custom_outbounds=canonical($o);$r->original_state_sha256=digest($r->original_state);
    rejected(fn()=>$engine->execute(request([$r],'withdraw')),'pin_shape_invalid');
});
test('exact_stage_required_even_with_current_hash',function(){global $engine;
    $r=row(fixture());rejected(fn()=>$engine->execute(request([$r],'apply_hidden')),'phase_state_mismatch');
    callAction($r,'withdraw');$r->expected_sha256=digest(routeState($r));
    rejected(fn()=>$engine->execute(request([$r],'publish')),'phase_state_mismatch');
});
test('original_hidden_flag_not_promoted_on_publish',function(){
    $r=row(fixture('U01',false,false));callAction($r,'withdraw');callAction($r,'apply_hidden');callAction($r,'publish');check(!routeState($r)->public->show,'original hidden kept');
});
test('rollback_refuses_concurrent_config_and_preserves_changes',function(){global $engine;
    $r=row(fixture());callAction($r,'withdraw');callAction($r,'apply_hidden');$r->expected_sha256=digest(routeState($r));
    Capsule::table('v2_server')->where('id',$r->backend_id)->update(['group_ids'=>'[5]']);
    rejected(fn()=>$engine->execute(request([$r],'rollback')),'concurrent_config_drift');check(routeState($r)->backend->group_ids==='[5]','new group retained');
});
test('private_snapshot_explicit_scope_and_mapping_guards',function(){global $engine;
    $r=row(fixture());$snapshot=$engine->privateSnapshot((object)['schema'=>1,'keys'=>['U01']]);
    check($snapshot->private&&$snapshot->routes[0]->state_sha256===digest(routeState($r)),'snapshot hash');
    rejected(fn()=>$engine->privateSnapshot((object)['schema'=>1,'keys'=>['U01'],'extra'=>'no']),'unexpected_fields');
    Capsule::table('v2_server')->where('id',$r->public_id)->update(['parent_id'=>148]);
    rejected(fn()=>$engine->privateSnapshot((object)['schema'=>1,'keys'=>['U01']]),'mapping_changed');
});
test('manifest_and_allocation_are_fixed_scope',function(){global $manifest;
    $bad=copyObject($manifest);$bad->routes[0]->backend_id=148;
    rejected(fn()=>new Recovery($GLOBALS['tools'].'/allocation.json',$bad),'scope_invalid');
});
test('no_candidate_allows_only_withdraw_and_fail_closed_rollback',function(){global $engine;
    $r=row(fixture('U06'));$r->identity=null;$r->candidate_digest=digest(null);
    callAction($r,'withdraw');check(!routeState($r)->backend->enabled&&!routeState($r)->public->show,'unrecoverable withdrawn');
    $r->expected_sha256=digest(routeState($r));
    rejected(fn()=>$engine->execute(request([$r],'apply_hidden')),'no_approved_candidate');
    rejected(fn()=>$engine->execute(request([$r],'publish')),'no_approved_candidate');
    callAction($r,'rollback');check(!routeState($r)->backend->enabled&&!routeState($r)->public->show,'remains closed');
});
test('canonical_matches_python_utf8_raw_json_and_float_contract',function(){
    $value=(object)['空'=>(object)['z'=>1.0,'a'=>[]],'raw'=>'{"ratio":1,"标签":"/"}','text'=>"x\u{2028}y",'nil'=>null];
    check(digest($value)==='ac6b15739b9e9fa9df06903646e9030fbd39f2a2c807b7b9e00dc79abeff20e0','Python canonical SHA agreement');
});
test('only_global_unicast_candidate_ips_accepted',function(){
    foreach(['8.8.8.8','1.1.1.1','2606:4700:4700::1111'] as $ip) check(Recovery::globalIp($ip),'global accepted');
    foreach(['0.0.0.0','10.1.2.3','127.0.0.1','169.254.169.254','172.16.0.1','192.168.1.1','192.0.2.1','198.51.100.1','203.0.113.1','198.18.0.1','100.64.0.1','224.0.0.1','240.0.0.1','255.255.255.255','::','::1','fc00::1','fe80::1','2001:db8::1','ff02::1','::ffff:127.0.0.1'] as $ip) check(!Recovery::globalIp($ip),'non-global rejected');
});
test('snapshot_php_state_canonical_agrees_with_recovery',function(){
    $source=file_get_contents($GLOBALS['tools'].'/snapshot.php');
    $start=strpos($source,'function upstream_prepare_stable_value(');$end=strpos($source,"\ntry {",$start);
    check($start!==false&&$end!==false,'snapshot pure function found');
    $pure=substr($source,$start,$end-$start);check(!str_contains($pure,'require')&&!str_contains($pure,'bootstrap'),'only reviewed pure function extracted');
    eval($pure);
    $r=row(fixture());$state=routeState($r);$state->backend->rate=1.0;$state->backend->name="固定/汉字\u{2028}";
    $array=json_decode(canonical($state),true,512,JSON_THROW_ON_ERROR);
    $snapshotHash=hash('sha256',json_encode(upstream_prepare_stable_value($array),JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_LINE_TERMINATORS|JSON_PRESERVE_ZERO_FRACTION));
    check($snapshotHash===digest($state),'actual snapshot function state hash match');
});
test('complete_python_payload_plan_digest_matches_php',function(){global $engine;
    $request=decode(file_get_contents(__DIR__.'/example-withdraw.test.json'));
    check(Recovery::planDigest($request->routes)===$request->plan_id,'Python plan_id matches PHP');
    check(digest($request->routes[0]->original_state)===$request->routes[0]->original_state_sha256,'Python state SHA matches PHP');
    check(digest($request->routes[0]->identity)===$request->routes[0]->candidate_digest,'Python identity SHA matches PHP');
    $engine->derivedStates($request->routes[0]);
});
echo 'RESULT '.json_encode(['passed'=>$passed,'failed'=>0,'database'=>':memory:','production_bootstrap'=>false]).PHP_EOL;
