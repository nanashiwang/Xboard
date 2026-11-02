<?php
namespace Tests\Feature\Desktop;

use App\Services\WebsiteAssetService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class WebsiteAssetTest extends TestCase
{
    use RefreshDatabase;

    public function test_public_asset_is_content_addressed_and_supports_conditional_get(): void
    {
        $url = app(WebsiteAssetService::class)->url('panel.js');
        $hash = hash_file('sha256', base_path('theme/Xboard/assets/umi.js'));
        $this->assertSame('/web-assets/'.$hash.'/panel.js', $url);
        $response = $this->get($url)->assertOk()
            ->assertHeader('ETag', '"'.$hash.'"')
            ->assertHeader('X-Content-Type-Options', 'nosniff');
        $this->assertStringContainsString('public', $response->headers->get('Cache-Control'));
        $this->assertStringContainsString('immutable', $response->headers->get('Cache-Control'));
        $this->assertSame($hash, hash_file('sha256', $response->baseResponse->getFile()->getPathname()));
        $this->get($url, ['If-None-Match' => '"'.$hash.'"'])->assertStatus(304);
    }

    public function test_unmatched_hash_and_non_allowlisted_files_never_get_immutable_cache(): void
    {
        foreach (['/web-assets/'.str_repeat('0', 64).'/panel.js', '/web-assets/'.str_repeat('a', 64).'/.env', '/web-assets/'.str_repeat('b', 64).'/config.php'] as $url) {
            $response = $this->get($url)->assertNotFound();
            $this->assertStringNotContainsString('immutable', $response->headers->get('Cache-Control', ''));
        }
    }

    public function test_go_preloads_same_url_without_external_bootstrap_dependency(): void
    {
        $url = app(WebsiteAssetService::class)->url('panel.js');
        $this->get('https://capybarago.uk/')->assertOk()
            ->assertSee('rel="modulepreload" href="'.$url.'" crossorigin="anonymous"', false)
            ->assertSee('data-panel-src="'.$url.'"', false)
            ->assertSee('正在打开登录页面')
            ->assertSee('重新加载')
            ->assertDontSee('src="/assets/capybara-home/home.js', false);
        foreach (['/', '/api/v1/guest/comm/config', '/desktop/login'] as $path) {
            $r = $this->get('https://capybarago.uk'.$path)->assertOk();
            $this->assertStringNotContainsString('immutable', $r->headers->get('Cache-Control', ''));
        }
    }
}
