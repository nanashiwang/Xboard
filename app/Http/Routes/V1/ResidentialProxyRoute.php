<?php
namespace App\Http\Routes\V1;
use Illuminate\Contracts\Routing\Registrar;
use App\Http\Controllers\V1\User\ResidentialProxyController;
use App\Http\Controllers\V1\ResidentialProxyAgentController;
use App\Http\Controllers\V1\ResidentialEnrollmentController;
class ResidentialProxyRoute {
    public function map(Registrar $router) {
        $router->get('proxy-agent/installer', [ResidentialEnrollmentController::class, 'installer'])->middleware('throttle:12,1');
        $router->post('proxy-agent/claim', [ResidentialEnrollmentController::class, 'claim'])->middleware('throttle:30,1');
        $router->match(['get', 'post'], 'proxy-agent/ingress', [ResidentialEnrollmentController::class, 'ingress'])->middleware('throttle:60,1');
        $router->post('proxy-agent/sync',[ResidentialProxyAgentController::class,'sync'])->middleware('throttle:120,1');
        foreach(['user'=>['user'],'client'=>['client.auth','client.device']] as $prefix=>$middleware) {
            $router->group(['prefix'=>"$prefix/proxies",'middleware'=>$middleware],function($router) {
                $router->get('/',[ResidentialProxyController::class,'index']);
                $router->get('/detail',[ResidentialProxyController::class,'detail']);
                $router->post('/save',[ResidentialProxyController::class,'save'])->middleware('throttle:15,1');
                $router->post('/update',[ResidentialProxyController::class,'update'])->middleware('throttle:15,1');
            });
        }
    }
}
