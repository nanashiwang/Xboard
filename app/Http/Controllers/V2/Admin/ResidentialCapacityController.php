<?php

namespace App\Http\Controllers\V2\Admin;

use App\Http\Controllers\Controller;
use App\Services\ResidentialCapacityService;

class ResidentialCapacityController extends Controller
{
    public function show(ResidentialCapacityService $capacity)
    {
        return response()->json(['data' => $capacity->summary()])->header('Cache-Control', 'no-store, private');
    }
}
