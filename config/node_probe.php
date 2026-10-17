<?php
return [
    'targets' => [
        ['id' => 'cloudflare', 'url' => 'https://speed.cloudflare.com/cdn-cgi/trace', 'status' => 200],
        ['id' => 'google', 'url' => 'https://www.gstatic.com/generate_204', 'status' => 204],
    ],
    'upload_url' => 'https://speed.cloudflare.com/__up',
    'download_url' => 'https://speed.cloudflare.com/__down',
];
