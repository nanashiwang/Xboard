<?php

namespace App\Services;

use App\Jobs\SendTrafficExhaustedEmailJob;
use App\Models\User;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Support\Facades\DB;

class TrafficExhaustedReminderService
{
    public const RETRY_SECONDS = 900;
    private const TABLE = 'v2_traffic_exhausted_reminders';

    private function eligibleUsers(): Builder
    {
        return User::query()
            ->where('remind_traffic', true)
            ->where('banned', false)
            ->whereNotNull('email')
            ->where('email', '<>', '')
            ->where('transfer_enable', '>', 0)
            ->whereRaw('u + d >= transfer_enable');
    }

    public function queuePending(int $chunkSize = 500): int
    {
        if (!admin_setting('remind_mail_enable', false)) {
            return 0;
        }

        $candidates = 0;
        $this->eligibleUsers()
            ->whereNotExists(function ($query) {
                $query->selectRaw('1')->from(self::TABLE)
                    ->whereColumn('user_id', 'v2_user.id')
                    ->whereColumn('reset_count', 'v2_user.reset_count')
                    ->where(function ($query) {
                        $query->whereNotNull('sent_at')->orWhere('retry_after', '>', now()->timestamp);
                    });
            })
            ->select(['id', 'reset_count'])
            ->chunkById($chunkSize, function ($users) use (&$candidates) {
                foreach ($users as $user) {
                    SendTrafficExhaustedEmailJob::dispatch($user->id, (int) $user->reset_count);
                    $candidates++;
                }
            });

        // Candidates are not a delivery count: an identical job may already be queued.
        return $candidates;
    }

    public function send(int $userId, int $resetCount): void
    {
        if (!admin_setting('remind_mail_enable', false)) {
            return;
        }

        $user = $this->eligibleUsers()->whereKey($userId)->where('reset_count', $resetCount)->first();
        if (!$user) {
            return;
        }

        $key = ['user_id' => $userId, 'reset_count' => $resetCount];
        DB::table(self::TABLE)->insertOrIgnore($key);
        // A durable claim also protects duplicate workers after a cache flush.
        $claimed = DB::table(self::TABLE)->where($key)->whereNull('sent_at')
            ->where(fn ($query) => $query->whereNull('retry_after')->orWhere('retry_after', '<=', now()->timestamp))
            ->update(['retry_after' => now()->timestamp + self::RETRY_SECONDS]);
        if (!$claimed) {
            return;
        }

        $mailLog = MailService::sendEmail([
            'email' => $user->email,
            'subject' => admin_setting('app_name', 'XBoard') . ' - 套餐流量已用完',
            'template_name' => 'remindTrafficExhausted',
            'template_value' => [
                'name' => admin_setting('app_name', 'XBoard'),
                'url' => admin_setting('app_url'),
            ],
        ]);

        if ($mailLog['error']) {
            // Keep the SMTP error in the existing mail log; do not copy credentials to the queue payload.
            throw new \RuntimeException('Traffic exhausted email failed; see the mail log.');
        }

        DB::table(self::TABLE)->where($key)->update(['sent_at' => now()->timestamp, 'retry_after' => null]);
    }
}
