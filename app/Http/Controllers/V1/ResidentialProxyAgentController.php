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
        if ($host->enrollment_state && $r->filled('certificate')) {
            $cert = $r->validate(['certificate' => 'required|string|max:6144'])['certificate'];
            abort_unless(preg_match('/\A-----BEGIN CERTIFICATE-----[A-Za-z0-9+\/=\r\n]+-----END CERTIFICATE-----\s*\z/', $cert)
                && openssl_x509_read($cert), 422, '无效的出口证书');
            ResidentialProxyHost::whereKey($host->id)->whereNull('transport_cert')->update(['transport_cert' => $cert]);
            abort_unless(hash_equals($host->fresh()->transport_cert, $cert), 409, '出口证书已绑定');
        }
        foreach($data['reports'] as $report) {
            ResidentialProxyEndpoint::where('host_id',$host->id)->whereKey($report['id'])->where('revision',$report['revision'])
                ->update(['applied_revision'=>$report['revision'],'running'=>$report['running'],'checked_at'=>time()]);
        }
        $host->seen_at=time(); $host->save();
        $host->refresh();
        app(\App\Services\ResidentialEnrollment::class)->releaseAfterRevoke($host);
        return response()->json($s->snapshot($host->fresh()))->header('Cache-Control','no-store');
    }
}
