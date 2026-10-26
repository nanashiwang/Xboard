<?php
declare(strict_types=1);

/** Bounded, manually approved one-off maintenance. No network/key discovery. */
namespace XboardUpstreamRecovery;

use App\Models\Server;
use Illuminate\Support\Facades\DB;

final class Rejected extends \RuntimeException {}
function reject(string $reason): never { throw new Rejected($reason); }
function exact(object $value, array $keys): void {
    $actual = array_keys(get_object_vars($value)); sort($actual); sort($keys);
    if ($actual !== $keys) reject('unexpected_fields');
}
function canonical(mixed $value): string {
    $normalize = function (mixed $item) use (&$normalize): mixed {
        if (is_object($item)) {
            $fields = get_object_vars($item); ksort($fields, SORT_STRING);
            $result = new \stdClass();
            foreach ($fields as $key => $child) $result->$key = $normalize($child);
            return $result;
        }
        if (is_array($item)) {
            if (array_is_list($item)) return array_map($normalize, $item);
            ksort($item, SORT_STRING);
            return (object) array_map($normalize, $item);
        }
        if (is_float($item) && !is_finite($item)) reject('invalid_number');
        return $item;
    };
    return json_encode($normalize($value), JSON_THROW_ON_ERROR | JSON_UNESCAPED_UNICODE |
        JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION | JSON_UNESCAPED_LINE_TERMINATORS);
}
function digest(mixed $value): string { return hash('sha256', canonical($value)); }
function isDigest(mixed $value): bool { return is_string($value) && preg_match('/^[a-f0-9]{64}$/D', $value) === 1; }
function decode(string $value): mixed { return json_decode($value, false, 512, JSON_THROW_ON_ERROR); }
function copyObject(object $value): object { return decode(canonical($value)); }

final class Recovery {
    public const ALLOCATION_SHA256 = '552b6a820def4a1a8c9e7775691205c1dc8a87ed9eeeb7a77943daf02c605769';
    public const RUNTIME = ['created_at', 'updated_at', 'u', 'd', 'last_check_at', 'last_push_at',
        'last_seen_at', 'load_status', 'metrics', 'online', 'online_conn'];
    private array $scope = [];

    public function __construct(string $allocationPath, object $manifest) {
        if (!hash_equals(self::ALLOCATION_SHA256, hash_file('sha256', $allocationPath))) reject('allocation_digest_mismatch');
        $allocation = decode(file_get_contents($allocationPath));
        if ($allocation->machine_id !== 21 || $manifest->machine_id !== 21 ||
            !is_array($allocation->routes) || count($allocation->routes) !== 41 ||
            !isset($manifest->routes) || !is_array($manifest->routes) || count($manifest->routes) !== 41) reject('scope_invalid');
        $approved = [];
        foreach ($manifest->routes as $row) {
            if (!is_object($row) || !isset($row->key, $row->backend_id, $row->public_id) || isset($approved[$row->key])) reject('manifest_ambiguous');
            $approved[$row->key] = $row;
        }
        foreach ($allocation->routes as $i => $row) {
            $key = sprintf('U%02d', $i + 1);
            if ($row->key !== $key || $row->backend_id !== 359 + 2 * $i || $row->public_id !== 360 + 2 * $i ||
                !isset($approved[$key]) || $approved[$key]->backend_id !== $row->backend_id || $approved[$key]->public_id !== $row->public_id) reject('scope_invalid');
            $this->scope[$key] = $row;
        }
    }

    public static function state(Server $backend, Server $public): object {
        $strip = static function (Server $model): object {
            $raw = $model->getRawOriginal();
            foreach (self::RUNTIME as $field) unset($raw[$field]);
            return (object) $raw;
        };
        return (object) ['backend' => $strip($backend), 'public' => $strip($public)];
    }

    private function scope(string $key): object {
        if (!isset($this->scope[$key])) reject('unapproved_key');
        return $this->scope[$key];
    }

    private static function flag(mixed $value): bool {
        if (!in_array($value, [0, 1, false, true], true)) reject('invalid_boolean_storage');
        return (bool) $value;
    }

    private static function storedFlag(mixed $old, bool $value): mixed {
        self::flag($old);
        return is_bool($old) ? $value : (int) $value;
    }

    private function validateState(string $key, object $state): void {
        exact($state, ['backend', 'public']);
        if (!is_object($state->backend) || !is_object($state->public)) reject('invalid_state');
        $scope = $this->scope($key); $b = $state->backend; $p = $state->public;
        if (($b->id ?? null) !== $scope->backend_id || ($p->id ?? null) !== $scope->public_id ||
            ($b->machine_id ?? null) !== 21 || ($p->parent_id ?? null) !== $b->id) reject('mapping_changed');
        foreach ([[$b, 'upstream-extension-backend'], [$p, 'upstream-extension-public']] as [$row, $tag]) {
            if (!isset($row->tags) || !is_string($row->tags)) reject('invalid_tags');
            $tags = decode($row->tags);
            if (!is_array($tags) || !in_array($tag, $tags, true)) reject('mapping_changed');
        }
        if (!property_exists($b, 'enabled') || !property_exists($b, 'show') ||
            !property_exists($p, 'show') || !property_exists($p, 'enabled') || self::flag($b->show)) reject('invalid_visibility');
        self::flag($b->enabled); self::flag($p->show); self::flag($p->enabled);
        if (($b->type ?? null) !== 'vless' || ($p->type ?? null) !== 'vless') reject('inbound_type_changed');
        if (!isset($b->custom_outbounds) || !is_string($b->custom_outbounds)) reject('invalid_outbound_storage');
    }

    private function pair(string $key): array {
        $scope = $this->scope($key);
        $rows = Server::query()->whereIn('id', [$scope->backend_id, $scope->public_id])->orderBy('id')->lockForUpdate()->get()->keyBy('id');
        if ($rows->count() !== 2) reject('missing_route');
        $backend = $rows->get($scope->backend_id); $public = $rows->get($scope->public_id);
        $this->validateState($key, self::state($backend, $public));
        return [$backend, $public];
    }

    /** Only this explicit CLI path emits private raw configuration. */
    public function privateSnapshot(object $request): object {
        exact($request, ['schema', 'keys']);
        if ($request->schema !== 1 || !is_array($request->keys) || !$request->keys || count($request->keys) > 41 || count(array_unique($request->keys, SORT_REGULAR)) !== count($request->keys)) reject('snapshot_scope_invalid');
        foreach ($request->keys as $key) { if (!is_string($key)) reject('unapproved_key'); $this->scope($key); }
        sort($request->keys, SORT_STRING);
        return DB::transaction(function () use ($request) {
            $result = [];
            foreach ($request->keys as $key) {
                [$backend, $public] = $this->pair($key); $state = self::state($backend, $public);
                $result[] = (object) ['key' => $key, 'backend_id' => $backend->id, 'public_id' => $public->id,
                    'state' => $state, 'state_sha256' => digest($state)];
            }
            return (object) ['schema' => 1, 'machine_id' => 21, 'private' => true, 'routes' => $result];
        });
    }

    public static function planDigest(array $rows): string {
        $bound = [];
        foreach ($rows as $row) $bound[] = (object) ['key' => $row->key, 'backend_id' => $row->backend_id,
            'public_id' => $row->public_id, 'original_state_sha256' => $row->original_state_sha256, 'candidate_digest' => $row->candidate_digest];
        usort($bound, static fn($a, $b) => strcmp($a->key, $b->key));
        return digest((object) ['schema' => 1, 'machine_id' => 21, 'routes' => $bound]);
    }

    public static function globalIp(mixed $ip): bool {
        if (!is_string($ip) || !defined('FILTER_FLAG_GLOBAL_RANGE') ||
            filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_GLOBAL_RANGE) === false) return false;
        $packed = inet_pton($ip);
        if ($packed === false) return false;
        // Global-range flags do not exclude multicast. A proxy endpoint must be
        // global unicast; both IPv4 and IPv6 multicast are explicitly rejected.
        if (strlen($packed) === 4 && ord($packed[0]) >= 224) return false;
        if (strlen($packed) === 16 && ord($packed[0]) === 255) return false;
        return true;
    }

    private static function validPin(mixed $pin): bool {
        if (!is_string($pin)) return false;
        $bytes = base64_decode($pin, true);
        return $bytes !== false && strlen($bytes) === 32 && base64_encode($bytes) === $pin;
    }

    /** Construct from the exact old raw JSON; no arbitrary replacement config. */
    private function candidateOutbound(object $row): string {
        if (!is_object($row->identity)) reject('invalid_identity');
        exact($row->identity, ['key', 'ip', 'port', 'sni', 'pin']); $identity = $row->identity;
        if ($identity->key !== $row->key || !self::globalIp($identity->ip) ||
            !is_int($identity->port) || $identity->port < 1 || $identity->port > 65535 || !is_string($identity->sni) || !$identity->sni ||
            preg_match('/[\s\x00-\x1f]/u', $identity->sni) || strlen($identity->sni) > 253) reject('invalid_identity');
        if (!isDigest($row->candidate_digest) || !hash_equals($row->candidate_digest, digest($identity))) reject('candidate_digest_mismatch');
        $outbounds = decode($row->original_state->backend->custom_outbounds);
        if (!is_array($outbounds) || count($outbounds) !== 1 || !is_object($outbounds[0])) reject('invalid_outbound_shape');
        $entry = $outbounds[0]; $scope = $this->scope($row->key);
        if (($entry->protocol ?? null) !== $scope->upstream_type || !property_exists($entry, 'settings')) reject('outbound_protocol_changed');
        $wasString = is_string($entry->settings);
        $settings = $wasString ? decode($entry->settings) : $entry->settings;
        if (!is_object($settings) || !is_string($settings->server ?? null) || !isset($settings->server_port) ||
            $settings->server_port !== $identity->port || !is_object($settings->tls ?? null)) reject('invalid_settings');
        if (property_exists($settings, 'type') && $settings->type !== $scope->upstream_type) reject('outbound_protocol_changed');
        $tls = $settings->tls;
        if (($tls->enabled ?? null) !== true || ($tls->insecure ?? null) !== false || ($tls->server_name ?? null) !== $identity->sni) reject('tls_boundary_changed');
        if ($scope->upstream_type === 'vless') {
            if ($identity->pin !== null || property_exists($tls, 'certificate_public_key_sha256')) reject('ca_boundary_changed');
        } else {
            $pins = $tls->certificate_public_key_sha256 ?? null;
            if (!is_array($pins) || count($pins) !== 1 || !self::validPin($pins[0]) || !self::validPin($identity->pin)) reject('pin_shape_invalid');
            $tls->certificate_public_key_sha256 = [$identity->pin];
        }
        $settings->server = $identity->ip;
        $entry->settings = $wasString ? canonical($settings) : $settings;
        return canonical($outbounds);
    }

    public function derivedStates(object $row): array {
        $this->validateState($row->key, $row->original_state);
        if (!isDigest($row->original_state_sha256) || !hash_equals($row->original_state_sha256, digest($row->original_state))) reject('baseline_digest_mismatch');
        $withdrawn = copyObject($row->original_state);
        $withdrawn->backend->enabled = self::storedFlag($withdrawn->backend->enabled, false);
        $withdrawn->public->show = self::storedFlag($withdrawn->public->show, false);
        if ($row->identity === null) {
            if (!isDigest($row->candidate_digest) || !hash_equals($row->candidate_digest, digest(null))) reject('candidate_digest_mismatch');
            return ['original' => $row->original_state, 'withdrawn' => $withdrawn];
        }
        $hidden = copyObject($withdrawn);
        $hidden->backend->custom_outbounds = $this->candidateOutbound($row);
        $hidden->backend->enabled = self::storedFlag($hidden->backend->enabled, true);
        $published = copyObject($hidden); $published->public->show = $row->original_state->public->show;
        return ['original' => $row->original_state, 'withdrawn' => $withdrawn, 'hidden' => $hidden, 'published' => $published];
    }

    public function execute(object $request): object {
        exact($request, ['schema', 'action', 'plan_id', 'routes']);
        if ($request->schema !== 1 || !in_array($request->action, ['withdraw', 'apply_hidden', 'publish', 'rollback'], true) ||
            !is_array($request->routes) || !$request->routes || count($request->routes) > 41 || !isDigest($request->plan_id)) reject('request_invalid');
        $seen = []; $states = [];
        foreach ($request->routes as $row) {
            if (!is_object($row)) reject('route_invalid');
            exact($row, ['key', 'backend_id', 'public_id', 'original_state', 'original_state_sha256', 'identity', 'candidate_digest', 'expected_sha256']);
            if (!is_string($row->key) || isset($seen[$row->key]) || !isDigest($row->expected_sha256) || !is_object($row->original_state)) reject('route_invalid');
            $scope = $this->scope($row->key);
            if ($row->backend_id !== $scope->backend_id || $row->public_id !== $scope->public_id) reject('mapping_changed');
            $seen[$row->key] = true; $states[$row->key] = $this->derivedStates($row);
            if ($row->identity === null && in_array($request->action, ['apply_hidden', 'publish'], true)) reject('no_approved_candidate');
        }
        if (!hash_equals($request->plan_id, self::planDigest($request->routes))) reject('plan_digest_mismatch');
        usort($request->routes, static fn($a, $b) => strcmp($a->key, $b->key));
        return DB::transaction(function () use ($request, $states) {
            $result = [];
            foreach ($request->routes as $row) {
                [$backend, $public] = $this->pair($row->key);
                $current = self::state($backend, $public); $currentHash = digest($current);
                if (!hash_equals($row->expected_sha256, $currentHash)) reject('concurrent_config_drift');
                $stage = $states[$row->key];
                $allowed = match ($request->action) {
                    'withdraw' => ['original', 'withdrawn'], 'apply_hidden' => ['withdrawn'],
                    'publish' => ['hidden'], 'rollback' => ['original', 'withdrawn', 'hidden', 'published']
                };
                $allowed = array_values(array_filter($allowed, static fn($name) => array_key_exists($name, $stage)));
                if (!in_array($currentHash, array_map(static fn($name) => digest($stage[$name]), $allowed), true)) reject('phase_state_mismatch');
                $target = $stage[match ($request->action) { 'withdraw', 'rollback' => 'withdrawn', 'apply_hidden' => 'hidden', 'publish' => 'published' }];
                // Only the maintenance-owned columns can be written. Eloquent
                // preserves existing node notifications and REST polling behavior.
                $this->write($backend, ['custom_outbounds' => $target->backend->custom_outbounds, 'enabled' => $target->backend->enabled]);
                $this->write($public, ['show' => $target->public->show]);
                $backend->refresh(); $public->refresh();
                $actual = self::state($backend, $public);
                if (!hash_equals(digest($target), digest($actual))) reject('post_write_mismatch');
                $result[] = ['key' => $row->key, 'backend_id' => $row->backend_id, 'public_id' => $row->public_id,
                    'state_sha256' => digest($actual)];
            }
            return (object) ['schema' => 1, 'action' => $request->action, 'plan_id' => $request->plan_id, 'routes' => $result];
        });
    }

    private function write(Server $model, array $fields): void {
        $model->setRawAttributes(array_replace($model->getAttributes(), $fields));
        if ($model->isDirty(array_keys($fields))) $model->save();
    }
}

if (!defined('XBOARD_UPSTREAM_RECOVERY_LIBRARY_ONLY')) {
    ini_set('display_errors', '0');
    try {
        $arguments = array_slice($argv, 1);
        if ($arguments !== [] && $arguments !== ['--private-snapshot']) reject('invalid_arguments');
        $raw = file_get_contents('php://stdin', false, null, 0, 12 * 1024 * 1024 + 1);
        if (strlen($raw) > 12 * 1024 * 1024) reject('input_too_large');
        $request = decode($raw); if (!is_object($request)) reject('request_invalid');
        require '/www/vendor/autoload.php';
        $app = require '/www/bootstrap/app.php';
        $app->make(\Illuminate\Contracts\Console\Kernel::class)->bootstrap();
        $manifestPath = __DIR__.'/manifest.private';
        $manifestStat = @lstat($manifestPath);
        if ($manifestStat === false || ($manifestStat['mode'] & 0170000) !== 0100000 ||
            ($manifestStat['mode'] & 0077) !== 0 || $manifestStat['size'] > 20 * 1024 * 1024 ||
            (function_exists('posix_geteuid') && $manifestStat['uid'] !== posix_geteuid())) reject('manifest_invalid');
        $manifest = decode(file_get_contents($manifestPath));
        if (!is_object($manifest)) reject('manifest_invalid');
        $engine = new Recovery(__DIR__.'/allocation.json', $manifest);
        $result = $arguments === ['--private-snapshot'] ? $engine->privateSnapshot($request) : $engine->execute($request);
        echo canonical($result).PHP_EOL;
    } catch (\Throwable $error) {
        echo json_encode(['error' => $error instanceof Rejected ? $error->getMessage() : 'execution_failed'], JSON_THROW_ON_ERROR).PHP_EOL;
        exit(1);
    }
}
