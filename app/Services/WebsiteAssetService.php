<?php

namespace App\Services;

use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\BinaryFileResponse;

/** Public, content-addressed files only; never cache application HTML or APIs. */
class WebsiteAssetService
{
    private const FILES = [
        'panel.js' => 'theme/Xboard/assets/umi.js',
        'entry.css' => 'public/assets/capybara-home/entry.css',
        'home.css' => 'public/assets/capybara-home/home.css',
    ];

    public function url(string $name): string
    {
        $path = $this->path($name);
        return '/web-assets/' . hash_file('sha256', $path) . '/' . $name;
    }

    public function response(Request $request, string $hash, string $name): BinaryFileResponse
    {
        $path = $this->path($name);
        $actual = hash_file('sha256', $path);
        abort_unless(hash_equals($actual, $hash), 404);
        $response = response()->file($path, [
            'Content-Type' => str_ends_with($name, '.js') ? 'application/javascript; charset=utf-8' : 'text/css; charset=utf-8',
            'Cache-Control' => 'public, max-age=31536000, immutable',
            'X-Content-Type-Options' => 'nosniff',
        ]);
        $response->setEtag($actual);
        $response->isNotModified($request);
        return $response;
    }

    private function path(string $name): string
    {
        abort_unless(isset(self::FILES[$name]), 404);
        $path = base_path(self::FILES[$name]);
        abort_unless(is_file($path), 404);
        return $path;
    }
}
