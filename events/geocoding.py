"""Nominatim (OpenStreetMap) geocoding helper.

Nominatim's usage policy requires:
- A descriptive User-Agent (configured via settings.GEOCODING_USER_AGENT).
- No more than 1 request per second.
- No bulk geocoding from a request handler.

This module enforces the rate limit with a process-wide lock and swallows any
HTTP/parsing/timeout error so callers never have to deal with failures.

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
import threading
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

_rate_lock = threading.Lock()
_last_call_at: float = 0.0


def _wait_for_rate_limit() -> None:
    """Block until at least MIN_INTERVAL_SECONDS have elapsed since the last call."""
    global _last_call_at
    with _rate_lock:
        elapsed = time.monotonic() - _last_call_at
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        _last_call_at = time.monotonic()


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

    user_agent = getattr(
        settings,
        "GEOCODING_USER_AGENT",
        "pleskal/1.0 (https://pleskal.dk)",
    )
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={
                "q": query,
                "format": "json",
                "limit": 1,
                "addressdetails": 0,
            },
            headers={"User-Agent": user_agent},
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
