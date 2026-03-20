"""Scraper for https://www.hautscene.dk/en/calendar

Fetches all event listing URLs, visits each detail page, and outputs a JSON
array of event dicts ready for ingestion into the Pleskal database.

Usage:
    uv run python scrapers/hautscene.py
    uv run python scrapers/hautscene.py --output events.json
    uv run python scrapers/hautscene.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import datetime
import logging
import re
import zoneinfo
from urllib.parse import urljoin

import markdownify
import requests
from bs4 import BeautifulSoup, Tag

from scrapers.base import build_arg_parser, get_soup, scrape_url_list, write_output

BASE_URL = "https://www.hautscene.dk"
CALENDAR_URL = f"{BASE_URL}/en/calendar"
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")
EXTERNAL_SOURCE = "hautscene"

# Map hautscene format strings → Pleskal EventCategory values
CATEGORY_MAP = {
    "talk": "talk",
    "talks": "talk",
    "workshop": "workshop",
    "worksharing": "workshop",
    "residencies": "other",
    "residency": "other",
    "other events": "other",
    "performances": "performance",
    "performance": "performance",
}

log = logging.getLogger(__name__)


# ── Listing page ──────────────────────────────────────────────────────────────


def _next_page_url(soup: BeautifulSoup, current_url: str) -> str | None:
    """
    Extract the next-page URL from Webflow's pagination controls.

    Webflow renders pagination links whose href contains the current page's
    query string with a page counter.  We find any link whose href includes
    a query parameter ending in ``_page=<N>`` and return the one with the
    highest page number that is greater than the current page.

    Falls back to None if no such link is found (last page or single page).
    """
    # Determine current page number from the URL we just fetched
    current_page_match = re.search(r"_page=(\d+)", current_url)
    current_page = int(current_page_match.group(1)) if current_page_match else 1

    best: tuple[int, str] | None = None
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        m = re.search(r"(_page=)(\d+)", href)
        if not m:
            continue
        n = int(m.group(2))
        if n > current_page and (best is None or n > best[0]):
            best = (n, urljoin(BASE_URL, href))

    return best[1] if best else None


def collect_event_urls(session: requests.Session) -> list[str]:
    """Return all unique event detail URLs from the calendar listing."""
    seen: set[str] = set()
    urls: list[str] = []

    page_url: str | None = CALENDAR_URL
    pages_fetched = 0
    while page_url:
        pages_fetched += 1
        try:
            soup = get_soup(page_url, session)
        except requests.HTTPError as exc:
            log.warning("[%d] HTTP error fetching %s: %s", pages_fetched, page_url, exc)
            break

        # Only collect from the upcoming events section, not .calendar-archive
        upcoming = soup.select_one("div.calendar-container") or soup
        found_on_page = 0
        for a in upcoming.select("div.calendar-event-teaser a[href]"):
            href = str(a.get("href", ""))
            if not re.search(r"/en/events/[^/]+$", href):
                continue
            url = urljoin(BASE_URL, href)
            if url not in seen:
                seen.add(url)
                urls.append(url)
                found_on_page += 1

        log.debug(
            "[%d] %s: found %d new event URLs", pages_fetched, page_url, found_on_page
        )

        page_url = _next_page_url(soup, page_url)

    log.info("Found %d event URLs across %d listing pages", len(urls), pages_fetched)
    return urls


# ── Date / time helpers ────────────────────────────────────────────────────────


def parse_date(date_str: str) -> datetime.date | None:
    """
    Parse a date string in DD.M.YY or DD.MM.YY format into a datetime.date.

    The year is always interpreted as 20XX (e.g. "26" → 2026).
    Returns None on failure.
    """
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{2})$", date_str.strip())
    if not m:
        return None
    day, month, year_short = int(m.group(1)), int(m.group(2)), int(m.group(3))
    year = 2000 + year_short
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def parse_time(time_str: str) -> tuple[datetime.time, datetime.time | None]:
    """
    Parse a time range string like "15:00 - 18:00" or "15:00".

    Also accepts dot-separated times like "15.00 - 17.00".
    Returns (start_time, end_time) where end_time may be None.
    Raises ValueError if start_time cannot be parsed.
    """
    parts = [p.strip() for p in time_str.split("-")]
    m_start = re.match(r"^(\d{1,2})[:.](\d{2})$", parts[0])
    if not m_start:
        raise ValueError(f"Cannot parse time: {time_str!r}")
    start_time = datetime.time(int(m_start.group(1)), int(m_start.group(2)))
    end_time = None
    if len(parts) >= 2:
        m_end = re.match(r"^(\d{1,2})[:.](\d{2})$", parts[1])
        if m_end:
            end_time = datetime.time(int(m_end.group(1)), int(m_end.group(2)))
    return start_time, end_time


def combine_dt(date: datetime.date, t: datetime.time) -> datetime.datetime:
    """Combine a date and time in CPH timezone, returned as UTC-aware datetime."""
    return datetime.datetime(
        date.year, date.month, date.day, t.hour, t.minute, tzinfo=CPH_TZ
    ).astimezone(datetime.UTC)


# ── Detail page ───────────────────────────────────────────────────────────────


def _get_info_row_value(info_div: Tag, label: str) -> str:
    """
    From the event-info block, find the row whose .row-title matches *label*
    (case-insensitive) and return the adjacent value text.
    """
    for row in info_div.select("div.info-row"):
        title_el = row.select_one("div.row-title")
        if title_el and label.lower() in title_el.get_text(strip=True).lower():
            value_el = row.find(
                lambda tag: tag.name == "div" and "size-medium" in tag.get("class", [])
            )
            if value_el:
                return value_el.get_text(" ", strip=True)
    return ""


def scrape_detail(url: str, session: requests.Session) -> dict | None:
    """
    Scrape a single event detail page.

    Returns an event dict, or None on parse errors.
    """
    try:
        soup = get_soup(url, session)
    except requests.HTTPError as exc:
        log.warning("HTTP error fetching %s: %s", url, exc)
        return None

    # ── Title ─────────────────────────────────────────────────────────────────
    title_el = soup.select_one("div.section-tag")
    if not title_el:
        log.warning("No title found at %s", url)
        return None
    title = title_el.get_text(strip=True)
    if not title:
        log.warning("Empty title at %s", url)
        return None

    # ── Dates and times ───────────────────────────────────────────────────────
    info_div = soup.select_one("div.event-info")
    if not info_div:
        log.warning("No event-info block at %s", url)
        return None

    date_elem = info_div.select_one("div[data-compare-dates='true']")
    start_date_str = str(date_elem.get("data-start", "")) if date_elem else ""
    end_date_str = str(date_elem.get("data-end", "")) if date_elem else ""

    start_date = parse_date(start_date_str)
    if not start_date:
        log.warning("Cannot parse date %r at %s", start_date_str, url)
        return None

    # Time row: look for a row labelled "time" or "Time"
    time_str = _get_info_row_value(info_div, "time")
    start_dt: datetime.datetime
    end_dt: datetime.datetime | None = None

    if time_str:
        try:
            start_time, end_time = parse_time(time_str)
            start_dt = combine_dt(start_date, start_time)
            if end_time:
                # Use end_date if available and different from start_date
                end_date = parse_date(end_date_str) if end_date_str else None
                end_day = (
                    end_date if (end_date and end_date != start_date) else start_date
                )
                end_dt = combine_dt(end_day, end_time)
        except ValueError as exc:
            log.warning("Cannot parse time %r at %s: %s", time_str, url, exc)
            # Fall back to midnight start with no end
            start_dt = combine_dt(start_date, datetime.time(0, 0))
    else:
        start_dt = combine_dt(start_date, datetime.time(0, 0))

    # ── Venue / address ───────────────────────────────────────────────────────
    place_text = _get_info_row_value(info_div, "place")
    venue_name = "Haut Scene"
    venue_address = place_text[:200]

    # ── Description ───────────────────────────────────────────────────────────
    # The description lives in .section-event-research, identified by a
    # .section-tag heading that matches one of the known intro phrases.
    DESCRIPTION_HEADINGS = {
        "om eventet",
        "the event",
        "about the event",
        "artistic research",
        "the artistic research",
        "the artistic researches",
        "frame",
        "artistic practice",
        "the artistic practice",
        "the artistic practice and research",
        "the conversation",
    }
    description = ""
    for section in soup.select(".section-event-research"):
        tag_el = section.select_one(".section-tag")
        if not tag_el:
            continue
        if tag_el.get_text(strip=True).lower() not in DESCRIPTION_HEADINGS:
            continue
        richtext = section.select_one(".w-richtext")
        if richtext:
            description = markdownify.markdownify(
                str(richtext), heading_style="ATX"
            ).strip()
            break

    # ── Image ─────────────────────────────────────────────────────────────────
    image_url = ""
    hero_img = soup.select_one("img.hero-figure-image")
    if hero_img:
        image_url = str(hero_img.get("src", ""))

    # ── Category ──────────────────────────────────────────────────────────────
    category = "other"
    tag_el = soup.select_one("div.event-tags a.link-button-tag")
    if tag_el:
        category = CATEGORY_MAP.get(tag_el.get_text(strip=True).lower(), "other")

    # ── Price / free detection ────────────────────────────────────────────────
    price_note = ""
    is_free = False
    booking_div = soup.select_one("div.booking-info .w-richtext")
    if booking_div:
        booking_text = booking_div.get_text(" ", strip=True)
        price_note = booking_text[:200]
        lower = booking_text.lower()
        if re.search(
            r"free admission|free entry|gratis|free of charge|no charge", lower
        ):
            is_free = True

    return {
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


# ── Main ──────────────────────────────────────────────────────────────────────


def scrape(delay: float = 0.5) -> list[dict]:
    """Scrape the full calendar and return a list of event dicts."""
    session = requests.Session()
    urls = collect_event_urls(session)
    return scrape_url_list(urls, session, scrape_detail, delay)


def main() -> None:
    args = build_arg_parser(
        "Scrape hautscene.dk calendar",
        "hautscene_events.json",
    ).parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    events = scrape(delay=args.delay)
    write_output(events, args.output, args.dry_run)


if __name__ == "__main__":
    main()
