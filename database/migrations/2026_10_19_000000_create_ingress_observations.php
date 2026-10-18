<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('v2_node_probe_ingress', function (Blueprint $t) {
            $t->id(); $t->string('name', 80); $t->string('host')->unique();
            $t->string('health_path')->default('/healthz'); $t->string('expected_body');
            $t->unsignedBigInteger('machine_id'); $t->json('server_tunnels');
            $t->boolean('enabled')->default(true); $t->timestamps();
        });
        Schema::create('v2_node_probe_ingress_sample', function (Blueprint $t) {
            $t->id(); $t->unsignedBigInteger('probe_id'); $t->unsignedBigInteger('ingress_id');
            $t->uuid('sample_id'); $t->unsignedInteger('checked_at'); $t->boolean('ok'); $t->json('measurement');
            $t->unique(['probe_id', 'sample_id']); $t->index(['probe_id', 'ingress_id', 'checked_at'], 'ingress_sample_scope');
        });
    }
    public function down(): void
    {
        Schema::dropIfExists('v2_node_probe_ingress_sample');
        Schema::dropIfExists('v2_node_probe_ingress');
    }
};
