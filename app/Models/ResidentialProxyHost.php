<?php
namespace App\Models;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\Model;
class ResidentialProxyHost extends Model {
    public const HEARTBEAT_SECONDS = 60;

    public function scopeAcceptingOrders(Builder $query, int $now): Builder
    {
        return $query->where('enabled', true)->where('seen_at', '>=', $now - self::HEARTBEAT_SECONDS);
    }

    protected $guarded = ['id'];
    protected $hidden = ['token_hash'];
    protected $casts = ['enabled'=>'boolean','seen_at'=>'integer'];
}
