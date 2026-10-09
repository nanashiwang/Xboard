<?php

namespace Tests\Feature\Desktop;

use App\Models\User;
use App\Services\ClientDownloadService;
use App\Utils\Helper;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Laravel\Sanctum\Sanctum;
use PHPUnit\Framework\Attributes\DataProvider;
use Tests\TestCase;

class ClientDownloadTest extends TestCase
{
    use RefreshDatabase;

    public function test_guest_can_download_but_cannot_get_a_personal_subscription(): void
    {
        $user = $this->user();
        $this->get('/clients')->assertOk()
            ->assertSee('客户端下载')->assertSee('Clash Verge Rev')
            ->assertSee('sing-box')->assertDontSee($user->token);
        $this->getJson('/api/v1/user/client/import?client=clash-verge')->assertForbidden();
    }

    public function test_download_page_respects_safe_mode_and_escapes_site_name(): void
    {
        admin_setting(['app_url' => 'https://example.com', 'safe_mode_enable' => 1]);
        $this->get('https://other.example/clients')->assertForbidden();
        admin_setting(['app_name' => '<script>alert(1)</script>']);
        $this->get('https://example.com/clients')->assertOk()
            ->assertDontSee('<script>alert(1)</script>', false)
            ->assertSee('&lt;script&gt;alert(1)&lt;/script&gt;', false);
    }

    public function test_catalog_uses_every_verified_package_and_its_official_fallback(): void
    {
        $manifest = collect(json_decode(file_get_contents(base_path('.docker/downloads/manifest.json')), true))->keyBy('name');
        $packages = collect(app(ClientDownloadService::class)->catalog())->pluck('packages')->flatten(1);
        $local = $packages->filter(fn ($package) => isset($package['sha256']));
        $this->assertCount($manifest->count(), $local);
        foreach ($local as $package) {
            $asset = $manifest->get(rawurldecode(basename($package['url'])));
            $this->assertNotNull($asset);
            $this->assertSame($asset['sha256'], $package['sha256']);
            $this->assertSame($asset['url'], $package['official_url']);
        }
    }

    #[DataProvider('clients')]
    public function test_import_preserves_nested_url_and_only_returns_current_users_subscription(string $client, string $scheme): void
    {
        $user = $this->user();
        $other = $this->user('other@example.com');
        Sanctum::actingAs($user);
        admin_setting(['app_name' => '测试 & A+B / 客户端', 'subscribe_url' => 'https://subscribe.example.com']);
        $response = $this->getJson('/api/v1/user/client/import?client=' . $client)
            ->assertOk()->assertHeader('Cache-Control', 'no-store, private')
            ->assertDontSee($other->token);
        $data = $response->json('data');
        $this->assertStringStartsWith($scheme . '://', $data['import_url']);
        $this->assertStringContainsString($user->token, $data['subscribe_url']);
        $this->assertStringNotContainsString('flag=', $data['subscribe_url']);
        parse_str(parse_url($data['import_url'], PHP_URL_QUERY), $query);
        $this->assertSame($data['subscribe_url'], $query['url']);
        if ($client === 'sing-box') {
            $this->assertSame('测试 & A+B / 客户端', rawurldecode(parse_url($data['import_url'], PHP_URL_FRAGMENT)));
        } else {
            $this->assertSame('测试 & A+B / 客户端', $query['name']);
            // Matches the official Clash Verge parser, which consumes the rest
            // of the query after url=, instead of reading a single query value.
            $this->assertSame($data['subscribe_url'], rawurldecode(explode('url=', $data['import_url'], 2)[1]));
        }
    }

    public static function clients(): array
    {
        return [['clash-verge', 'clash-verge'], ['clash-meta', 'clashmeta'], ['sing-box', 'sing-box']];
    }

    #[DataProvider('unavailableUsers')]
    public function test_unavailable_user_cannot_obtain_import_link(array $changes): void
    {
        $user = $this->user();
        $user->forceFill($changes)->save();
        Sanctum::actingAs($user);
        $this->getJson('/api/v1/user/client/import?client=clash-meta')
            ->assertForbidden()->assertDontSee($user->token)
            ->assertJsonPath('message', '当前订阅不可用，请检查套餐有效期和剩余流量');
    }

    public static function unavailableUsers(): array
    {
        return [
            'banned' => [['banned' => true]],
            'expired' => [['expired_at' => 1]],
            'no subscription' => [['transfer_enable' => 0]],
            'exhausted' => [['u' => 1024, 'd' => 0]],
        ];
    }

    public function test_unsupported_client_is_rejected(): void
    {
        Sanctum::actingAs($this->user());
        $this->getJson('/api/v1/user/client/import?client=javascript')->assertUnprocessable();
    }

    private function user(string $email = 'download@example.com'): User
    {
        return User::create([
            'email' => $email, 'password' => password_hash('test-only-password', PASSWORD_DEFAULT),
            'uuid' => Helper::guid(true), 'token' => Helper::guid(),
            'u' => 0, 'd' => 0, 'transfer_enable' => 1024, 'expired_at' => time() + 86400,
        ]);
    }
}
