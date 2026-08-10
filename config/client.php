<?php

return [
    'access_token_ttl' => (int) env('CLIENT_ACCESS_TOKEN_TTL', 7200),
    'refresh_token_ttl' => (int) env('CLIENT_REFRESH_TOKEN_TTL', 2592000),
    'config_download_ttl' => (int) env('CLIENT_CONFIG_DOWNLOAD_TTL', 300),
    'registered_device_limit' => (int) env('CLIENT_REGISTERED_DEVICE_LIMIT', 5),
];
