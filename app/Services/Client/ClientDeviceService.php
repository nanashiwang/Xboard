<?php

namespace App\Services\Client;

use App\Exceptions\ClientApiException;
use App\Models\ClientDevice;
use App\Models\ClientRefreshToken;
use App\Models\Plan;
use App\Models\User;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Laravel\Sanctum\PersonalAccessToken;

class ClientDeviceService
{
    public function register(
        User $user,
        array $attributes,
        ?string $ip = null,
        bool $allowReactivation = true
    ): ClientDevice
    {
        return DB::transaction(function () use ($user, $attributes, $ip, $allowReactivation): ClientDevice {
            $lockedUser = User::query()->whereKey($user->id)->lockForUpdate()->firstOrFail();
            $deviceHash = $this->hashDeviceId($attributes['device_id']);
            $device = ClientDevice::query()
                ->where('user_id', $lockedUser->id)
                ->where('device_id_hash', $deviceHash)
                ->lockForUpdate()
                ->first();

            if ($device?->status === ClientDevice::STATUS_REVOKED && !$allowReactivation) {
                throw new ClientApiException('DEVICE_REVOKED', '当前设备已解绑，请重新登录', 401);
            }

            if (!$device || $device->status !== ClientDevice::STATUS_ACTIVE) {
                $this->assertWithinLimit($lockedUser, $device?->id);
            }

            $now = now();
            $values = [
                'name' => $attributes['name'],
                'platform' => strtolower($attributes['platform']),
                'architecture' => isset($attributes['architecture'])
                    ? strtolower($attributes['architecture'])
                    : null,
                'os_version' => $attributes['os_version'] ?? null,
                'app_version' => $attributes['app_version'] ?? null,
                'status' => ClientDevice::STATUS_ACTIVE,
                'last_ip' => $ip,
                'last_seen_at' => $now,
                'revoked_at' => null,
            ];

            if ($device) {
                $device->fill($values)->save();
                return $device->refresh();
            }

            return ClientDevice::query()->create([
                ...$values,
                'user_id' => $lockedUser->id,
                'device_id_hash' => $deviceHash,
                'first_ip' => $ip,
                'registered_at' => $now,
            ]);
        });
    }

    public function assertRequestDevice(Request $request): ClientDevice
    {
        $user = $request->user();
        $accessToken = $user?->currentAccessToken();
        $deviceId = trim((string) $request->header('X-Device-ID'));

        if (!$user || !$accessToken) {
            throw new ClientApiException('AUTH_TOKEN_EXPIRED', '登录状态已过期', 401);
        }
        if ($deviceId === '') {
            throw new ClientApiException('DEVICE_ID_REQUIRED', '缺少设备标识', 400);
        }
        if (blank($accessToken->client_device_id)) {
            throw new ClientApiException('DEVICE_NOT_REGISTERED', '当前登录状态未绑定设备', 401);
        }

        $device = ClientDevice::query()
            ->whereKey($accessToken->client_device_id)
            ->where('user_id', $user->id)
            ->where('status', ClientDevice::STATUS_ACTIVE)
            ->first();

        if (!$device || !hash_equals($device->device_id_hash, $this->hashDeviceId($deviceId))) {
            throw new ClientApiException('AUTH_DEVICE_MISMATCH', '设备校验失败，请重新登录', 401);
        }

        if (!$device->last_seen_at || $device->last_seen_at->lt(now()->subMinutes(5))) {
            $device->forceFill([
                'last_seen_at' => now(),
                'last_ip' => $request->ip(),
                'app_version' => $request->header('X-Client-Version', $device->app_version),
            ])->saveQuietly();
        }

        $request->attributes->set('client_device', $device);
        return $device;
    }

    public function findActiveForUser(User $user, string $deviceId): ?ClientDevice
    {
        return ClientDevice::query()
            ->where('user_id', $user->id)
            ->where('device_id_hash', $this->hashDeviceId($deviceId))
            ->where('status', ClientDevice::STATUS_ACTIVE)
            ->first();
    }

    public function list(User $user, ?string $currentDeviceId = null): array
    {
        $items = ClientDevice::query()
            ->where('user_id', $user->id)
            ->where('status', ClientDevice::STATUS_ACTIVE)
            ->orderByDesc('last_seen_at')
            ->get()
            ->map(fn(ClientDevice $device) => $this->toArray($device, $device->id === $currentDeviceId))
            ->values()
            ->all();

        return [
            'items' => $items,
            'registered_device_count' => count($items),
            'registered_device_limit' => $this->limitFor($user),
        ];
    }

    public function revoke(User $user, string $deviceId): void
    {
        DB::transaction(function () use ($user, $deviceId): void {
            $device = ClientDevice::query()
                ->whereKey($deviceId)
                ->where('user_id', $user->id)
                ->lockForUpdate()
                ->first();

            if (!$device || $device->status === ClientDevice::STATUS_REVOKED) {
                return;
            }

            $device->forceFill([
                'status' => ClientDevice::STATUS_REVOKED,
                'revoked_at' => now(),
            ])->save();

            ClientRefreshToken::query()
                ->where('client_device_id', $device->id)
                ->whereNull('revoked_at')
                ->update(['revoked_at' => now(), 'updated_at' => now()]);

            PersonalAccessToken::query()
                ->where('tokenable_type', User::class)
                ->where('tokenable_id', $user->id)
                ->where('client_device_id', $device->id)
                ->delete();
        });
    }

    public function registeredCount(User $user): int
    {
        return ClientDevice::query()
            ->where('user_id', $user->id)
            ->where('status', ClientDevice::STATUS_ACTIVE)
            ->count();
    }

    public function limitFor(User $user): int
    {
        $userLimit = $user->getAttribute('registered_device_limit');
        if ($userLimit !== null) {
            return max(0, (int) $userLimit);
        }

        $planLimit = $user->plan_id
            ? Plan::query()->whereKey($user->plan_id)->value('registered_device_limit')
            : null;

        return max(0, (int) ($planLimit ?? admin_setting(
            'client_registered_device_limit',
            config('client.registered_device_limit', 5)
        )));
    }

    public function toArray(ClientDevice $device, bool $current = false): array
    {
        return [
            'id' => $device->id,
            'name' => $device->name,
            'platform' => $device->platform,
            'architecture' => $device->architecture,
            'os_version' => $device->os_version,
            'app_version' => $device->app_version,
            'last_ip' => $this->maskIp($device->last_ip),
            'last_seen_at' => $device->last_seen_at?->utc()->format('Y-m-d\TH:i:s\Z'),
            'registered_at' => $device->registered_at?->utc()->format('Y-m-d\TH:i:s\Z'),
            'current' => $current,
        ];
    }

    public function hashDeviceId(string $deviceId): string
    {
        $key = (string) config('app.key');
        return hash_hmac('sha256', strtolower(trim($deviceId)), $key);
    }

    private function assertWithinLimit(User $user, ?string $ignoredDeviceId = null): void
    {
        $limit = $this->limitFor($user);
        if ($limit <= 0) {
            return;
        }

        $query = ClientDevice::query()
            ->where('user_id', $user->id)
            ->where('status', ClientDevice::STATUS_ACTIVE);
        if ($ignoredDeviceId) {
            $query->where('id', '!=', $ignoredDeviceId);
        }

        $count = $query->count();
        if ($count < $limit) {
            return;
        }

        $devices = ClientDevice::query()
            ->where('user_id', $user->id)
            ->where('status', ClientDevice::STATUS_ACTIVE)
            ->orderByDesc('last_seen_at')
            ->limit(10)
            ->get()
            ->map(fn(ClientDevice $device) => $this->toArray($device))
            ->values()
            ->all();

        throw new ClientApiException('DEVICE_LIMIT_REACHED', '已达到客户端设备数量上限', 409, [
            'limit' => $limit,
            'current_count' => $count,
            'devices' => $devices,
        ]);
    }

    private function maskIp(?string $ip): ?string
    {
        if (!$ip) {
            return null;
        }
        if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
            $parts = explode('.', $ip);
            $parts[3] = '*';
            return implode('.', $parts);
        }
        if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6)) {
            $parts = explode(':', $ip);
            return implode(':', array_slice($parts, 0, 4)) . '::*';
        }
        return null;
    }
}
