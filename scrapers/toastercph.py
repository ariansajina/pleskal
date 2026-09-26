"""Scraper for https://toastercph.dk/program/?lang=en

Collects upcoming events from the Toaster CPH program listing page, then
visits each detail page for description and ticket info.  Outputs a JSON
array of event dicts ready for ingestion into the pleskal database.

Usage:
    uv run python scrapers/toastercph.py
    uv run python scrapers/toastercph.py --output events.json
    uv run python scrapers/toastercph.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import datetime
import logging
import re
import time
import zoneinfo

import markdownify
import requests
from bs4 import NavigableString, Tag

from scrapers.base import (
    build_arg_parser,
    get_crawl_delay,
    get_soup,
    make_session,
    write_output,
)

BASE_URL = "https://toastercph.dk"
PROGRAM_URL = f"{BASE_URL}/program/?lang=en"
EXTERNAL_SOURCE = "toastercph"
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")

# Series strings that imply a more specific category than "performance"
_SERIES_CATEGORY_OVERRIDES: dict[str, str] = {
    "workshop": "workshop",
    "workshops": "workshop",
    "workshop & performance": "workshop",
    "talk": "talk",
    "talks": "talk",
    "open call": "other",
}

log = logging.getLogger(__name__)


# ── Date / time helpers ───────────────────────────────────────────────────────


# How far back a year-less "23/9" may lie and still mean this year's date:
# multi-date entries stay in the upcoming list after their first dates pass,
# and rolling those into next year would invent a performance a year out.
_RECENT_PAST = datetime.timedelta(days=183)


def _infer_year(month: int, day: int, today: datetime.date) -> int:
    """Return the year a year-less day/month most plausibly refers to."""
    year = today.year
    try:
        candidate = datetime.date(year, month, day)
    except ValueError:
        return year + 1
    return year if candidate >= today - _RECENT_PAST else year + 1


def _parse_time_str(s: str) -> datetime.time | None:
    """Parse '20.30', '20:30' or a bare hour '10' → datetime.time; None on failure."""
    m = re.match(r"^(\d{1,2})(?:[.:](\d{2}))?$", s.strip())
    if not m:
        return None
    try:
        return datetime.time(int(m.group(1)), int(m.group(2) or 0))
    except ValueError:
        return None


def _make_dt(
    date: datetime.date,
    t: datetime.time | None,
) -> datetime.datetime:
    """Combine date + CPH wall-clock time (midnight if t is None) → UTC datetime."""
    hour, minute = (t.hour, t.minute) if t else (0, 0)
    return datetime.datetime(
        date.year, date.month, date.day, hour, minute, tzinfo=CPH_TZ
    ).astimezone(datetime.UTC)


# "16/4", "01/10 2026", "1/10/2026"
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})(?:(?:/|\s+)(\d{4}))?")
# "at 20.30-01.00", "kl. 10-12", "at 19.00"
_TIME_RE = re.compile(
    r"\b(?:at|kl\.?)\s*(\d{1,2}(?:[.:]\d{2})?)(?:\s*-\s*(\d{1,2}(?:[.:]\d{2})?))?",
    re.IGNORECASE,
)


def _slot_times(slot: str) -> tuple[datetime.time | None, datetime.time | None] | None:
    """Return (start, end) from a slot's time spec, or None if it has none."""
    m = _TIME_RE.search(slot)
    if not m:
        return None
    start = _parse_time_str(m.group(1))
    if start is None:
        return None
    end = _parse_time_str(m.group(2)) if m.group(2) else None
    return start, end


def _parse_single_slot(
    slot: str,
    today: datetime.date,
    times: tuple[datetime.time | None, datetime.time | None] | None = None,
) -> tuple[datetime.datetime, datetime.datetime | None] | None:
    """
    Parse a single date/time slot like "16/4 at 20.30-01.00" or
    "01/10 2026 at 18.00-21.00".

    *times* supplies the time for a slot that states none of its own (see
    ``parse_date_raw``). Returns (start_dt, end_dt) where end_dt may be None,
    or None if the slot has no date.
    """
    m = _DATE_RE.match(slot.strip())
    if not m:
        return None

    day, month = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else _infer_year(month, day, today)
    try:
        date = datetime.date(year, month, day)
    except ValueError:
        return None

    start_time, end_time = _slot_times(slot[m.end() :]) or times or (None, None)
    start_dt = _make_dt(date, start_time)

    end_dt: datetime.datetime | None = None
    if end_time is not None:
        # If end time is earlier than start, the show crosses midnight
        end_date = date
        if start_time is not None and end_time < start_time:
            end_date = date + datetime.timedelta(days=1)
        end_dt = _make_dt(end_date, end_time)

    return start_dt, end_dt


def parse_date_raw(
    date_raw: str,
    today: datetime.date | None = None,
) -> list[tuple[datetime.datetime, datetime.datetime | None]]:
    """
    Parse a raw date string into a list of (start_dt, end_dt) pairs.

    Handles:
      - Single slot:  "16/4 at 20.30-01.00", "01/10 2026 at 18.00-21.00"
      - Multi-slot:   "17/4 at 19.00-20.40 + 18/4 at 15.00-16.40"
      - Shared time:  "23/9 2026 + 11/11 2026 + 3/3 2027 - alle dage kl. 10-12"
        (a slot without a time of its own takes the next stated one)
      - Date range:   "17/4 - 3/5 - during opening hours at Husets Teater"
        (skipped: an exhibition, not a performance)

    Slots dated before *today* are dropped: a multi-date entry stays listed as
    upcoming after its first dates have passed.

    Returns [] if nothing can be parsed.
    """
    if not date_raw:
        return []
    if today is None:
        today = datetime.date.today()

    # Exhibitions / open-hours entries don't represent a single performance
    # time — skip them.
    if "during opening hours" in date_raw.lower():
        return []

    slots = [slot.strip() for slot in date_raw.split(" + ")]
    if len(slots) == 1:
        # Date range "DD/M - DD/M …" — use the start date only
        range_m = re.match(
            rf"({_DATE_RE.pattern})\s*-\s*{_DATE_RE.pattern}", date_raw.strip()
        )
        if range_m:
            slots = [range_m.group(1)]

    results: list[tuple[datetime.datetime, datetime.datetime | None]] = []
    shared: tuple[datetime.time | None, datetime.time | None] | None = None
    for slot in reversed(slots):
        date_m = _DATE_RE.match(slot)
        own = _slot_times(slot[date_m.end() :]) if date_m else None
        shared = own or shared
        parsed = _parse_single_slot(slot, today, shared)
        if parsed and parsed[0].astimezone(CPH_TZ).date() >= today:
            results.append(parsed)
    results.reverse()
    return results


# ── Category helper ───────────────────────────────────────────────────────────


def _determine_category(event_type: str, series: str | None) -> str:
    """Map event_type + series to a pleskal EventCategory string."""
    if series:
        override = _SERIES_CATEGORY_OVERRIDES.get(series.lower().strip())
        if override:
            return override
    if event_type == "show":
        return "performance"
    return "other"


_CREDIT_LINE_RE = re.compile(
    r"(?:udviklet|præsenteret|arrangeret|produceret) af\b"
    r"|(?:developed|presented|organi[sz]ed|produced) by\b",
    re.IGNORECASE,
)


# ── Listing page ──────────────────────────────────────────────────────────────


def collect_listing_cards(session: requests.Session) -> list[dict]:
    """
    Fetch the program page and return a list of raw card dicts for all
    upcoming events.  Each dict contains title_raw, detail_url, date_raw,
    venue, series, image_url, and event_type.

    The page has multiple ``div.event-list`` sections (one upcoming, several
    past).  We find the one whose nearest preceding ``<h1>`` says "Upcoming".
    Within it, each event is a ``div.event`` card.
    """
    soup = get_soup(PROGRAM_URL, session)

    # Find the upcoming event-list: the div.event-list whose nearest preceding
    # h1 contains "Upcoming"
    upcoming_list: Tag | None = None
    for el in soup.find_all("div", class_="event-list"):
        if not isinstance(el, Tag):
            continue
        prev_h1 = el.find_previous("h1")
        if isinstance(prev_h1, Tag) and "Upcoming" in prev_h1.get_text():
            upcoming_list = el
            break

    if upcoming_list is None:
        log.warning("Could not find upcoming event-list on %s", PROGRAM_URL)
        return []

    cards: list[dict] = []

    for event_div in upcoming_list.find_all("div", class_="event"):
        if not isinstance(event_div, Tag):
            continue

        # Detail URL + title from the <a><h2> link inside div.c3
        link_div = event_div.find("div", class_="c3")
        if not isinstance(link_div, Tag):
            continue
        a_tag = link_div.find("a")
        if not isinstance(a_tag, Tag):
            continue
        h2 = a_tag.find("h2")
        if not isinstance(h2, Tag):
            continue

        detail_url = str(a_tag.get("href", ""))
        if "/show/" not in detail_url and "/industry-event/" not in detail_url:
            continue

        # h2 contains the event name as a text node and the artist in a <span>
        artist_span = h2.find("span")
        if isinstance(artist_span, Tag):
            event_name = "".join(
                s for s in h2.children if isinstance(s, NavigableString)
            ).strip()
            artist_name = artist_span.get_text(strip=True)
            # Some entries put a credit line where the artist goes ("Udviklet
            # af Art Hub Copenhagen, HAUT og Toaster og muliggjort gennem ...");
            # "<title> by Udviklet af ..." is no title.
            if _CREDIT_LINE_RE.match(artist_name):
                artist_name = ""
            title_raw = (
                f"{event_name} by {artist_name}"
                if (event_name and artist_name)
                else (event_name or artist_name)
            )
        else:
            title_raw = h2.get_text(" ", strip=True)
        # Three <h5> tags inside div.info hold date, venue, series (in order)
        info_div = event_div.find("div", class_="info")
        h5s = (
            [h.get_text(strip=True) for h in info_div.find_all("h5")]
            if isinstance(info_div, Tag)
            else []
        )
        date_raw = h5s[0] if len(h5s) > 0 else None
        venue = h5s[1] if len(h5s) > 1 else None
        series = h5s[2] if len(h5s) > 2 else None

        # Thumbnail image from div.image
        image_url = ""
        image_div = event_div.find("div", class_="image")
        if isinstance(image_div, Tag):
            img = image_div.find("img")
            if isinstance(img, Tag):
                image_url = str(img.get("src", ""))

        event_type = "show" if "/show/" in detail_url else "industry_event"

        cards.append(
            {
                "title_raw": title_raw,
                "detail_url": detail_url,
                "date_raw": date_raw,
                "venue": venue,
                "series": series,
                "image_url": image_url,
                "event_type": event_type,
            }
        )

    log.info("Found %d upcoming event cards on listing page", len(cards))
    return cards


# ── Detail page ───────────────────────────────────────────────────────────────

_FREE_PATTERN = re.compile(
    r"free admission|free entry|gratis adgang|free of charge|no charge|free event",
    re.IGNORECASE,
)


def scrape_detail(
    card: dict,
    session: requests.Session,
    today: datetime.date,
) -> list[dict]:
    """
    Fetch the event detail page, combine with listing *card* data, and return
    a list of event dicts — one per parsed date slot.  Returns [] on failure.
    """
    url: str = card["detail_url"]
    try:
        soup = get_soup(url, session)
    except requests.HTTPError as exc:
        log.warning("HTTP error fetching %s: %s", url, exc)
        return []

    # ── Description ───────────────────────────────────────────────────────────
    # All description sections live inside div.description on the detail page.
    description = ""
    desc_div = soup.find("div", class_="description")
    if isinstance(desc_div, Tag):
        description = markdownify.markdownify(
            str(desc_div), heading_style="ATX"
        ).strip()

    # ── Free / price ──────────────────────────────────────────────────────────
    price_note = ""
    # Look for a ticket/booking element for a short price note. The ".ticket"
    # class is also on the "Read more"/ticket link button, whose label is not
    # a price.
    for selector in [".ticket-info", ".booking-info", ".price", ".ticket"]:
        for el in soup.select(selector):
            if el.name in {"a", "button"} or "button" in (el.get("class") or []):
                continue
            price_note = el.get_text(" ", strip=True)[:200]
            break
        if price_note:
            break

    # Only the event's own text: the rest of the page (navigation, other
    # programme teasers) can mention a free event that isn't this one.
    event_text = " ".join(
        [
            desc_div.get_text(" ", strip=True) if isinstance(desc_div, Tag) else "",
            price_note,
        ]
    )
    is_free = bool(_FREE_PATTERN.search(event_text))

    # ── Build records from listing metadata ───────────────────────────────────
    date_raw: str = card.get("date_raw") or ""
    date_slots = parse_date_raw(date_raw, today)
    if not date_slots:
        log.warning("Could not parse date %r for %s — skipping", date_raw, url)
        return []

    title = re.sub(
        r"\s+(?:by\s+)?offered in collaboration\b.*",
        "",
        card.get("title_raw") or "",
        flags=re.IGNORECASE,
    ).strip()
    if not title:
        log.warning("No title for %s — skipping", url)
        return []

    venue_name = card.get("venue") or "Toaster CPH"
    # Some venues are given as a street address ("Thoravej29, Lokale 3.1,
    # 2400 København NV"); pass it on as the address too, for geocoding.
    venue_address = venue_name if re.search(r"\b\d{4}\s+\w", venue_name) else ""
    series = card.get("series")
    event_type = card.get("event_type", "show")
    image_url = card.get("image_url") or ""
    category = _determine_category(event_type, series)

    records: list[dict] = []
    for start_dt, end_dt in date_slots:
        records.append(
            {
                "title": title,
                "description": description,
                "start_datetime": start_dt.isoformat(),
                "end_datetime": end_dt.isoformat() if end_dt else None,
                "venue_name": venue_name,
                "venue_address": venue_address,
                "category": category,
                "is_free": is_free,
                "is_wheelchair_accessible": False,
                "price_note": price_note,
                "source_url": url,
                "external_source": EXTERNAL_SOURCE,
                "image_url": image_url,
            }
        )

    return records


# ── Main scrape entry point ───────────────────────────────────────────────────


def scrape(delay: float = 0.5) -> list[dict]:
    """Scrape the full program listing and return a list of event dicts."""
    session = make_session()

    crawl_delay = get_crawl_delay(BASE_URL)
    if crawl_delay is not None and crawl_delay > delay:
        log.info(
            "robots.txt Crawl-delay %.1fs overrides --delay %.1fs", crawl_delay, delay
        )
        delay = crawl_delay

    cards = collect_listing_cards(session)
    if not cards:
        return []

    today = datetime.date.today()
    events: list[dict] = []

    for i, card in enumerate(cards, 1):
        log.info("[%d/%d] Scraping %s", i, len(cards), card["detail_url"])
        records = scrape_detail(card, session, today)
        events.extend(records)
        if i < len(cards):
            time.sleep(delay)

    log.info("Scraped %d event records from %d cards", len(events), len(cards))
    return events


def main() -> None:
    args = build_arg_parser(
        "Scrape toastercph.dk program",
        "toastercph_events.json",
    ).parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    events = scrape(delay=args.delay)
    write_output(events, args.output, args.dry_run)


if __name__ == "__main__":
    main()
