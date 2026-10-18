<?php
namespace App\Http\Controllers\V2\Admin\Probe;

use App\Http\Controllers\Controller;
use App\Models\{NodeProbe, Server};
use App\Services\Probes\NodeProbeService;
use App\Services\Probes\IngressProbeService;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;

class ProbeController extends Controller
{
    private function respond($data) { return response()->json(['data' => $data])->header('Cache-Control', 'no-store'); }

    public function index(NodeProbeService $service)
    {
        return $this->respond(['probes' => NodeProbe::orderBy('id')->get()->map(fn ($p) => [...$service->overview($p), 'ingresses' => app(IngressProbeService::class)->overview($p)]),
            'servers' => Server::where('show', true)->orderBy('sort')->get(['id', 'name', 'host'])]);
    }

    public function ingressHistory(int $id, int $ingress, IngressProbeService $service)
    {
        return $this->respond($service->history(NodeProbe::findOrFail($id), $ingress));
    }

    public function create(Request $request, NodeProbeService $service)
    {
        $data = $request->validate([
            'name' => 'required|string|max:80', 'location' => 'required|string|max:120', 'user_id' => 'required|integer|exists:v2_user,id',
            'server_ids' => 'required|array|min:1|max:50', 'server_ids.*' => 'required|integer|distinct|exists:v2_server,id',
            'interval_seconds' => 'sometimes|integer|between:60,3600', 'transfer_interval_seconds' => 'sometimes|integer|between:1800,86400',
            'transfer_bytes' => 'sometimes|integer|between:65536,1048576',
        ]);
        [$probe, $token] = $service->create($data);
        return $this->respond(['id' => $probe->id, 'agent_config' => ['panel_url' => rtrim(config('app.url'), '/'), 'token' => $token]]);
    }

    public function enabled(Request $request, int $id)
    {
        $data = $request->validate(['enabled' => 'required|boolean']);
        NodeProbe::findOrFail($id)->update($data);
        return $this->respond(true);
    }

    public function rotate(int $id)
    {
        $probe = NodeProbe::findOrFail($id);
        $token = Str::random(64);
        $probe->update(['token_hash' => hash('sha256', $token), 'last_seen_at' => null]);
        return $this->respond(['agent_config' => ['panel_url' => rtrim(config('app.url'), '/'), 'token' => $token]]);
    }

    public function history(int $id, int $server)
    {
        $probe = NodeProbe::findOrFail($id);
        abort_unless(in_array($server, $probe->server_ids, true), 404);
        $scope = ['probe_id' => $id, 'server_id' => $server];
        $samples = DB::table('v2_node_probe_sample')->where($scope)->where('checked_at', '>=', time() - 86400)->orderByDesc('checked_at')->limit(200)->get()->map(function ($row) {
            $row->checks = json_decode($row->checks, true); return $row;
        });
        $latencies = [];
        // P95 uses all retained successful HTTP observations, not only the 200-row display window.
        DB::table('v2_node_probe_sample')->where($scope)->where('checked_at', '>=', time() - 86400)->orderBy('id')->chunkById(500, function ($rows) use (&$latencies) {
            foreach ($rows as $row) foreach (json_decode($row->checks, true)['checks'] as $c) {
                if (in_array($c['id'], ['cloudflare', 'google']) && $c['ok']) $latencies[] = $c['ms'];
            }
        });
        sort($latencies);
        return $this->respond(['samples' => $samples, 'latency_p95_ms' => $latencies ? $latencies[(int) ceil(count($latencies) * .95) - 1] : null,
            'hours' => DB::table('v2_node_probe_hour')->where($scope)->where('hour', '>=', time() - 30 * 86400)->orderBy('hour')->get(),
            'events' => DB::table('v2_node_probe_event')->where($scope)->orderByDesc('created_at')->limit(100)->get()]);
    }
}
