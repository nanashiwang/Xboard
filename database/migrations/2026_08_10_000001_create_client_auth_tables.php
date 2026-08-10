<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        if (!Schema::hasTable('client_devices')) {
            Schema::create('client_devices', function (Blueprint $table): void {
                $table->char('id', 26)->primary();
                $table->unsignedBigInteger('user_id')->index();
                $table->char('device_id_hash', 64);
                $table->string('name', 255);
                $table->string('platform', 32);
                $table->string('architecture', 32)->nullable();
                $table->string('os_version', 64)->nullable();
                $table->string('app_version', 32)->nullable();
                $table->string('status', 16)->default('active')->index();
                $table->string('first_ip', 45)->nullable();
                $table->string('last_ip', 45)->nullable();
                $table->timestamp('registered_at')->nullable();
                $table->timestamp('last_seen_at')->nullable();
                $table->timestamp('revoked_at')->nullable();
                $table->timestamps();

                $table->unique(['user_id', 'device_id_hash']);
                $table->index(['user_id', 'status']);
            });
        }

        if (!Schema::hasTable('client_refresh_tokens')) {
            Schema::create('client_refresh_tokens', function (Blueprint $table): void {
                $table->char('id', 26)->primary();
                $table->unsignedBigInteger('user_id')->index();
                $table->char('client_device_id', 26)->index();
                $table->unsignedBigInteger('personal_access_token_id')->nullable()->index();
                $table->char('family_id', 26)->index();
                $table->char('token_hash', 64)->unique();
                $table->timestamp('expires_at');
                $table->timestamp('used_at')->nullable();
                $table->timestamp('revoked_at')->nullable();
                $table->char('replaced_by_id', 26)->nullable();
                $table->timestamps();
            });
        }

        if (Schema::hasTable('personal_access_tokens')) {
            Schema::table('personal_access_tokens', function (Blueprint $table): void {
                if (!Schema::hasColumn('personal_access_tokens', 'client_device_id')) {
                    $table->char('client_device_id', 26)->nullable()->index()->after('abilities');
                }
                if (!Schema::hasColumn('personal_access_tokens', 'session_id')) {
                    $table->char('session_id', 26)->nullable()->index()->after('client_device_id');
                }
            });
        }

        if (Schema::hasTable('v2_user') && !Schema::hasColumn('v2_user', 'registered_device_limit')) {
            Schema::table('v2_user', function (Blueprint $table): void {
                $table->unsignedInteger('registered_device_limit')->nullable()->after('device_limit');
            });
        }

        if (Schema::hasTable('v2_plan') && !Schema::hasColumn('v2_plan', 'registered_device_limit')) {
            Schema::table('v2_plan', function (Blueprint $table): void {
                $table->unsignedInteger('registered_device_limit')->nullable()->after('device_limit');
            });
        }
    }

    public function down(): void
    {
        if (Schema::hasTable('personal_access_tokens')) {
            Schema::table('personal_access_tokens', function (Blueprint $table): void {
                if (Schema::hasColumn('personal_access_tokens', 'session_id')) {
                    $table->dropColumn('session_id');
                }
                if (Schema::hasColumn('personal_access_tokens', 'client_device_id')) {
                    $table->dropColumn('client_device_id');
                }
            });
        }

        if (Schema::hasTable('v2_user') && Schema::hasColumn('v2_user', 'registered_device_limit')) {
            Schema::table('v2_user', function (Blueprint $table): void {
                $table->dropColumn('registered_device_limit');
            });
        }

        if (Schema::hasTable('v2_plan') && Schema::hasColumn('v2_plan', 'registered_device_limit')) {
            Schema::table('v2_plan', function (Blueprint $table): void {
                $table->dropColumn('registered_device_limit');
            });
        }

        Schema::dropIfExists('client_refresh_tokens');
        Schema::dropIfExists('client_devices');
    }
};
