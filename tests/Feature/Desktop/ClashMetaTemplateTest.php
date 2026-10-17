<?php

namespace Tests\Feature\Desktop;

use App\Models\SubscribeTemplate;
use App\Protocols\ClashMeta;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Symfony\Component\Yaml\Yaml;
use Tests\TestCase;

class ClashMetaTemplateTest extends TestCase
{
    use RefreshDatabase;

    public function test_fresh_install_uses_meta_dns_without_changing_other_clients(): void
    {
        $this->assertSame(file_get_contents(base_path(ClashMeta::DEFAULT_TEMPLATE_FILE)), subscribe_template('clashmeta'));
        foreach (['clash', 'stash'] as $client) {
            $this->assertSame(file_get_contents(base_path('resources/rules/default.clash.yaml')), subscribe_template($client));
        }

        admin_setting(['app_name' => '测试代理']);
        $yaml = $this->render();
        $config = Yaml::parse($yaml);
        $this->assertStringNotContainsString('$app_name', $yaml);
        $groups = array_column($config['proxy-groups'], 'name');
        foreach (array_merge(array_values($config['dns']['nameserver-policy']), [$config['dns']['fallback']]) as $resolvers) {
            $this->assertCount(2, $resolvers);
            foreach ($resolvers as $resolver) {
                $this->assertContains(explode('#', $resolver, 2)[1], $groups);
            }
        }
        foreach ($config['dns']['proxy-server-nameserver'] as $resolver) {
            $this->assertStringNotContainsString('#', $resolver, 'Node bootstrap DNS must not depend on the proxy.');
        }

        foreach (['services.googleapis.cn', 'android.clients.google.com', 'redirector.gvt1.com', 'r1.gvt2.com', 'r1-cn.googlevideo.com'] as $domain) {
            $this->assertSame('测试代理', $this->firstDomainPolicy($config['rules'], $domain), $domain);
        }
        foreach (['www.example.cn', 'www.baidu.com', 'localhost'] as $domain) {
            $this->assertSame('DIRECT', $this->firstDomainPolicy($config['rules'], $domain), $domain);
        }
    }

    public function test_saved_custom_template_remains_authoritative(): void
    {
        SubscribeTemplate::setContent('clashmeta', Yaml::dump([
            'proxies' => [],
            'proxy-groups' => [['name' => '自定义', 'type' => 'select', 'proxies' => []]],
            'rules' => ['MATCH,自定义'],
        ]));
        $config = Yaml::parse($this->render());
        $this->assertArrayNotHasKey('dns', $config);
        $this->assertSame('MATCH,自定义', end($config['rules']));
        $this->assertSame('自定义', $config['proxy-groups'][0]['name']);
    }

    private function firstDomainPolicy(array $rules, string $domain): ?string
    {
        foreach ($rules as $rule) {
            [$type, $value, $policy] = array_pad(explode(',', $rule), 3, null);
            $matches = match ($type) {
                'DOMAIN' => $domain === $value,
                'DOMAIN-SUFFIX' => $domain === $value || str_ends_with($domain, '.'.$value),
                'DOMAIN-KEYWORD' => str_contains($domain, $value),
                default => false,
            };
            if ($matches) {
                return $policy;
            }
        }
        return null;
    }

    private function render(): string
    {
        $user = ['u' => 0, 'd' => 0, 'transfer_enable' => 1024, 'expired_at' => time() + 86400];
        $server = [
            'id' => 1, 'name' => '测试节点', 'type' => 'vless',
            'host' => 'node.example.com', 'port' => 443,
            'password' => '11111111-1111-4111-8111-111111111111',
            'protocol_settings' => [
                'network' => 'ws', 'tls' => 1,
                'tls_settings' => ['server_name' => 'node.example.com'],
                'network_settings' => ['path' => '/proxy'],
            ],
        ];
        return (new ClashMeta($user, [$server]))->handle()->getContent();
    }
}
