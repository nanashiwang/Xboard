<?php

namespace App\Services;

use App\Models\InviteCode;
use App\Models\User;
use App\Utils\Helper;
use Illuminate\Support\Facades\DB;

class InviteService
{
    public function create(User $user): ?InviteCode
    {
        return DB::transaction(function () use ($user) {
            // Website and desktop requests share the same per-user quota lock.
            User::whereKey($user->id)->lockForUpdate()->firstOrFail();
            if (InviteCode::where('user_id', $user->id)->where('status', InviteCode::STATUS_UNUSED)->count()
                >= max(0, (int) admin_setting('invite_gen_limit', 5))) {
                return null;
            }
            $code = new InviteCode();
            $code->user_id = $user->id;
            $code->code = Helper::randomChar(8);
            $code->save();
            return $code;
        }, 3);
    }
}
