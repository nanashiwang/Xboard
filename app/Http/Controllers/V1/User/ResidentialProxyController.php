<?php
namespace App\Http\Controllers\V1\User;
use App\Http\Controllers\Controller;
use App\Services\ResidentialProxyService;
use App\Support\ClientApiResponse;
use Illuminate\Http\Request;

class ResidentialProxyController extends Controller {
    private function result(Request $r,$data) {
        return ($r->is('api/v1/client/*') ? ClientApiResponse::success($r,$data) : $this->success($data))
            ->header('Cache-Control','no-store')->header('Referrer-Policy','no-referrer');
    }
    public function index(Request $r,ResidentialProxyService $s) { return $this->result($r,$s->index($r->user())); }
    public function detail(Request $r,ResidentialProxyService $s) {
        $r->validate(['id'=>'required|integer|min:1']);
        return $this->result($r,$s->describe($s->owned($r->user(),$r->integer('id')),true));
    }
    public function save(Request $r,ResidentialProxyService $s) {
        $r->validate(['id'=>'nullable|integer|min:1']);
        $o=$s->create($r->user(),$r->integer('id')?:null);
        return $this->result($r,['trade_no'=>$o->trade_no,'total_amount'=>$o->total_amount,'balance_amount'=>$o->balance_amount]);
    }
    public function update(Request $r,ResidentialProxyService $s) {
        $input=$r->validate(['id'=>'required|integer|min:1','name'=>'sometimes|required|string|max:60','reset'=>'sometimes|boolean']);
        return $this->result($r,$s->update($r->user(),$r->integer('id'),$input));
    }
}
