<?php

namespace App\Http\Requests\Client;

class RefreshRequest extends ClientRequest
{
    public function rules(): array
    {
        return [
            'refresh_token' => ['required', 'string', 'max:255'],
            'device_id' => ['required', 'uuid'],
        ];
    }
}
