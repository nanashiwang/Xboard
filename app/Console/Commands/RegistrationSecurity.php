<?php
namespace App\Console\Commands;

use App\Models\Setting;
use App\Support\Setting as Settings;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\{Cache, DB, Log};

class RegistrationSecurity extends Command
{
    protected $signature = 'security:registration {operation=inspect : inspect|apply|rollback|review} {--backup=registration-20261103 : Private snapshot name}';
    protected $description = 'Inspect, enable or roll back the reviewed registration policy without exposing secrets';
    private const POLICY = [
        'registration_guard_enable' => 1, 'email_verify' => 1,
        'register_limit_by_ip_enable' => 1, 'register_limit_count' => 3,
        'register_limit_expire' => 60, 'register_limit_daily_count' => 10,
        'registration_blocked_email_domains' => ['fldubai.com'],
        'captcha_enable' => 1, 'captcha_type' => 'turnstile',
        'turnstile_action' => 'passport',
        'turnstile_allowed_hostnames' => ['capybarago.uk', 'taige.us', 'board.taige.us'],
    ];
    private function values(): array
    {
        return Setting::whereIn('name', array_keys(self::POLICY))->get()->mapWithKeys(fn ($row) => [$row->name => $row->value])->all();
    }
    public function handle(): int
    {
        $operation = $this->argument('operation');
        if (!in_array($operation, ['inspect', 'apply', 'rollback', 'review'], true)) return self::INVALID;
        $name = $this->option('backup');
        if (!preg_match('/^[a-z0-9-]{1,64}$/D', $name)) return self::INVALID;
        $path = storage_path('app/security-backups/' . $name . '.json');
        if ($operation === 'apply' || $operation === 'rollback') {
            return Cache::lock('registration-security-config', 30)->block(5, function () use ($operation, $path) {
                $current = $this->values();
                if ($operation === 'apply') {
                    if (!(Cache::getStore() instanceof \Illuminate\Cache\RedisStore)) {
                        $this->error('Production policy requires a shared Redis cache.'); return self::FAILURE;
                    }
                    if (!admin_setting('turnstile_secret_key') || !admin_setting('turnstile_site_key')) {
                        $this->error('Existing Turnstile keys must be configured first.'); return self::FAILURE;
                    }
                    $desired = self::POLICY;
                    $desired['registration_blocked_email_domains'] = array_values(array_unique(array_merge(
                        (array) ($current['registration_blocked_email_domains'] ?? []), $desired['registration_blocked_email_domains'])));
                    if (is_file($path)) {
                        $snapshot = json_decode(file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
                        if ($current == $snapshot['after']) { $this->info('Policy already applied.'); return self::SUCCESS; }
                        $this->error('Snapshot exists; refuse to overwrite.'); return self::FAILURE;
                    }
                    if (!is_dir(dirname($path))) mkdir(dirname($path), 0700, true);
                    $stream = fopen($path, 'x'); chmod($path, 0600);
                    fwrite($stream, json_encode(['before' => $current, 'after' => $desired, 'created_at' => time(), 'review_after' => time()+604800], JSON_THROW_ON_ERROR));
                    fflush($stream); fclose($stream);
                } else {
                    if (!is_file($path)) { $this->error('Snapshot missing.'); return self::FAILURE; }
                    $snapshot = json_decode(file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
                    if ($current != $snapshot['after']) { $this->error('Settings changed since apply; refuse unsafe rollback.'); return self::FAILURE; }
                    $desired = $snapshot['before'];
                }
                DB::transaction(function () use ($desired) {
                    Setting::whereIn('name', array_diff(array_keys(self::POLICY), array_keys($desired)))->delete();
                    app(Settings::class)->save($desired);
                });
                if ($this->values() != $desired) throw new \RuntimeException('Policy verification failed');
                $this->info($operation . ' verified; snapshot: ' . $path);
                return self::SUCCESS;
            });
        }
        $values = $this->values();
        $values['allowed_email_count'] = count((array) admin_setting('registration_allowed_emails', []));
        $values['shared_cache'] = Cache::getStore() instanceof \Illuminate\Cache\RedisStore;
        $values['turnstile_keys_configured'] = (bool) admin_setting('turnstile_secret_key') && (bool) admin_setting('turnstile_site_key');
        $values['domain_review_due'] = is_file($path) && (json_decode(file_get_contents($path), true)['review_after'] ?? PHP_INT_MAX) <= time();
        if ($operation === 'review' && $values['domain_review_due']) {
            Log::channel('registration')->warning('registration_domain_policy_review_due', ['backup' => $name]);
        }
        $this->line(json_encode($values, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
        return self::SUCCESS;
    }
}
