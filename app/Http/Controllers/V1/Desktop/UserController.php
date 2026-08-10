<?php

namespace App\Http\Controllers\V1\Desktop;

use App\Http\Controllers\Controller;
use App\Models\Plan;
use App\Models\User;
use App\Services\Client\ClientDeviceService;
use App\Support\ClientApiResponse;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class UserController extends Controller
{
    public function __construct(private readonly ClientDeviceService $deviceService)
    {
    }

    public function profile(Request $request): JsonResponse
    {
        $user = User::query()->with('plan')->findOrFail($request->user()->id);
        $name = trim((string) $user->getAttribute('name'));
        if ($name === '') {
            $name = strstr($user->email, '@', true) ?: $user->email;
        }

        return ClientApiResponse::success($request, [
            'id' => $user->id,
            'email' => $user->email,
            'name' => $name,
            'avatar_url' => 'https://cdn.v2ex.com/gravatar/' . md5($user->email) . '?s=128&d=identicon',
            'account_status' => $user->banned ? 'banned' : 'active',
            'plan' => $user->plan ? [
                'id' => $user->plan->id,
                'name' => $user->plan->name,
                'status' => $this->subscriptionStatus($user),
            ] : null,
            'created_at' => $this->formatTimestamp($user->getRawOriginal('created_at')),
        ]);
    }

    public function subscription(Request $request): JsonResponse
    {
        $user = User::query()->findOrFail($request->user()->id);
        $plan = $user->plan_id ? Plan::query()->find($user->plan_id) : null;
        $upload = max(0, (int) ($user->u ?? 0));
        $download = max(0, (int) ($user->d ?? 0));
        $total = max(0, (int) ($user->transfer_enable ?? 0));
        $used = $upload + $download;
        $status = $this->subscriptionStatus($user);

        return ClientApiResponse::success($request, [
            'status' => $status,
            'unavailable_reason' => $status === 'active' ? null : $status,
            'plan_id' => $plan?->id,
            'plan_name' => $plan?->name,
            'expires_at' => $this->formatTimestamp($user->expired_at),
            'traffic' => [
                'total_bytes' => $total,
                'used_bytes' => $used,
                'upload_bytes' => $upload,
                'download_bytes' => $download,
                'remaining_bytes' => max(0, $total - $used),
                'reset_at' => $this->formatTimestamp($user->getRawOriginal('next_reset_at')),
            ],
            'speed_limit_mbps' => $user->speed_limit !== null ? (int) $user->speed_limit : null,
            'online_ip_limit' => $user->device_limit !== null ? (int) $user->device_limit : null,
            'registered_device_limit' => $this->deviceService->limitFor($user),
            'registered_device_count' => $this->deviceService->registeredCount($user),
        ]);
    }

    private function subscriptionStatus(User $user): string
    {
        if ($user->banned) {
            return 'banned';
        }
        if (!$user->plan_id) {
            return 'no_plan';
        }
        if ($user->expired_at && $user->expired_at <= time()) {
            return 'expired';
        }
        if ($user->getRemainingTraffic() <= 0) {
            return 'traffic_exhausted';
        }
        return 'active';
    }

    private function formatTimestamp(mixed $timestamp): ?string
    {
        if (!$timestamp) {
            return null;
        }
        if ($timestamp instanceof \DateTimeInterface) {
            return $timestamp->setTimezone(new \DateTimeZone('UTC'))->format('Y-m-d\TH:i:s\Z');
        }
        return now('UTC')->setTimestamp((int) $timestamp)->format('Y-m-d\TH:i:s\Z');
    }
}
