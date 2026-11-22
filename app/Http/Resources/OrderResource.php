<?php

namespace App\Http\Resources;

use App\Models\Order;
use App\Services\PlanService;
use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;

/**
 * @mixin Order
 */
class OrderResource extends JsonResource
{
    /**
     * Transform the resource into an array.
     *
     * @return array<string, mixed>
     */
    public function toArray(Request $request): array
    {
        return [
            ...parent::toArray($request),
            // Bundled themes still use the old API name for credit returned to the balance.
            'refund_amount' => $this->surplus_credit,
            'period' => PlanService::getLegacyPeriod((string)$this->period),
            'plan' => $this->product_type === Order::WALLET_TOPUP ? ['id' => 0, 'name' => '钱包充值'] : $this->whenLoaded('plan', fn() => PlanResource::make($this->plan)),
        ];
    }
}
