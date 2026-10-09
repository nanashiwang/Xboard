<?php

namespace App\Http\Controllers\V1\User;

use App\Http\Controllers\Controller;
use App\Services\ClientDownloadService;
use App\Services\UserService;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

class ClientDownloadController extends Controller
{
    public function import(Request $request, ClientDownloadService $downloads, UserService $users)
    {
        $request->validate(['client' => ['required', 'string', Rule::in(['clash-verge', 'clash-meta', 'sing-box'])]]);
        $user = $request->user();
        if (!$users->isAvailable($user) || $user->u + $user->d >= $user->transfer_enable) {
            return $this->fail([403, '当前订阅不可用，请检查套餐有效期和剩余流量'])
                ->header('Cache-Control', 'private, no-store');
        }
        return $this->success($downloads->importData($user, $request->input('client')))
            ->header('Cache-Control', 'private, no-store');
    }
}
