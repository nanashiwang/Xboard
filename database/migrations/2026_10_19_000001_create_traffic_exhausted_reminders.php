<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('v2_traffic_exhausted_reminders', function (Blueprint $table) {
            $table->bigIncrements('id');
            $table->unsignedBigInteger('user_id');
            $table->unsignedInteger('reset_count');
            $table->unsignedInteger('sent_at')->nullable();
            $table->unsignedInteger('retry_after')->nullable();
            $table->unique(['user_id', 'reset_count'], 'traffic_exhausted_user_cycle_unique');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('v2_traffic_exhausted_reminders');
    }
};
