<?php
namespace App\Models;
use Illuminate\Database\Eloquent\Model;
class ResidentialProxyEndpoint extends Model {
    protected $guarded = ['id'];
    protected $hidden = ['credentials'];
    protected $casts = ['user_id'=>'integer','host_id'=>'integer','port'=>'integer','reserved_order_id'=>'integer','credentials'=>'encrypted:array','expires_at'=>'integer','revision'=>'integer','applied_revision'=>'integer','running'=>'boolean','checked_at'=>'integer'];
    public function host() { return $this->belongsTo(ResidentialProxyHost::class, 'host_id'); }
}
