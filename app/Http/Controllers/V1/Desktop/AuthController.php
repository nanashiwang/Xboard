<?php

namespace App\Http\Controllers\V1\Desktop;

use App\Exceptions\ClientApiException;
use App\Http\Controllers\Controller;
use App\Http\Requests\Client\LoginRequest;
use App\Http\Requests\Client\RefreshRequest;
use App\Services\Auth\LoginService;
use App\Services\Client\ClientAuthService;
use App\Support\ClientApiResponse;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class AuthController extends Controller
{
    public function __construct(
        private readonly LoginService $loginService,
        private readonly ClientAuthService $clientAuthService
    ) {
    }

    public function login(LoginRequest $request): JsonResponse
    {
        [$success, $result] = $this->loginService->login(
            $request->string('email')->toString(),
            $request->string('password')->toString()
        );

        if (!$success) {
            $httpStatus = (int) ($result[0] ?? 401);
            if ($httpStatus === 429) {
                throw new ClientApiException('RATE_LIMITED', (string) ($result[1] ?? '请求过于频繁'), 429);
            }
            if (($result[1] ?? null) === __('Your account has been suspended')) {
                throw new ClientApiException('ACCOUNT_BANNED', '账号已被封禁', 403);
            }
            throw new ClientApiException('AUTH_INVALID_CREDENTIALS', '账号或密码错误', 401);
        }

        $data = $this->clientAuthService->login(
            $result,
            $request->validated('device'),
            $request->ip()
        );

        return ClientApiResponse::success($request, $data, '登录成功');
    }

    public function refresh(RefreshRequest $request): JsonResponse
    {
        $data = $this->clientAuthService->refresh(
            $request->string('refresh_token')->toString(),
            $request->string('device_id')->toString()
        );

        return ClientApiResponse::success($request, $data, '续期成功');
    }

    public function logout(Request $request): JsonResponse
    {
        $this->clientAuthService->logout(
            $request->header('Authorization'),
            $request->input('refresh_token')
        );

        return ClientApiResponse::success($request, true, '已注销当前设备');
    }
}
