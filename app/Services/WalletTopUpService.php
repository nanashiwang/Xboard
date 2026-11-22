<?php

namespace App\Services;

use App\Exceptions\ClientApiException;
use App\Models\Order;
use App\Models\Payment;
use App\Models\User;
use App\Utils\Helper;
use Illuminate\Support\Facades\DB;

class WalletTopUpService
{
    // These adapters verify and return the settled CNY amount (including fees).
    public const METHODS = ['EPay', 'StripeCheckout', 'AlipayF2F'];

    public static function create(User $user, int $amount, int $method): Order
    {
        return DB::transaction(function () use ($user, $amount, $method) {
            User::lockForUpdate()->findOrFail($user->id);
            if (app(UserService::class)->isNotCompleteOrderByUserId($user->id)) {
                throw new ClientApiException('STORE_PENDING_ORDER', '请先处理未完成订单', 409);
            }
            $payment = Payment::whereKey($method)->where('enable', true)
                ->whereIn('payment', self::METHODS)->first();
            if (!$payment) {
                throw new ClientApiException('STORE_PAYMENT_UNAVAILABLE', '此充值方式不可用，请刷新', 422);
            }
            return Order::create([
                'user_id' => $user->id, 'trade_no' => Helper::generateOrderNo(),
                'product_type' => Order::WALLET_TOPUP, 'type' => Order::TYPE_WALLET_TOPUP,
                'plan_id' => 0, 'period' => Order::WALLET_TOPUP, 'status' => Order::STATUS_PENDING,
                'total_amount' => $amount, 'payment_id' => $payment->id,
                'handling_amount' => (int) round($amount * $payment->handling_fee_percent / 100 + $payment->handling_fee_fixed),
            ]);
        }, 5);
    }

    // Caller holds the order row lock inside the payment notification transaction.
    public static function settle(Order $order, array $event, string $method, string $uuid): bool
    {
        if (!in_array($method, self::METHODS, true)
            || !Payment::whereKey($order->payment_id)->where('uuid', $uuid)->where('payment', $method)->exists()
            || ($event['paid_cents'] ?? null) !== (int) $order->total_amount + (int) $order->handling_amount
            || empty($event['callback_no'])) {
            return false;
        }
        if ($order->status === Order::STATUS_COMPLETED) {
            return $order->callback_no === (string) $event['callback_no'];
        }
        if (!in_array($order->status, [Order::STATUS_PENDING, Order::STATUS_CANCELLED], true)) {
            return false;
        }
        if (!app(UserService::class)->addBalance($order->user_id, $order->total_amount)) {
            throw new \RuntimeException('钱包入账失败');
        }
        $order->update(['status' => Order::STATUS_COMPLETED, 'paid_at' => time(), 'callback_no' => $event['callback_no']]);
        return true;
    }

    public static function cents(mixed $amount): ?int
    {
        if (!is_scalar($amount) || !preg_match('/^(\d{1,8})(?:\.(\d{1,2}))?$/D', (string) $amount, $parts)) {
            return null;
        }
        return (int) $parts[1] * 100 + (int) str_pad($parts[2] ?? '', 2, '0');
    }
}
