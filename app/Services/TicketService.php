<?php
namespace App\Services;


use App\Exceptions\ApiException;
use App\Jobs\SendEmailJob;
use App\Models\Ticket;
use App\Models\TicketMessage;
use App\Models\User;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Bus;
use Illuminate\Support\Facades\Log;
use App\Services\Plugin\HookManager;

class TicketService
{
    public function reply($ticket, $message, $userId)
    {
        try {
            DB::beginTransaction();
            $ticketMessage = TicketMessage::create([
                'user_id' => $userId,
                'ticket_id' => $ticket->id,
                'message' => $message
            ]);
            $isAdmin = $userId !== $ticket->user_id;
            $ticket->reply_status = $isAdmin
                ? Ticket::REPLY_STATUS_REPLIED
                : Ticket::REPLY_STATUS_WAITING;
            $ticket->last_reply_user_id = $userId;
            if (!$ticketMessage || !$ticket->save()) {
                throw new \Exception();
            }
            DB::commit();
            return $ticketMessage;
        } catch (\Exception $e) {
            DB::rollback();
            return false;
        }
    }

    public function replyByAdmin($ticketId, $message, $userId): void
    {
        $ticket = Ticket::where('id', $ticketId)->first();
        if (!$ticket) {
            throw new ApiException('工单不存在');
        }
        $ticketMessage = $this->reply($ticket, $message, $userId);
        if (!$ticketMessage) {
            throw new ApiException('工单回复失败');
        }
        HookManager::call('ticket.reply.admin.after', [$ticket, $ticketMessage]);
        $this->sendEmailNotify($ticket, $ticketMessage);
    }

    public function createTicket($userId, $subject, $level, $message)
    {
        try {
            DB::beginTransaction();
            if (Ticket::where('status', 0)->where('user_id', $userId)->lockForUpdate()->first()) {
                throw new ApiException('存在未关闭的工单');
            }
            $ticket = Ticket::create([
                'user_id' => $userId,
                'subject' => $subject,
                'level' => $level,
                'reply_status' => Ticket::REPLY_STATUS_WAITING,
                'last_reply_user_id' => $userId,
            ]);
            if (!$ticket) {
                throw new ApiException('工单创建失败');
            }
            $ticketMessage = TicketMessage::create([
                'user_id' => $userId,
                'ticket_id' => $ticket->id,
                'message' => $message
            ]);
            if (!$ticketMessage) {
                throw new ApiException('工单消息创建失败');
            }
            DB::afterCommit(fn () => $this->sendCreatedEmailNotify($ticket, $ticketMessage));
            DB::commit();
            return $ticket;
        } catch (\Exception $e) {
            DB::rollBack();
            throw $e;
        }
    }

    private function sendCreatedEmailNotify(Ticket $ticket, TicketMessage $ticketMessage): void
    {
        try {
            $emails = User::where('is_admin', true)->where('banned', false)
                ->pluck('email', 'id')
                ->map(fn ($email) => strtolower(trim((string) $email)))
                ->filter(fn ($email) => filter_var($email, FILTER_VALIDATE_EMAIL))
                ->unique();
            if ($emails->isEmpty()) {
                Log::warning('新工单通知没有可用的管理员邮箱', ['ticket_id' => $ticket->id]);
                return;
            }
            $customerEmail = User::whereKey($ticket->user_id)->value('email');
            $name = admin_setting('app_name', 'XBoard');
            foreach ($emails as $adminId => $email) {
                try {
                    Bus::dispatch(new SendEmailJob([
                        'email' => $email,
                        'subject' => $name . ' 收到新工单 #' . $ticket->id,
                        'template_name' => 'notify',
                        'template_value' => [
                            'name' => $name,
                            'url' => admin_setting('app_url'),
                            'content_mode' => 'text',
                            'content' => "工单编号：#{$ticket->id}\r\n客户邮箱：{$customerEmail}\r\n主题：{$ticket->subject}\r\n工单内容：{$ticketMessage->message}",
                        ],
                    ]));
                } catch (\Throwable $e) {
                    // A notification failure must not turn a committed ticket into an API failure.
                    Log::warning('新工单管理员邮件入队失败', [
                        'ticket_id' => $ticket->id,
                        'admin_id' => $adminId,
                        'exception_type' => get_class($e),
                    ]);
                }
            }
        } catch (\Throwable $e) {
            Log::warning('新工单管理员邮件准备失败', [
                'ticket_id' => $ticket->id,
                'exception_type' => get_class($e),
            ]);
        }
    }

    // 半小时内不再重复通知
    private function sendEmailNotify(Ticket $ticket, TicketMessage $ticketMessage)
    {
        $user = User::find($ticket->user_id);
        $cacheKey = 'ticket_sendEmailNotify_' . $ticket->user_id;
        if (!Cache::get($cacheKey)) {
            Cache::put($cacheKey, 1, 1800);
            SendEmailJob::dispatch([
                'email' => $user->email,
                'subject' => '您在' . admin_setting('app_name', 'XBoard') . '的工单得到了回复',
                'template_name' => 'notify',
                'template_value' => [
                    'name' => admin_setting('app_name', 'XBoard'),
                    'url' => admin_setting('app_url'),
                    'content' => "主题：{$ticket->subject}\r\n回复内容：{$ticketMessage->message}"
                ]
            ]);
        }
    }
}
