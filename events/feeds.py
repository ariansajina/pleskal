"""iCal and RSS feed views for upcoming events."""

import re

from django.contrib.syndication.views import Feed
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


def _upcoming_qs(category: str | None = None):
    qs = Event.objects.filter(
        start_datetime__gte=timezone.now(),
    ).order_by("start_datetime")
    if category and category in {c.value for c in EventCategory}:
        qs = qs.filter(category=category)
    return qs


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
        category = getattr(self, "_request", None)
        if category:
            category = self._request.GET.get("category")
        return _upcoming_qs(category)[:50]

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
        category = request.GET.get("category")
        queryset = _upcoming_qs(category)

        cal = Calendar()
        cal.add("prodid", "-//Copenhagen Dance Calendar//EN")
        cal.add("version", "2.0")
        cal.add("calscale", "GREGORIAN")
        cal.add("x-wr-calname", "Copenhagen Dance Calendar")

        for event in queryset:
            vevent = ICalEvent()
            vevent.add("uid", str(event.id))
            vevent.add("summary", event.title)
            vevent.add("dtstart", event.start_datetime)
            if event.end_datetime:
                vevent.add("dtend", event.end_datetime)
            # Location
            location_parts = [event.venue_name]
            if event.venue_address:
                location_parts.append(event.venue_address)
            vevent.add("location", ", ".join(location_parts))
            # Description — plain text only, no author info
            if event.description:
                vevent.add("description", _plain_text(event.description))
            # URL for more info
            if event.source_url:
                vevent.add("url", event.source_url)
            cal.add_component(vevent)

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
        event = get_object_or_404(Event, slug=slug)

        cal = Calendar()
        cal.add("prodid", "-//Copenhagen Dance Calendar//EN")
        cal.add("version", "2.0")
        cal.add("calscale", "GREGORIAN")

        vevent = ICalEvent()
        vevent.add("uid", str(event.id))
        vevent.add("summary", event.title)
        vevent.add("dtstart", event.start_datetime)
        if event.end_datetime:
            vevent.add("dtend", event.end_datetime)
        location_parts = [event.venue_name]
        if event.venue_address:
            location_parts.append(event.venue_address)
        vevent.add("location", ", ".join(location_parts))
        if event.description:
            vevent.add("description", _plain_text(event.description))
        if event.source_url:
            vevent.add("url", event.source_url)
        cal.add_component(vevent)

        content = cal.to_ical()
        filename = f"{event.slug}.ics"
        return HttpResponse(
            content,
            content_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
