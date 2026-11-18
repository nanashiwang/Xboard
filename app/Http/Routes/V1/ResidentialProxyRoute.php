<?php
namespace App\Http\Routes\V1;
use Illuminate\Contracts\Routing\Registrar;
use App\Http\Controllers\V1\User\ResidentialProxyController;
use App\Http\Controllers\V1\ResidentialProxyAgentController;
class ResidentialProxyRoute {
    public function map(Registrar $router) {
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
