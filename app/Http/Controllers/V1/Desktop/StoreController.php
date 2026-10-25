<?php

namespace App\Http\Controllers\V1\Desktop;

use App\Exceptions\ApiException;
use App\Exceptions\ClientApiException;
use App\Http\Controllers\Controller;
use App\Http\Controllers\V1\User\OrderController;
use App\Http\Resources\PlanResource;
use App\Models\Order;
use App\Models\Payment;
use App\Models\Plan;
use App\Models\User;
use App\Services\OrderService;
use App\Services\PlanService;
use App\Services\UserService;
use App\Support\ClientApiResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Validator;

class StoreController extends Controller
{
    public function catalog(Request $request)
    {
        return ClientApiResponse::success($request, $this->plans($request));
    }

    public function index(Request $request)
    {
        $user = $this->user($request);
        $pending = Order::with('plan')->where('user_id', $user->id)
            ->whereIn('status', [Order::STATUS_PENDING, Order::STATUS_PROCESSING])->latest('id')->first();
        return ClientApiResponse::success($request, [
            'plans' => $this->plans($request, $user),
            'balance' => (int) $user->balance,
            'order' => $pending ? $this->orderData($pending) : null,
            'methods' => Payment::where('enable', true)->orderBy('sort')->get([
                'id', 'name', 'handling_fee_fixed', 'handling_fee_percent',
            ]),
        ]);
    }

    public function save(Request $request)
    {
        $this->validateInput($request, [
            'plan_id' => 'required|integer',
            'period' => 'required|in:' . implode(',', array_keys(Plan::LEGACY_PERIOD_MAPPING)),
            'coupon_code' => 'nullable|string|max:128',
        ]);
        $user = $this->user($request);
        // Serialize desktop submissions, including retries after an uncertain network result.
        $lock = Cache::lock('desktop-store:' . $user->id, 60);
        if (!$lock->get()) {
            throw new ClientApiException('STORE_BUSY', '订单正在处理，请稍后刷新', 409);
        }
        try {
            if (app(UserService::class)->isNotCompleteOrderByUserId($user->id)) {
                throw new ClientApiException('STORE_PENDING_ORDER', '请先处理未完成订单', 409);
            }
            $plan = Plan::find($request->integer('plan_id'));
            if (!$plan || !(new PlanService($plan))->isPlanAvailableForUser($plan, $user)) {
                throw new ClientApiException('STORE_PLAN_UNAVAILABLE', '套餐不可购买，请刷新列表');
            }
            try {
                $order = OrderService::createFromRequest($user, $plan, $request->input('period'), $request->input('coupon_code'));
            } catch (ApiException $e) {
                // Do not forward plugin or upstream exception text to the WebView.
                throw new ClientApiException('STORE_ORDER_REJECTED', '下单未完成，请检查周期、优惠码或换购规则');
            }
            return ClientApiResponse::success($request, $this->orderData($order->fresh('plan')));
        } finally {
            $lock->release();
        }
    }

    public function detail(Request $request)
    {
        return ClientApiResponse::success($request, $this->orderData($this->order($request)));
    }

    public function cancel(Request $request)
    {
        return $this->locked($request, fn() => $this->cancelOrder($request));
    }

    private function cancelOrder(Request $request)
    {
        $this->order($request);
        $response = app(OrderController::class)->cancel($request);
        if (!$response->isSuccessful()) {
            throw new ClientApiException('STORE_ORDER_CHANGED', '订单状态已变化，请刷新');
        }
        return ClientApiResponse::success($request, $this->orderData($this->order($request)));
    }

    public function checkout(Request $request)
    {
        return $this->locked($request, fn() => $this->checkoutOrder($request));
    }

    private function checkoutOrder(Request $request)
    {
        $this->validateInput($request, ['method' => 'nullable|integer']);
        $this->order($request);
        try {
            $response = app(OrderController::class)->checkout($request);
        } catch (ApiException $e) {
            throw new ClientApiException('STORE_PAYMENT_FAILED', '支付请求未完成，请刷新订单后重试');
        }
        if (!$response->isSuccessful()) {
            throw new ClientApiException('STORE_PAYMENT_FAILED', '支付请求未完成，请刷新订单后重试');
        }
        $result = json_decode($response->getContent(), true);
        $type = $result['type'] ?? null;
        $data = $result['data'] ?? null;
        $kind = match ($type) { -1 => 'submitted', 0 => 'qr', 1 => 'url', default => null };
        if (!$kind || ($kind !== 'submitted' && (!is_string($data) || strlen($data) > 4096 || $data === ''))) {
            throw new ClientApiException('STORE_PAYMENT_UNSUPPORTED', '此支付方式请在网站订单中心继续');
        }
        if ($kind === 'url' && (!$this->safeUrl($data))) {
            throw new ClientApiException('STORE_PAYMENT_UNSUPPORTED', '此支付方式请在网站订单中心继续');
        }
        return ClientApiResponse::success($request, [
            'kind' => $kind, 'data' => $kind === 'submitted' ? null : $data,
            'order' => $this->orderData($this->order($request)),
        ]);
    }

    private function safeUrl(string $url): bool
    {
        $parts = parse_url($url);
        return $parts && in_array(strtolower($parts['scheme'] ?? ''), ['https', 'http'], true)
            && !empty($parts['host']) && !isset($parts['user']) && !isset($parts['pass'])
            && !preg_match('/[\x00-\x20\x7f]/', $url);
    }

    private function locked(Request $request, \Closure $operation)
    {
        $lock = Cache::lock('desktop-store:' . $this->user($request)->id, 60);
        if (!$lock->get()) {
            throw new ClientApiException('STORE_BUSY', '订单正在处理，请稍后刷新', 409);
        }
        try {
            return $operation();
        } finally {
            $lock->release();
        }
    }

    private function plans(Request $request, ?User $user = null): array
    {
        $plans = (new PlanService(new Plan()))->getAvailablePlans();
        if ($user?->plan_id && ($current = Plan::find($user->plan_id)) && $current->renew) {
            $plans = $plans->push($current)->unique('id');
        }
        return $plans->map(function (Plan $plan) use ($request, $user) {
            $resource = (new PlanResource($plan))->toArray($request);
            $periods = [];
            foreach (Plan::LEGACY_PERIOD_MAPPING as $legacy => $period) {
                if ($legacy === 'reset_price' || $resource[$legacy] === null) {
                    continue;
                }
                $periods[] = ['id' => $legacy, 'amount' => (int) round($resource[$legacy])];
            }
            return [
                'id' => $plan->id, 'name' => $plan->name,
                'description' => trim(html_entity_decode(strip_tags(preg_replace('/<br\s*\/?>|<\/(?:p|li|div)>/i', "\n", $resource['content'])), ENT_QUOTES | ENT_HTML5, 'UTF-8')),
                'transfer_gb' => $plan->transfer_enable, 'speed_mbps' => $plan->speed_limit,
                'device_limit' => $plan->device_limit, 'periods' => $periods,
                'current' => $user?->plan_id === $plan->id,
                'purchasable' => !$user || (new PlanService($plan))->isPlanAvailableForUser($plan, $user),
            ];
        })->values()->all();
    }

    private function user(Request $request): User
    {
        $user = User::findOrFail($request->user()->id);
        if ($user->banned) {
            throw new ClientApiException('ACCOUNT_BANNED', '账号已停用，请联系客服', 403);
        }
        return $user;
    }

    private function order(Request $request): Order
    {
        $this->validateInput($request, ['trade_no' => 'required|string|max:64']);
        $order = Order::with('plan')->where('user_id', $this->user($request)->id)
            ->where('trade_no', $request->input('trade_no'))->first();
        if (!$order) {
            throw new ClientApiException('STORE_ORDER_NOT_FOUND', '找不到订单，请刷新', 404);
        }
        return $order;
    }

    private function orderData(Order $order): array
    {
        return [
            'trade_no' => $order->trade_no, 'plan_name' => $order->plan?->name ?? '套餐已下架',
            'period' => PlanService::getLegacyPeriod($order->period), 'status' => (int) $order->status,
            'total_amount' => (int) $order->total_amount, 'balance_amount' => (int) $order->balance_amount,
            'discount_amount' => (int) $order->discount_amount, 'surplus_amount' => (int) $order->surplus_amount,
            'surplus_credit' => (int) $order->surplus_credit, 'handling_amount' => (int) $order->handling_amount,
            'account_balance' => (int) User::whereKey($order->user_id)->value('balance'),
        ];
    }

    private function validateInput(Request $request, array $rules): void
    {
        if (Validator::make($request->all(), $rules)->fails()) {
            throw new ClientApiException('STORE_INVALID_INPUT', '请选择有效套餐、周期和订单', 422);
        }
    }
}
