<?php

namespace App\Jobs;

use App\Exceptions\DedicatedExitUnavailableException;
use App\Models\Order;
use App\Services\OrderService;
use Illuminate\Bus\Queueable;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Bus\Dispatchable;
use Illuminate\Queue\InteractsWithQueue;
use Illuminate\Queue\SerializesModels;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Log;

class OrderHandleJob implements ShouldQueue
{
    use Dispatchable, InteractsWithQueue, Queueable, SerializesModels;
    protected $order;
    protected $tradeNo;

    public $tries = 3;
    public $timeout = 5;
    public const DEDICATED_EXIT_RETRY_SECONDS = 300;

    private static function dedicatedExitRetryKey(int $orderId): string
    {
        return 'order:dedicated-exit-retry:' . $orderId;
    }

    public static function isWaitingForDedicatedExit(int $orderId): bool
    {
        return Cache::has(self::dedicatedExitRetryKey($orderId));
    }
    /**
     * Create a new job instance.
     *
     * @return void
     */
    public function __construct($tradeNo)
    {
        $this->onQueue('order_handle');
        $this->tradeNo = $tradeNo;
    }

    /**
     * Execute the job.
     *
     * @return void
     */
    public function handle()
    {
        $order = Order::where('trade_no', $this->tradeNo)
            ->lockForUpdate()
            ->first();
        if (!$order) return;
        $orderService = new OrderService($order);
        switch ($order->status) {
            // cancel
            case Order::STATUS_PENDING:
                if ($order->created_at <= (time() - 3600 * 2)) {
                    $orderService->cancel();
                }
                break;
            case Order::STATUS_PROCESSING:
                if (self::isWaitingForDedicatedExit($order->id)) {
                    return;
                }
                try {
                    $orderService->open();
                    Cache::forget(self::dedicatedExitRetryKey($order->id));
                } catch (DedicatedExitUnavailableException $e) {
                    // open() has rolled back. The durable processing order is retried by check:order.
                    $retryAt = now()->addSeconds(self::DEDICATED_EXIT_RETRY_SECONDS);
                    Cache::put(self::dedicatedExitRetryKey($order->id), $retryAt->timestamp, $retryAt);
                    Log::warning($e->getMessage(), [
                        'order_id' => $order->id,
                        'reason' => 'dedicated_exit_unavailable',
                        'next_attempt_at' => $retryAt->toIso8601String(),
                    ]);
                }
                break;
        }
    }
}
