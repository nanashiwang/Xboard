<?php

namespace App\Http\Middleware;

use App\Services\Client\ClientDeviceService;
use Closure;
use Illuminate\Http\Request;

class ClientDevice
{
    public function __construct(private readonly ClientDeviceService $deviceService)
    {
    }

    public function handle(Request $request, Closure $next): mixed
    {
        $this->deviceService->assertRequestDevice($request);
        return $next($request);
    }
}
