<?php

namespace App\Http\Controllers\V1\Desktop;

use App\Exceptions\ClientApiException;
use App\Http\Controllers\Controller;
use App\Http\Requests\Client\RegisterDeviceRequest;
use App\Models\ClientDevice;
use App\Services\Client\ClientDeviceService;
use App\Support\ClientApiResponse;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Str;

class DeviceController extends Controller
{
    public function __construct(private readonly ClientDeviceService $deviceService)
    {
    }

    public function register(RegisterDeviceRequest $request): JsonResponse
    {
        $user = $request->user();
        $accessToken = $user->currentAccessToken();

        if ($accessToken?->client_device_id) {
            $boundDevice = ClientDevice::query()
                ->whereKey($accessToken->client_device_id)
                ->where('user_id', $user->id)
                ->first();
            if (
                !$boundDevice ||
                !hash_equals(
                    $boundDevice->device_id_hash,
                    $this->deviceService->hashDeviceId($request->string('device_id')->toString())
                )
            ) {
                throw new ClientApiException('AUTH_DEVICE_MISMATCH', '当前登录状态与设备不匹配', 401);
            }
        }

        $device = $this->deviceService->register(
            $user,
            $request->validated(),
            $request->ip(),
            false
        );

        if ($accessToken && blank($accessToken->client_device_id)) {
            $accessToken->forceFill([
                'client_device_id' => $device->id,
                'session_id' => $accessToken->session_id ?: (string) Str::ulid(),
            ])->save();
        }

        return ClientApiResponse::success($request, [
            ...$this->deviceService->toArray($device, true),
            'device_id' => $request->string('device_id')->toString(),
            'registered_device_count' => $this->deviceService->registeredCount($user),
            'registered_device_limit' => $this->deviceService->limitFor($user),
        ], '设备已注册');
    }

    public function index(Request $request): JsonResponse
    {
        $currentDevice = $request->attributes->get('client_device');
        return ClientApiResponse::success(
            $request,
            $this->deviceService->list($request->user(), $currentDevice?->id)
        );
    }

    public function destroy(Request $request, string $id): JsonResponse
    {
        $this->deviceService->revoke($request->user(), $id);
        return ClientApiResponse::success($request, true, '设备已解绑');
    }
}
