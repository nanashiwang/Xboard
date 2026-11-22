<?php

namespace App\Http\Controllers\V1;

use App\Http\Controllers\Controller;
use App\Services\ResidentialEnrollment;
use Illuminate\Http\Request;
use ZipArchive;

class ResidentialEnrollmentController extends Controller
{
    public function installer()
    {
        $dir = base_path('.docker/proxy-endpoints');
        $file = tempnam(sys_get_temp_dir(), 'proxy-install-');
        try {
            $zip = new ZipArchive();
            abort_unless($zip->open($file, ZipArchive::OVERWRITE) === true, 500);
            foreach (['__main__.py', 'manage.py', 'agent.py', 'stage1.py', 'ingress.py'] as $name) {
                abort_unless($zip->addFile("$dir/$name", $name), 500);
            }
            abort_unless($zip->close(), 500);
            return response(file_get_contents($file))->header('Content-Type', 'application/octet-stream');
        } finally {
            unlink($file);
        }
    }

    public function claim(Request $request, ResidentialEnrollment $enrollment)
    {
        $data = $request->validate(['id' => 'required|integer|min:1', 'digest' => 'required|regex:/^[0-9a-f]{64}$/D']);
        $enrollment->claim($data['id'], (string)$request->bearerToken(), $data['digest']);
        return response()->noContent();
    }

    public function ingress(Request $request, ResidentialEnrollment $enrollment)
    {
        abort_unless(hash_equals(ResidentialEnrollment::ingressToken(), (string)$request->bearerToken()), 401);
        if ($request->isMethod('post')) {
            $data = $request->validate(['id' => 'required|integer|min:1', 'probe' => 'required|regex:/^[0-9a-f]{32}$/D',
                'passed' => 'required|boolean', 'error' => 'nullable|in:direct,route,auth,timeout']);
            $enrollment->finish($data['id'], $data['probe'], $data['passed'], $data['error'] ?? 'timeout');
            return response()->noContent();
        }
        return response()->json(['hosts' => $enrollment->manifest()])->header('Cache-Control', 'no-store');
    }
}
