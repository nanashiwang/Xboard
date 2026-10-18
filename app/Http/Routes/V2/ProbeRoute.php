<?php
namespace App\Http\Routes\V2;

use App\Http\Controllers\V2\Probe\AgentController;
use App\Http\Controllers\V2\Admin\Probe\ProbeController;
use App\Http\Middleware\NodeProbeAuth;
use Illuminate\Contracts\Routing\Registrar;

class ProbeRoute
{
    public function map(Registrar $router)
    {
        $router->group(['prefix' => 'probe', 'middleware' => ['throttle:240,1', NodeProbeAuth::class]], function ($r) {
            $r->post('config', [AgentController::class, 'configuration']);
            $r->post('report', [AgentController::class, 'report']);
            $r->post('ingress-report', [AgentController::class, 'ingressReport']);
        });
        $path = admin_setting('secure_path', admin_setting('frontend_admin_path', hash('crc32b', config('app.key'))));
        $router->group(['prefix' => $path . '/node-probes', 'middleware' => ['admin', 'log']], function ($r) {
            $r->get('/', [ProbeController::class, 'index']);
            $r->post('/', [ProbeController::class, 'create']);
            $r->post('/{id}/enabled', [ProbeController::class, 'enabled']);
            $r->post('/{id}/rotate', [ProbeController::class, 'rotate']);
            $r->get('/{id}/history/{server}', [ProbeController::class, 'history']);
            $r->get('/{id}/ingress-history/{ingress}', [ProbeController::class, 'ingressHistory']);
        });
    }
}
