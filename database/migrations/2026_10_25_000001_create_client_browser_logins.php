<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('client_browser_logins', function (Blueprint $table): void {
            $table->char('id', 26)->primary();
            $table->char('secret_hash', 64);
            $table->json('device');
            $table->unsignedBigInteger('user_id')->nullable();
            $table->string('state', 16)->default('pending');
            $table->timestamp('expires_at')->index();
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('client_browser_logins');
    }
};
