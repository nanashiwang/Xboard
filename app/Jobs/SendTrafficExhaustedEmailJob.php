<?php

namespace App\Jobs;

use App\Services\TrafficExhaustedReminderService;
use Illuminate\Bus\Queueable;
use Illuminate\Contracts\Queue\ShouldBeUnique;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Bus\Dispatchable;
use Illuminate\Queue\InteractsWithQueue;
use Illuminate\Queue\SerializesModels;

class SendTrafficExhaustedEmailJob implements ShouldQueue, ShouldBeUnique
{
    use Dispatchable, InteractsWithQueue, Queueable, SerializesModels;

    public $tries = 3;
    public $timeout = 30;
    public $uniqueFor = 3600;
    public $backoff = TrafficExhaustedReminderService::RETRY_SECONDS;

    public function __construct(public int $userId, public int $resetCount)
    {
        $this->onQueue('send_email');
    }

    public function uniqueId(): string
    {
        return "{$this->userId}:{$this->resetCount}";
    }

    public function handle(TrafficExhaustedReminderService $service): void
    {
        $service->send($this->userId, $this->resetCount);
    }
}
