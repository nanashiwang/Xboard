<?php

namespace App\Http\Requests\Client;

class BrowserStartRequest extends LoginRequest
{
    public function rules(): array
    {
        $rules = parent::rules();
        unset($rules['email'], $rules['password']);
        $rules['secret'] = ['required', 'string', 'regex:/^[a-f0-9]{64}$/D'];
        return $rules;
    }
}
