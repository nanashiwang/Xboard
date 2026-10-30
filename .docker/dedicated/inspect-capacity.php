<?php
// Read-only deployed feature verification. No user identities or credentials are printed.
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$path = admin_setting('secure_path', admin_setting('frontend_admin_path', hash('crc32b', config('app.key'))));
$route = app('router')->getRoutes()->match(Illuminate\Http\Request::create('/api/v2/'.$path.'/stat/getResidentialCapacity'));
if (!in_array('admin', $route->gatherMiddleware(), true)) throw new RuntimeException('Admin middleware missing');
$view = file_get_contents('/www/resources/views/admin.blade.php');
$assets = [];
foreach (['js', 'css'] as $extension) {
    $name = 'residential-capacity.'.$extension;
    if (!str_contains($view, '/assets/'.$name)) throw new RuntimeException('Dashboard asset missing');
    $assets[$name] = hash_file('sha256', '/www/public/assets/'.$name);
}
echo json_encode(['status' => 'inspected', 'version' => config('app.version'), 'admin_middleware' => true,
    'assets' => $assets, 'data' => app(App\Services\ResidentialCapacityService::class)->summary()],
    JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES).PHP_EOL;
