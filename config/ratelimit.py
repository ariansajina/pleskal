"""Cache-based rate limiting utilities for protecting sensitive endpoints."""

from django.core.cache import cache
from django.http import HttpResponse


def get_client_ip(request):
    """Extract client IP from request, respecting X-Forwarded-For."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "127.0.0.1")


def check_rate_limit(key, limit, window):
    """
    Check and increment a rate limit counter.

    Returns True if the request exceeds the limit, False if it is allowed.
    The counter is stored in Django's cache and expires after ``window`` seconds.
    """
    current = cache.get(key)
    if current is None:
        cache.set(key, 1, window)
        return False
    if current >= limit:
        return True
    cache.incr(key)
    return False


class RateLimitMixin:
    """
    Mixin for class-based views that adds IP-based rate limiting on POST requests.

    Attributes:
        rate_limit_key    Unique string identifying this endpoint (e.g. "register").
        rate_limit_limit  Maximum number of POST requests allowed in the window.
        rate_limit_window Time window in seconds (default: 3600 = 1 hour).
    """

    rate_limit_key: str = ""
    rate_limit_limit: int = 10
    rate_limit_window: int = 3600

    def get_rate_limit_cache_key(self, request):
        ip = get_client_ip(request)
        return f"rl:{self.rate_limit_key}:{ip}"

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST":
            key = self.get_rate_limit_cache_key(request)
            if check_rate_limit(key, self.rate_limit_limit, self.rate_limit_window):
                return HttpResponse(
                    "Too many requests. Please try again later.", status=429
                )
        return super().dispatch(request, *args, **kwargs)


class UserRateLimitMixin(RateLimitMixin):
    """
    Rate limit by authenticated user ID instead of IP address.

    Falls back to IP-based limiting for unauthenticated requests.
    """

    def get_rate_limit_cache_key(self, request):
        if request.user.is_authenticated:
            return f"rl:{self.rate_limit_key}:user:{request.user.pk}"
        return super().get_rate_limit_cache_key(request)
