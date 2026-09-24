"""Server-side, cookieless analytics recording.

Counts successful HTML page views after the response is built. Nothing is
stored on (or read from) the visitor's device, so no consent banner is needed.
See ``analytics.models`` for what is stored.
"""

import hashlib
import logging
import re
import secrets
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.http import QueryDict
from django.utils import timezone

from config.ratelimit import get_client_ip
from events.models import EventCategory

from .models import DailyCount, DailySalt, VisitorHash

logger = logging.getLogger(__name__)

BOT_USER_AGENT_RE = re.compile(
    r"bot|crawl|spider|slurp|preview|monitor|curl|wget|python|httpx|go-http"
    r"|java/|headless|lighthouse|facebookexternalhit|scrapy|axios|node-fetch",
    re.IGNORECASE,
)

# URL names that are never counted (infrastructure, not pages people read).
EXCLUDED_URL_NAMES = {
    "health",
    "pwa_manifest",
    "pwa_service_worker",
    "pwa_offline",
    "robots_txt",
    "django.contrib.sitemaps.views.sitemap",
    "stats_dashboard",
}
EXCLUDED_NAMESPACES = {"admin", "djdt"}

FILTERABLE_URL_NAMES = {"event_list", "event_map"}
SEARCH_KEY_MAX_LENGTH = 100
KEY_MAX_LENGTH = 255

# In-process memo of today's salt so each worker reads it once per day.
_salt_cache: dict = {}


class AnalyticsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.ANALYTICS_ENABLED and _should_record(request, response):
            try:
                with transaction.atomic():
                    _record(request, response)
            except Exception:
                # Analytics must never break a page.
                logger.exception("Failed to record analytics")
        return response


def _should_record(request, response) -> bool:
    if request.method != "GET" or response.status_code != 200:
        return False
    match = getattr(request, "resolver_match", None)
    if match is None or match.url_name in EXCLUDED_URL_NAMES:
        return False
    if EXCLUDED_NAMESPACES.intersection(match.namespaces):
        return False
    user_agent = request.headers.get("User-Agent", "")
    if not user_agent or BOT_USER_AGENT_RE.search(user_agent):
        return False
    # Browser prefetches/prerenders aren't views (yet).
    purpose = request.headers.get("Sec-Purpose", "") or request.headers.get(
        "Purpose", ""
    )
    if "prefetch" in purpose:
        return False
    user = getattr(request, "user", None)
    return not (user is not None and user.is_staff)


def _record(request, response) -> None:
    url_name = request.resolver_match.url_name
    if url_name == "event_ical_single":
        DailyCount.increment(DailyCount.CALENDAR, request.path[:KEY_MAX_LENGTH])
        return
    if not response.get("Content-Type", "").startswith("text/html"):
        return

    is_htmx = request.headers.get("HX-Request") == "true"
    if url_name in FILTERABLE_URL_NAMES:
        _record_search_and_filters(request, is_htmx)
    if is_htmx:
        # Partial swaps (filtering, pagination) aren't page views.
        return

    DailyCount.increment(DailyCount.PAGE, request.path[:KEY_MAX_LENGTH])
    referrer = _external_referrer(request)
    if referrer:
        DailyCount.increment(DailyCount.REFERRER, referrer)
    if not _opted_out(request):
        _record_visitor(request)


def _opted_out(request) -> bool:
    """Honour Global Privacy Control / Do Not Track for visitor hashing."""
    return request.headers.get("Sec-GPC") == "1" or request.headers.get("DNT") == "1"


def _external_referrer(request) -> str:
    """Return the referring site's host, or "" for none / our own site."""
    host = urlsplit(request.headers.get("Referer", "")).hostname or ""
    host = host.lower().removeprefix("www.")
    own_host = request.get_host().split(":")[0].lower().removeprefix("www.")
    if not host or host == own_host:
        return ""
    return host[:KEY_MAX_LENGTH]


def _daily_salt(today) -> str:
    salt = _salt_cache.get(today)
    if salt is None:
        obj, created = DailySalt.objects.get_or_create(
            date=today, defaults={"salt": secrets.token_hex(32)}
        )
        if created:
            # A new day: forget yesterday's salt and hashes for good.
            DailySalt.objects.filter(date__lt=today).delete()
            VisitorHash.objects.filter(date__lt=today).delete()
        _salt_cache.clear()
        _salt_cache[today] = salt = obj.salt
    return salt


def _record_visitor(request) -> None:
    today = timezone.localdate()
    raw = "|".join(
        [
            _daily_salt(today),
            get_client_ip(request),
            request.headers.get("User-Agent", ""),
        ]
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()
    _, created = VisitorHash.objects.get_or_create(date=today, digest=digest)
    if created:
        DailyCount.increment(DailyCount.VISITORS)


def _normalize_search(value: str) -> str:
    return " ".join(value.lower().split())[:SEARCH_KEY_MAX_LENGTH]


def _previous_params(request, is_htmx: bool) -> QueryDict:
    """Query params of the page an HTMX filter request was made from.

    The filter panel pushes each result URL into the address bar, so
    HX-Current-URL holds the filters that were already applied. Comparing
    against it counts each newly applied filter once instead of on every
    subsequent partial request.
    """
    if not is_htmx:
        return QueryDict()
    current = urlsplit(request.headers.get("HX-Current-URL", ""))
    if current.path != request.path:
        return QueryDict()
    return QueryDict(current.query)


def _filter_keys(params: QueryDict) -> set[str]:
    valid_categories = {c.value for c in EventCategory}
    keys = {
        f"category:{c}" for c in params.getlist("category") if c in valid_categories
    }
    keys |= {
        f"publisher:{p}"[:KEY_MAX_LENGTH]
        for p in params.getlist("publisher")[:20]
        if re.fullmatch(r"[\w-]{1,100}", p)
    }
    for param, key in (
        ("is_free", "is_free"),
        ("is_wheelchair_accessible", "is_wheelchair_accessible"),
        ("past", "past"),
    ):
        if params.get(param) == "1":
            keys.add(key)
    if params.get("date_to"):
        keys.add("date_range")
    return keys


def _record_search_and_filters(request, is_htmx: bool) -> None:
    previous = _previous_params(request, is_htmx)

    query = _normalize_search(request.GET.get("q", ""))
    previous_query = _normalize_search(previous.get("q", ""))
    if query != previous_query:
        # The search box fires as the user types, so "wor" -> "work" ->
        # "workshop" arrive as separate requests. Treat a refinement of the
        # previous query as replacing it, so only the final term is counted.
        is_refinement = previous_query and (
            query.startswith(previous_query) or previous_query.startswith(query)
        )
        if is_refinement and len(previous_query) >= 2:
            DailyCount.decrement(DailyCount.SEARCH, previous_query)
        if len(query) >= 2:
            DailyCount.increment(DailyCount.SEARCH, query)

    for key in sorted(_filter_keys(request.GET) - _filter_keys(previous)):
        DailyCount.increment(DailyCount.FILTER, key)
