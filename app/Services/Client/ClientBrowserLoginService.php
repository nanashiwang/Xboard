<?php

namespace App\Services\Client;

use App\Exceptions\ClientApiException;
use App\Models\User;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;

class ClientBrowserLoginService
{
    private const TABLE = 'client_browser_logins';

    public function __construct(private readonly ClientAuthService $auth) {}

    public function start(array $device, string $secret): array
    {
        DB::table(self::TABLE)->where('expires_at', '<', now()->subDay())->delete();
        $id = (string) Str::ulid();
        DB::table(self::TABLE)->insert([
            'id' => $id, 'secret_hash' => hash('sha256', $secret),
            'device' => json_encode($device, JSON_THROW_ON_ERROR), 'state' => 'pending',
            'expires_at' => now()->addMinutes(5), 'created_at' => now(), 'updated_at' => now(),
        ]);
        return ['request_id' => $id, 'expires_in' => 300, 'interval' => 3];
    }

    private function current(string $id, bool $lock = false): object
    {
        $query = DB::table(self::TABLE)->where('id', $id);
        $row = ($lock ? $query->lockForUpdate() : $query)->first();
        if (!$row || Carbon::parse($row->expires_at)->lte(now()) || $row->state === 'consumed') {
            throw new ClientApiException('AUTH_BROWSER_EXPIRED', '本次授权已失效，请返回客户端重新登录', 410);
        }
        if ($row->state === 'cancelled') {
            throw new ClientApiException('AUTH_BROWSER_CANCELLED', '本次授权已取消', 410);
        }
        return $row;
    }

    private function verifySecret(object $row, string $secret): void
    {
        if (!hash_equals($row->secret_hash, hash('sha256', $secret))) {
            throw new ClientApiException('AUTH_BROWSER_INVALID', '无效的授权请求', 401);
        }
    }

    public function context(string $id): array
    {
        $row = $this->current($id);
        $device = json_decode($row->device, true, 512, JSON_THROW_ON_ERROR);
        return [
            'phase' => $row->state, 'device_name' => $device['name'],
            'platform' => $device['platform'], 'app_version' => $device['app_version'] ?? '',
            'expires_at' => Carbon::parse($row->expires_at)->toIso8601String(),
        ];
    }

    public function approve(string $id, User $user, bool $approved): void
    {
        if ($user->banned) {
            throw new ClientApiException('ACCOUNT_BANNED', '账号已停用', 403);
        }
        $abilities = $user->currentAccessToken()?->abilities ?? [];
        if (!in_array('*', $abilities, true) || in_array('client', $abilities, true)) {
            throw new ClientApiException('AUTH_TOKEN_INVALID', '请使用官网账号登录后授权', 403);
        }
        DB::transaction(function () use ($id, $user, $approved): void {
            $row = $this->current($id, true);
            if ($row->user_id !== null && (int) $row->user_id !== $user->id) {
                throw new ClientApiException('AUTH_BROWSER_ACCOUNT_MISMATCH', '本次请求已由其他账号处理，请重新发起', 409);
            }
            DB::table(self::TABLE)->where('id', $id)->update([
                'user_id' => $user->id, 'state' => $approved ? 'approved' : 'cancelled', 'updated_at' => now(),
            ]);
        });
    }

    public function poll(string $id, string $secret, ?string $ip): array
    {
        return DB::transaction(function () use ($id, $secret, $ip): array {
            $row = $this->current($id, true);
            $this->verifySecret($row, $secret);
            if ($row->state === 'pending') {
                return ['phase' => 'pending'];
            }
            $user = User::query()->find($row->user_id);
            if (!$user || $user->banned) {
                throw new ClientApiException('ACCOUNT_BANNED', '账号已停用', 403);
            }
            $tokens = $this->auth->login($user, json_decode($row->device, true, 512, JSON_THROW_ON_ERROR), $ip);
            DB::table(self::TABLE)->where('id', $id)->update(['state' => 'consumed', 'updated_at' => now()]);
            return ['phase' => 'complete', 'tokens' => $tokens];
        });
    }

    public function cancel(string $id, string $secret): void
    {
        DB::transaction(function () use ($id, $secret): void {
            $row = $this->current($id, true);
            $this->verifySecret($row, $secret);
            DB::table(self::TABLE)->where('id', $id)->update(['state' => 'cancelled', 'updated_at' => now()]);
        });
    }
}
