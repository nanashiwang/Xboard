<?php

namespace Plugin\Stripe;

use App\Exceptions\ApiException;

final class UsdPricing
{
    /** The input and output are currency minor units; never use float arithmetic. */
    public static function calculate(int $cnyCents, string $rate, string $percent, string $fixed): array
    {
        $rateUnits = self::decimal($rate, 6);
        $basisPoints = self::decimal($percent, 2);
        $fixedCents = self::decimal($fixed, 2);
        if ($cnyCents <= 0 || $cnyCents > 100000000 || $rateUnits < 1000000 || $rateUnits > 20000000
            || $basisPoints > 1000 || $fixedCents > 10000) {
            throw new ApiException('Stripe 美元报价参数超出范围，请检查汇率和成本预算');
        }
        // ceil((CNY / rate + fixed fee) / (1 - percentage)), in USD cents.
        $numerator = ($cnyCents * 1000000 + $fixedCents * $rateUnits) * 10000;
        $denominator = $rateUnits * (10000 - $basisPoints);
        $usdCents = intdiv($numerator + $denominator - 1, $denominator);
        if ($usdCents < 50 || $usdCents > 99999999) {
            throw new ApiException('Stripe 美元应付金额须在 0.50 至 999999.99 美元之间');
        }
        return ['currency' => 'usd', 'amount' => $usdCents, 'cny_amount' => $cnyCents,
            'exchange_rate' => $rate, 'cost_percent' => $percent, 'cost_fixed_usd' => $fixed];
    }

    private static function decimal(string $value, int $scale): int
    {
        if (!preg_match('/^\d{1,4}(?:\.\d{1,' . $scale . '})?$/D', $value)) {
            throw new ApiException('Stripe 汇率和成本预算必须是非负十进制数字');
        }
        $parts = explode('.', $value, 2);
        return (int) $parts[0] * (10 ** $scale) + (int) str_pad($parts[1] ?? '', $scale, '0');
    }
}
