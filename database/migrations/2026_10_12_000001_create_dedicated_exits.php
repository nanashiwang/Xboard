<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::table('v2_plan', function (Blueprint $table) {
            $table->boolean('dedicated')->default(false);
            $table->unsignedBigInteger('allocation_version')->default(0);
        });
        Schema::create('v2_dedicated_exit', function (Blueprint $table) {
            $table->id();
            $table->unsignedBigInteger('plan_id')->index();
            $table->string('name');
            $table->string('public_ip')->unique();
            $table->boolean('enabled')->default(false);
            $table->boolean('standby')->default(false);
            $table->boolean('healthy')->default(false);
            $table->unsignedInteger('failures')->default(0);
            $table->unsignedInteger('successes')->default(0);
            $table->unsignedBigInteger('checked_at')->nullable();
            $table->timestamps();
        });
        Schema::table('v2_server', function (Blueprint $table) {
            $table->unsignedBigInteger('dedicated_exit_id')->nullable()->index();
        });
        Schema::create('v2_dedicated_assignment', function (Blueprint $table) {
            $table->id();
            $table->unsignedBigInteger('plan_id')->index();
            $table->unsignedBigInteger('exit_id')->index();
            $table->unsignedTinyInteger('slot');
            $table->unsignedBigInteger('user_id')->unique();
            $table->unsignedBigInteger('order_id')->nullable()->index();
            $table->unsignedBigInteger('reserved_until')->nullable();
            $table->timestamps();
            $table->unique(['exit_id', 'slot']);
        });
        Schema::create('v2_dedicated_assignment_log', function (Blueprint $table) {
            $table->id();
            $table->unsignedBigInteger('user_id')->index();
            $table->unsignedBigInteger('from_exit_id')->nullable();
            $table->unsignedBigInteger('to_exit_id')->nullable();
            $table->string('reason');
            $table->unsignedBigInteger('created_at');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('v2_dedicated_assignment_log');
        Schema::dropIfExists('v2_dedicated_assignment');
        Schema::table('v2_server', fn (Blueprint $table) => $table->dropColumn('dedicated_exit_id'));
        Schema::dropIfExists('v2_dedicated_exit');
        Schema::table('v2_plan', fn (Blueprint $table) => $table->dropColumn(['dedicated', 'allocation_version']));
    }
};
