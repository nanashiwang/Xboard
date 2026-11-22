<?php

namespace App\Services;

use App\Models\{Plan, ResidentialProxyEndpoint, ResidentialProxyHost};
use Illuminate\Support\Facades\DB;

class ResidentialEnrollment
{
    public const PANEL = 'https://capybarago.uk';
    public const PORTS = [20001, 20002, 20003, 20004, 20005, 20006, 20007, 20008, 20009, 20010];

    public function register(array $data): array
    {
        abort_unless(filter_var($data['address'], FILTER_VALIDATE_IP, FILTER_FLAG_IPV4 | FILTER_FLAG_GLOBAL_RANGE)
            && (int)explode('.', $data['address'])[0] < 224, 422, '请输入固定公网 IPv4');
        return DB::transaction(function () use ($data) {
            abort_unless(Plan::where('is_proxy', true)->exists(), 422, '请先配置家宽代理商品');
            $host = ResidentialProxyHost::firstOrCreate(['address' => $data['address']], [
                'label' => $data['label'], 'country' => $data['country'], 'enabled' => false,
                'token_hash' => hash('sha256', random_bytes(32)), 'enrollment_state' => 'registered',
            ]);
            abort_unless($host->wasRecentlyCreated, 409, '该 IP 已登记，请在对应出口继续操作');
            foreach (self::PORTS as $port) {
                ResidentialProxyEndpoint::create(['host_id' => $host->id, 'port' => $port, 'name' => $host->label]);
            }
            return $this->issue($host->id);
        }, 5);
    }

    public function issue(int $id): array
    {
        $code = bin2hex(random_bytes(32));
        $expires = time() + 1800;
        $updated = ResidentialProxyHost::whereKey($id)->where('enrollment_state', 'registered')
            ->update(['install_hash' => hash('sha256', $code), 'install_until' => $expires]);
        abort_unless($updated, 409, '该机器已领取安装身份');
        $ip = ResidentialProxyHost::findOrFail($id)->address;
        return ['command' => self::installCommand("exit $id $ip", $code), 'expires_at' => $expires];
    }

    public static function installCommand(string $role, string $secret): string
    {
        $url = self::PANEL . '/api/v1/proxy-agent/installer';
        return '(set -e; f=$(mktemp); trap \'rm -f "$f"\' EXIT; curl -fsS ' . escapeshellarg($url)
            . ' -o "$f"; printf "%s\\n" ' . escapeshellarg($secret) . ' | sudo python3 "$f" ' . $role . ')';
    }

    public function claim(int $id, string $code, string $digest): void
    {
        $count = ResidentialProxyHost::whereKey($id)->where('enrollment_state', 'registered')
            ->where('install_until', '>=', time())->where('install_hash', hash('sha256', $code))
            ->update(['token_hash' => $digest, 'enrollment_state' => 'installed', 'install_hash' => null, 'install_until' => null]);
        // A lost HTTP response can be replayed only by the holder of the persistent agent token via sync.
        abort_unless($count, 409, '安装凭据已使用或已过期');
    }

    public static function ingressToken(): string
    {
        return hash_hmac('sha256', 'residential-ingress-worker-v1', app('encrypter')->getKey());
    }

    public static function probeCredentials(ResidentialProxyHost $host, int $port): array
    {
        $key = hash_hmac('sha256', "probe/{$host->id}/{$host->probe_id}/$port", app('encrypter')->getKey());
        return ['username' => 'ck_' . substr($key, 0, 16), 'password' => substr($key, 16, 40)];
    }

    public function start(int $id): void
    {
        $now = time();
        DB::transaction(function () use ($id, $now) {
            $changed = ResidentialProxyHost::whereKey($id)->where('enabled', false)
                ->where('seen_at', '>=', $now - 60)->whereNotNull('transport_cert')
                ->where(fn ($q) => $q->whereIn('enrollment_state', ['installed', 'failed'])
                    ->orWhere(fn ($q) => $q->whereIn('enrollment_state', ['testing', 'draining'])->where('probe_until', '<', $now)))
                ->update(['enrollment_state' => 'testing', 'probe_id' => bin2hex(random_bytes(16)),
                    'probe_until' => $now + 600, 'probe_error' => null]);
            abort_unless($changed, 409, '需要已安装并在线的出口，或等待本次验收结束');
            ResidentialProxyEndpoint::where('host_id', $id)->increment('revision');
        }, 5);
    }

    public function manifest(): array
    {
        return ResidentialProxyHost::whereNotNull('enrollment_state')->whereNotNull('transport_cert')
            ->orderBy('id')->get()->map(function ($host) {
                $row = ['id' => $host->id, 'address' => $host->address, 'cert' => $host->transport_cert];
                if ($host->enrollment_state === 'testing' && $host->probe_until > time() && $host->seen_at >= time() - 60
                    && ResidentialProxyEndpoint::where('host_id', $host->id)->where('running', true)
                        ->whereColumn('revision', 'applied_revision')->where('checked_at', '>=', time() - 60)->count() === count(self::PORTS)) {
                    $row['probe'] = ['id' => $host->probe_id, 'ports' => collect(self::PORTS)->map(fn ($port) =>
                        ['port' => $port] + self::probeCredentials($host, $port))->all()];
                }
                return $row;
            })->all();
    }

    public function finish(int $id, string $probe, bool $passed, ?string $error): void
    {
        DB::transaction(function () use ($id, $probe, $passed, $error) {
            $count = ResidentialProxyHost::whereKey($id)->where('enabled', false)->where('enrollment_state', 'testing')
                ->where('probe_id', $probe)->where('probe_until', '>=', time())
                ->update(['enrollment_state' => $passed ? 'draining' : 'failed', 'probe_error' => $passed ? null : $error,
                    'probe_until' => $passed ? time() + 180 : null]);
            abort_unless($count, 409);
            ResidentialProxyEndpoint::where('host_id', $id)->increment('revision');
        }, 5);
    }

    public function releaseAfterRevoke(ResidentialProxyHost $host): void
    {
        if ($host->enrollment_state !== 'draining') return;
        // Only fresh acknowledgements of all ten post-test revisions can admit customers.
        $stopped = ResidentialProxyEndpoint::where('host_id', $host->id)->where('running', false)
            ->whereColumn('applied_revision', 'revision')->where('checked_at', '>=', time() - 60)->count();
        if ($stopped === count(self::PORTS)) {
            ResidentialProxyHost::whereKey($host->id)->where('enrollment_state', 'draining')
                ->where('probe_id', $host->probe_id)->where('probe_until', '>=', time())
                ->update(['enabled' => true, 'enrollment_state' => 'live', 'probe_id' => null, 'probe_until' => null]);
        }
    }
}
