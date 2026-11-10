"""iCal and RSS feed views for upcoming events."""

import hashlib
import re
import zlib

from django.contrib.syndication.views import Feed
from django.core.cache import cache
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.cache import get_conditional_response, patch_cache_control
from django.utils.http import http_date
from django.views import View
from icalendar import Calendar
from icalendar import Event as ICalEvent

from .models import Event, EventCategory, FeedHit

ICAL_CONTENT_TYPE = "text/calendar; charset=utf-8"


def _new_calendar() -> Calendar:
    """An empty VCALENDAR with the headers every pleskal .ics carries."""
    cal = Calendar()
    cal.add("prodid", "-//Copenhagen Dance Calendar//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    return cal


def _plain_text(markdown_text: str) -> str:
    """Strip markdown markup to get plain text for feeds."""
    # Remove markdown links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", markdown_text or "")
    # Remove emphasis markers
    text = re.sub(r"[*_`#>]", "", text)
    return text.strip()


# How long an event stays in the iCal feed after it ends, so it doesn't vanish
# from subscribers' calendars the moment it's over and they can look back at
# what they attended.
ICAL_PAST_EVENT_DAYS = 30


def _upcoming_qs(
    categories: list[str] | None = None,
    publisher_slugs: list[str] | None = None,
    past_days: int = 0,
):
    since = timezone.now() - timezone.timedelta(days=past_days)
    # Upcoming *or still running* (or ended within *past_days*): a multi-day
    # event stays in the feed until it ends, rather than vanishing from
    # subscribers' calendars the moment it starts.
    qs = Event.objects.filter(
        Q(start_datetime__gte=since) | Q(end_datetime__gte=since),
        is_draft=False,
    ).order_by("start_datetime", "id")
    if categories:
        valid = {c.value for c in EventCategory}
        clean = [c for c in categories if c in valid]
        if clean:
            qs = qs.filter(category__in=clean)
    if publisher_slugs:
        other = "community" in publisher_slugs
        named = [s for s in publisher_slugs if s != "community"]
        # "Community" = anything not from a system (scraper) account, including
        # events whose submitter deleted their account (submitted_by NULL) —
        # matching the event list's "other" publisher filter.
        community = ~Q(submitted_by__is_system_account=True)
        if other and named:
            qs = qs.filter(Q(submitted_by__display_name_slug__in=named) | community)
        elif other:
            qs = qs.filter(community)
        else:
            qs = qs.filter(submitted_by__display_name_slug__in=named)
    return qs


def _stable_uid(event: Event) -> str:
    """Return an iCal UID that survives the importer's delete+recreate cycle.

    Scraped events are matched for upsert/deletion on
    (external_source, source_url, start_datetime) — see base_import.py — but
    a delete+recreate assigns a fresh DB UUID, which previously became the
    iCal UID and made subscriber calendars treat the re-imported event as a
    brand new one (duplicate entries). Deriving the UID from the same match
    key instead keeps it stable across that cycle. User-submitted events
    (blank external_source) aren't subject to delete+recreate, so the DB UUID
    remains a fine, unique UID for them.
    """
    if event.external_source and event.source_url:
        start_iso = event.start_datetime.isoformat()  # ty: ignore[unresolved-attribute]
        basis = f"{event.external_source}|{event.source_url}|{start_iso}"
        digest = hashlib.sha1(basis.encode(), usedforsecurity=False).hexdigest()
        return f"{digest}@pleskal.dk"
    return f"{event.id}@pleskal.dk"


def _build_vevent(event: Event) -> ICalEvent:
    """Build an iCalendar VEVENT component from an Event instance."""
    vevent = ICalEvent()
    vevent.add("uid", _stable_uid(event))
    # DTSTAMP is REQUIRED by RFC 5545; LAST-MODIFIED lets clients spot edits.
    vevent.add("dtstamp", event.updated_at)
    vevent.add("last-modified", event.updated_at)
    vevent.add("summary", event.title)
    vevent.add("dtstart", event.start_datetime)
    vevent.add("dtend", event.effective_end)
    location_parts: list[str] = [str(event.venue_name)]
    if event.venue_address:
        location_parts.append(str(event.venue_address))
    vevent.add("location", ", ".join(location_parts))
    description = event.description_for("en")
    if description:
        vevent.add("description", _plain_text(str(description)))
    if event.source_url:
        vevent.add("url", event.source_url)
    return vevent


# ---------------------------------------------------------------------------
# RSS Feed
# ---------------------------------------------------------------------------


class EventRSSFeed(Feed):
    title = "Copenhagen Dance Calendar"
    description = "Upcoming dance events in Copenhagen."

    def get_object(self, request, *args, **kwargs):
        # The filters travel as the feed "object" rather than on self: Django
        # shares one Feed instance across all requests (and threads), so
        # request state stored on it could leak into a concurrent response.
        FeedHit.record(FeedHit.RSS)
        return {
            "categories": request.GET.getlist("category"),
            "publisher_slugs": request.GET.getlist("publisher"),
        }

    def link(self):
        return "/"

    def items(self, obj):
        return _upcoming_qs(
            categories=obj["categories"], publisher_slugs=obj["publisher_slugs"]
        )[:50]

    def item_title(self, item):
        return str(item.title)

    def item_description(self, item):
        return _plain_text(str(item.description_for("en")))

    def item_link(self, item):
        from django.urls import reverse

        return reverse("event_detail", kwargs={"slug": str(item.slug)})

    def item_pubdate(self, item):
        return item.created_at

    # Deliberately no item_author_* — privacy: do not expose submitter identity


# ---------------------------------------------------------------------------
# iCal Feed
# ---------------------------------------------------------------------------


# Calendar apps poll the feed, and building it means rendering every upcoming
# event, so the rendered file is cached (compressed) per filter combination
# for this long. Edits reach subscribers that much later, which is nothing
# next to their own polling interval (the feed asks for a daily refresh).
ICAL_FEED_CACHE_SECONDS = 5 * 60
_ICAL_FEED_CACHE_PREFIX = "feed:ical:"


def _ical_feed_cache_key(categories: list[str], publisher_slugs: list[str]) -> str:
    """Cache key for one filter combination, independent of parameter order.

    Unknown categories are dropped, as `_upcoming_qs` ignores them, so junk
    parameters can't multiply the cache entries.
    """
    valid = {c.value for c in EventCategory}
    basis = "|".join(
        [
            ",".join(sorted({c for c in categories if c in valid})),
            ",".join(sorted(set(publisher_slugs))),
        ]
    )
    digest = hashlib.sha256(basis.encode()).hexdigest()
    return f"{_ICAL_FEED_CACHE_PREFIX}{digest}"


def _render_ical_feed(categories: list[str], publisher_slugs: list[str]) -> bytes:
    queryset = _upcoming_qs(
        categories=categories,
        publisher_slugs=publisher_slugs,
        past_days=ICAL_PAST_EVENT_DAYS,
    )

    cal = _new_calendar()
    cal.add("x-wr-calname", "Copenhagen Dance Calendar")
    # Polling hint for subscribed calendars (Apple uses X-PUBLISHED-TTL,
    # RFC 7986 clients REFRESH-INTERVAL); matches the daily refresh the
    # subscribe page recommends.
    cal.add(
        "refresh-interval",
        timezone.timedelta(days=1),
        parameters={"VALUE": "DURATION"},
    )
    cal.add("x-published-ttl", "P1D")

    for event in queryset:
        cal.add_component(_build_vevent(event))

    return cal.to_ical()


class EventICalFeed(View):
    """The subscribable feed of upcoming events.

    The rendered file is cached for ICAL_FEED_CACHE_SECONDS and served with an
    ETag (hash of the content) and Last-Modified (when it was rendered), so a
    client polling with If-None-Match / If-Modified-Since gets a bodyless 304
    while nothing has changed.
    """

    def get(self, request):
        FeedHit.record(FeedHit.ICAL)
        categories = request.GET.getlist("category")
        publisher_slugs = request.GET.getlist("publisher")

        key = _ical_feed_cache_key(categories, publisher_slugs)
        cached = cache.get(key)
        if cached is None:
            content = _render_ical_feed(categories, publisher_slugs)
            etag = f'"{hashlib.sha256(content).hexdigest()[:32]}"'
            # Whole seconds: Last-Modified has no finer resolution.
            last_modified = int(timezone.now().timestamp())
            # The .ics compresses ~10x, which keeps the database cache row small.
            cache.set(
                key,
                (zlib.compress(content), etag, last_modified),
                ICAL_FEED_CACHE_SECONDS,
            )
        else:
            compressed, etag, last_modified = cached
            content = zlib.decompress(compressed)

        conditional = get_conditional_response(
            request, etag=etag, last_modified=last_modified
        )
        response = conditional or HttpResponse(
            content,
            content_type=ICAL_CONTENT_TYPE,
            headers={"Content-Disposition": 'attachment; filename="events.ics"'},
        )
        response.headers["ETag"] = etag
        response.headers["Last-Modified"] = http_date(last_modified)
        patch_cache_control(response, max_age=ICAL_FEED_CACHE_SECONDS)
        return response


# ---------------------------------------------------------------------------
# Single-event iCal download
# ---------------------------------------------------------------------------


class EventICalSingleView(View):
    def get(self, request, slug):
        event = get_object_or_404(Event, slug=slug, is_draft=False)

        cal = _new_calendar()

        cal.add_component(_build_vevent(event))

        content = cal.to_ical()
        filename = f"{event.slug}.ics"
        # ``?inline=1`` serves the file inline rather than as a download. On
        # iOS/macOS Safari an inline ``text/calendar`` response is handed
        # straight to Calendar, which opens an interactive "Add" sheet; an
        # ``attachment`` response instead downloads the file and opens a
        # read-only Quick Look preview with no one-tap add. The Apple Calendar
        # button uses the inline variant; the "Download .ics" link does not.
        if request.GET.get("inline") == "1":
            disposition = "inline"
        else:
            disposition = f'attachment; filename="{filename}"'
        return HttpResponse(
            content,
            content_type=ICAL_CONTENT_TYPE,
            headers={"Content-Disposition": disposition},
        )


# ---------------------------------------------------------------------------
# All dates of a series
# ---------------------------------------------------------------------------


class EventICalSeriesView(View):
    """Every upcoming published date of the series *slug* belongs to."""

    def get(self, request, slug):
        event = get_object_or_404(
            Event, slug=slug, is_draft=False, series__isnull=False
        )
        dates = Event.objects.filter(
            series_id=event.series_id,
            is_draft=False,
            start_datetime__gte=timezone.now(),
        ).order_by("start_datetime", "id")

        cal = _new_calendar()
        for occurrence in dates:
            cal.add_component(_build_vevent(occurrence))

        return HttpResponse(
            cal.to_ical(),
            content_type=ICAL_CONTENT_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{event.slug}-all-dates.ics"'
            },
        )
