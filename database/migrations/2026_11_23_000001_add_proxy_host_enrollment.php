<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::table('residential_proxy_hosts', function (Blueprint $t) {
            $t->string('label', 80)->nullable();
            $t->string('country', 40)->default('美国');
            $t->string('enrollment_state', 16)->nullable();
            $t->string('install_hash', 64)->nullable();
            $t->unsignedBigInteger('install_until')->nullable();
            $t->text('transport_cert')->nullable();
            $t->string('probe_id', 32)->nullable();
            $t->unsignedBigInteger('probe_until')->nullable();
            $t->string('probe_error', 100)->nullable();
        });
    }

    public function down(): void
    {
        Schema::table('residential_proxy_hosts', fn (Blueprint $t) => $t->dropColumn([
            'label', 'country', 'enrollment_state', 'install_hash', 'install_until',
            'transport_cert', 'probe_id', 'probe_until', 'probe_error',
        ]));
    }
};
