<?php

namespace App\Http\Routes\V1;

use App\Http\Controllers\V1\Desktop\AuthController;
use App\Http\Controllers\V1\Desktop\ClientController;
use App\Http\Controllers\V1\Desktop\DeviceController;
use App\Http\Controllers\V1\Desktop\NoticeController;
use App\Http\Controllers\V1\Desktop\UserController;
use Illuminate\Contracts\Routing\Registrar;

class DesktopRoute
{
    public function map(Registrar $router): void
    {
        $router->group(['prefix' => 'auth'], function ($router): void {
            $router->post('/login', [AuthController::class, 'login'])->middleware('throttle:10,1');
            $router->post('/refresh', [AuthController::class, 'refresh'])->middleware('throttle:30,1');
            $router->post('/logout', [AuthController::class, 'logout'])->middleware('throttle:30,1');
        });

        $router->get('/client/version', [ClientController::class, 'version'])->middleware('throttle:60,1');
        $router->get('/client/config/download/{grant}', [ClientController::class, 'download'])
            ->middleware('throttle:60,1')
            ->name('desktop.client.config.download');
        $router->get('/notices', [NoticeController::class, 'index'])->middleware('throttle:60,1');

        $router->group(['middleware' => 'client.auth'], function ($router): void {
            $router->post('/devices/register', [DeviceController::class, 'register'])
                ->middleware('throttle:20,1');

            $router->group(['middleware' => 'client.device'], function ($router): void {
                $router->get('/user/profile', [UserController::class, 'profile']);
                $router->get('/user/subscription', [UserController::class, 'subscription']);
                $router->get('/client/config', [ClientController::class, 'config'])->middleware('throttle:30,1');
                $router->get('/devices', [DeviceController::class, 'index']);
                $router->delete('/devices/{id}', [DeviceController::class, 'destroy'])
                    ->middleware('throttle:30,1');
            });
        });
    }
}
