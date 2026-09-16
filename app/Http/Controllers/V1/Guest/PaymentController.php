<?php

namespace App\Http\Controllers\V1\Guest;

use App\Http\Controllers\Controller;
use App\Models\Order;
use App\Services\OrderService;
use App\Services\PaymentService;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use App\Services\Plugin\HookManager;

class PaymentController extends Controller
{
    public function notify($method, $uuid, Request $request)
    {
        HookManager::call('payment.notify.before', [$method, $uuid, $request]);
        try {
            $paymentService = new PaymentService($method, null, $uuid);
            $verify = $paymentService->notify($request->input());
            if (!$verify) {
                HookManager::call('payment.notify.failed', [$method, $uuid, $request]);
                return $this->fail([422, 'verify error']);
            }
            // A verified event that does not represent a paid order needs only
            // an acknowledgement (for example an unpaid Checkout session).
            if (!empty($verify['skip_order'])) {
                return $verify['custom_result'] ?? 'success';
            }
            HookManager::call('payment.notify.verified', $verify);
            if (!$this->handle($verify['trade_no'], $verify['callback_no'])) {
                return $this->fail([400, 'handle error']);
            }
            return (isset($verify['custom_result']) ? $verify['custom_result'] : 'success');
        } catch (\Exception $e) {
            Log::error($e);
            return $this->fail([500, 'fail']);
        }
    }

    private function handle($tradeNo, $callbackNo)
    {
        return \Illuminate\Support\Facades\DB::transaction(function () use ($tradeNo, $callbackNo) {
            $order = Order::where('trade_no', $tradeNo)->lockForUpdate()->first();
            if (!$order) {
                return false;
            }
            if ($order->status !== Order::STATUS_PENDING) {
                return true;
            }
            $orderService = new OrderService($order);
            if (!$orderService->paid($callbackNo)) {
                throw new \RuntimeException('Payment fulfilment failed');
            }

            HookManager::call('payment.notify.success', $order);
            return true;
        });
    }
}
