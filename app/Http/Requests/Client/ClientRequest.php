<?php

namespace App\Http\Requests\Client;

use App\Exceptions\ClientApiException;
use Illuminate\Contracts\Validation\Validator;
use Illuminate\Foundation\Http\FormRequest;

abstract class ClientRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    protected function failedValidation(Validator $validator): void
    {
        throw new ClientApiException(
            'VALIDATION_ERROR',
            '请求参数错误',
            422,
            $validator->errors()->toArray()
        );
    }
}
