<?php

namespace App\Services;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;
use ReCaptcha\ReCaptcha;

class CaptchaService
{
    /**
     * 验证人机验证码
     *
     * @param Request $request 请求对象
     * @return array [是否通过, 错误消息]
     */
    public function verify(Request $request): array
    {
        if (!(int) admin_setting('captcha_enable', 0)) {
            return [true, null];
        }

        $captchaType = admin_setting('captcha_type', 'recaptcha');

        return match ($captchaType) {
            'turnstile' => $this->verifyTurnstile($request),
            'recaptcha-v3' => $this->verifyRecaptchaV3($request),
            'recaptcha' => $this->verifyRecaptcha($request),
            default => [false, [400, __('Invalid captcha type')]]
        };
    }

    /**
     * 验证 Cloudflare Turnstile
     *
     * @param Request $request
     * @return array
     */
    private function verifyTurnstile(Request $request): array
    {
        $token = $request->input('turnstile_token');
        if (!is_string($token) || $token === '' || strlen($token) > 2048) {
            return $this->turnstileFailure($request, 'missing_token');
        }
        try {
            $response = Http::connectTimeout(3)->timeout(8)->post('https://challenges.cloudflare.com/turnstile/v0/siteverify', [
                'secret' => admin_setting('turnstile_secret_key'),
                'response' => $token,
                'remoteip' => $request->ip(),
            ]);
            if (!$response->successful() || !is_array($result = $response->json())) {
                return $this->turnstileFailure($request, 'service_unavailable', 503);
            }
        } catch (\Throwable) {
            return $this->turnstileFailure($request, 'service_unavailable', 503);
        }
        if (($result['success'] ?? false) !== true) {
            $codes = (array) ($result['error-codes'] ?? []);
            $reason = in_array('timeout-or-duplicate', $codes, true) ? 'expired_or_used' : 'verification_failed';
            return $this->turnstileFailure($request, $reason);
        }
        $hosts = (array) admin_setting('turnstile_allowed_hostnames', array_merge(config('website.entry_hosts', []), config('website.compatible_hosts', [])));
        $hostname = $result['hostname'] ?? null;
        if (!is_string($hostname) || !in_array($hostname, $hosts, true) || $hostname !== $request->getHost()) {
            return $this->turnstileFailure($request, 'hostname_mismatch');
        }
        // Existing third-party themes can explicitly retain an empty action until upgraded.
        $action = (string) admin_setting('turnstile_action', 'passport');
        if (($result['action'] ?? '') !== $action) {
            return $this->turnstileFailure($request, 'action_mismatch');
        }
        return [true, null];
    }

    private function turnstileFailure(Request $request, string $reason, int $status = 400): array
    {
        $request->attributes->set('registration_guard_reason', 'captcha_' . $reason);
        return [false, [$status, $status === 503
            ? '人机验证服务暂时不可用，请稍后重新点击发送或注册。'
            : '人机验证未完成或已过期，请重新点击发送或注册进行验证。']];
    }

    /**
     * 验证 Google reCAPTCHA v3
     *
     * @param Request $request
     * @return array
     */
    private function verifyRecaptchaV3(Request $request): array
    {
        $recaptchaV3Token = $request->input('recaptcha_v3_token');
        if (!$recaptchaV3Token) {
            return [false, [400, __('Invalid code is incorrect')]];
        }

        $recaptcha = new ReCaptcha(admin_setting('recaptcha_v3_secret_key'));
        $recaptchaResp = $recaptcha->verify($recaptchaV3Token, $request->ip());

        if (!$recaptchaResp->isSuccess()) {
            return [false, [400, __('Invalid code is incorrect')]];
        }

        // 检查分数阈值（如果有的话）
        $score = $recaptchaResp->getScore();
        $threshold = admin_setting('recaptcha_v3_score_threshold', 0.5);
        if ($score < $threshold) {
            return [false, [400, __('Invalid code is incorrect')]];
        }

        return [true, null];
    }

    /**
     * 验证 Google reCAPTCHA v2
     *
     * @param Request $request
     * @return array
     */
    private function verifyRecaptcha(Request $request): array
    {
        $recaptchaData = $request->input('recaptcha_data');
        if (!$recaptchaData) {
            return [false, [400, __('Invalid code is incorrect')]];
        }

        $recaptcha = new ReCaptcha(admin_setting('recaptcha_key'));
        $recaptchaResp = $recaptcha->verify($recaptchaData);

        if (!$recaptchaResp->isSuccess()) {
            return [false, [400, __('Invalid code is incorrect')]];
        }

        return [true, null];
    }
} 