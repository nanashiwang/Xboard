<?php

namespace App\Http\Requests\Client;

class LoginRequest extends ClientRequest
{
    public function rules(): array
    {
        return [
            'email' => ['required', 'email:strict', 'max:64'],
            'password' => ['required', 'string', 'max:255'],
            'device' => ['required', 'array'],
            'device.device_id' => ['required', 'uuid'],
            'device.name' => ['required', 'string', 'max:255'],
            'device.platform' => ['required', 'string', 'in:windows,macos,linux,android,ios'],
            'device.architecture' => ['nullable', 'string', 'max:32'],
            'device.os_version' => ['nullable', 'string', 'max:64'],
            'device.app_version' => ['nullable', 'string', 'max:32'],
        ];
    }
}
