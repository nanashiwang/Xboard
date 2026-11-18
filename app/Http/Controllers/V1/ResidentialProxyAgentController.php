<?php
namespace App\Http\Controllers\V1;
use App\Http\Controllers\Controller;
use App\Models\{ResidentialProxyHost,ResidentialProxyEndpoint};
use App\Services\ResidentialProxyService;
use Illuminate\Http\Request;
class ResidentialProxyAgentController extends Controller {
    public function sync(Request $r,ResidentialProxyService $s) {
        $token=$r->bearerToken();
        abort_unless(is_string($token) && strlen($token)===64,401);
        $host=ResidentialProxyHost::where('token_hash',hash('sha256',$token))->first();
        abort_unless($host,401);
        $data=$r->validate(['reports'=>'present|array|max:10','reports.*.id'=>'required|integer','reports.*.revision'=>'required|integer|min:1','reports.*.running'=>'required|boolean']);
        foreach($data['reports'] as $report) {
            ResidentialProxyEndpoint::where('host_id',$host->id)->whereKey($report['id'])->where('revision',$report['revision'])
                ->update(['applied_revision'=>$report['revision'],'running'=>$report['running'],'checked_at'=>time()]);
        }
        $host->seen_at=time(); $host->save();
        return response()->json($s->snapshot($host))->header('Cache-Control','no-store');
    }
}
