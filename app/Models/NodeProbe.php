<?php
namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class NodeProbe extends Model
{
    protected $table = 'v2_node_probe';
    protected $guarded = ['id'];
    protected $hidden = ['token_hash'];
    protected $casts = [
        'enabled' => 'boolean', 'server_ids' => 'array', 'expected_exits' => 'array',
        'last_seen_at' => 'integer', 'interval_seconds' => 'integer',
        'transfer_interval_seconds' => 'integer', 'transfer_bytes' => 'integer',
    ];

    public function user() { return $this->belongsTo(User::class); }

    public function staleAfter(): int
    {
        // Includes bounded four-worker rounds; slow or missing data never stays green.
        return max(300, $this->interval_seconds * 3 + (int) ceil(count($this->server_ids) / 4) * 30);
    }
}
