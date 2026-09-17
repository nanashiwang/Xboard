<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('v2_stripe_quotes', function (Blueprint $table) {
            $table->string('id', 64)->primary();
            $table->unsignedBigInteger('order_id')->index();
            $table->unsignedBigInteger('payment_id');
            $table->unsignedBigInteger('cny_amount');
            $table->unsignedBigInteger('amount');
            $table->string('currency', 3);
            $table->string('exchange_rate', 24);
            $table->string('cost_percent', 16);
            $table->string('cost_fixed_usd', 16);
            $table->unsignedBigInteger('created_at');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('v2_stripe_quotes');
    }
};
