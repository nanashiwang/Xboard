<?php
namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class NodeProbeIngress extends Model
{
    protected $table = 'v2_node_probe_ingress';
    protected $guarded = ['id'];
    protected $casts = ['server_tunnels' => 'array', 'enabled' => 'boolean'];
    public function machine() { return $this->belongsTo(ServerMachine::class, 'machine_id'); }
}
