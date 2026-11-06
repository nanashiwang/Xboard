<?php

// Patch the pinned upstream distribution without maintaining a fork or stale cache URL.
$root = $argv[1] ?? __DIR__ . '/../../public/assets/admin';
$manifestPath = $root . '/manifest.json';
$manifest = json_decode(file_get_contents($manifestPath), true, 512, JSON_THROW_ON_ERROR);
$entry = $manifest['index.html']['file'];
$source = file_get_contents($root . '/' . $entry);
$before = 'Mf.set(Af,e,259200)';
$after = 'Mf.set(Af,e,2592000)';
if (substr_count($source, $before) === 1 && substr_count($source, $after) === 0) {
    $source = str_replace($before, $after, $source);
} elseif (substr_count($source, $before) !== 0 || substr_count($source, $after) !== 1) {
    throw new RuntimeException('Admin login storage changed; review the pinned distribution before publishing.');
}
$newEntry = 'assets/index-session-' . substr(hash('sha256', $source), 0, 16) . '.js';
$index = file_get_contents($root . '/index.html');
if (substr_count($index, './' . $entry) !== 1) {
    throw new RuntimeException('Admin HTML entry does not match manifest.');
}
$manifest['index.html']['file'] = $newEntry;
file_put_contents($root . '/' . $newEntry, $source);
file_put_contents($root . '/index.html', str_replace('./' . $entry, './' . $newEntry, $index));
file_put_contents($manifestPath, json_encode($manifest, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n");
echo "Admin browser login retention: 30 days; entry $newEntry\n";
