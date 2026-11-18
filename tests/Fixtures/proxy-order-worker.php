<?php
require __DIR__.'/../../vendor/autoload.php';
$app=require __DIR__.'/../../bootstrap/app.php';$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
config(['database.connections.sqlite.database'=>getenv('PROXY_TEST_DATABASE')]);
Illuminate\Support\Facades\DB::purge('sqlite');
Illuminate\Support\Facades\DB::statement('PRAGMA busy_timeout = 10000');
try {app(App\Services\ResidentialProxyService::class)->create(App\Models\User::findOrFail($argv[1]));echo 'reserved';}
catch(App\Exceptions\ApiException $e){echo 'sold_out';}
