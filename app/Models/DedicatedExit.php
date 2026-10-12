<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class DedicatedExit extends Model
{
    public const CAPACITY = 5;
    public const HEALTH_TTL = 300;

    protected $table = 'v2_dedicated_exit';
    protected $guarded = ['id'];
    protected $casts = [
        'plan_id' => 'integer', 'enabled' => 'boolean', 'standby' => 'boolean',
        'healthy' => 'boolean', 'checked_at' => 'integer',
    ];

    public function isHealthy(): bool
    {
        return $this->enabled && $this->healthy && $this->checked_at >= time() - self::HEALTH_TTL;
    }
}
