<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Support\Str;

class ClientRefreshToken extends Model
{
    protected $table = 'client_refresh_tokens';
    protected $guarded = ['id'];
    protected $hidden = ['token_hash'];
    protected $keyType = 'string';
    public $incrementing = false;

    protected $casts = [
        'expires_at' => 'datetime',
        'used_at' => 'datetime',
        'revoked_at' => 'datetime',
    ];

    protected static function booted(): void
    {
        static::creating(function (ClientRefreshToken $token): void {
            $token->id ??= (string) Str::ulid();
        });
    }

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    public function device(): BelongsTo
    {
        return $this->belongsTo(ClientDevice::class, 'client_device_id');
    }
}
