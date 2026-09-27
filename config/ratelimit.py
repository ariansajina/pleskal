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


def get_login_username(request, credentials):
    """Return the attempted login email for django-axes, lower-cased.

    Lower-casing keeps "Victim@x.dk" and "victim@x.dk" on one failure counter,
    so case variations can't be used to multiply the attempts allowed.
    """
    credentials = credentials or {}
    username = credentials.get("username") or credentials.get("email")
    if username is None:
        username = request.POST.get("username", "")
    return str(username).strip().lower()


def check_rate_limit(key, limit, window):
    """
    Check and increment a fixed-window rate limit counter.

    Returns True if the request exceeds the limit, False if it is allowed.

    The counter key is bucketed by the current window index
    (``int(time.time() // window)``), so each window gets a fresh key that
    starts at zero. This makes correctness independent of how the cache
    backend handles TTLs on update.

    Why bucketing matters: production uses DatabaseCache (see CACHES in
    settings), whose writes re-set the key's expiry. Without bucketing, a
    counter under sustained traffic would keep pushing its expiry forward and
    never reset, permanently locking the client out. With it, a stale bucket's
    TTL is irrelevant because the next window uses a new key.

    The counter is a plain get-then-set rather than ``add()`` + ``incr()``:
    DatabaseCache has no atomic increment (its ``incr`` is itself a get and a
    set) and every write costs several queries, so this does the same work in
    half the round trips. Once the limit is reached, rejected requests only
    read the counter, so a client hammering the endpoint adds no writes.
    Concurrent requests can occasionally undercount by one — acceptable for
    abuse throttling.
    """
    window_index = int(time.time() // window)
    bucket_key = f"{key}:{window_index}"
    count = cache.get(bucket_key, 0)
    if count >= limit:
        return True
    cache.set(bucket_key, count + 1, window)
    return False


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
