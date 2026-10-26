<?php
// Read-only model snapshot. Its stdout is PRIVATE and must be captured by prepare.py.
ini_set('display_errors', '0');
set_error_handler(static function () { throw new RuntimeException('snapshot_io_failed'); });
$stage = 'bootstrap';
$diagnostics = [];
function upstream_prepare_stable_value($value) {
    if (is_array($value)) {
        if (!array_is_list($value)) { ksort($value, SORT_STRING); }
        foreach ($value as &$child) { $child = upstream_prepare_stable_value($child); }
        unset($child);
    }
    return $value;
}
try {
    require '/www/vendor/autoload.php';
    $app = require '/www/bootstrap/app.php';
    $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
    $stage = 'manifest';
    $allocation = json_decode(base64_decode('__ALLOCATION_BASE64__', true), true, 512, JSON_THROW_ON_ERROR);
    $path = '/www/storage/app/backups/upstream-20261022/manifest.private';
    $diagnostics = ['manifest_exists' => file_exists($path), 'manifest_readable' => is_readable($path)];
    $manifest = json_decode(file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
    $diagnostics += ['manifest_object' => is_array($manifest), 'machine_matches' => ($manifest['machine_id'] ?? null) === 21,
        'routes_array' => is_array($manifest['routes'] ?? null), 'route_count' => is_array($manifest['routes'] ?? null) ? count($manifest['routes']) : 0];
    if (($allocation['machine_id'] ?? null) !== 21 || ($manifest['machine_id'] ?? null) !== 21
        || count($allocation['routes'] ?? []) !== 41 || count($manifest['routes'] ?? []) !== 41) {
        throw new RuntimeException('scope_invalid');
    }
    $approved = [];
    foreach ($manifest['routes'] as $row) {
        if (isset($approved[$row['key']])) { throw new RuntimeException('duplicate_mapping'); }
        $approved[$row['key']] = $row;
    }
    $snapshot = Illuminate\Support\Facades\DB::transaction(static function () use ($allocation, $approved, &$stage) {
        $rows = [];
        foreach ($allocation['routes'] as $row) {
            $stage = 'mapping';
            $expected = $approved[$row['key']] ?? null;
            if (!$expected || $row['backend_id'] !== $expected['backend_id'] || $row['public_id'] !== $expected['public_id']) {
                throw new RuntimeException('unapproved_mapping');
            }
            $backend = App\Models\Server::findOrFail($row['backend_id']);
            $public = App\Models\Server::findOrFail($row['public_id']);
            if ($backend->machine_id !== 21 || (int) $public->parent_id !== $backend->id
                || !in_array('upstream-extension-backend', $backend->tags ?? [], true)
                || !in_array('upstream-extension-public', $public->tags ?? [], true)) {
                throw new RuntimeException('mapping_changed');
            }
            $stage = 'read_fields';
            $backendFields = ['id', 'machine_id', 'parent_id', 'type', 'tags', 'group_ids', 'rate', 'enabled', 'custom_outbounds', 'custom_routes'];
            $publicFields = ['id', 'parent_id', 'type', 'tags', 'group_ids', 'rate', 'show', 'enabled'];
            $runtimeFields = array_flip(['created_at', 'updated_at', 'u', 'd', 'last_check_at', 'last_push_at', 'last_seen_at', 'load_status', 'metrics', 'online', 'online_conn']);
            $state = [
                'backend' => array_diff_key($backend->getRawOriginal(), $runtimeFields),
                'public' => array_diff_key($public->getRawOriginal(), $runtimeFields),
            ];
            $stateHash = hash('sha256', json_encode(upstream_prepare_stable_value($state), JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION | JSON_UNESCAPED_LINE_TERMINATORS));
            $rows[] = [
                'key' => $row['key'],
                'backend' => $backend->only($backendFields),
                'public' => $public->only($publicFields),
                'backend_raw' => array_intersect_key($backend->getRawOriginal(), array_flip($backendFields)),
                'public_raw' => array_intersect_key($public->getRawOriginal(), array_flip($publicFields)),
                'state' => $state,
                'state_sha256' => $stateHash,
            ];
        }
        return ['machine_id' => 21, 'routes' => $rows];
    });
    echo json_encode($snapshot, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION);
} catch (Throwable $error) {
    // No exception message, SQL, source row, or framework stack may leave capture.
    echo json_encode(['error' => 'snapshot_failed', 'stage' => $stage, 'diagnostics' => $diagnostics], JSON_THROW_ON_ERROR);
    exit(1);
}
