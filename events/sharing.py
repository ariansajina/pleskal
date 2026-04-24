"""Helpers for building calendar deep-link URLs for the event detail page.

Google Calendar and Outlook deep links both expect start/end timestamps in
UTC. Google uses the basic ISO 8601 form ``YYYYMMDDTHHMMSSZ``; Outlook uses
the extended form ``YYYY-MM-DDTHH:MM:SSZ``. Aware datetimes are converted
with :meth:`datetime.astimezone`, so Copenhagen-local times come out right
across DST boundaries.
"""

from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlencode, urlparse, urlunparse

from .feeds import _plain_text
from .models import Event


def _to_utc_basic(dt: datetime) -> str:
    """Format an aware datetime as ``YYYYMMDDTHHMMSSZ`` in UTC."""
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _to_utc_extended(dt: datetime) -> str:
    """Format an aware datetime as ``YYYY-MM-DDTHH:MM:SSZ`` in UTC."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _location(event: Event) -> str:
    if event.venue_address:
        return f"{event.venue_name}, {event.venue_address}"
    return str(event.venue_name)


def _plain_description(event: Event) -> str:
    """Strip markdown markup so calendar apps show readable plain text."""
    return _plain_text(str(event.description or ""))


def _start_end(event: Event) -> tuple[datetime, datetime]:
    start = cast(datetime, event.start_datetime)
    end = cast(datetime, event.end_datetime) if event.end_datetime else start
    return start, end


def google_calendar_url(event: Event) -> str:
    """Build a Google Calendar ``render?action=TEMPLATE`` deep link."""
    start, end = _start_end(event)
    params = {
        "action": "TEMPLATE",
        "text": str(event.title),
        "dates": f"{_to_utc_basic(start)}/{_to_utc_basic(end)}",
        "location": _location(event),
        "details": _plain_description(event),
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params)


def outlook_calendar_url(event: Event) -> str:
    """Build an Outlook.com ``deeplink/compose`` URL for a new event."""
    start, end = _start_end(event)
    params = {
        "path": "/calendar/action/compose",
        "rru": "addevent",
        "subject": str(event.title),
        "startdt": _to_utc_extended(start),
        "enddt": _to_utc_extended(end),
        "body": _plain_description(event),
        "location": _location(event),
    }
    return "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode(params)


def apple_calendar_url(absolute_ical_url: str) -> str:
    """Convert an absolute http(s) ``.ics`` URL to a ``webcal://`` URL.

    Apple Calendar (and most desktop calendar clients) treat ``webcal://``
    as the "subscribe / add to calendar" handoff. On non-Apple desktops the
    browser typically shows an OS handler dialog instead of a silent failure.
    """
    parsed = urlparse(absolute_ical_url)
    if parsed.scheme in {"http", "https"}:
        return urlunparse(parsed._replace(scheme="webcal"))
    return absolute_ical_url
