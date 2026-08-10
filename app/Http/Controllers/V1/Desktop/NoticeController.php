<?php

namespace App\Http\Controllers\V1\Desktop;

use App\Http\Controllers\Controller;
use App\Models\Notice;
use App\Support\ClientApiResponse;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class NoticeController extends Controller
{
    public function index(Request $request): JsonResponse
    {
        $page = max(1, (int) $request->input('page', 1));
        $pageSize = min(100, max(1, (int) $request->input('page_size', 20)));
        $query = Notice::query()
            ->where('show', true)
            ->orderByRaw('sort IS NULL, sort ASC')
            ->orderByDesc('id');
        $total = $query->count();
        $items = $query->forPage($page, $pageSize)->get()->map(function (Notice $notice): array {
            $tags = $notice->tags ?? [];
            $level = collect(['critical', 'warning', 'success', 'info'])->first(
                fn(string $value) => in_array($value, $tags, true)
            ) ?? 'info';

            return [
                'id' => $notice->id,
                'title' => $notice->title,
                'content' => $notice->content,
                'content_type' => 'markdown',
                'level' => $level,
                'pinned' => false,
                'force_popup' => false,
                'image_url' => $notice->img_url,
                'tags' => $tags,
                'published_at' => $this->formatTimestamp($notice->getRawOriginal('created_at')),
                'expires_at' => null,
                'action' => null,
            ];
        })->values()->all();

        return ClientApiResponse::success($request, [
            'items' => $items,
            'page' => $page,
            'page_size' => $pageSize,
            'total' => $total,
        ]);
    }

    private function formatTimestamp(mixed $timestamp): ?string
    {
        return $timestamp
            ? now('UTC')->setTimestamp((int) $timestamp)->format('Y-m-d\TH:i:s\Z')
            : null;
    }
}
