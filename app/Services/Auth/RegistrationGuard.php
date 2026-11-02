<?php

namespace App\Services\Auth;

use App\Exceptions\ApiException;
use App\Models\User;
use App\Utils\CacheKey;
use Illuminate\Contracts\Cache\LockTimeoutException;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Log;

// Decision: .agents/notes/implemented/feature/2026-11-03-registration-abuse-defense.md
class RegistrationGuard
{
    public function enabled(): bool
    {
        return (bool) admin_setting('registration_guard_enable', true);
    }

    public static function email(string $email): string
    {
        return strtolower(trim($email));
    }

    public function key(string $scope, string $identity): string
    {
        return 'registration_guard:' . $scope . ':' . hash_hmac('sha256', $identity, (string) config('app.key'));
    }

    public function deny(string $reason, string $message, int $status = 429): never
    {
        request()->attributes->set('registration_guard_reason', $reason);
        throw new ApiException($message, $status);
    }

    public function locked(string $scope, string $identity, callable $callback): mixed
    {
        try {
            return Cache::lock($this->key('lock:' . $scope, $identity), 10)->block(2, $callback);
        } catch (LockTimeoutException) {
            $this->deny('busy', '请求较多，请稍后重试。');
        }
    }

    /** Atomic sliding window; rejected requests do not extend a window. */
    public function consume(string $scope, string $identity, int $limit, int $seconds): void
    {
        $limit = max(1, min(500, $limit));
        $seconds = max(1, min(86400, $seconds));
        $this->locked($scope, $identity, function () use ($scope, $identity, $limit, $seconds) {
            $key = $this->key($scope, $identity);
            $now = now()->getTimestamp();
            $events = array_values(array_filter(Cache::get($key, []), fn ($time) => $time > $now - $seconds));
            if (count($events) >= $limit) {
                $this->deny('rate_limit', '操作过于频繁，请稍后重试。');
            }
            $events[] = $now;
            Cache::put($key, $events, $seconds);
        });
    }

    public function before(Request $request, string $operation): void
    {
        $input = $request->input('email', '');
        $email = self::email(is_string($input) ? $input : '');
        $request->merge(['email' => $email]);
        $ip = $request->ip() ?? 'unknown';
        // Independent IP and email buckets: changing email cannot reset IP quotas.
        $limits = match ($operation) {
            'send' => [[5, 600], [20, 3600], [50, 86400]],
            'register' => [[10, 60], [60, 3600], [100, 86400]],
            default => [[5, 600], [20, 3600]],
        };
        foreach ($limits as [$limit, $seconds]) {
            $this->consume($operation . ':ip:' . $seconds, $ip, $limit, $seconds);
        }
        if ($operation === 'register' || ($operation === 'send' && !User::byEmail($email)->exists())) {
            if ((bool) admin_setting('stop_register', false)) {
                $this->deny('registration_closed', '当前暂停新用户注册。', 403);
            }
            $domain = substr(strrchr($email, '@') ?: '', 1);
            $blocked = array_map('strtolower', (array) admin_setting('registration_blocked_email_domains', []));
            $allowed = array_map([self::class, 'email'], (array) admin_setting('registration_allowed_emails', []));
            if (in_array($domain, $blocked, true) && !in_array($email, $allowed, true)) {
                $this->deny('email_domain', '此邮箱暂不支持新用户注册，请更换邮箱或联系支持。', 403);
            }
        }
        if ($operation === 'send') {
            foreach ([[1, 60], [5, 3600], [10, 86400]] as [$limit, $seconds]) {
                $this->consume('send:email:' . $seconds, $email, $limit, $seconds);
            }
        }
    }

    /** Reserve before inserting the account; a failed insert keeps its reservation. */
    public function reserveRegistration(Request $request): void
    {
        if (!(bool) admin_setting('register_limit_by_ip_enable', false)) {
            return;
        }
        $ip = $request->ip() ?? 'unknown';
        $this->consume('accepted:ip:hour', $ip, (int) admin_setting('register_limit_count', 3), (int) admin_setting('register_limit_expire', 60) * 60);
        $this->consume('accepted:ip:day', $ip, (int) admin_setting('register_limit_daily_count', 10), 86400);
    }

    /** Shared by signup and recovery: attempts cannot be reset by resending a code. */
    public function consumeEmailCode(string $email, mixed $code): bool
    {
        $email = self::email($email);
        return $this->locked('email-code', $email, function () use ($email, $code) {
            $this->consume('verify:email:300', $email, 5, 300);
            $key = CacheKey::get('EMAIL_VERIFY_CODE', $email);
            $expected = Cache::get($key);
            if (!is_scalar($code) || !preg_match('/^[0-9]{6}$/D', (string) $code) || $expected === null
                || !hash_equals((string) $expected, (string) $code)) {
                return false;
            }
            // Consume before the database write, including on downstream failure.
            Cache::forget($key);
            return true;
        });
    }

    public function audit(Request $request, string $operation, int $status): void
    {
        $input = $request->input('email', '');
        $email = self::email(is_string($input) ? $input : '');
        $domain = substr(strrchr($email, '@') ?: '', 1);
        $domain = preg_match('/^[a-z0-9.-]{1,253}$/D', $domain) ? $domain : 'invalid';
        $context = [
            'request_id' => $request->attributes->get('registration_guard_id'),
            'operation' => $operation, 'status' => $status,
            'user_id' => $request->attributes->get('registration_guard_user_id'),
            'reason' => $request->attributes->get('registration_guard_reason', $status < 400 ? 'accepted' : 'rejected'),
            'email_domain' => $domain,
            'email_hash' => $this->key('email', $email),
            'ip_hash' => $this->key('ip', $request->ip() ?? 'unknown'),
        ];
        Log::channel('registration')->info('registration_event', $context);
        if ($operation !== 'register' || $status >= 400 || $domain === 'invalid') return;
        // One warning per domain/hour, no automatic ban of popular/shared domains.
        $this->locked('domain-observation', $domain, function () use ($domain) {
            $key = $this->key('domain-observation', $domain);
            $now = now()->getTimestamp();
            $times = array_values(array_filter(Cache::get($key, []), fn ($t) => $t > $now - 3600));
            $times[] = $now;
            Cache::put($key, array_slice($times, -100), 3600);
            if (count($times) >= 8 && Cache::add($this->key('domain-alert', $domain), true, 3600)) {
                Log::channel('registration')->warning('registration_domain_velocity', ['email_domain' => $domain, 'count_1h' => count($times)]);
            }
        });
    }
}
