<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('v2_node_probe', function (Blueprint $t) {
            $t->id();
            $t->string('name', 80);
            $t->string('location', 120);
            $t->unsignedBigInteger('user_id')->index();
            $t->string('token_hash', 64)->unique();
            $t->boolean('enabled')->default(true);
            $t->json('server_ids');
            $t->json('expected_exits')->nullable();
            $t->unsignedInteger('interval_seconds')->default(60);
            $t->unsignedInteger('transfer_interval_seconds')->default(1800);
            $t->unsignedInteger('transfer_bytes')->default(262144);
            $t->unsignedBigInteger('last_seen_at')->nullable();
            $t->string('last_error', 40)->nullable();
            $t->string('agent_version', 40)->nullable();
            $t->timestamps();
        });
        Schema::create('v2_node_probe_state', function (Blueprint $t) {
            $t->id();
            $t->unsignedBigInteger('probe_id');
            $t->unsignedBigInteger('server_id');
            $t->string('status', 20)->default('unknown');
            $t->unsignedInteger('failures')->default(0);
            $t->unsignedInteger('successes')->default(0);
            $t->unsignedBigInteger('checked_at')->nullable();
            $t->json('checks')->nullable();
            $t->json('transfers')->nullable();
            $t->unsignedBigInteger('transfer_checked_at')->nullable();
            $t->string('exit_ip', 45)->nullable();
            $t->unique(['probe_id', 'server_id']);
        });
        Schema::create('v2_node_probe_sample', function (Blueprint $t) {
            $t->id();
            $t->unsignedBigInteger('probe_id');
            $t->unsignedBigInteger('server_id');
            $t->uuid('sample_id');
            $t->unsignedBigInteger('checked_at')->index();
            $t->json('checks');
            $t->string('exit_ip', 45)->nullable();
            $t->unique(['probe_id', 'sample_id']);
            $t->index(['probe_id', 'server_id', 'checked_at'], 'probe_sample_history');
        });
        Schema::create('v2_node_probe_hour', function (Blueprint $t) {
            $t->id();
            $t->unsignedBigInteger('probe_id');
            $t->unsignedBigInteger('server_id');
            $t->unsignedBigInteger('hour')->index();
            foreach (['rounds', 'healthy_rounds', 'requests', 'successes', 'uploads', 'upload_successes', 'downloads', 'download_successes'] as $column) {
                $t->unsignedInteger($column)->default(0);
            }
            $t->double('latency_sum_ms')->default(0);
            $t->double('latency_max_ms')->default(0);
            $t->unique(['probe_id', 'server_id', 'hour']);
        });
        Schema::create('v2_node_probe_event', function (Blueprint $t) {
            $t->id();
            $t->unsignedBigInteger('probe_id');
            $t->unsignedBigInteger('server_id');
            $t->string('from_status', 20);
            $t->string('to_status', 20);
            $t->unsignedBigInteger('created_at')->index();
            $t->index(['probe_id', 'server_id', 'created_at'], 'probe_event_history');
        });
    }

    public function down(): void
    {
        foreach (['event', 'hour', 'sample', 'state'] as $suffix) Schema::dropIfExists('v2_node_probe_' . $suffix);
        Schema::dropIfExists('v2_node_probe');
    }
};
