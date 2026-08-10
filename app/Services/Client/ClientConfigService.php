<?php

namespace App\Services\Client;

use App\Exceptions\ClientApiException;
use App\Models\User;
use App\Protocols\ClashMeta;
use App\Services\Plugin\HookManager;
use App\Services\ServerService;
use Illuminate\Http\Request;

class ClientConfigService
{
    public function generate(User $user, Request $request): array
    {
        if (!$user->isAvailable()) {
            throw new ClientApiException(
                'SUBSCRIPTION_UNAVAILABLE',
                '当前订阅不可用',
                403,
                ['reason' => $this->unavailableReason($user)]
            );
        }

        HookManager::call('client.subscribe.before');
        $servers = ServerService::getAvailableServers($user);
        $servers = HookManager::filter('client.subscribe.servers', $servers, $user, $request);

        $clientVersion = (string) $request->header('X-Client-Version', '');
        $protocol = app()->make(ClashMeta::class, [
            'user' => $user,
            'servers' => $servers,
            'clientName' => 'meta',
            'clientVersion' => $clientVersion ?: null,
            'userAgent' => $request->userAgent(),
        ]);
        $response = $protocol->handle();
        $content = (string) $response->getContent();

        return [
            'content' => $content,
            'sha256' => hash('sha256', $content),
            'headers' => [
                'subscription-userinfo' => $response->headers->get('subscription-userinfo'),
                'profile-update-interval' => $response->headers->get('profile-update-interval'),
                'content-disposition' => $response->headers->get('content-disposition'),
            ],
        ];
    }

    private function unavailableReason(User $user): string
    {
        if ($user->banned) {
            return 'banned';
        }
        if (!$user->plan_id) {
            return 'no_plan';
        }
        if ($user->expired_at && $user->expired_at <= time()) {
            return 'expired';
        }
        if ($user->getRemainingTraffic() <= 0) {
            return 'traffic_exhausted';
        }
        return 'unavailable';
    }
}
