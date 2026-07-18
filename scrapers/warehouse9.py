"""Scraper for https://warehouse9.dk/calendar/

Warehouse9 runs WordPress with The Events Calendar (Tribe Events) plugin,
which publishes a standards-compliant iCal feed of upcoming events.  We fetch
that feed and parse it with the ``icalendar`` library rather than scraping HTML
detail pages — it is the cleanest, most stable source and gives us titles,
timezone-aware dates, descriptions, location, source URLs, and a poster image
(via ATTACH) in one request.

All Warehouse9 events are marked wheelchair accessible: the venue has a level
entrance and a gender-neutral accessible toilet (stated in every event's
ACCESSIBILITY note).

Usage:
    uv run python scrapers/warehouse9.py
    uv run python scrapers/warehouse9.py --output events.json
    uv run python scrapers/warehouse9.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import datetime
import logging
import zoneinfo

from icalendar import Calendar

from events.models import MAX_VENUE_LENGTH
from scrapers.base import HEADERS, build_arg_parser, make_session, write_output

BASE_URL = "https://warehouse9.dk"
ICAL_URL = f"{BASE_URL}/?post_type=tribe_events&ical=1&eventDisplay=list"
EXTERNAL_SOURCE = "warehouse9"
VENUE_NAME = "Warehouse9"
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")

# Title/description keyword → pleskal EventCategory.  The feed carries no
# per-event category, so we infer one from the text and otherwise default to
# "performance" (Warehouse9 is a performance-art venue).  Order matters: the
# first matching keyword wins.
_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    ("work presentation", "worksharing"),
    ("work-in-progress", "worksharing"),
    ("work in progress", "worksharing"),
    ("work sharing", "worksharing"),
    ("worksharing", "worksharing"),
    ("showing", "worksharing"),
    ("workshop", "workshop"),
    ("artist talk", "talk"),
    ("talk", "talk"),
    ("open practice", "openpractice"),
    ("open studio", "openpractice"),
    ("open call", "other"),
    ("party", "social"),
    ("celebration", "social"),
]

# Words that signal free admission anywhere in the event text.
_FREE_KEYWORDS = ("free", "gratis", "no charge", "free of charge")

log = logging.getLogger(__name__)


# ── Feed fetch ────────────────────────────────────────────────────────────────


def fetch_calendar() -> Calendar:
    """Fetch the Tribe Events iCal feed and return a parsed Calendar."""
    session = make_session()
    resp = session.get(ICAL_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return Calendar.from_ical(resp.content)


# ── Field extraction ──────────────────────────────────────────────────────────


def _to_utc(value: datetime.datetime | datetime.date) -> datetime.datetime:
    """Normalise an iCal DTSTART/DTEND value to an aware UTC datetime.

    Datetimes carry a timezone (Europe/Copenhagen) from the feed.  Bare dates
    (all-day events) are interpreted as midnight Copenhagen time.
    """
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=CPH_TZ)
        return value.astimezone(datetime.UTC)
    # datetime.date (all-day) → midnight CPH
    return datetime.datetime(
        value.year, value.month, value.day, tzinfo=CPH_TZ
    ).astimezone(datetime.UTC)


def _format_description(raw: str) -> str:
    """Turn the feed's plain-text description into paragraph-separated markdown.

    The feed separates logical lines with single newlines, which markdown
    collapses into one run-on paragraph.  Splitting on newlines and re-joining
    with blank lines preserves the intended structure.
    """
    lines = [line.strip() for line in (raw or "").splitlines()]
    return "\n\n".join(line for line in lines if line).strip()


def _split_location(location: str) -> tuple[str, str]:
    """Split an iCal LOCATION into (venue_name, venue_address).

    The feed formats LOCATION as "Warehouse9, <street>, <city>, ...".  We take
    the first comma-separated part as the venue name and the remainder as the
    address.
    """
    location = (location or "").strip()
    if not location:
        return VENUE_NAME, ""
    parts = [p.strip() for p in location.split(",")]
    venue_name = parts[0] or VENUE_NAME
    venue_address = ", ".join(parts[1:]).strip()
    return venue_name[:MAX_VENUE_LENGTH], venue_address[:MAX_VENUE_LENGTH]


def _determine_category(title: str, description: str) -> str:
    """Infer a pleskal category from the event text, defaulting to performance.

    The title is the authoritative signal, so it is matched first; a stray
    keyword in the body (e.g. "workshop" mentioned in a party description) must
    not override a clear title like "Summer Party".
    """
    for haystack in (title.lower(), description.lower()):
        for keyword, category in _CATEGORY_KEYWORDS:
            if keyword in haystack:
                return category
    return "performance"


def _is_free(title: str, description: str) -> bool:
    """Return True if the event text signals free admission."""
    haystack = f"{title}\n{description}".lower()
    return any(keyword in haystack for keyword in _FREE_KEYWORDS)


def _extract_image_url(component) -> str:
    """Return the first ATTACH image URL on the component, or ''."""
    attach = component.get("ATTACH")
    if attach is None:
        return ""
    if isinstance(attach, list):
        attach = attach[0] if attach else None
    return str(attach) if attach else ""


def build_record(component) -> dict | None:
    """Map a single VEVENT component to a pleskal event record dict.

    Returns None when essential fields (title, start, URL) are missing.
    """
    title = str(component.get("SUMMARY") or "").strip()
    if not title:
        return None

    dtstart = component.get("DTSTART")
    if dtstart is None:
        log.warning("Skipping event with no DTSTART: %s", title)
        return None
    start_dt = _to_utc(dtstart.dt)

    dtend = component.get("DTEND")
    end_dt = _to_utc(dtend.dt) if dtend is not None else None

    source_url = str(component.get("URL") or "").strip()
    if not source_url:
        log.warning("Skipping event with no URL: %s", title)
        return None

    description = _format_description(str(component.get("DESCRIPTION") or ""))
    venue_name, venue_address = _split_location(str(component.get("LOCATION") or ""))

    return {
        "title": title,
        "description": description,
        "start_datetime": start_dt.isoformat(),
        "end_datetime": end_dt.isoformat() if end_dt else None,
        "venue_name": venue_name,
        "venue_address": venue_address,
        "category": _determine_category(title, description),
        "is_free": _is_free(title, description),
        # Warehouse9 is wheelchair accessible for all events (level entrance,
        # accessible toilet via certified stairlift).
        "is_wheelchair_accessible": True,
        "price_note": "",
        "source_url": source_url,
        "external_source": EXTERNAL_SOURCE,
        "image_url": _extract_image_url(component),
    }


def is_upcoming(record: dict, now: datetime.datetime | None = None) -> bool:
    """Return True if the event ends today or in the future."""
    if now is None:
        now = datetime.datetime.now(datetime.UTC)
    ref = record.get("end_datetime") or record["start_datetime"]
    try:
        ref_dt = datetime.datetime.fromisoformat(ref)
    except ValueError:
        return False
    return ref_dt >= now


# ── Main scrape entry point ───────────────────────────────────────────────────


def scrape() -> list[dict]:
    """Fetch the iCal feed, build records, and filter to upcoming events."""
    calendar = fetch_calendar()

    records: list[dict] = []
    for component in calendar.walk("VEVENT"):
        record = build_record(component)
        if record is not None:
            records.append(record)

    log.info("Parsed %d event records from feed", len(records))

    now = datetime.datetime.now(datetime.UTC)
    upcoming = [r for r in records if is_upcoming(r, now)]
    log.info("%d upcoming events after date filter", len(upcoming))

    return upcoming


def main() -> None:
    args = build_arg_parser(
        "Scrape warehouse9.dk calendar (Tribe Events iCal feed)",
        "warehouse9_events.json",
        include_delay=False,
    ).parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    records = scrape()
    write_output(records, args.output, args.dry_run)


if __name__ == "__main__":
    main()
