<?php

namespace App\Exceptions;

class DedicatedExitUnavailableException extends ApiException
{
    public function __construct()
    {
        parent::__construct('专属出口暂不可用，订单已保留，恢复后自动开通');
    }
}
