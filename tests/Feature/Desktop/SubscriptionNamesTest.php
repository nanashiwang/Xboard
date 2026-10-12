<?php

namespace Tests\Feature\Desktop;

use App\Http\Controllers\V1\Client\ClientController;
use App\Models\SubscribeTemplate;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Request;
use PHPUnit\Framework\Attributes\DataProvider;
use Symfony\Component\Yaml\Yaml;
use Tests\TestCase;

class SubscriptionNamesTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        admin_setting(['show_protocol_to_server_enable' => true, 'show_info_to_server_enable' => false]);
        $template = Yaml::dump([
            'proxies' => [],
            'proxy-groups' => [['name' => '选择线路', 'type' => 'select', 'proxies' => []]],
            'rules' => ['MATCH,选择线路'],
        ]);
        foreach (['clash', 'clashmeta', 'stash'] as $format) {
            SubscribeTemplate::setContent($format, $template);
        }
        SubscribeTemplate::setContent('singbox', json_encode([
            'outbounds' => [
                ['tag' => 'direct', 'type' => 'direct'],
                ['tag' => '选择线路', 'type' => 'selector', 'outbounds' => []],
            ],
            'route' => ['rules' => [], 'final' => '选择线路'],
        ]));
    }

    public static function clients(): array
    {
        return [
            'Clash Verge' => ['Clash-Verge/2.4.2', 'vless', 'yaml'],
            'Clash Meta' => ['ClashMetaForAndroid/2.11.12', 'vless', 'yaml'],
            'Clash' => ['Clash/1.18.0', 'vmess', 'yaml'],
            'Stash' => ['Stash/2.7.0', 'vmess', 'yaml'],
            'sing-box' => ['sing-box/1.12.0', 'vless', 'json'],
        ];
    }

    #[DataProvider('clients')]
    public function test_duplicate_routes_are_preserved_with_unique_names_and_valid_group_references(
        string $agent, string $type, string $format
    ): void {
        $servers = [
            $this->server(101, '美国凤凰城|高速下载', $type),
            $this->server(102, '美国凤凰城|高速下载', $type),
            $this->server(103, '美国凤凰城|高速下载｜CF备用', $type),
        ];
        [$proxies, $references] = $this->subscription($agent, $servers, $format);

        $this->assertCount(3, $proxies);
        $this->assertCount(3, array_unique(array_column($proxies, 'name')));
        $this->assertSame(array_column($proxies, 'name'), $references);
        $this->assertSame(array_column($servers, 'host'), array_column($proxies, 'server'));
        $this->assertStringEndsWith(' [101]', $proxies[0]['name']);
        $this->assertStringEndsWith(' [102]', $proxies[1]['name']);
        $this->assertStringEndsWith('｜CF备用', $proxies[2]['name']);
    }

    public function test_numbered_names_do_not_collide_with_existing_names_and_survive_reordering(): void
    {
        $servers = [
            $this->server(101, '美国凤凰城'),
            $this->server(102, '美国凤凰城'),
            $this->server(103, '美国凤凰城 [101]'),
        ];
        [$forward] = $this->subscription('Clash-Verge/2.4.2', $servers);
        [$reverse] = $this->subscription('Clash-Verge/2.4.2', array_reverse($servers));
        $expected = [
            'node-101.example.com' => '[vless]美国凤凰城 [101-2]',
            'node-102.example.com' => '[vless]美国凤凰城 [102]',
            'node-103.example.com' => '[vless]美国凤凰城 [101]',
        ];

        $this->assertEquals($expected, array_column($forward, 'name', 'server'));
        $this->assertEquals($expected, array_column($reverse, 'name', 'server'));
    }

    public function test_filtered_protocols_do_not_rename_the_remaining_route(): void
    {
        admin_setting(['show_protocol_to_server_enable' => false]);
        [$proxies, $references] = $this->subscription('Clash/1.18.0', [
            $this->server(101, '美国出口', 'vmess'),
            $this->server(102, '美国出口', 'vless'),
        ]);

        $this->assertCount(1, $proxies);
        $this->assertSame(['美国出口'], $references);
        $this->assertSame('美国出口', $proxies[0]['name']);
    }

    public function test_repeated_or_missing_ids_do_not_drop_routes(): void
    {
        $server = $this->server(101, '美国出口');
        $withoutId = $server;
        unset($withoutId['id']);
        [$proxies, $references] = $this->subscription('Clash-Verge/2.4.2', [
            $server, $server, $withoutId, $withoutId,
        ]);

        $this->assertCount(4, $proxies);
        $this->assertCount(4, array_unique($references));
        $this->assertSame(array_column($proxies, 'name'), $references);
    }

    private function subscription(string $agent, array $servers, string $format = 'yaml'): array
    {
        $request = Request::create('https://example.com/api/v1/client/subscribe', 'GET', [], [], [], [
            'HTTP_USER_AGENT' => $agent,
        ]);
        $this->app->instance('request', $request);
        $user = new User([
            'uuid' => '11111111-1111-4111-8111-111111111111',
            'u' => 0, 'd' => 0, 'transfer_enable' => 1073741824, 'expired_at' => time() + 86400,
        ]);
        $response = app(ClientController::class)->doSubscribe($request, $user, $servers);
        $this->assertSame(200, $response->getStatusCode());

        if ($format === 'json') {
            $config = json_decode($response->getContent(), true, 512, JSON_THROW_ON_ERROR);
            $proxies = array_values(array_filter($config['outbounds'], fn ($outbound) => isset($outbound['server'])));
            $proxies = array_map(fn ($proxy) => ['name' => $proxy['tag'], 'server' => $proxy['server']], $proxies);
            return [$proxies, $config['outbounds'][1]['outbounds']];
        }

        $config = Yaml::parse($response->getContent());
        return [$config['proxies'], $config['proxy-groups'][0]['proxies']];
    }

    private function server(int $id, string $name, string $type = 'vless'): array
    {
        return [
            'id' => $id, 'name' => $name, 'type' => $type,
            'host' => "node-{$id}.example.com", 'port' => 443,
            'password' => '11111111-1111-4111-8111-111111111111',
            'protocol_settings' => [
                'network' => 'ws', 'tls' => 1,
                'tls_settings' => ['server_name' => 'example.com'],
                'network_settings' => ['path' => '/proxy'],
            ],
        ];
    }
}
