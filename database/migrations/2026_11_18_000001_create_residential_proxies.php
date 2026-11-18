<?php
use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;
return new class extends Migration {
    public function up(): void {
        Schema::table('v2_plan', fn(Blueprint $t) => $t->boolean('is_proxy')->default(false));
        Schema::table('v2_order', function(Blueprint $t) {
            $t->string('product_type', 16)->default('vpn')->index();
            $t->unsignedBigInteger('proxy_endpoint_id')->nullable();
        });
        Schema::create('residential_proxy_hosts', function(Blueprint $t) {
            $t->id(); $t->string('address')->unique(); $t->string('token_hash',64);
            $t->boolean('enabled')->default(false); $t->unsignedBigInteger('seen_at')->nullable();
            $t->timestamps();
        });
        Schema::create('residential_proxy_endpoints', function(Blueprint $t) {
            $t->id(); $t->unsignedBigInteger('host_id'); $t->unsignedInteger('port');
            $t->unsignedBigInteger('user_id')->nullable()->index();
            $t->unsignedBigInteger('reserved_order_id')->nullable()->unique();
            $t->string('name')->default('美国家宽代理');
            $t->text('credentials')->nullable(); $t->unsignedBigInteger('expires_at')->nullable();
            $t->unsignedBigInteger('revision')->default(1);
            $t->unsignedBigInteger('applied_revision')->default(0);
            $t->unsignedBigInteger('checked_at')->nullable();
            $t->boolean('running')->default(false); $t->timestamps();
            $t->unique(['host_id','port']);
        });
    }
    public function down(): void {
        Schema::dropIfExists('residential_proxy_endpoints'); Schema::dropIfExists('residential_proxy_hosts');
        Schema::table('v2_order', fn(Blueprint $t) => $t->dropColumn(['product_type','proxy_endpoint_id']));
        Schema::table('v2_plan', fn(Blueprint $t) => $t->dropColumn('is_proxy'));
    }
};
