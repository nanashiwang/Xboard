<?php
// Read-only local attestation. Never change show/enabled, user or probe state.
function stable($value) {
    if (!is_array($value)) return $value;
    if (!array_is_list($value)) ksort($value, SORT_STRING);
    foreach ($value as $key => $child) $value[$key] = stable($child);
    return $value;
}
try {
    $reason = 'probe_scope_invalid';
    require '/www/vendor/autoload.php';
    $app = require '/www/bootstrap/app.php';
    $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
    $input = json_decode(base64_decode('__INPUT_BASE64__', true), true, 512, JSON_THROW_ON_ERROR);
    $probe = App\Models\NodeProbe::findOrFail(2);
    $token = $input['token'] ?? '';
    if (!is_string($token) || strlen($token) !== 64 || !$probe->enabled ||
        !hash_equals($probe->token_hash, hash('sha256', $token))) throw new RuntimeException();
    $allocation = $input['allocation'];
    if (($allocation['machine_id'] ?? null) !== 21 || count($allocation['routes'] ?? []) !== 41) throw new RuntimeException();
    $expected = array_column($allocation['routes'], 'public_id'); sort($expected, SORT_NUMERIC);
    $actual = $probe->server_ids; sort($actual, SORT_NUMERIC);
    if ($actual !== $expected || count(array_unique($expected)) !== 41) throw new RuntimeException();
    $user = $probe->user;
    if (!$user || $user->banned || $user->is_admin || $user->is_staff || (int)$user->group_id !== 6 ||
        ($user->expired_at !== null && $user->expired_at <= time()) ||
        $user->u + $user->d >= $user->transfer_enable || $user->plan?->dedicated) throw new RuntimeException();
    $builder = new App\Services\Probes\ProbeOutbound($user->toArray(), []);
    $runtime = array_flip(['created_at', 'updated_at', 'u', 'd', 'last_check_at', 'last_push_at',
        'last_seen_at', 'load_status', 'metrics', 'online', 'online_conn']);
    $rows = [];
    foreach ($allocation['routes'] as $row) {
        $public = App\Models\Server::findOrFail($row['public_id']);
        $backend = App\Models\Server::findOrFail($row['backend_id']);
        if ((int)$backend->machine_id !== 21 || (int)$public->parent_id !== (int)$backend->id ||
            !in_array('upstream-extension-public', $public->tags ?? [], true) ||
            !in_array('upstream-extension-backend', $backend->tags ?? [], true) ||
            !in_array('6', array_map('strval', $public->group_ids ?? []), true) ||
            !in_array('6', array_map('strval', $backend->group_ids ?? []), true) ||
            ($public->transfer_enable && $public->u + $public->d >= $public->transfer_enable) ||
            app(App\Services\DedicatedExitService::class)->nodeExitId($public)) throw new RuntimeException();
        $data = $public->toArray();
        if (data_get($data, 'protocol_settings.utls.enabled') && data_get($data, 'protocol_settings.utls.fingerprint') === 'random') {
            $reason = 'probe_random_fingerprint_not_repeatable';
            throw new RuntimeException();
        }
        $data['port'] = (int)explode('-', (string)$public->port)[0];
        $data['password'] = $public->generateServerPassword($user);
        $outbound = $builder->build($data);
        $hash = hash('sha256', json_encode(stable($outbound), JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION | JSON_UNESCAPED_LINE_TERMINATORS));
        $state = ['backend'=>array_diff_key($backend->getRawOriginal(), $runtime),
            'public'=>array_diff_key($public->getRawOriginal(), $runtime)];
        $stateHash = hash('sha256', json_encode(stable($state), JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION | JSON_UNESCAPED_LINE_TERMINATORS));
        $rows[] = ['key'=>$row['key'], 'public_id'=>(int)$public->id, 'backend_id'=>(int)$backend->id,
            'show'=>(bool)$public->show, 'enabled'=>(bool)$backend->enabled, 'public_config_sha256'=>$hash,
            'state_sha256'=>$stateHash];
    }
    echo json_encode(['scope_valid'=>true, 'probe_id'=>2, 'routes'=>$rows], JSON_THROW_ON_ERROR);
} catch (Throwable $error) {
    echo json_encode(['scope_valid'=>false, 'reason'=>$reason ?? 'probe_scope_invalid'], JSON_THROW_ON_ERROR);
    exit(1);
}
