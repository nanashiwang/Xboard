<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class DedicatedAssignment extends Model
{
    protected $table = 'v2_dedicated_assignment';
    protected $guarded = ['id'];
    protected $casts = [
        'plan_id' => 'integer', 'exit_id' => 'integer', 'user_id' => 'integer',
        'order_id' => 'integer', 'slot' => 'integer', 'reserved_until' => 'integer',
    ];
}
