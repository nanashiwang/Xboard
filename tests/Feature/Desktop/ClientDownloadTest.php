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
            ->assertSee('卡皮巴拉客户端下载')->assertSee('Clash Verge Rev')
            ->assertSee('sing-box')->assertDontSee($user->token);
        $this->getJson('/api/v1/user/client/import?client=clash-verge')->assertForbidden();
    }

    public function test_own_desktop_clients_use_account_login_and_never_offer_subscription_import(): void
    {
        $catalog = app(ClientDownloadService::class)->catalog();
        $html = $this->get('/clients')->assertOk()->getContent();
        $dom = new \DOMDocument();
        @$dom->loadHTML('<?xml encoding="UTF-8">' . $html);
        $xpath = new \DOMXPath($dom);
        foreach (['windows' => 1, 'macos' => 2, 'linux' => 2] as $platform => $count) {
            $client = $catalog[$platform];
            $this->assertSame('capybara', $client['id']);
            $this->assertSame('account', $client['flow']);
            $this->assertSame('0.1.9', $client['version']);
            $this->assertCount($count, $client['packages']);
            $section = $xpath->query('//section[@id="' . $platform . '"]')->item(0);
            $this->assertStringContainsString('无需复制订阅地址', $section->textContent);
            $this->assertStringContainsString('正式版', $section->textContent);
            $this->assertSame(0, $xpath->query('.//*[contains(@class,"import-controls")]', $section)->length);
            foreach ($client['packages'] as $package) {
                $this->assertStringStartsWith('/downloads/Capybara_0.1.9_', $package['url']);
                $this->assertStringStartsWith('https://github.com/nanashiwang/Xboard/releases/download/capybara-v0.1.9/', $package['official_url']);
            }
        }
        $this->assertStringContainsString('macOS 12', $catalog['macos']['requirement']);
        $this->assertStringContainsString('GNOME', $catalog['linux']['requirement']);
    }

    public function test_mobile_and_legacy_desktop_keep_third_party_import_flows(): void
    {
        $catalog = app(ClientDownloadService::class)->catalog();
        foreach (['android', 'ios', 'clash-verge'] as $platform) {
            $this->assertSame('subscription', $catalog[$platform]['flow']);
            $this->assertNotSame('capybara', $catalog[$platform]['id']);
        }
        $this->assertCount(4, $catalog['clash-verge']['packages']);
        $this->get('/clients')->assertOk()->assertSee('目前没有卡皮巴拉手机版')
            ->assertSee('href="#clash-verge"', false);
        Sanctum::actingAs($this->user());
        $this->getJson('/api/v1/user/client/import?client=capybara')->assertUnprocessable();
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

    public function test_catalog_uses_current_installers_and_verified_official_fallbacks(): void
    {
        $manifest = collect(json_decode(file_get_contents(base_path('.docker/downloads/manifest.json')), true))->keyBy('name');
        $packages = collect(app(ClientDownloadService::class)->catalog())->pluck('packages')->flatten(1);
        $local = $packages->filter(fn ($package) => isset($package['sha256']));
        $this->assertCount(11, $local);
        $this->assertCount(5, $local->filter(fn ($package) => str_contains($package['url'], 'Capybara_0.1.9_')));
        $this->assertFalse($local->contains(fn ($package) => str_contains($package['url'], 'Capybara_0.1.8_')));
        foreach ($local as $package) {
            $asset = $manifest->get(rawurldecode(basename($package['url'])));
            $this->assertNotNull($asset);
            $this->assertSame($asset['sha256'], $package['sha256']);
            $this->assertSame($asset['url'], $package['official_url']);
        }
    }

    public function test_catalog_tracks_the_selected_index_version_without_selecting_historical_installers(): void
    {
        $assets = json_decode(file_get_contents(base_path('.docker/downloads/manifest.json')), true);
        $assets = json_decode(str_replace('0.1.9', '0.1.42', json_encode($assets)), true);
        $service = new class($assets) extends ClientDownloadService {
            public function __construct(private array $assets) {}
            protected function manifest(): array { return $this->assets; }
        };
        $catalog = $service->catalog();
        foreach (['windows', 'macos', 'linux'] as $platform) {
            $this->assertSame('0.1.42', $catalog[$platform]['version']);
            $this->assertStringContainsString('capybara-v0.1.42', $catalog[$platform]['releases']);
            foreach ($catalog[$platform]['packages'] as $package) {
                $this->assertStringStartsWith('/downloads/Capybara_0.1.42_', $package['url']);
                $this->assertStringContainsString('capybara-v0.1.42/', $package['official_url']);
            }
        }
    }

    public function test_incomplete_selected_release_is_rejected_instead_of_mixing_old_packages(): void
    {
        $assets = array_values(array_filter(json_decode(file_get_contents(base_path('.docker/downloads/manifest.json')), true),
            fn ($asset) => $asset['name'] !== 'Capybara_0.1.9_x86_64-pc-windows-msvc.exe'));
        $service = new class($assets) extends ClientDownloadService {
            public function __construct(private array $assets) {}
            protected function manifest(): array { return $this->assets; }
        };
        $this->expectException(\LogicException::class);
        $this->expectExceptionMessage('Missing installer');
        $service->catalog();
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
