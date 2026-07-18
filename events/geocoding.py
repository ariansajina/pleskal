"""Nominatim (OpenStreetMap) geocoding helper.

Nominatim's usage policy requires:
- A descriptive User-Agent (configured via settings.GEOCODING_USER_AGENT).
- No more than 1 request per second.
- No bulk geocoding from a request handler.

This module enforces the rate limit with a cache-backed lock (shared across
worker processes, not just threads) and swallows any HTTP/parsing/timeout
error so callers never have to deal with failures.

Results are cached in Django's cache (the shared database cache in
production), keyed by the normalized query. Copenhagen has a small recurring
venue set, so after warm-up almost every Event.save() and scraper import hits
the cache instead of blocking on Nominatim. Definitive "no result" answers
are cached too (shorter TTL); transient failures are never cached, so they
are retried on the next save.
"""

from __future__ import annotations

import hashlib
import logging
import time

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
MIN_INTERVAL_SECONDS = 1.1
REQUEST_TIMEOUT_SECONDS = 5

GEOCODE_CACHE_TTL = 60 * 60 * 24 * 30  # positive results: 30 days
GEOCODE_NEGATIVE_TTL = 60 * 60 * 24 * 7  # definitive "no result": 7 days
_NEGATIVE = "negative"

# Coordinates the rate limit across every worker process via the shared cache
# (a per-process lock, e.g. threading.Lock, would let each gunicorn worker run
# its own independent 1 req/s budget, exceeding Nominatim's policy overall).
_RATE_LOCK_KEY = "geocode:rate-lock"
_RATE_LOCK_TIMEOUT_SECONDS = 10  # auto-expires if a worker dies mid-call
_LAST_CALL_AT_KEY = "geocode:last-call-at"
_LAST_CALL_AT_TTL = 300
_LOCK_POLL_INTERVAL_SECONDS = 0.05


def _wait_for_rate_limit() -> None:
    """Block until at least MIN_INTERVAL_SECONDS have elapsed since the last
    Nominatim call made by any process."""
    while not cache.add(_RATE_LOCK_KEY, 1, _RATE_LOCK_TIMEOUT_SECONDS):
        time.sleep(_LOCK_POLL_INTERVAL_SECONDS)
    try:
        last_call_at = cache.get(_LAST_CALL_AT_KEY)
        now = time.time()
        if last_call_at is not None:
            elapsed = now - last_call_at
            if elapsed < MIN_INTERVAL_SECONDS:
                time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        cache.set(_LAST_CALL_AT_KEY, time.time(), _LAST_CALL_AT_TTL)
    finally:
        cache.delete(_RATE_LOCK_KEY)


def _cache_key(query: str) -> str:
    digest = hashlib.sha256(query.strip().lower().encode()).hexdigest()
    return f"geocode:{digest}"


def geocode(query: str) -> tuple[float, float] | None:
    """Return (latitude, longitude) for the query, or None on any failure."""
    if not query:
        return None

    key = _cache_key(query)
    cached = cache.get(key)
    if cached == _NEGATIVE:
        return None
    if cached is not None:
        return tuple(cached)

    result, definitive = _geocode_remote(query)
    if result is not None:
        cache.set(key, result, GEOCODE_CACHE_TTL)
    elif definitive:
        cache.set(key, _NEGATIVE, GEOCODE_NEGATIVE_TTL)
    return result


def _geocode_remote(query: str) -> tuple[tuple[float, float] | None, bool]:
    """Call Nominatim. Returns (coords or None, definitive).

    ``definitive`` is True when Nominatim answered (even with no results or a
    malformed result) and False on transient failures (timeout, HTTP error,
    bad JSON) that should be retried rather than cached.
    """
    _wait_for_rate_limit()

    try:
        response = requests.get(
            NOMINATIM_URL,
            params={
                "q": query,
                "format": "json",
                "limit": 1,
                "addressdetails": 0,
                "countrycodes": "dk",
            },
            headers={"User-Agent": settings.GEOCODING_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        logger.warning("Nominatim geocoding failed for query %r", query, exc_info=True)
        return None, False

    if not payload:
        return None, True

    first = payload[0]
    try:
        return (float(first["lat"]), float(first["lon"])), True
    except (KeyError, TypeError, ValueError):
        logger.warning("Nominatim returned unexpected payload for %r: %r", query, first)
        return None, True
