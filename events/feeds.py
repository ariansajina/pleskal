"""iCal and RSS feed views for upcoming events."""

import hashlib
import re

from django.contrib.syndication.views import Feed
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View
from icalendar import Calendar
from icalendar import Event as ICalEvent

from .models import Event, EventCategory, FeedHit


def _plain_text(markdown_text: str) -> str:
    """Strip markdown markup to get plain text for feeds."""
    # Remove markdown links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", markdown_text or "")
    # Remove emphasis markers
    text = re.sub(r"[*_`#>]", "", text)
    return text.strip()


def _upcoming_qs(
    categories: list[str] | None = None,
    publisher_slugs: list[str] | None = None,
):
    qs = Event.objects.filter(
        start_datetime__gte=timezone.now(),
        is_draft=False,
    ).order_by("start_datetime")
    if categories:
        valid = {c.value for c in EventCategory}
        clean = [c for c in categories if c in valid]
        if clean:
            qs = qs.filter(category__in=clean)
    if publisher_slugs:
        other = "community" in publisher_slugs
        named = [s for s in publisher_slugs if s != "community"]
        if other and named:
            qs = qs.filter(
                Q(submitted_by__display_name_slug__in=named)
                | Q(submitted_by__is_system_account=False)
            )
        elif other:
            qs = qs.filter(submitted_by__is_system_account=False)
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
    vevent.add("summary", event.title)
    vevent.add("dtstart", event.start_datetime)
    if event.end_datetime:
        vevent.add("dtend", event.end_datetime)
    location_parts: list[str] = [str(event.venue_name)]
    if event.venue_address:
        location_parts.append(str(event.venue_address))
    vevent.add("location", ", ".join(location_parts))
    if event.description:
        vevent.add("description", _plain_text(str(event.description)))
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
        # Store request so we can access query params
        self._request = request
        FeedHit.record(FeedHit.RSS)
        return None

    def link(self):
        return "/"

    def items(self):
        req = getattr(self, "_request", None)
        if not req:
            return _upcoming_qs()[:50]
        categories = req.GET.getlist("category")
        publisher_slugs = req.GET.getlist("publisher")
        return _upcoming_qs(categories=categories, publisher_slugs=publisher_slugs)[:50]

    def item_title(self, item):
        return str(item.title)

    def item_description(self, item):
        return _plain_text(str(item.description))

    def item_link(self, item):
        from django.urls import reverse

        return reverse("event_detail", kwargs={"slug": str(item.slug)})

    def item_pubdate(self, item):
        return item.created_at

    # Deliberately no item_author_* — privacy: do not expose submitter identity


# ---------------------------------------------------------------------------
# iCal Feed
# ---------------------------------------------------------------------------


class EventICalFeed(View):
    def get(self, request):
        FeedHit.record(FeedHit.ICAL)
        categories = request.GET.getlist("category")
        publisher_slugs = request.GET.getlist("publisher")
        queryset = _upcoming_qs(categories=categories, publisher_slugs=publisher_slugs)

        cal = Calendar()
        cal.add("prodid", "-//Copenhagen Dance Calendar//EN")
        cal.add("version", "2.0")
        cal.add("calscale", "GREGORIAN")
        cal.add("x-wr-calname", "Copenhagen Dance Calendar")

        for event in queryset:
            cal.add_component(_build_vevent(event))

        content = cal.to_ical()
        return HttpResponse(
            content,
            content_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="events.ics"'},
        )


# ---------------------------------------------------------------------------
# Single-event iCal download
# ---------------------------------------------------------------------------


class EventICalSingleView(View):
    def get(self, request, slug):
        event = get_object_or_404(Event, slug=slug, is_draft=False)

        cal = Calendar()
        cal.add("prodid", "-//Copenhagen Dance Calendar//EN")
        cal.add("version", "2.0")
        cal.add("calscale", "GREGORIAN")

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
            content_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": disposition},
        )
