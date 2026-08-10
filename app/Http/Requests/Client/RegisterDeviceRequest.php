<?php

namespace App\Http\Requests\Client;

class RegisterDeviceRequest extends ClientRequest
{
    public function rules(): array
    {
        return [
            'device_id' => ['required', 'uuid'],
            'name' => ['required', 'string', 'max:255'],
            'platform' => ['required', 'string', 'in:windows,macos,linux,android,ios'],
            'architecture' => ['nullable', 'string', 'max:32'],
            'os_version' => ['nullable', 'string', 'max:64'],
            'app_version' => ['nullable', 'string', 'max:32'],
        ];
    }
}
