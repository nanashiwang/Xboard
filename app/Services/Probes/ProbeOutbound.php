<?php
namespace App\Services\Probes;

use App\Protocols\SingBox;
use InvalidArgumentException;

class ProbeOutbound extends SingBox
{
    public function build(array $server): array
    {
        if ($server['type'] === 'vless' && !in_array(data_get($server, 'protocol_settings.network', 'tcp'), ['tcp', 'ws', 'grpc', 'http', 'quic', 'httpupgrade'], true)) {
            throw new InvalidArgumentException('unsupported_protocol');
        }
        $method = match ($server['type']) {
            'vless' => 'buildVless', 'vmess' => 'buildVmess', 'trojan' => 'buildTrojan',
            'shadowsocks' => 'buildShadowsocks', 'hysteria' => 'buildHysteria',
            'tuic' => 'buildTuic', 'anytls' => 'buildAnyTLS', 'socks' => 'buildSocks', 'http' => 'buildHttp',
            default => throw new InvalidArgumentException('unsupported_protocol'),
        };
        $outbound = $this->$method($server['password'], $server);
        if (data_get($outbound, 'tls.insecure')) throw new InvalidArgumentException('insecure_tls');
        $outbound['tag'] = 'node';
        return $outbound;
    }
}
