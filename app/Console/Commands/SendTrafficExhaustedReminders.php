<?php

namespace App\Console\Commands;

use App\Services\TrafficExhaustedReminderService;
use Illuminate\Console\Command;

class SendTrafficExhaustedReminders extends Command
{
    protected $signature = 'send:traffic-exhausted {--chunk-size=500 : 每批检查的用户数量}';
    protected $description = '将本周期尚未通知的流量耗尽用户加入邮件队列';

    public function handle(TrafficExhaustedReminderService $service): int
    {
        if (!admin_setting('remind_mail_enable', false)) {
            $this->info('邮件提醒功能未启用');
            return self::SUCCESS;
        }

        $count = $service->queuePending(max(100, min(2000, (int) $this->option('chunk-size'))));
        $this->info("流量耗尽提醒候选用户：{$count}；实际发送结果请查看邮件日志。");
        return self::SUCCESS;
    }
}
