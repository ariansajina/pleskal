"""Nominatim (OpenStreetMap) geocoding helper.

Nominatim's usage policy requires:
- A descriptive User-Agent (configured via settings.GEOCODING_USER_AGENT).
- No more than 1 request per second.
- No bulk geocoding from a request handler.

This module enforces the rate limit with a process-wide lock and swallows any
HTTP/parsing/timeout error so callers never have to deal with failures.
"""

from __future__ import annotations

import logging
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
MIN_INTERVAL_SECONDS = 1.1
REQUEST_TIMEOUT_SECONDS = 5

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


def geocode(query: str) -> tuple[float, float] | None:
    """Return (latitude, longitude) for the query, or None on any failure."""
    if not query:
        return None

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
        return None

    if not payload:
        return None

    first = payload[0]
    try:
        return float(first["lat"]), float(first["lon"])
    except (KeyError, TypeError, ValueError):
        logger.warning("Nominatim returned unexpected payload for %r: %r", query, first)
        return None
