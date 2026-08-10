<?php

namespace App\Http\Controllers\V1\Desktop;

use App\Exceptions\ClientApiException;
use App\Http\Controllers\Controller;
use App\Models\ClientDevice;
use App\Models\User;
use App\Services\Client\ClientConfigService;
use App\Support\ClientApiResponse;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Http\Response;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Carbon;
use Illuminate\Support\Str;
use Throwable;

class ClientController extends Controller
{
    public function __construct(private readonly ClientConfigService $configService)
    {
    }

    public function config(Request $request): JsonResponse|Response
    {
        $format = strtolower((string) $request->input('format', 'mihomo'));
        $delivery = strtolower((string) $request->input('delivery', 'url'));
        if (!in_array($format, ['mihomo', 'clash-meta'], true)) {
            throw new ClientApiException('VALIDATION_ERROR', '不支持的配置格式', 422, [
                'format' => ['仅支持 mihomo 或 clash-meta'],
            ]);
        }
        if (!in_array($delivery, ['url', 'inline'], true)) {
            throw new ClientApiException('VALIDATION_ERROR', '不支持的配置交付方式', 422, [
                'delivery' => ['仅支持 url 或 inline'],
            ]);
        }

        $generated = $this->configService->generate($request->user(), $request);
        $revision = 'sha256:' . $generated['sha256'];
        $ifNoneMatch = trim((string) $request->header('If-None-Match'), ' "');
        $clientRevision = trim((string) $request->input('revision'));
        if (in_array($generated['sha256'], [$ifNoneMatch, str_replace('sha256:', '', $clientRevision)], true)) {
            return response('', 304)->header('ETag', '"' . $generated['sha256'] . '"');
        }

        if ($delivery === 'inline') {
            return $this->yamlResponse($generated);
        }

        $grant = Str::random(64);
        $ttl = max(60, (int) config('client.config_download_ttl', 300));
        $device = $request->attributes->get('client_device');
        Cache::put($this->grantKey($grant), [
            ...$generated,
            'user_id' => $request->user()->id,
            'client_device_id' => $device->id,
        ], $ttl);

        return ClientApiResponse::success($request, [
            'format' => 'mihomo',
            'delivery' => 'url',
            'revision' => $revision,
            'download_url' => route('desktop.client.config.download', ['grant' => $grant]),
            'url_expires_at' => now('UTC')->addSeconds($ttl)->format('Y-m-d\TH:i:s\Z'),
            'sha256' => $generated['sha256'],
            'content_type' => 'application/yaml',
            'refresh_interval' => 3600,
        ]);
    }

    public function download(Request $request, string $grant): Response
    {
        $cached = Cache::get($this->grantKey($grant));
        if (!is_array($cached)) {
            throw new ClientApiException('CONFIG_DOWNLOAD_EXPIRED', '配置下载地址已过期', 404);
        }

        $device = ClientDevice::query()
            ->whereKey($cached['client_device_id'] ?? null)
            ->where('user_id', $cached['user_id'] ?? null)
            ->where('status', ClientDevice::STATUS_ACTIVE)
            ->first();
        $user = User::query()->find($cached['user_id'] ?? null);
        if (!$device || !$user || !$user->isAvailable()) {
            throw new ClientApiException('SUBSCRIPTION_UNAVAILABLE', '当前订阅或设备不可用', 403);
        }

        return $this->yamlResponse($cached);
    }

    public function version(Request $request): JsonResponse
    {
        $platform = strtolower((string) $request->input('platform', 'windows'));
        $architecture = strtolower((string) $request->input('arch', 'x64'));
        $channel = strtolower((string) $request->input('channel', 'stable'));
        $currentVersion = ltrim((string) $request->input('current_version', ''), 'vV');

        if (!in_array($platform, ['windows', 'macos', 'linux'], true)) {
            throw new ClientApiException('VALIDATION_ERROR', '不支持的客户端平台', 422);
        }
        if (!in_array($architecture, ['x64', 'arm64'], true)) {
            throw new ClientApiException('VALIDATION_ERROR', '不支持的客户端架构', 422);
        }
        if (!in_array($channel, ['stable', 'beta'], true)) {
            throw new ClientApiException('VALIDATION_ERROR', '不支持的更新渠道', 422);
        }

        $prefix = $channel === 'beta' ? $platform . '_beta' : $platform;
        $latestVersion = ltrim((string) admin_setting($prefix . '_version', ''), 'vV');
        $minSupportedVersion = ltrim((string) admin_setting($prefix . '_min_supported_version', ''), 'vV');
        $updateAvailable = $latestVersion !== '' && (
            $currentVersion === '' || version_compare($currentVersion, $latestVersion, '<')
        );
        $mandatory = $currentVersion !== '' && $minSupportedVersion !== ''
            && version_compare($currentVersion, $minSupportedVersion, '<');

        return ClientApiResponse::success($request, [
            'update_available' => $updateAvailable,
            'mandatory' => $mandatory,
            'latest_version' => $latestVersion ?: null,
            'build_number' => (int) admin_setting($prefix . '_build_number', 0),
            'min_supported_version' => $minSupportedVersion ?: null,
            'platform' => $platform,
            'architecture' => $architecture,
            'channel' => $channel,
            'download_url' => admin_setting($prefix . '_download_url'),
            'size_bytes' => (int) admin_setting($prefix . '_size_bytes', 0),
            'sha256' => admin_setting($prefix . '_sha256'),
            'signature' => admin_setting($prefix . '_signature'),
            'release_notes' => admin_setting($prefix . '_release_notes', ''),
            'published_at' => $this->formatPublishedAt(admin_setting($prefix . '_published_at')),
        ]);
    }

    private function formatPublishedAt(mixed $value): ?string
    {
        if (blank($value)) {
            return null;
        }

        try {
            return Carbon::parse((string) $value)->utc()->format('Y-m-d\TH:i:s\Z');
        } catch (Throwable) {
            return null;
        }
    }

    private function yamlResponse(array $config): Response
    {
        $response = response($config['content'], 200, [
            'Content-Type' => 'application/yaml; charset=utf-8',
            'Cache-Control' => 'private, no-store',
            'ETag' => '"' . $config['sha256'] . '"',
        ]);
        foreach ($config['headers'] ?? [] as $name => $value) {
            if ($value) {
                $response->headers->set($name, $value);
            }
        }
        return $response;
    }

    private function grantKey(string $grant): string
    {
        return 'client_config_download:' . hash('sha256', $grant);
    }
}
