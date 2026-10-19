<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::table('v2_dedicated_exit', function (Blueprint $table) {
            $table->unsignedBigInteger('shared_server_id')->nullable()->unique();
            $table->unsignedBigInteger('probe_id')->nullable();
            $table->unsignedBigInteger('probe_server_id')->nullable();
        });
    }

    public function down(): void
    {
        Schema::table('v2_dedicated_exit', function (Blueprint $table) {
            $table->dropUnique(['shared_server_id']);
            $table->dropColumn(['shared_server_id', 'probe_id', 'probe_server_id']);
        });
    }
};
