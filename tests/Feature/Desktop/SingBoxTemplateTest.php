<?php

namespace Tests\Feature\Desktop;

use App\Http\Controllers\V1\Client\ClientController;
use App\Models\SubscribeTemplate;
use App\Models\User;
use App\Protocols\SingBox;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Request;
use PHPUnit\Framework\Attributes\DataProvider;
use Symfony\Component\Process\Process;
use Tests\TestCase;

class SingBoxTemplateTest extends TestCase
{
    use RefreshDatabase;

    public static function versions(): array
    {
        return array_map(fn ($version) => [$version], ['1.9.7', '1.10.7', '1.11.0', '1.12.0', '1.13.19', '']);
    }

    #[DataProvider('versions')]
    public function test_complete_default_subscription_preserves_routing_and_node_contract(string $version): void
    {
        $template = file_get_contents(base_path(SingBox::DEFAULT_TEMPLATE_FILE));
        $this->assertSame($template, subscribe_template('singbox'));
        $config = $this->render($version);
        $modernDns = $version === '' || version_compare($version, '1.12.0', '>=');
        $modernRules = $version === '' || version_compare($version, '1.11.0', '>=');
        $dns = array_column($config['dns']['servers'], null, 'tag');
        $this->assertSame('节点选择', $dns['remote']['detour']);
        if ($modernDns) {
            $this->assertSame('https', $dns['remote']['type']);
            $this->assertSame('1.1.1.1', $dns['remote']['server']);
            $this->assertSame('223.5.5.5', $dns['local']['server']);
            $this->assertArrayNotHasKey('detour', $dns['local']);
            $this->assertSame('local', $config['route']['default_domain_resolver']);
            foreach ($config['dns']['rules'] as $rule) {
                $this->assertArrayNotHasKey('outbound', $rule);
            }
        } else {
            $this->assertSame('https://1.1.1.1/dns-query', $dns['remote']['address']);
            $this->assertSame('https://223.5.5.5/dns-query', $dns['local']['address']);
            $this->assertSame('direct', $dns['local']['detour']);
            $this->assertSame(['outbound' => ['any'], 'server' => 'local'], $config['dns']['rules'][0]);
            $this->assertArrayNotHasKey('default_domain_resolver', $config['route']);
        }
        $rules = $config['route']['rules'];
        if ($modernRules) {
            $this->assertSame(['resolve', 'sniff', 'hijack-dns'], array_column(array_slice($rules, 0, 3), 'action'));
            $this->assertSame('prefer_ipv4', $rules[0]['strategy']);
            foreach ($config['inbounds'] as $inbound) {
                foreach (['sniff', 'sniff_override_destination', 'domain_strategy', 'endpoint_independent_nat'] as $field) {
                    $this->assertArrayNotHasKey($field, $inbound);
                }
            }
            $this->assertNotContains('dns', array_column($config['outbounds'], 'type'));
            $this->assertNotContains('block', array_column($config['outbounds'], 'type'));
        } else {
            $this->assertEquals(['protocol' => 'dns', 'outbound' => 'dns-out'], $rules[0]);
            foreach ($config['inbounds'] as $inbound) {
                $this->assertTrue($inbound['sniff']);
                $this->assertTrue($inbound['sniff_override_destination']);
                $this->assertSame('prefer_ipv4', $inbound['domain_strategy']);
            }
            $this->assertTrue($config['inbounds'][0]['endpoint_independent_nat']);
        }
        $this->assertSame([
            ['clash_mode' => 'direct', 'outbound' => 'direct'],
            ['clash_mode' => 'global', 'outbound' => '节点选择'],
            ['ip_is_private' => true, 'outbound' => 'direct'],
            ['rule_set' => ['geosite-cn', 'geoip-cn'], 'outbound' => 'direct'],
        ], array_slice($rules, $modernRules ? 3 : 1));
        $tun = $config['inbounds'][0];
        if ($version !== '' && version_compare($version, '1.10.0', '<')) {
            $this->assertSame('172.19.0.1/30', $tun['inet4_address']);
            $this->assertSame('2001:0470:f9da:fdfa::1/64', $tun['inet6_address']);
            $this->assertArrayNotHasKey('address', $tun);
        } else {
            $this->assertSame(['172.19.0.1/30', '2001:0470:f9da:fdfa::1/64'], $tun['address']);
        }
        $outbounds = array_column($config['outbounds'], null, 'tag');
        $node = $outbounds['香港入口测试'];
        $this->assertSame('hk-ingress.example.com', $node['server']);
        $this->assertSame(443, $node['server_port']);
        $this->assertSame('11111111-1111-4111-8111-111111111111', $node['uuid']);
        $this->assertTrue($node['tls']['enabled']);
        $this->assertFalse($node['tls']['insecure']);
        $this->assertSame('hk-ingress.example.com', $node['tls']['server_name']);
        $this->assertSame('ws', $node['transport']['type']);
        $this->assertSame('/hk-test', $node['transport']['path']);
        $this->assertSame(['自动选择', '香港入口测试'], $outbounds['节点选择']['outbounds']);
        $this->assertSame(['香港入口测试'], $outbounds['自动选择']['outbounds']);
        $this->assertSame($template, subscribe_template('singbox'), 'Export must not rewrite stored templates.');
    }

    public function test_existing_custom_template_is_not_replaced_by_the_default(): void
    {
        $custom = json_encode([
            'dns' => ['servers' => [['tag' => 'custom', 'address' => '9.9.9.9']]],
            'inbounds' => [['type' => 'mixed', 'listen' => '127.0.0.1', 'listen_port' => 18080]],
            'outbounds' => [['type' => 'direct', 'tag' => 'custom-direct']],
            'route' => ['rules' => [], 'final' => 'custom-direct'],
        ]);
        SubscribeTemplate::setContent('singbox', $custom);
        $config = $this->render('1.10.7');
        $this->assertSame('9.9.9.9', $config['dns']['servers'][0]['address']);
        $this->assertSame([], $config['route']['rules']);
        $this->assertArrayNotHasKey('sniff', $config['inbounds'][0]);
        $this->assertSame('custom-direct', $config['route']['final']);
        $this->assertSame($custom, SubscribeTemplate::getContent('singbox'));
    }

    public function test_dns_downgrade_uses_the_existing_direct_tag_and_preserves_explicit_detour(): void
    {
        SubscribeTemplate::setContent('singbox', json_encode([
            'dns' => ['servers' => [
                ['type' => 'https', 'server' => '9.9.9.9', 'tag' => 'bootstrap'],
                ['type' => 'https', 'server' => '1.1.1.1', 'tag' => 'remote', 'detour' => 'selected'],
            ]],
            'outbounds' => [
                ['type' => 'direct', 'tag' => 'custom-direct'],
                ['type' => 'selector', 'tag' => 'selected', 'outbounds' => []],
            ],
            'route' => ['rules' => [], 'default_domain_resolver' => 'bootstrap'],
        ]));
        $config = $this->render('1.11.0');
        $this->assertSame('custom-direct', $config['dns']['servers'][0]['detour']);
        $this->assertSame('selected', $config['dns']['servers'][1]['detour']);
        $this->assertSame(['outbound' => ['any'], 'server' => 'bootstrap'], $config['dns']['rules'][0]);
    }

    public function test_complete_export_passes_real_core_check_when_binary_is_supplied(): void
    {
        $binary = getenv('SING_BOX_BINARY');
        if (!$binary) {
            $this->markTestSkipped('Set SING_BOX_BINARY to validate the full exported subscription with a real core.');
        }
        $version = new Process([$binary, 'version']);
        $version->mustRun();
        $this->assertSame(1, preg_match('/sing-box version (\d+\.\d+\.\d+)/', $version->getOutput(), $matches));
        $config = $this->render($matches[1]);
        $file = tempnam(sys_get_temp_dir(), 'singbox-subscription-');
        try {
            file_put_contents($file, json_encode($config, JSON_THROW_ON_ERROR));
            $check = new Process([$binary, 'check', '-c', $file], null, [
                'ENABLE_DEPRECATED_LEGACY_DNS_SERVERS' => false,
                'ENABLE_DEPRECATED_SPECIAL_OUTBOUNDS' => false,
            ]);
            $check->run();
            $this->assertSame(0, $check->getExitCode(), $check->getOutput() . $check->getErrorOutput());
        } finally {
            unlink($file);
        }
    }

    private function render(string $version): array
    {
        admin_setting(['show_protocol_to_server_enable' => false, 'show_info_to_server_enable' => false]);
        $request = Request::create('https://example.com/api/v1/client/subscribe', 'GET', [], [], [], [
            'HTTP_USER_AGENT' => 'sing-box' . ($version === '' ? '' : '/' . $version),
        ]);
        $this->app->instance('request', $request);
        $user = new User([
            'uuid' => '11111111-1111-4111-8111-111111111111',
            'u' => 0, 'd' => 0, 'transfer_enable' => 1073741824, 'expired_at' => time() + 86400,
        ]);
        $response = app(ClientController::class)->doSubscribe($request, $user, [[
            'id' => 1, 'name' => '香港入口测试', 'type' => 'vless',
            'host' => 'hk-ingress.example.com', 'port' => 443,
            'protocol_settings' => [
                'network' => 'ws', 'tls' => 1,
                'tls_settings' => ['server_name' => 'hk-ingress.example.com', 'allow_insecure' => false],
                'network_settings' => ['path' => '/hk-test'],
            ],
        ]]);
        $this->assertSame(200, $response->getStatusCode());
        return json_decode($response->getContent(), true, 512, JSON_THROW_ON_ERROR);
    }
}
