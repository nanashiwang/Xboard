<?php

namespace App\Support;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Str;

class ClientApiResponse
{
    public static function success(
        Request $request,
        mixed $data = null,
        string $message = '操作成功',
        int $status = 200
    ): JsonResponse {
        $meta = self::meta($request);
        return response()->json([
            'status' => 'success',
            'code' => 'OK',
            'message' => $message,
            'data' => $data,
            'error' => null,
            ...$meta,
        ], $status)->header('X-Request-ID', $meta['request_id']);
    }

    public static function error(
        Request $request,
        string $code,
        string $message,
        int $status,
        mixed $details = null
    ): JsonResponse {
        $meta = self::meta($request);
        return response()->json([
            'status' => 'fail',
            'code' => $code,
            'message' => $message,
            'data' => null,
            'error' => ['details' => $details],
            ...$meta,
        ], $status)->header('X-Request-ID', $meta['request_id']);
    }

    private static function meta(Request $request): array
    {
        $requestId = trim((string) $request->header('X-Request-ID'));
        if (
            $requestId === '' ||
            strlen($requestId) > 128 ||
            !preg_match('/^[A-Za-z0-9._:-]+$/', $requestId)
        ) {
            $requestId = (string) Str::uuid();
        }

        return [
            'request_id' => $requestId,
            'server_time' => now('UTC')->format('Y-m-d\TH:i:s\Z'),
        ];
    }
}
