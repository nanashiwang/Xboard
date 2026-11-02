<?php

namespace Tests\Feature\Desktop;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class WebsiteHomeTest extends TestCase
{
    use RefreshDatabase;

    public function test_public_home_renders_and_keeps_existing_panel_entry_points(): void
    {
        $response = $this->get('/')->assertOk()
            ->assertSee('与卡皮巴拉一起')
            ->assertSee('href="/#/login"', false)
            ->assertSee('href="/#/register"', false)
            ->assertSee('href="/#/plan"', false)
            ->assertSee('href="/clients"', false)
            ->assertSee('电脑端安装卡皮巴拉后直接登录本站账号并连接')
            ->assertSee('Android 和 iOS 暂使用下载中心推荐的第三方客户端')
            ->assertSee('data-panel-src="/theme/Xboard/assets/umi.js"', false)
            ->assertSee('window.routerBase = "/"', false)
            ->assertDontSee('type="module" crossorigin src=', false);
        $this->assertStringNotContainsString('50+', $response->getContent());
    }

    public function test_safe_mode_still_restricts_the_home_host(): void
    {
        admin_setting(['app_url' => 'https://home.example', 'safe_mode_enable' => 1]);
        $this->get('https://other.example/')->assertForbidden();
        $this->get('https://home.example/')->assertOk()->assertSee('与卡皮巴拉一起');
    }

    public function test_panel_settings_are_safely_serialized_without_losing_theme_values(): void
    {
        admin_setting([
            'app_name' => "旅行 ' </script><script>alert(1)</script>",
            'app_description' => "A & B's journey",
            'theme_Xboard' => ['theme_color' => 'blue', 'background_url' => 'https://example.com/a?b=1&c=2', 'custom_html' => ''],
        ]);
        $this->get('/')->assertOk()
            ->assertDontSee('</script><script>alert(1)</script>', false)
            ->assertSee('旅行', false)
            ->assertSee('window.settings =', false)
            ->assertSee('blue');
    }

    public function test_invitation_query_is_not_redirected_or_discarded_by_the_server(): void
    {
        $this->get('/?code=example-invitation')->assertOk()
            ->assertSee('data-panel-src=', false);
    }

    public function test_owned_application_domain_has_a_button_and_preserves_the_hash_loader(): void
    {
        admin_setting(['app_url' => 'https://taige.us', 'safe_mode_enable' => 1]);
        $this->get('https://capybarago.uk/?code=invitation')->assertOk()
            ->assertSee('点击进入官网')
            ->assertSee('href="#/login"', false)
            ->assertSee('/assets/capybara-home/entry.css', false)
            ->assertSee('data-panel-src="/theme/Xboard/assets/umi.js"', false)
            ->assertDontSee('与卡皮巴拉一起');
        $this->get('https://capybarago.uk/clients')->assertOk()->assertDontSee('点击进入官网');
        $this->get('https://capybarago.uk/desktop/login')->assertOk()->assertDontSee('点击进入官网');
        $this->getJson('https://capybarago.uk/api/v1/guest/comm/config')->assertOk()->assertJsonStructure(['data']);
        $this->get('https://capybarago.uk.evil.example/')->assertForbidden();
        $this->get('https://unknown.example/clients')->assertForbidden();
        $this->get('https://unknown.example/desktop/login')->assertForbidden();
    }

    public function test_original_browser_domains_remain_available_after_primary_url_migration(): void
    {
        admin_setting(['app_url' => 'https://capybarago.uk', 'safe_mode_enable' => 1]);
        foreach (['taige.us', 'board.taige.us'] as $host) {
            $this->get('https://'.$host.'/')->assertOk()->assertSee('与卡皮巴拉一起')->assertDontSee('点击进入官网');
            $this->get('https://'.$host.'/clients')->assertOk();
            $this->get('https://'.$host.'/desktop/login')->assertOk();
        }
    }
}
