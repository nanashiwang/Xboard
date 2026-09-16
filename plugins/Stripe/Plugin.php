<?php

namespace Plugin\Stripe;

use App\Contracts\PaymentInterface;
use App\Exceptions\ApiException;
use App\Models\Order;
use App\Services\Plugin\AbstractPlugin;
use Illuminate\Support\Facades\Http;
use Stripe\Webhook;

class Plugin extends AbstractPlugin implements PaymentInterface
{
    public function boot(): void
    {
        $this->filter('available_payment_methods', function ($methods) {
            $methods['StripeCheckout'] = ['name' => 'Stripe Checkout', 'plugin_code' => $this->getPluginCode(), 'type' => 'plugin'];
            return $methods;
        });
    }

    public function form(): array
    {
        return [
            'secret_key' => ['label' => 'Stripe Secret Key', 'type' => 'string', 'description' => '先使用 sk_test_ 测试密钥；上线时替换为 sk_live_。不要填写 pk_ 公钥。'],
            'webhook_secret' => ['label' => 'Webhook 签名密钥', 'type' => 'string', 'description' => '填写对应回调端点的 whsec_ 密钥，测试与正式环境分别配置。'],
            'currency' => ['label' => '收款币种', 'type' => 'select', 'default' => 'cny', 'select_options' => ['cny' => '人民币 CNY'], 'description' => '与本站人民币价格一致，金额以分传给 Stripe，不自动换汇。'],
        ];
    }

    private function credentials(): array
    {
        $key = trim((string) $this->getConfig('secret_key', ''));
        $secret = trim((string) $this->getConfig('webhook_secret', ''));
        if (!preg_match('/^sk_(test|live)_\S+$/', $key) || !str_starts_with($secret, 'whsec_')) {
            throw new ApiException('请先配置 Stripe Secret Key 和 Webhook 签名密钥');
        }
        if (strtolower((string) $this->getConfig('currency', 'cny')) !== 'cny'
            || strtoupper((string) admin_setting('currency', 'CNY')) !== 'CNY') {
            throw new ApiException('Stripe 收款币种必须与本站人民币计价一致');
        }
        return [$key, $secret];
    }

    public function pay($order): array
    {
        [$key] = $this->credentials();
        $amount = (int) $order['total_amount'];
        if ($amount <= 0 || !$this->getConfig('id') || !$this->getConfig('uuid')) {
            throw new ApiException('Stripe 支付金额或通道配置无效');
        }
        $metadata = ['trade_no' => (string) $order['trade_no'], 'payment_id' => (string) $this->getConfig('id')];
        $params = [
            'mode' => 'payment',
            'payment_method_types' => ['card'],
            'client_reference_id' => $metadata['trade_no'],
            'metadata' => $metadata,
            'payment_intent_data' => ['metadata' => $metadata],
            'line_items' => [[
                'price_data' => ['currency' => 'cny', 'unit_amount' => $amount, 'product_data' => ['name' => '订单 ' . $metadata['trade_no']]],
                'quantity' => 1,
            ]],
            'success_url' => $order['return_url'],
            'cancel_url' => $order['return_url'],
        ];
        $idempotency = 'xboard-' . hash('sha256', $key . $this->getConfig('uuid') . json_encode($params));
        $response = Http::asForm()->withToken($key)->withHeaders([
            'Stripe-Version' => '2024-06-20', 'Idempotency-Key' => $idempotency,
        ])->connectTimeout(10)->timeout(30)->post('https://api.stripe.com/v1/checkout/sessions', $params);
        $url = $response->json('url');
        if (!$response->successful() || !is_string($url) || !str_starts_with($url, 'https://checkout.stripe.com/')) {
            throw new ApiException('Stripe 创建支付失败，请检查密钥、人民币收款权限和订单金额');
        }
        return ['type' => 1, 'data' => $url];
    }

    public function notify($params): array|bool
    {
        [$key, $secret] = $this->credentials();
        try {
            // Use the untouched body and Laravel request headers (Octane safe).
            $event = Webhook::constructEvent(request()->getContent(), (string) request()->header('Stripe-Signature'), $secret);
        } catch (\UnexpectedValueException | \Stripe\Exception\SignatureVerificationException $e) {
            return false;
        }
        if ((bool) $event->livemode !== str_starts_with($key, 'sk_live_')) {
            return false;
        }
        if (!in_array($event->type, ['checkout.session.completed', 'checkout.session.async_payment_succeeded'], true)) {
            return ['skip_order' => true];
        }
        $session = $event->data->object;
        if ($session->payment_status !== 'paid') {
            return ['skip_order' => true];
        }
        $tradeNo = (string) ($session->metadata->trade_no ?? '');
        $order = Order::where('trade_no', $tradeNo)->first();
        if (!$order || $session->mode !== 'payment' || $session->currency !== 'cny'
            || $session->client_reference_id !== $tradeNo
            || (string) ($session->metadata->payment_id ?? '') !== (string) $this->getConfig('id')
            || (int) $order->payment_id !== (int) $this->getConfig('id')
            || (int) $session->amount_total !== (int) $order->total_amount + (int) $order->handling_amount
            || !is_string($session->payment_intent) || !str_starts_with($session->payment_intent, 'pi_')) {
            return false;
        }
        return ['trade_no' => $tradeNo, 'callback_no' => $session->payment_intent];
    }
}
