<?php

namespace App\Http\Controllers\V1\Desktop;

use App\Exceptions\ClientApiException;
use App\Http\Controllers\Controller;
use App\Http\Controllers\V1\User\InviteController as WebsiteInvites;
use App\Models\User;
use App\Services\InviteService;
use App\Support\ClientApiResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Validator;

class InviteController extends Controller
{
    private function user(Request $request): User
    {
        $user = User::findOrFail($request->user()->id);
        if ($user->banned) {
            throw new ClientApiException('ACCOUNT_BANNED', '账号已停用，请联系客服', 403);
        }
        return $user;
    }

    public function index(Request $request)
    {
        $this->user($request);
        $data = json_decode(app(WebsiteInvites::class)->fetch($request)->getContent(), true)['data'];
        $stats = $data['stat'];
        $limit = max(0, (int) admin_setting('invite_gen_limit', 5));
        $open = !(bool) admin_setting('stop_register', 0);
        $rate = (int) $stats[3];
        $rates = admin_setting('commission_distribution_enable', 0)
            ? array_map(fn($level) => (int) floor($rate * (float) admin_setting('commission_distribution_l' . $level, 0) / 100), [1, 2, 3])
            : [$rate];
        return ClientApiResponse::success($request, [
            'codes' => array_map(fn($code) => [
                'code' => $code['code'], 'created_at' => $code['created_at'], 'visits' => (int) ($code['pv'] ?? 0),
            ], $data['codes']),
            'stats' => ['registered' => (int) $stats[0], 'total_commission' => (int) $stats[1],
                'pending_commission' => (int) $stats[2], 'available_commission' => (int) $stats[4]],
            'rules' => ['generation_limit' => $limit, 'can_generate' => $open && count($data['codes']) < $limit,
                'registration_open' => $open, 'reusable' => (bool) admin_setting('invite_never_expire', 0),
                'commission_rates' => $rates],
        ]);
    }

    public function generate(Request $request)
    {
        $user = $this->user($request);
        if (admin_setting('stop_register', 0)) {
            throw new ClientApiException('INVITE_REGISTRATION_CLOSED', '网站暂未开放注册，请稍后再邀请', 409);
        }
        $lock = Cache::lock('desktop-invite:' . $user->id, 30);
        if (!$lock->get()) {
            throw new ClientApiException('INVITE_BUSY', '邀请码正在生成，请稍后刷新查看', 409);
        }
        try {
            if (!app(InviteService::class)->create($user)) {
                throw new ClientApiException('INVITE_LIMIT_REACHED', '已达到可用邀请码数量上限，请使用已有邀请码', 409);
            }
            return $this->index($request);
        } finally {
            $lock->release();
        }
    }

    public function details(Request $request)
    {
        $this->user($request);
        if (Validator::make($request->all(), ['page' => 'sometimes|integer|min:1|max:100000'])->fails()) {
            throw new ClientApiException('INVITE_INVALID_PAGE', '页码无效，请刷新后重试', 422);
        }
        $page = $request->integer('page', 1);
        // Force a bounded page size; never forward arbitrary website query parameters.
        $request->merge(['current' => $page, 'page_size' => 10]);
        $data = json_decode(app(WebsiteInvites::class)->details($request)->getContent(), true);
        return ClientApiResponse::success($request, [
            'items' => array_map(fn($item) => [
                'id' => $item['id'], 'order_amount' => $item['order_amount'],
                'commission' => $item['get_amount'], 'created_at' => $item['created_at'],
            ], $data['data']),
            'total' => (int) $data['total'], 'page' => $page, 'page_size' => 10,
        ]);
    }
}
