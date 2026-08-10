<?php

namespace Tests\Feature\Desktop;

use App\Models\ClientDevice;
use App\Models\ClientRefreshToken;
use App\Models\Plan;
use App\Models\User;
use App\Services\AuthService;
use App\Utils\Helper;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class ClientAuthTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        admin_setting(['password_limit_enable' => 0]);
    }

    public function test_login_registers_device_and_returns_token_pair(): void
    {
        $user = $this->createUser();
        $deviceId = '9dfc6298-69c4-4f4d-a42e-0ca109b76440';

        $response = $this->postJson('/api/v1/auth/login', $this->loginPayload($deviceId));

        $response->assertOk()
            ->assertJsonPath('code', 'OK')
            ->assertJsonPath('data.user.id', $user->id)
            ->assertJsonPath('data.device.device_id', $deviceId)
            ->assertJsonStructure(['data' => [
                'access_token', 'refresh_token', 'expires_in', 'refresh_expires_in',
            ]]);

        $this->assertDatabaseCount('client_devices', 1);
        $this->assertDatabaseCount('client_refresh_tokens', 1);
        $this->assertDatabaseCount('personal_access_tokens', 1);
    }

    public function test_refresh_rotates_token_and_reuse_revokes_family(): void
    {
        $this->createUser();
        $deviceId = '9dfc6298-69c4-4f4d-a42e-0ca109b76440';
        $login = $this->postJson('/api/v1/auth/login', $this->loginPayload($deviceId))->json('data');

        $refresh = $this->postJson('/api/v1/auth/refresh', [
            'refresh_token' => $login['refresh_token'],
            'device_id' => $deviceId,
        ])->assertOk()->json('data');

        $this->assertNotSame($login['refresh_token'], $refresh['refresh_token']);

        $this->postJson('/api/v1/auth/refresh', [
            'refresh_token' => $login['refresh_token'],
            'device_id' => $deviceId,
        ])->assertStatus(401)->assertJsonPath('code', 'AUTH_REFRESH_REUSED');

        $this->withHeaders([
            'Authorization' => 'Bearer ' . $refresh['access_token'],
            'X-Device-ID' => $deviceId,
        ])->getJson('/api/v1/user/profile')
            ->assertStatus(401)
            ->assertJsonPath('code', 'AUTH_TOKEN_EXPIRED');

        $this->assertSame(0, ClientRefreshToken::query()->whereNull('revoked_at')->count());
    }

    public function test_device_limit_rejects_new_installation(): void
    {
        $this->createUser(['registered_device_limit' => 1]);

        $this->postJson('/api/v1/auth/login', $this->loginPayload(
            '9dfc6298-69c4-4f4d-a42e-0ca109b76440'
        ))->assertOk();

        $this->postJson('/api/v1/auth/login', $this->loginPayload(
            '2afc6298-69c4-4f4d-a42e-0ca109b76441'
        ))->assertStatus(409)
            ->assertJsonPath('code', 'DEVICE_LIMIT_REACHED')
            ->assertJsonPath('error.details.limit', 1);

        $this->assertSame(1, ClientDevice::query()->where('status', 'active')->count());
    }

    public function test_logout_revokes_refresh_token(): void
    {
        $this->createUser();
        $deviceId = '9dfc6298-69c4-4f4d-a42e-0ca109b76440';
        $login = $this->postJson('/api/v1/auth/login', $this->loginPayload($deviceId))->json('data');

        $this->withHeaders(['Authorization' => 'Bearer ' . $login['access_token']])
            ->postJson('/api/v1/auth/logout', ['refresh_token' => $login['refresh_token']])
            ->assertOk();

        $this->postJson('/api/v1/auth/refresh', [
            'refresh_token' => $login['refresh_token'],
            'device_id' => $deviceId,
        ])->assertStatus(401)->assertJsonPath('code', 'AUTH_REFRESH_EXPIRED');
    }

    public function test_logout_only_revokes_the_access_token_session_when_tokens_are_mixed(): void
    {
        $this->createUser();
        $firstDeviceId = '9dfc6298-69c4-4f4d-a42e-0ca109b76440';
        $secondDeviceId = '2afc6298-69c4-4f4d-a42e-0ca109b76441';
        $first = $this->postJson('/api/v1/auth/login', $this->loginPayload($firstDeviceId))->json('data');
        $second = $this->postJson('/api/v1/auth/login', $this->loginPayload($secondDeviceId))->json('data');

        $this->withHeaders(['Authorization' => 'Bearer ' . $first['access_token']])
            ->postJson('/api/v1/auth/logout', ['refresh_token' => $second['refresh_token']])
            ->assertOk();

        $this->postJson('/api/v1/auth/refresh', [
            'refresh_token' => $first['refresh_token'],
            'device_id' => $firstDeviceId,
        ])->assertStatus(401)->assertJsonPath('code', 'AUTH_REFRESH_EXPIRED');

        $this->postJson('/api/v1/auth/refresh', [
            'refresh_token' => $second['refresh_token'],
            'device_id' => $secondDeviceId,
        ])->assertOk();
    }

    public function test_unbinding_device_revokes_its_access_and_refresh_tokens(): void
    {
        $this->createUser();
        $deviceId = '9dfc6298-69c4-4f4d-a42e-0ca109b76440';
        $login = $this->postJson('/api/v1/auth/login', $this->loginPayload($deviceId))->json('data');
        $headers = [
            'Authorization' => 'Bearer ' . $login['access_token'],
            'X-Device-ID' => $deviceId,
        ];

        $this->withHeaders($headers)
            ->deleteJson('/api/v1/devices/' . $login['device']['id'])
            ->assertOk();

        [$accessTokenId] = explode('|', $login['access_token'], 2);
        $this->assertDatabaseMissing('personal_access_tokens', ['id' => $accessTokenId]);

        $profile = $this->withHeaders($headers)->getJson('/api/v1/user/profile')->assertStatus(401);
        $this->assertContains($profile->json('code'), ['AUTH_TOKEN_EXPIRED', 'AUTH_DEVICE_MISMATCH']);
        $this->postJson('/api/v1/auth/refresh', [
            'refresh_token' => $login['refresh_token'],
            'device_id' => $deviceId,
        ])->assertStatus(401)->assertJsonPath('code', 'AUTH_REFRESH_EXPIRED');
    }

    public function test_removing_a_session_also_revokes_its_refresh_token(): void
    {
        $user = $this->createUser();
        $deviceId = '9dfc6298-69c4-4f4d-a42e-0ca109b76440';
        $login = $this->postJson('/api/v1/auth/login', $this->loginPayload($deviceId))->json('data');
        [$accessTokenId] = explode('|', $login['access_token'], 2);

        (new AuthService($user))->removeSession($accessTokenId);

        $this->postJson('/api/v1/auth/refresh', [
            'refresh_token' => $login['refresh_token'],
            'device_id' => $deviceId,
        ])->assertStatus(401)->assertJsonPath('code', 'AUTH_REFRESH_EXPIRED');
    }

    public function test_legacy_sanctum_token_cannot_register_a_client_device(): void
    {
        $user = $this->createUser();
        $legacyToken = $user->createToken('legacy', ['*'])->plainTextToken;

        $this->withHeaders(['Authorization' => 'Bearer ' . $legacyToken])
            ->postJson('/api/v1/devices/register', $this->loginPayload(
                '9dfc6298-69c4-4f4d-a42e-0ca109b76440'
            )['device'])
            ->assertStatus(401)
            ->assertJsonPath('code', 'AUTH_TOKEN_INVALID');
    }

    private function createUser(array $overrides = []): User
    {
        $plan = Plan::query()->create([
            'group_id' => 1,
            'transfer_enable' => 100,
            'name' => '测试套餐',
            'created_at' => time(),
            'updated_at' => time(),
        ]);

        return User::query()->create(array_merge([
            'email' => 'user@example.com',
            'password' => password_hash('password123', PASSWORD_DEFAULT),
            'uuid' => Helper::guid(true),
            'token' => Helper::guid(true),
            'plan_id' => $plan->id,
            'transfer_enable' => 100 * 1073741824,
            'expired_at' => time() + 86400,
            'created_at' => time(),
            'updated_at' => time(),
        ], $overrides));
    }

    private function loginPayload(string $deviceId): array
    {
        return [
            'email' => 'user@example.com',
            'password' => 'password123',
            'device' => [
                'device_id' => $deviceId,
                'name' => '测试电脑',
                'platform' => 'windows',
                'architecture' => 'x64',
                'os_version' => '11.0.26100',
                'app_version' => '1.0.0',
            ],
        ];
    }
}
