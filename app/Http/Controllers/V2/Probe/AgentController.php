<?php
namespace App\Http\Controllers\V2\Probe;

use App\Http\Controllers\Controller;
use App\Services\Probes\NodeProbeService;
use App\Services\Probes\IngressProbeService;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

class AgentController extends Controller
{
    public function ingressReport(Request $request, IngressProbeService $service)
    {
        $data = $request->validate([
            'sample_id' => 'required|uuid', 'ingress_id' => 'required|integer|min:1',
            'checked_at' => 'required|integer|between:' . (time() - 900) . ',' . (time() + 60),
            'measurement' => 'required|array:status,body_ok,error,dns_ms,tcp_ms,tls_ms,ttfb_ms,total_ms',
            'measurement.status' => 'required|integer|between:0,599', 'measurement.body_ok' => 'required|boolean',
            'measurement.error' => ['nullable', Rule::in([...NodeProbeService::ERRORS, 'body'])],
            'measurement.dns_ms' => 'nullable|numeric|between:0,60000',
            'measurement.tcp_ms' => 'nullable|numeric|between:0,60000',
            'measurement.tls_ms' => 'nullable|numeric|between:0,60000',
            'measurement.ttfb_ms' => 'nullable|numeric|between:0,60000',
            'measurement.total_ms' => 'required|numeric|between:0,60000',
        ]);
        return response()->json(['data' => ['accepted' => $service->report($request->attributes->get('node_probe'), $data)]]);
    }

    public function configuration(Request $request, NodeProbeService $service)
    {
        $data = $request->validate(['agent_version' => 'required|string|max:40', 'error' => ['nullable', Rule::in(NodeProbeService::CONFIG_ERRORS)]]);
        $probe = $request->attributes->get('node_probe');
        $probe->update(['last_seen_at' => time(), 'agent_version' => $data['agent_version'], 'last_error' => $data['error'] ?? null]);
        return response()->json(['data' => $service->configuration($probe)]);
    }

    public function report(Request $request, NodeProbeService $service)
    {
        $data = $request->validate([
            'sample_id' => 'required|uuid', 'server_id' => 'required|integer|min:1',
            'checked_at' => 'required|integer|between:' . (time() - 900) . ',' . (time() + 60),
            'exit_ip' => 'nullable|ip', 'error' => ['nullable', Rule::in(NodeProbeService::CONFIG_ERRORS)],
            'checks' => 'present|array|max:4', 'checks.*.id' => 'required|distinct|in:cloudflare,google,upload,download',
            'checks.*.status' => 'required|integer|between:0,599', 'checks.*.ms' => 'required|numeric|between:0,60000',
            'checks.*.bytes' => 'required|integer|between:0,4194304', 'checks.*.error' => ['nullable', Rule::in(NodeProbeService::ERRORS)],
        ]);
        if (empty($data['error'])) {
            $ids = array_column($data['checks'], 'id');
            abort_unless(in_array('cloudflare', $ids) && in_array('google', $ids), 422, 'Missing connectivity checks');
            abort_unless(in_array('upload', $ids) === in_array('download', $ids), 422, 'Incomplete transfer pair');
        } else {
            abort_unless(count($data['checks']) === 0, 422);
        }
        return response()->json(['data' => ['accepted' => $service->report($request->attributes->get('node_probe'), $data)]]);
    }
}
