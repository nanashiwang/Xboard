<?php

namespace App\Http\Controllers\V1\Desktop;

use App\Http\Controllers\Controller;
use App\Http\Requests\Client\BrowserRequest;
use App\Http\Requests\Client\BrowserStartRequest;
use App\Services\Client\ClientBrowserLoginService;
use App\Support\ClientApiResponse;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Auth;

class BrowserLoginController extends Controller
{
    public function __construct(private readonly ClientBrowserLoginService $service) {}

    public function start(BrowserStartRequest $request): JsonResponse
    {
        return ClientApiResponse::success($request, $this->service->start($request->validated('device'), $request->validated('secret')))
            ->header('Cache-Control', 'no-store');
    }
    public function context(BrowserRequest $request): JsonResponse
    {
        return ClientApiResponse::success($request, $this->service->context($request->validated('request_id')))
            ->header('Cache-Control', 'no-store');
    }
    public function poll(BrowserRequest $request): JsonResponse
    {
        return ClientApiResponse::success($request, $this->service->poll($request->validated('request_id'), $request->validated('secret'), $request->ip()))
            ->header('Cache-Control', 'no-store');
    }
    public function cancel(BrowserRequest $request): JsonResponse
    {
        $this->service->cancel($request->validated('request_id'), $request->validated('secret'));
        return ClientApiResponse::success($request, true)->header('Cache-Control', 'no-store');
    }
    public function approve(BrowserRequest $request): JsonResponse
    {
        $user = Auth::guard('sanctum')->user();
        if (!$user) {
            throw new \App\Exceptions\ClientApiException('AUTH_UNAUTHENTICATED', '请先登录官网账号', 401);
        }
        $this->service->approve($request->validated('request_id'), $user, $request->boolean('approved'));
        return ClientApiResponse::success($request, true)->header('Cache-Control', 'no-store');
    }
}
