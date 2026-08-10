<?php

namespace App\Http\Middleware;

use App\Exceptions\ClientApiException;
use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Auth;

class ClientAuthenticate
{
    public function handle(Request $request, Closure $next): mixed
    {
        $guard = Auth::guard('sanctum');
        if (!$guard->check()) {
            throw new ClientApiException('AUTH_TOKEN_EXPIRED', '登录状态已过期', 401);
        }

        $user = $guard->user();
        $accessToken = $user?->currentAccessToken();
        if (!$accessToken || !in_array('client', $accessToken->abilities ?? [], true)) {
            throw new ClientApiException('AUTH_TOKEN_INVALID', '登录凭证不适用于桌面客户端', 401);
        }

        $request->setUserResolver(fn() => $user);
        return $next($request);
    }
}
