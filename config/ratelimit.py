"""Cache-based rate limiting utilities for protecting sensitive endpoints."""

from django.core.cache import cache
from django.http import HttpResponse


def get_client_ip(request):
    """Extract client IP from request, respecting X-Forwarded-For.

    Reads the *rightmost* entry from X-Forwarded-For, which is the address
    appended by the last trusted proxy (e.g. Railway's load balancer).
    The leftmost entry is client-supplied and trivially spoofable.
    Falls back to REMOTE_ADDR when the header is absent.
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "127.0.0.1")


def check_rate_limit(key, limit, window):
    """
    Check and increment a rate limit counter.

    Returns True if the request exceeds the limit, False if it is allowed.
    The counter is stored in Django's cache and expires after ``window`` seconds.

    Uses cache.add() + cache.incr() to reduce the check-then-set race window
    present in a naive get/set pattern: add() is a conditional atomic set (no-op
    if the key already exists), and incr() is an atomic increment.

    Note: Django's default LocMemCache is per-process. On a multi-worker gunicorn
    deployment, each worker maintains independent counters, so the effective limit
    is multiplied by the number of workers. For strict enforcement, configure a
    shared cache backend (e.g. database cache or Redis via django-redis).
    """
    # cache.add() sets key=0 only if absent (atomic no-op if key exists).
    cache.add(key, 0, window)
    count = cache.incr(key)  # atomic increment
    return count > limit


class RateLimitMixin:
    """
    Mixin for class-based views that adds rate limiting.

    Attributes:
        rate_limit_key      Unique string identifying this endpoint (e.g. "login").
        rate_limit_limit    Maximum number of requests allowed in the window.
        rate_limit_window   Time window in seconds (default: 3600 = 1 hour).
        rate_limit_methods  HTTP methods to rate limit (default: POST only).
        rate_limit_by_user  Key by authenticated user ID instead of IP.
                            Falls back to IP for unauthenticated requests.
    """

    rate_limit_key: str = ""
    rate_limit_limit: int = 10
    rate_limit_window: int = 3600
    rate_limit_methods: list[str] = ["POST"]
    rate_limit_by_user: bool = False

    def get_rate_limit_cache_key(self, request):
        if self.rate_limit_by_user and request.user.is_authenticated:
            return f"rl:{self.rate_limit_key}:user:{request.user.pk}"
        ip = get_client_ip(request)
        return f"rl:{self.rate_limit_key}:{ip}"

    def dispatch(self, request, *args, **kwargs):
        if request.method in self.rate_limit_methods:
            key = self.get_rate_limit_cache_key(request)
            if check_rate_limit(key, self.rate_limit_limit, self.rate_limit_window):
                return HttpResponse(
                    "Too many requests. Please try again later.", status=429
                )
        return super().dispatch(request, *args, **kwargs)  # type: ignore
