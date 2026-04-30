from django.conf import settings
from django.http import JsonResponse
from django_ratelimit.core import is_ratelimited


def get_real_ip(request):
    """Return client IP honoring Cloudflare and proxy headers."""
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP", "").strip()
    if cf_ip:
        return cf_ip

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR", "")


class GlobalApiRateLimitMiddleware:
    """Apply a global API ratelimit in production, excluding keep-alive."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_limit(request):
            rate = self._resolve_rate(request)
            limited = is_ratelimited(
                request=request,
                group="global_api",
                key="ip",
                rate=rate,
                method=(request.method,),
                increment=True,
            )
            if limited:
                return JsonResponse(
                    {
                        "detail": "Demasiadas solicitudes. Intenta de nuevo en unos segundos.",
                    },
                    status=429,
                )

        return self.get_response(request)

    def _should_limit(self, request):
        if not getattr(settings, "GLOBAL_API_RATELIMIT_ENABLED", False):
            return False

        # Nunca limitar preflight CORS.
        if request.method == "OPTIONS":
            return False

        path = request.path.rstrip("/")
        if not path.startswith("/api/v1"):
            return False

        exempt = {p.rstrip("/") for p in getattr(settings, "GLOBAL_API_RATELIMIT_EXEMPT_PATHS", [])}
        return path not in exempt

    def _resolve_rate(self, request):
        if request.method in {"GET", "HEAD"}:
            return getattr(settings, "GLOBAL_API_RATELIMIT_READ_RATE", "120/m")
        return getattr(settings, "GLOBAL_API_RATELIMIT_WRITE_RATE", "30/m")
