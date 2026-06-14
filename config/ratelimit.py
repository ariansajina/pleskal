"""Cache-based rate limiting utilities for protecting sensitive endpoints."""

import time

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
    Check and increment a fixed-window rate limit counter.

    Returns True if the request exceeds the limit, False if it is allowed.

    The counter key is bucketed by the current window index
    (``int(time.time() // window)``), so each window gets a fresh key that
    starts at zero. This makes correctness independent of whether the cache
    backend's ``incr()`` preserves the original TTL.

    Why bucketing matters: production uses DatabaseCache (see CACHES in
    settings), which inherits ``BaseCache.incr`` — a get-then-``set`` with no
    timeout, so each increment re-sets the key with the *default* cache timeout
    (DEFAULT_TIMEOUT, 300s). Without bucketing that would (a) inflate every
    window to 300s and (b) — because even rejected (over-limit) requests still
    increment — keep pushing the expiry forward on every hit, so a counter that
    crossed the limit would never reset under sustained traffic, permanently
    locking out the client. Bucketing sidesteps this: a stale bucket's inflated
    TTL is harmless because the next window uses a new key. (LocMemCache, used in
    dev/tests, preserves the add() TTL on incr(), so it was never affected.)

    cache.add() seeds the bucket at 0 only if absent (atomic no-op if present),
    then cache.incr() increments it. DatabaseCache's incr is not atomic
    (get-then-set), so concurrent requests can occasionally undercount by one —
    acceptable for abuse throttling.
    """
    window_index = int(time.time() // window)
    bucket_key = f"{key}:{window_index}"
    # cache.add() sets the bucket to 0 only if absent (no-op if it exists).
    cache.add(bucket_key, 0, window)
    try:
        count = cache.incr(bucket_key)
    except ValueError:
        # Rare: the bucket expired between add() and incr(). Re-seed and count
        # this request as the first in a fresh window.
        cache.add(bucket_key, 0, window)
        count = cache.incr(bucket_key)
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
