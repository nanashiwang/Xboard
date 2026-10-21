<?php
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
try {
    $dir = '/www/storage/app/backups/upstream-20261022';
    $manifest = json_decode(file_get_contents($dir.'/manifest.private'), true, 512, JSON_THROW_ON_ERROR);
    $request = json_decode(file_get_contents($dir.'/guard.request.json'), true, 512, JSON_THROW_ON_ERROR);
    $approved = array_column($manifest['routes'], null, 'key');
    $changed = Illuminate\Support\Facades\DB::transaction(function () use ($request, $approved, $manifest) {
        $changed = [];
        foreach ($request as $row) {
            $expected = $approved[$row['key']] ?? null;
            if (!$expected || $row['backend_id'] !== $expected['backend_id'] || $row['public_id'] !== $expected['public_id']) {
                throw new RuntimeException('unapproved_mapping');
            }
            $backend = App\Models\Server::findOrFail($row['backend_id']);
            $public = App\Models\Server::findOrFail($row['public_id']);
            if ($backend->machine_id !== $manifest['machine_id'] || $public->parent_id !== $backend->id
                || !in_array('upstream-extension-backend', $backend->tags ?? [], true)
                || !in_array('upstream-extension-public', $public->tags ?? [], true)) {
                throw new RuntimeException('mapping_changed');
            }
            if ($public->show || $backend->enabled) {
                $public->update(['show' => false]);
                $backend->update(['enabled' => false]);
                $changed[] = $row['key'];
            }
        }
        return $changed;
    });
    echo json_encode(['withdrawn' => $changed], JSON_THROW_ON_ERROR);
} catch (Throwable $error) {
    echo json_encode(['error' => get_class($error)], JSON_THROW_ON_ERROR);
    exit(1);
}
