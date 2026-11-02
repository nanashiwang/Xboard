<?php

/** One authorized service-address notice. Output only aggregate results. */
class HubAddressNotice
{
    public const SUBJECT = '卡皮巴拉访问地址更新｜请收藏新导航页';
    public const URL = 'https://capybarahub.fyi/';
    public const TEMPLATE = 'hubAddressUpdate20261103';
    public const CONTENT = "你好，卡皮巴拉用户：\n\n为方便你在访问入口调整时找到我们，我们启用了新的统一导航地址：\n\nhttps://capybarahub.fyi/\n\n请将这个地址加入浏览器书签，或保存本邮件。今后可从导航页进入应用、查找客户端下载入口。\n\n更换网页访问入口后，仍使用原来的卡皮巴拉账号；账号、套餐和剩余权益不会因本次地址更新而改变，无需重新注册。\n\n如果旧网址无法打开，请从新导航页进入应用。我们会持续优化访问体验与服务稳定性，继续为大家提供更可靠的服务。\n\n感谢你的理解与支持。\n卡皮巴拉";

    public function __construct(private string $directory, private int $delay = 500000) {}

    public function recipients(): array
    {
        $unique = []; $invalid = 0; $duplicates = 0;
        foreach (App\Models\User::orderBy('id')->get(['id', 'email']) as $user) {
            $email = strtolower(trim((string) $user->email));
            if (!filter_var($email, FILTER_VALIDATE_EMAIL)) { $invalid++; continue; }
            $key = hash('sha256', $email);
            if (isset($unique[$key])) { $duplicates++; continue; }
            $unique[$key] = ['id' => $user->id, 'email_hash' => $key, 'status' => 'pending'];
        }
        return ['targets' => $unique, 'invalid' => $invalid, 'duplicates' => $duplicates];
    }

    private function fingerprint(): string
    {
        return hash('sha256', self::SUBJECT . "\n" . self::URL . "\n" . self::CONTENT . "\n" . self::TEMPLATE);
    }

    private function ledgerPath(): string { return $this->directory . '/hub-address-notice-20261103.json'; }

    private function read(): ?array
    {
        if (!is_file($this->ledgerPath())) return null;
        $state = json_decode(file_get_contents($this->ledgerPath()), true, 512, JSON_THROW_ON_ERROR);
        if (($state['fingerprint'] ?? '') !== $this->fingerprint()) throw new RuntimeException('Notice content changed; stop before sending.');
        return $state;
    }

    private function save(array $state): void
    {
        $file = tempnam($this->directory, '.notice-');
        try {
            chmod($file, 0600);
            if (file_put_contents($file, json_encode($state, JSON_THROW_ON_ERROR)) === false || !rename($file, $this->ledgerPath())) {
                throw new RuntimeException('Cannot checkpoint notice.');
            }
        } finally { if (is_file($file)) unlink($file); }
    }

    private function accepted(string $email): bool
    {
        return App\Models\MailLog::where('subject', self::SUBJECT)->where('email', $email)
            ->whereIn('template_name', ['mail.default.' . self::TEMPLATE, 'db:' . self::TEMPLATE])
            ->whereNull('error')->exists();
    }

    public function status(): array
    {
        $recipients = $this->recipients();
        $state = $this->read();
        $counts = array_count_values(array_column($state['targets'] ?? [], 'status'));
        return [
            'subject' => self::SUBJECT, 'navigation_url' => self::URL,
            'eligible_unique_addresses' => count($recipients['targets']),
            'invalid_addresses' => $recipients['invalid'], 'duplicate_addresses' => $recipients['duplicates'],
            'snapshot_total' => $state ? count($state['targets']) : null,
            'counts' => (object) $counts,
            'smtp_accepted_logs' => App\Models\MailLog::where('subject', self::SUBJECT)
                ->where('template_name', 'mail.default.' . self::TEMPLATE)->whereNull('error')->count(),
            'smtp_error_logs' => App\Models\MailLog::where('subject', self::SUBJECT)
                ->where('template_name', 'mail.default.' . self::TEMPLATE)->whereNotNull('error')->count(),
            'template_available' => Illuminate\Support\Facades\View::exists('mail.default.' . self::TEMPLATE),
            'template_override' => App\Models\MailTemplate::where('name', self::TEMPLATE)->exists(),
            'mail_transport' => config('mail.driver'),
            'smtp_configured' => (bool) admin_setting('email_host') && (bool) admin_setting('email_from_address'),
        ];
    }

    public function sendBatch(int $limit = 25): array
    {
        if ($limit < 1 || $limit > 50) throw new RuntimeException('Invalid batch limit.');
        if (!is_dir($this->directory)) mkdir($this->directory, 0700, true);
        $lock = fopen($this->directory . '/hub-address-notice-20261103.lock', 'c');
        chmod($this->directory . '/hub-address-notice-20261103.lock', 0600);
        if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) throw new RuntimeException('Another notice sender is running.');
        try {
            if (App\Models\MailTemplate::where('name', self::TEMPLATE)->exists()) throw new RuntimeException('Unexpected notice template override.');
            $state = $this->read() ?? ['fingerprint' => $this->fingerprint(), 'started_at' => time(), 'targets' => $this->recipients()['targets']];
            $this->save($state);
            $attempts = 0;
            foreach ($state['targets'] as $key => &$target) {
                if (in_array($target['status'], ['sent', 'changed', 'failed', 'uncertain'], true)) continue;
                $user = App\Models\User::find($target['id']);
                $email = strtolower(trim((string) ($user?->email ?? '')));
                if (!hash_equals($key, hash('sha256', $email))) { $target['status'] = 'changed'; $this->save($state); continue; }
                if ($this->accepted($email)) { $target['status'] = 'sent'; $this->save($state); continue; }
                if ($target['status'] === 'attempting') { $target['status'] = 'uncertain'; $this->save($state); continue; }
                if ($attempts >= $limit) break;
                $target['status'] = 'attempting'; $this->save($state); $attempts++;
                try {
                    $log = App\Services\MailService::sendEmail([
                        'email' => $email, 'subject' => self::SUBJECT, 'template_name' => self::TEMPLATE,
                        'template_value' => ['name' => '卡皮巴拉', 'url' => self::URL, 'content' => self::CONTENT, 'content_mode' => 'text'],
                    ]);
                    $target['status'] = $log['error'] ? 'failed' : 'sent';
                } catch (Throwable $error) {
                    $target['status'] = $this->accepted($email) ? 'sent' : 'uncertain';
                }
                $this->save($state);
                if ($target['status'] !== 'sent') break; // Inspect a failed/ambiguous send before further attempts.
                if ($this->delay > 0) usleep($this->delay);
            }
            unset($target);
        } finally { flock($lock, LOCK_UN); fclose($lock); }
        return $this->status();
    }
}

if (getenv('HUB_NOTICE_OPERATION')) {
    require '/www/vendor/autoload.php';
    $app = require '/www/bootstrap/app.php';
    $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
    try {
        $operation = getenv('HUB_NOTICE_OPERATION');
        if (!in_array($operation, ['preview', 'send', 'status'], true)) throw new RuntimeException('Invalid operation.');
        $connection = Illuminate\Support\Facades\DB::connection();
        $database = $connection->getDatabaseName();
        if ($connection->getDriverName() !== 'sqlite' || !is_file($database)) throw new RuntimeException('Expected persistent SQLite database.');
        $notice = new HubAddressNotice(dirname($database) . '/operations');
        $status = $notice->status();
        if ($operation === 'send') {
            if ($status['mail_transport'] !== 'smtp' || !$status['smtp_configured'] || !$status['template_available']) throw new RuntimeException('Mail configuration/template is not ready.');
            config(['mail.timeout' => 20]);
            $status = $notice->sendBatch(25);
        }
        echo json_encode($status, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . PHP_EOL;
    } catch (Throwable $error) {
        // Raw SMTP/DB errors can contain addresses or credentials; retain them only in existing server logs.
        fwrite(STDERR, "Notice operation failed; inspect private server state before retrying.\n");
        exit(1);
    }
}
