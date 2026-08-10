<?php

namespace App\Exceptions;

use RuntimeException;

class ClientApiException extends RuntimeException
{
    public function __construct(
        private readonly string $apiCode,
        string $message,
        private readonly int $httpStatus = 400,
        private readonly mixed $details = null
    ) {
        parent::__construct($message, $httpStatus);
    }

    public function apiCode(): string
    {
        return $this->apiCode;
    }

    public function httpStatus(): int
    {
        return $this->httpStatus;
    }

    public function details(): mixed
    {
        return $this->details;
    }
}
