<?php

namespace Plugin\Stripe;

use App\Contracts\PaymentInterface;
use App\Exceptions\ApiException;
use App\Models\Order;
use App\Models\Plan;
use Illuminate\Support\Facades\DB;
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
            'secret_key' => ['label' => 'Stripe API 密钥', 'type' => 'string', 'description' => '支持 rk_test_/rk_live_ 受限密钥（推荐）及 sk_test_/sk_live_。不要填写 pk_ 公钥。'],
            'webhook_secret' => ['label' => 'Webhook 签名密钥', 'type' => 'string', 'description' => '填写对应回调端点的 whsec_ 密钥，测试与正式环境分别配置。'],
            'currency' => ['label' => '收款币种', 'type' => 'select', 'default' => 'usd', 'select_options' => [['value' => 'usd', 'label' => '美元 USD'], ['value' => 'cny', 'label' => '人民币 CNY']], 'description' => '站点仍按人民币记账，美元模式使用以下报价参数。'],
            'exchange_rate' => ['label' => '结算汇率：1 USD 对应 CNY', 'type' => 'string', 'description' => '例如 6.7075，最多 6 位小数；调整只影响尚未报价的订单。'],
            'cost_percent' => ['label' => '美元售价比例成本预算（%）', 'type' => 'string', 'default' => '4.4', 'description' => '美国国际卡标准成本预算，不代表每张卡的实际费率。'],
            'cost_fixed_usd' => ['label' => '美元售价固定成本预算（USD）', 'type' => 'string', 'default' => '0.30'],
            'catalog_usd' => ['label' => '美元商品价格映射（JSON）', 'type' => 'string', 'description' => '已配置的套餐商品和价格对应关系；通常无需修改。'],
        ];
    }

    private function credentials(): array
    {
        $key = trim((string) $this->getConfig('secret_key', ''));
        $secret = trim((string) $this->getConfig('webhook_secret', ''));
        if (!preg_match('/^[sr]k_(test|live)_\S+$/', $key) || !str_starts_with($secret, 'whsec_')) {
            throw new ApiException('请先配置 Stripe Secret Key 和 Webhook 签名密钥');
        }
        if (!in_array(strtolower((string) $this->getConfig('currency', 'cny')), ['cny', 'usd'], true)
            || strtoupper((string) admin_setting('currency', 'CNY')) !== 'CNY') {
            throw new ApiException('Stripe 支持美元或人民币收款，站点记账币种须为人民币');
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
        $currency = strtolower((string) $this->getConfig('currency', 'cny'));
        $productData = ['name' => '订单 ' . $metadata['trade_no']];
        $quote = null;
        if ($currency === 'usd') {
            $dbOrder = Order::where('trade_no', $order['trade_no'])->first();
            if (!$dbOrder || (int) $dbOrder->payment_id !== (int) $this->getConfig('id')
                || (int) $dbOrder->total_amount + (int) $dbOrder->handling_amount !== $amount) {
                throw new ApiException('Stripe 报价订单或金额不匹配');
            }
            // The first quote survives rate/config changes and concurrent retries.
            $quoteId = hash('sha256', implode('|', [$dbOrder->id, $this->getConfig('uuid'), $amount, hash('sha256', $key)]));
            $quote = DB::table('v2_stripe_quotes')->where('id', $quoteId)->first();
            if (!$quote) {
                $pricing = UsdPricing::calculate($amount, trim((string) $this->getConfig('exchange_rate', '')),
                    trim((string) $this->getConfig('cost_percent', '4.4')), trim((string) $this->getConfig('cost_fixed_usd', '0.30')));
                DB::table('v2_stripe_quotes')->insertOrIgnore(array_merge($pricing, [
                    'id' => $quoteId, 'order_id' => $dbOrder->id, 'payment_id' => (int) $this->getConfig('id'), 'created_at' => time(),
                ]));
                $quote = DB::table('v2_stripe_quotes')->where('id', $quoteId)->first();
            }
            $amount = (int) $quote->amount;
            $metadata['quote_id'] = $quoteId;
            $period = Plan::getAvailablePeriods()[$dbOrder->period]['name'] ?? $dbOrder->period;
            $productData = ['name' => ($dbOrder->plan?->name ?? 'taige 套餐') . ' · ' . $period,
                'description' => sprintf('人民币参考金额 ¥%.2f；结算汇率 1 USD = %s CNY。美元售价含 %s%% + $%s 的支付成本预算。发卡行可能另收换汇费。',
                    $quote->cny_amount / 100, $quote->exchange_rate, $quote->cost_percent, $quote->cost_fixed_usd)];
        }
        $params = [
            'mode' => 'payment',
            'adaptive_pricing' => ['enabled' => false],
            'integration_identifier' => 'xboard-usd-kqmvzjtr',
            'client_reference_id' => $metadata['trade_no'],
            'metadata' => $metadata,
            'payment_intent_data' => ['metadata' => $metadata],
            'line_items' => [[
                'price_data' => ['currency' => $currency, 'unit_amount' => $amount, 'product_data' => $productData],
                'quantity' => 1,
            ]],
            'success_url' => $order['return_url'],
            'cancel_url' => $order['return_url'],
        ];
        if ($quote) {
            $params['custom_text']['submit']['message'] = $productData['name'] . '。' . $productData['description'];
            // Provisioned catalog prices are used only if they exactly match the quote.
            // Discounts/balance deductions receive an inline price on the same product.
            $catalog = $this->getConfig('catalog_usd', []);
            if (is_string($catalog)) {
                $catalog = json_decode($catalog, true);
            }
            $entry = is_array($catalog) ? ($catalog[(string) $dbOrder->plan_id] ?? null) : null;
            if (is_array($entry) && !empty($entry['product'])) {
                $price = $entry['prices'][$dbOrder->period] ?? null;
                if (is_array($price) && (int) ($price['amount'] ?? 0) === $amount && !empty($price['id'])) {
                    $params['line_items'][0] = ['price' => $price['id'], 'quantity' => 1];
                } else {
                    unset($params['line_items'][0]['price_data']['product_data']);
                    $params['line_items'][0]['price_data']['product'] = $entry['product'];
                }
            }
        }
        $idempotency = 'xboard-' . hash('sha256', $key . $this->getConfig('uuid') . json_encode($params) . gmdate('Y-m-d'));
        $response = Http::asForm()->withToken($key)->withHeaders([
            'Stripe-Version' => '2026-07-29.dahlia', 'Idempotency-Key' => $idempotency,
        ])->connectTimeout(10)->timeout(30)->post('https://api.stripe.com/v1/checkout/sessions', $params);
        $url = $response->json('url');
        if (!$response->successful() || !is_string($url) || !str_starts_with($url, 'https://checkout.stripe.com/')) {
            throw new ApiException('Stripe 创建支付失败，请检查密钥、收款币种权限和订单金额');
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
        if ((bool) $event->livemode !== (bool) preg_match('/^[sr]k_live_/', $key)) {
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
        if (!$order || $session->mode !== 'payment' || !in_array($session->currency, ['cny', 'usd'], true)
            || $session->client_reference_id !== $tradeNo
            || (string) ($session->metadata->payment_id ?? '') !== (string) $this->getConfig('id')
            || (int) $order->payment_id !== (int) $this->getConfig('id')
            || !is_string($session->payment_intent) || !str_starts_with($session->payment_intent, 'pi_')) {
            return false;
        }
        $baseAmount = (int) $order->total_amount + (int) $order->handling_amount;
        if ($session->currency === 'usd') {
            $quote = DB::table('v2_stripe_quotes')->where('id', (string) ($session->metadata->quote_id ?? ''))->first();
            if (!$quote || (int) $quote->order_id !== (int) $order->id
                || (int) $quote->payment_id !== (int) $order->payment_id || $quote->currency !== 'usd'
                || (int) $quote->cny_amount !== $baseAmount || (int) $quote->amount !== (int) $session->amount_total) {
                return false;
            }
        } elseif ((int) $session->amount_total !== $baseAmount || isset($session->metadata->quote_id)) {
            return false;
        }
        return ['trade_no' => $tradeNo, 'callback_no' => $session->payment_intent];
    }
}
