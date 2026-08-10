<?php

namespace App\Services\Client;

use App\Exceptions\ClientApiException;
use App\Models\ClientDevice;
use App\Models\ClientRefreshToken;
use App\Models\User;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Laravel\Sanctum\PersonalAccessToken;

class ClientAuthService
{
    public function __construct(private readonly ClientDeviceService $deviceService)
    {
    }

    public function login(User $user, array $deviceAttributes, ?string $ip = null): array
    {
        return DB::transaction(function () use ($user, $deviceAttributes, $ip): array {
            $device = $this->deviceService->register($user, $deviceAttributes, $ip);
            $tokens = $this->createTokenPair($user, $device);

            return [
                ...$tokens['payload'],
                'user' => $this->userSummary($user),
                'device' => [
                    ...$this->deviceService->toArray($device, true),
                    'device_id' => $deviceAttributes['device_id'],
                ],
            ];
        });
    }

    public function refresh(string $plainRefreshToken, string $plainDeviceId): array
    {
        [$tokenId, $secret] = $this->parseRefreshToken($plainRefreshToken);

        $result = DB::transaction(function () use ($tokenId, $secret, $plainDeviceId): array {
            $refreshToken = ClientRefreshToken::query()->lockForUpdate()->find($tokenId);
            if (!$refreshToken || !hash_equals($refreshToken->token_hash, hash('sha256', $secret))) {
                return ['error' => 'expired'];
            }

            if ($refreshToken->used_at) {
                $this->revokeFamily($refreshToken->family_id);
                return ['error' => 'reused'];
            }

            if ($refreshToken->revoked_at || $refreshToken->expires_at->isPast()) {
                return ['error' => 'expired'];
            }

            $device = ClientDevice::query()
                ->whereKey($refreshToken->client_device_id)
                ->where('status', ClientDevice::STATUS_ACTIVE)
                ->first();
            $user = User::query()->find($refreshToken->user_id);

            if (!$device || !$user || $user->banned) {
                $this->revokeFamily($refreshToken->family_id);
                return ['error' => 'expired'];
            }

            if (!hash_equals($device->device_id_hash, $this->deviceService->hashDeviceId($plainDeviceId))) {
                return ['error' => 'device'];
            }

            $refreshToken->forceFill(['used_at' => now()])->save();
            if ($refreshToken->personal_access_token_id) {
                PersonalAccessToken::query()->whereKey($refreshToken->personal_access_token_id)->delete();
            }

            $newTokens = $this->createTokenPair($user, $device, $refreshToken->family_id);
            $refreshToken->forceFill([
                'replaced_by_id' => $newTokens['refresh_model']->id,
            ])->save();

            return ['payload' => $newTokens['payload']];
        });

        if (($result['error'] ?? null) === 'reused') {
            throw new ClientApiException(
                'AUTH_REFRESH_REUSED',
                '续期凭证已被重复使用，请重新登录',
                401
            );
        }
        if (($result['error'] ?? null) === 'device') {
            throw new ClientApiException('AUTH_DEVICE_MISMATCH', '设备校验失败，请重新登录', 401);
        }
        if (isset($result['error'])) {
            throw new ClientApiException('AUTH_REFRESH_EXPIRED', '续期凭证已过期，请重新登录', 401);
        }

        return $result['payload'];
    }

    public function logout(?string $authorization, ?string $plainRefreshToken = null): void
    {
        $familyId = null;

        if ($authorization) {
            $plainAccessToken = (string) preg_replace('/^Bearer\s+/i', '', trim($authorization));
            $accessToken = PersonalAccessToken::findToken($plainAccessToken);
            if ($accessToken && in_array('client', $accessToken->abilities ?? [], true)) {
                $familyId = $accessToken->session_id;
                $accessToken->delete();
            }
        }

        if (!$familyId && $plainRefreshToken) {
            try {
                [$tokenId, $secret] = $this->parseRefreshToken($plainRefreshToken);
                $refreshToken = ClientRefreshToken::query()->find($tokenId);
                if ($refreshToken && hash_equals($refreshToken->token_hash, hash('sha256', $secret))) {
                    $familyId = $refreshToken->family_id;
                }
            } catch (ClientApiException) {
                // Logout is idempotent; malformed or expired credentials are treated as already revoked.
            }
        }

        if ($familyId) {
            DB::transaction(fn() => $this->revokeFamily($familyId));
        }
    }

    public function revokeFamily(string $familyId): void
    {
        ClientRefreshToken::query()
            ->where('family_id', $familyId)
            ->whereNull('revoked_at')
            ->update(['revoked_at' => now(), 'updated_at' => now()]);

        PersonalAccessToken::query()
            ->where('tokenable_type', User::class)
            ->where('session_id', $familyId)
            ->delete();
    }

    private function createTokenPair(
        User $user,
        ClientDevice $device,
        ?string $familyId = null
    ): array {
        $accessTtl = max(60, (int) config('client.access_token_ttl', 7200));
        $refreshTtl = max($accessTtl, (int) config('client.refresh_token_ttl', 2592000));
        $familyId ??= (string) Str::ulid();

        $newAccessToken = $user->createToken(
            'desktop:' . $device->id,
            ['client'],
            now()->addSeconds($accessTtl)
        );
        $accessToken = $newAccessToken->accessToken;
        $accessToken->forceFill([
            'client_device_id' => $device->id,
            'session_id' => $familyId,
        ])->save();

        $secret = Str::random(64);
        $refreshToken = ClientRefreshToken::query()->create([
            'user_id' => $user->id,
            'client_device_id' => $device->id,
            'personal_access_token_id' => $accessToken->id,
            'family_id' => $familyId,
            'token_hash' => hash('sha256', $secret),
            'expires_at' => now()->addSeconds($refreshTtl),
        ]);

        return [
            'payload' => [
                'access_token' => $newAccessToken->plainTextToken,
                'refresh_token' => $refreshToken->id . '|' . $secret,
                'token_type' => 'Bearer',
                'expires_in' => $accessTtl,
                'refresh_expires_in' => $refreshTtl,
            ],
            'refresh_model' => $refreshToken,
        ];
    }

    private function parseRefreshToken(string $plainToken): array
    {
        $parts = explode('|', trim($plainToken), 2);
        if (count($parts) !== 2 || strlen($parts[0]) !== 26 || $parts[1] === '') {
            throw new ClientApiException('AUTH_REFRESH_EXPIRED', '续期凭证无效，请重新登录', 401);
        }

        return $parts;
    }

    private function userSummary(User $user): array
    {
        $name = trim((string) $user->getAttribute('name'));
        if ($name === '') {
            $name = strstr($user->email, '@', true) ?: $user->email;
        }

        return [
            'id' => $user->id,
            'name' => $name,
            'avatar_url' => 'https://cdn.v2ex.com/gravatar/' . md5($user->email) . '?s=128&d=identicon',
        ];
    }
}
