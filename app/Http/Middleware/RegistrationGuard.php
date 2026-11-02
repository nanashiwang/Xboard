<?php
namespace App\Http\Middleware;

use App\Exceptions\ApiException;
use App\Services\Auth\RegistrationGuard as Guard;
use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Str;
use Illuminate\Validation\ValidationException;
use Throwable;

class RegistrationGuard
{
    public function handle(Request $request, Closure $next, string $operation)
    {
        $guard = app(Guard::class);
        if (!$guard->enabled()) return $next($request);
        $request->attributes->set('registration_guard_id', (string) Str::uuid());
        $status = 500;
        try {
            $guard->before($request, $operation);
            $response = $next($request);
            $status = $response->getStatusCode();
            return $response;
        } catch (ValidationException $e) {
            $status = $e->status;
            throw $e;
        } catch (ApiException $e) {
            $status = (int) substr((string) $e->getCode(), 0, 3);
            throw $e;
        } finally {
            // Observability failures must not turn an already created account into an error.
            try { $guard->audit($request, $operation, $status); } catch (Throwable) {}
        }
    }
}
