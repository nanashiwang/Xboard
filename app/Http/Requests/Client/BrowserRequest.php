<?php

namespace App\Http\Requests\Client;

class BrowserRequest extends ClientRequest
{
    public function rules(): array
    {
        $rules = ['request_id' => ['required', 'string', 'regex:/^[0-9A-HJKMNP-TV-Z]{26}$/D']];
        if (in_array($this->route()?->getActionMethod(), ['poll', 'cancel'], true)) {
            $rules['secret'] = ['required', 'string', 'regex:/^[a-f0-9]{64}$/D'];
        }
        if ($this->route()?->getActionMethod() === 'approve') {
            $rules['approved'] = ['required', 'boolean'];
        }
        return $rules;
    }
}
