<?php
declare(strict_types=1);
namespace XboardUpstreamGuard;

use App\Models\Server;
use Illuminate\Support\Facades\DB;

class Rejected extends \RuntimeException {}
function reject(string $reason): never { throw new Rejected($reason); }
function fields(mixed $row, array $expected): void {
    if (!is_array($row)) reject('invalid_schema');
    $keys=array_keys($row); sort($keys); sort($expected);
    if ($keys !== $expected) reject('invalid_schema');
}
function validate(array $manifest, array $request): array {
    fields($manifest, ['machine_id','routes']);
    fields($request, ['schema','machine_id','routes']);
    if ($manifest['machine_id'] !== 21 || $request['schema'] !== 1 || $request['machine_id'] !== 21 ||
        !is_array($manifest['routes']) || !array_is_list($manifest['routes']) || count($manifest['routes']) !== 41 ||
        !is_array($request['routes']) || !array_is_list($request['routes']) || count($request['routes']) < 1 || count($request['routes']) > 41) reject('invalid_scope');
    $approved=[];
    foreach ($manifest['routes'] as $row) {
        fields($row, ['key','backend_id','public_id']);
        if (!is_string($row['key']) || preg_match('/^U(?:0[1-9]|[1-3][0-9]|4[01])$/D', $row['key']) !== 1 || isset($approved[$row['key']])) reject('invalid_scope');
        $number=(int)substr($row['key'],1);
        if ($row['backend_id'] !== 357+2*$number || $row['public_id'] !== 358+2*$number) reject('invalid_scope');
        $approved[$row['key']]=$row;
    }
    $reasons=['expired_or_near_expiry','quota_exhausted','missing_or_ambiguous_source','source_changed_requires_acceptance',
        'metadata_stale','known_expiry','runtime_identity_scope_invalid','runtime_identity_mapping_invalid',
        'runtime_public_key_mismatch','runtime_identity_timeout','runtime_tls_failed','runtime_identity_tool_unavailable',
        'runtime_certificate_invalid','runtime_tcp_unreachable','runtime_identity_check_failed'];
    $seen=[];
    foreach ($request['routes'] as $row) {
        fields($row, ['key','backend_id','public_id','reason']);
        if (!is_string($row['key']) || isset($seen[$row['key']]) || !isset($approved[$row['key']]) ||
            $row['backend_id'] !== $approved[$row['key']]['backend_id'] || $row['public_id'] !== $approved[$row['key']]['public_id'] ||
            !in_array($row['reason'], $reasons, true)) reject('unapproved_mapping');
        $seen[$row['key']]=true;
    }
    return $request['routes'];
}
function withdraw(array $manifest, array $request): array {
    $routes=validate($manifest,$request);
    return DB::transaction(function() use($routes) {
        $changed=[];
        foreach ($routes as $row) {
            $backend=Server::query()->lockForUpdate()->findOrFail($row['backend_id']);
            $public=Server::query()->lockForUpdate()->findOrFail($row['public_id']);
            if ($backend->machine_id !== 21 || $public->parent_id !== $backend->id ||
                !in_array('upstream-extension-backend',$backend->tags ?? [],true) ||
                !in_array('upstream-extension-public',$public->tags ?? [],true)) reject('mapping_changed');
            if ($public->show || $backend->enabled) {
                $public->update(['show'=>false]);
                $backend->update(['enabled'=>false]);
                $changed[]=$row['key'];
            }
        }
        return ['withdrawn'=>$changed];
    });
}
if (!defined('XBOARD_UPSTREAM_GUARD_APPLY_LIBRARY_ONLY')) {
    ini_set('display_errors','0');
    try {
        $manifest=json_decode(base64_decode('__XBOARD_GUARD_MANIFEST_BASE64__',true),true,512,JSON_THROW_ON_ERROR);
        $request=json_decode(base64_decode('__XBOARD_GUARD_REQUEST_BASE64__',true),true,512,JSON_THROW_ON_ERROR);
        if (!is_array($manifest) || !is_array($request)) reject('invalid_schema');
        validate($manifest,$request);
        require '/www/vendor/autoload.php';
        $app=require '/www/bootstrap/app.php';
        $app->make(\Illuminate\Contracts\Console\Kernel::class)->bootstrap();
        echo json_encode(withdraw($manifest,$request),JSON_THROW_ON_ERROR);
    } catch (\Throwable $error) {
        echo json_encode(['error'=>$error instanceof Rejected ? $error->getMessage() : 'withdrawal_failed'],JSON_THROW_ON_ERROR);
        exit(1);
    }
}
