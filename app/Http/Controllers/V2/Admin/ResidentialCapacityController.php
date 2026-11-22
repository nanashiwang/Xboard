<?php

namespace App\Http\Controllers\V2\Admin;

use App\Http\Controllers\Controller;
use App\Services\ResidentialCapacityService;
use App\Services\ResidentialEnrollment;
use Illuminate\Http\Request;

class ResidentialCapacityController extends Controller
{
    public function show(ResidentialCapacityService $capacity)
    {
        return response()->json(['data' => $capacity->summary()])->header('Cache-Control', 'no-store, private');
    }

    public function register(Request $request, ResidentialEnrollment $enrollment)
    {
        $data = $request->validate(['label' => 'required|string|max:80', 'country' => 'required|string|max:40', 'address' => 'required|ipv4']);
        return response()->json(['data' => $enrollment->register($data)])->header('Cache-Control', 'no-store');
    }

    public function command(Request $request, ResidentialEnrollment $enrollment)
    {
        $data = $request->validate(['id' => 'required|integer|min:1']);
        return response()->json(['data' => $enrollment->issue($data['id'])])->header('Cache-Control', 'no-store');
    }

    public function accept(Request $request, ResidentialEnrollment $enrollment)
    {
        $data = $request->validate(['id' => 'required|integer|min:1']);
        $enrollment->start($data['id']);
        return response()->json(['data' => true])->header('Cache-Control', 'no-store');
    }
}
