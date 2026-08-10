<?php

namespace Tests\Feature\Desktop;

use App\Models\Notice;
use App\Models\Plan;
use App\Models\User;
use App\Services\Client\ClientConfigService;
use App\Utils\Helper;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Request;
use RuntimeException;
use Tests\TestCase;

class ClientApiTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        admin_setting(['password_limit_enable' => 0]);
    }

    public function test_profile_and_subscription_require_bound_device(): void
    {
        $this->createUser();
        $deviceId = '9dfc6298-69c4-4f4d-a42e-0ca109b76440';
        $token = $this->postJson('/api/v1/auth/login', $this->loginPayload($deviceId))
            ->assertOk()
            ->json('data.access_token');

        $headers = [
            'Authorization' => 'Bearer ' . $token,
            'X-Device-ID' => $deviceId,
        ];

        $this->withHeaders($headers)->getJson('/api/v1/user/profile')
            ->assertOk()
            ->assertJsonPath('data.plan.status', 'active');

        $this->withHeaders($headers)->getJson('/api/v1/user/subscription')
            ->assertOk()
            ->assertJsonPath('data.status', 'active')
            ->assertJsonPath('data.traffic.remaining_bytes', 90 * 1073741824);
    }

    public function test_config_endpoint_returns_a_short_lived_download_url(): void
    {
        $this->createUser();
        $deviceId = '9dfc6298-69c4-4f4d-a42e-0ca109b76440';
        $token = $this->postJson('/api/v1/auth/login', $this->loginPayload($deviceId))
            ->assertOk()
            ->json('data.access_token');
        $headers = [
            'Authorization' => 'Bearer ' . $token,
            'X-Device-ID' => $deviceId,
            'X-Client-Version' => '1.0.0',
        ];

        $config = $this->withHeaders($headers)
            ->getJson('/api/v1/client/config')
            ->assertOk()
            ->assertJsonPath('data.delivery', 'url')
            ->assertJsonStructure(['data' => ['download_url', 'revision', 'sha256']])
            ->json('data');

        $downloadPath = (string) parse_url($config['download_url'], PHP_URL_PATH);
        $this->get($downloadPath)
            ->assertOk()
            ->assertHeader('Content-Type', 'application/yaml; charset=utf-8')
            ->assertHeader('ETag', '"' . $config['sha256'] . '"');
    }

    public function test_unexpected_desktop_errors_use_the_standard_response(): void
    {
        $this->createUser();
        $deviceId = '9dfc6298-69c4-4f4d-a42e-0ca109b76440';
        $token = $this->postJson('/api/v1/auth/login', $this->loginPayload($deviceId))
            ->assertOk()
            ->json('data.access_token');

        $this->app->instance(ClientConfigService::class, new class extends ClientConfigService {
            public function generate(User $user, Request $request): array
            {
                throw new RuntimeException('test error');
            }
        });

        $this->withHeaders([
            'Authorization' => 'Bearer ' . $token,
            'X-Device-ID' => $deviceId,
        ])->getJson('/api/v1/client/config')
            ->assertStatus(500)
            ->assertJsonPath('code', 'SERVER_ERROR')
            ->assertJsonStructure(['request_id', 'server_time']);
    }

    public function test_version_endpoint_is_public(): void
    {
        admin_setting([
            'windows_version' => '1.3.0',
            'windows_min_supported_version' => '1.1.0',
            'windows_download_url' => 'https://example.com/xboard.exe',
            'windows_sha256' => str_repeat('a', 64),
            'windows_published_at' => '2026-08-10 14:30:00+08:00',
        ]);

        $this->getJson('/api/v1/client/version?platform=windows&arch=x64&current_version=1.0.0')
            ->assertOk()
            ->assertJsonPath('data.update_available', true)
            ->assertJsonPath('data.mandatory', true)
            ->assertJsonPath('data.latest_version', '1.3.0')
            ->assertJsonPath('data.published_at', '2026-08-10T06:30:00Z');
    }

    public function test_notices_endpoint_is_public_and_respects_sort_order(): void
    {
        Notice::query()->create([
            'title' => '第二条',
            'content' => '内容二',
            'show' => true,
            'sort' => 2,
            'created_at' => time(),
            'updated_at' => time(),
        ]);
        Notice::query()->create([
            'title' => '第一条',
            'content' => '内容一',
            'show' => true,
            'sort' => 1,
            'created_at' => time(),
            'updated_at' => time(),
        ]);

        $this->getJson('/api/v1/notices')
            ->assertOk()
            ->assertJsonPath('data.total', 2)
            ->assertJsonPath('data.items.0.title', '第一条')
            ->assertJsonPath('data.items.1.title', '第二条');
    }

    public function test_plan_can_store_registered_device_limit(): void
    {
        $plan = Plan::query()->create([
            'group_id' => 1,
            'transfer_enable' => 100,
            'name' => '双设备套餐',
            'registered_device_limit' => 2,
            'created_at' => time(),
            'updated_at' => time(),
        ]);

        $this->assertSame(2, (int) $plan->fresh()->registered_device_limit);
    }

    private function createUser(): User
    {
        $plan = Plan::query()->create([
            'group_id' => 1,
            'transfer_enable' => 100,
            'name' => '测试套餐',
            'created_at' => time(),
            'updated_at' => time(),
        ]);

        return User::query()->create([
            'email' => 'user@example.com',
            'password' => password_hash('password123', PASSWORD_DEFAULT),
            'uuid' => Helper::guid(true),
            'token' => Helper::guid(true),
            'plan_id' => $plan->id,
            'u' => 5 * 1073741824,
            'd' => 5 * 1073741824,
            'transfer_enable' => 100 * 1073741824,
            'expired_at' => time() + 86400,
            'created_at' => time(),
            'updated_at' => time(),
        ]);
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
                'app_version' => '1.0.0',
            ],
        ];
    }
}
