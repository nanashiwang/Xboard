<?php

namespace App\Services;

use Illuminate\Http\Request;

class WebsiteEntryService
{
    public function isButtonEntry(Request $request): bool
    {
        return in_array($request->getHost(), config('website.entry_hosts', []), true);
    }

    public function allowsHost(Request $request): bool
    {
        if (!admin_setting('app_url') || !admin_setting('safe_mode_enable', 0)) {
            return true;
        }

        return $request->getHost() === parse_url(admin_setting('app_url'), PHP_URL_HOST)
            || $this->isButtonEntry($request)
            || in_array($request->getHost(), config('website.compatible_hosts', []), true);
    }
}
