<?php
namespace App\Http\Middleware;

use App\Models\NodeProbe;
use Closure;
use Illuminate\Http\Request;

class NodeProbeAuth
{
    public function handle(Request $request, Closure $next)
    {
        $token = $request->bearerToken();
        abort_unless(is_string($token) && strlen($token) === 64, 401);
        $probe = NodeProbe::where('token_hash', hash('sha256', $token))->where('enabled', true)->first();
        abort_unless($probe, 401);
        $request->attributes->set('node_probe', $probe);
        return $next($request)->header('Cache-Control', 'no-store')->header('Referrer-Policy', 'no-referrer');
    }
}
