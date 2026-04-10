"""Scraper for https://sort-hvid.dk/en/program-en/

Fetches all event listing URLs, visits each detail page, and outputs a JSON
array of event dicts ready for ingestion into the pleskal database.

Each detail page carries a date range and a recurring weekly schedule, e.g.:
    24. April 2026 - 22. May 2026
    Tuesday-Friday @ 20h00, Saturday @ 17h00

The scraper expands this into one record per matching performance date.

Usage:
    uv run python scrapers/sort_hvid.py
    uv run python scrapers/sort_hvid.py --output events.json
    uv run python scrapers/sort_hvid.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import datetime
import logging
import re
import zoneinfo
from urllib.parse import urljoin

import markdownify
import requests

from events.models import MAX_VENUE_LENGTH
from scrapers.base import (
    build_arg_parser,
    get_crawl_delay,
    get_soup,
    make_session,
    scrape_url_list,
    write_output,
)

BASE_URL = "https://sort-hvid.dk"
PROGRAM_URL = f"{BASE_URL}/en/program-en/"
EXTERNAL_SOURCE = "sort-hvid"
VENUE_NAME = "Sort/Hvid"
VENUE_ADDRESS = "Valdemarsgade 35, 1665 København V"
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")

# Day-name → Python weekday number (Monday=0)
WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

CATEGORY_MAP = {
    "opera": "performance",
    "theatre": "performance",
    "dance": "performance",
    "performance": "performance",
    "talk": "talk",
    "workshop": "workshop",
}

log = logging.getLogger(__name__)


# ── Listing page ──────────────────────────────────────────────────────────────


def collect_event_urls(session: requests.Session) -> list[str]:
    """Return all unique event detail URLs from the programme listing page."""
    soup = get_soup(PROGRAM_URL, session)
    seen: set[str] = set()
    urls: list[str] = []

    for a in soup.find_all("a", href=True):
        href = str(a.get("href", ""))
        url = urljoin(BASE_URL, href)
        if url not in seen and re.search(r"/en/forestilling/[^/]+/?$", url):
            seen.add(url)
            urls.append(url)

    log.info("Found %d event URLs on listing page", len(urls))
    return urls


# ── Date / time helpers ────────────────────────────────────────────────────────


def _parse_date(s: str) -> datetime.date | None:
    """
    Parse a date string like "24. April 2026" into a datetime.date.

    Uses Python's built-in ``%B`` directive which handles English month names
    natively — no custom month map required.
    Returns None on any parse failure.
    """
    try:
        return datetime.datetime.strptime(s.strip(), "%d. %B %Y").date()
    except ValueError:
        return None


def _parse_schedule(schedule_str: str) -> dict[int, datetime.time]:
    """
    Parse a recurring schedule string into a weekday→time mapping.

    Handles patterns like:
        "Tuesday-Friday @ 20h00, Saturday @ 17h00"
        "Wednesday @ 19h00"
        "Tuesday, Thursday @ 20h00"

    Each comma-separated segment may have:
      - A day range:  "Tuesday-Friday"  → expand to all weekdays in range
      - A day list:   "Tuesday, Thursday" is handled by splitting on comma first
      - A single day: "Saturday"

    Returns a dict mapping Python weekday ints (Mon=0) to datetime.time.
    Falls back to Mon–Fri at 20:00 if the string cannot be parsed at all.
    """
    result: dict[int, datetime.time] = {}

    # Split on comma; each segment looks like "Day[range] @ HHhMM" or "Day[range] HHHxx"
    segments = [seg.strip() for seg in schedule_str.split(",")]
    for seg in segments:
        time_match = re.search(r"(?:@\s*)?(\d{1,2})[Hh](\d{2})", seg)
        if not time_match:
            continue
        t = datetime.time(int(time_match.group(1)), int(time_match.group(2)))

        # Day spec is everything before the time (strip trailing @ or whitespace)
        day_spec = seg[: time_match.start()].strip().rstrip("@").strip()

        if "-" in day_spec:
            # Range: "Tuesday-Friday"
            parts = [p.strip().lower() for p in day_spec.split("-", 1)]
            start_wd = WEEKDAY_MAP.get(parts[0])
            end_wd = WEEKDAY_MAP.get(parts[1])
            if start_wd is not None and end_wd is not None:
                # Handle wrap-around (e.g. Friday-Sunday)
                if start_wd <= end_wd:
                    for wd in range(start_wd, end_wd + 1):
                        result[wd] = t
                else:
                    for wd in list(range(start_wd, 7)) + list(range(0, end_wd + 1)):
                        result[wd] = t
        else:
            wd = WEEKDAY_MAP.get(day_spec.lower())
            if wd is not None:
                result[wd] = t

    if not result:
        log.warning(
            "Could not parse schedule %r; defaulting to Mon–Fri 20:00", schedule_str
        )
        default_time = datetime.time(20, 0)
        result = {wd: default_time for wd in range(5)}

    return result


def _expand_dates(
    start: datetime.date,
    end: datetime.date,
    schedule: dict[int, datetime.time],
) -> list[tuple[datetime.date, datetime.time]]:
    """
    Expand a date range + schedule into a list of (date, time) pairs.

    Iterates every date from *start* to *end* inclusive and yields those
    whose weekday appears in *schedule*.
    """
    pairs: list[tuple[datetime.date, datetime.time]] = []
    current = start
    one_day = datetime.timedelta(days=1)
    while current <= end:
        if current.weekday() in schedule:
            pairs.append((current, schedule[current.weekday()]))
        current += one_day
    return pairs


def _combine_dt(date: datetime.date, t: datetime.time) -> datetime.datetime:
    """Combine date and time in CPH timezone, returned as UTC-aware datetime."""
    return datetime.datetime(
        date.year, date.month, date.day, t.hour, t.minute, tzinfo=CPH_TZ
    ).astimezone(datetime.UTC)


# ── Detail page ───────────────────────────────────────────────────────────────


def scrape_detail(url: str, session: requests.Session) -> list[dict] | None:
    """
    Scrape a single event detail page.

    Returns a list of event dicts (one per performance date), or None on
    parse errors.
    """
    try:
        soup = get_soup(url, session)
    except requests.HTTPError as exc:
        log.warning("HTTP error fetching %s: %s", url, exc)
        return None

    # ── Title ─────────────────────────────────────────────────────────────────
    h1 = soup.find("h1")
    if not h1:
        log.warning("No <h1> title found at %s", url)
        return None
    title = h1.get_text(strip=True)
    if not title:
        log.warning("Empty title at %s", url)
        return None

    # ── Date range and schedule ───────────────────────────────────────────────
    # Both appear as <strong> tags on the detail page.
    # Date range matches: "24. April 2026 - 22. May 2026"
    # Schedule matches:   "Tuesday-Friday @ 20h00, Saturday @ 17h00"
    #                  or "Tuesday-Thursday 20H00, Friday 17H00, Saturday 16H00"
    date_range_str = ""
    schedule_str = ""
    for strong in soup.find_all("strong"):
        text = strong.get_text(" ", strip=True)
        if not date_range_str and re.search(r"\d+\.\s+\w+\s+\d{4}", text):
            date_range_str = text
        elif not schedule_str and re.search(r"\d+[Hh]\d+", text):
            schedule_str = text

    if not date_range_str:
        log.warning("No date range found at %s", url)
        return None

    # Parse start / end dates from "24. April 2026 - 22. May 2026"
    date_parts = re.split(r"\s+-\s+", date_range_str, maxsplit=1)
    start_date = _parse_date(date_parts[0])
    end_date = _parse_date(date_parts[1]) if len(date_parts) > 1 else start_date

    if not start_date:
        log.warning("Cannot parse start date from %r at %s", date_range_str, url)
        return None
    if not end_date:
        end_date = start_date

    # Parse schedule; fall back to a single performance on start_date at 20:00
    if schedule_str:
        schedule = _parse_schedule(schedule_str)
    else:
        log.warning(
            "No schedule string found at %s; defaulting to start date 20:00", url
        )
        schedule = {start_date.weekday(): datetime.time(20, 0)}

    # Expand into individual (date, time) pairs
    date_time_pairs = _expand_dates(start_date, end_date, schedule)
    if not date_time_pairs:
        log.warning(
            "Schedule %r produced no dates in range %s–%s at %s",
            schedule_str,
            start_date,
            end_date,
            url,
        )
        return None

    # ── Description ───────────────────────────────────────────────────────────
    # Target .performance-content specifically to avoid:
    #   - .mobile: a hidden duplicate of the full page used for mobile layout
    #   - .newsletter: newsletter signup block
    #   - .cmplz-cookiebanner: cookie consent widget (rendered in Danish)
    description = ""
    content_el = soup.find(class_="performance-content")
    if content_el:
        raw_html = "".join(
            str(p) for p in content_el.find_all("p") if p.get_text(strip=True)
        )
        description = markdownify.markdownify(raw_html, heading_style="ATX").strip()

    # ── Image ─────────────────────────────────────────────────────────────────
    # Only GIFs are available; Pillow will extract the first frame on import.
    image_url = ""
    img = soup.find("img", src=re.compile(r"wp-content/uploads"))
    if img:
        image_url = str(img.get("src", ""))

    # ── Category ──────────────────────────────────────────────────────────────
    category = "performance"
    # Hashtag elements like "#opera", "#cph stage" appear as text nodes
    for el in soup.find_all(string=re.compile(r"#\w+")):
        tag_text = str(el).strip().lstrip("#").lower()
        if tag_text in CATEGORY_MAP:
            category = CATEGORY_MAP[tag_text]
            break

    # ── Venue ─────────────────────────────────────────────────────────────────
    venue_name = VENUE_NAME[:MAX_VENUE_LENGTH]
    venue_address = VENUE_ADDRESS[:MAX_VENUE_LENGTH]

    # ── Build one record per performance date ─────────────────────────────────
    records: list[dict] = []
    for perf_date, perf_time in date_time_pairs:
        start_dt = _combine_dt(perf_date, perf_time)
        records.append(
            {
                "title": title,
                "description": description,
                "start_datetime": start_dt.isoformat(),
                "end_datetime": None,
                "venue_name": venue_name,
                "venue_address": venue_address,
                "category": category,
                "is_free": False,
                "is_wheelchair_accessible": False,
                "price_note": "",
                "source_url": url,
                "external_source": EXTERNAL_SOURCE,
                "image_url": image_url,
            }
        )

    log.debug("Scraped %d performance dates for %r", len(records), title)
    return records


# ── Main ──────────────────────────────────────────────────────────────────────


def scrape(delay: float = 0.5) -> list[dict]:
    """Scrape the full programme and return a list of event dicts."""
    session = make_session()
    crawl_delay = get_crawl_delay(BASE_URL)
    if crawl_delay is not None and crawl_delay > delay:
        log.info(
            "robots.txt Crawl-delay %.1fs overrides --delay %.1fs", crawl_delay, delay
        )
        delay = crawl_delay
    urls = collect_event_urls(session)
    return scrape_url_list(urls, session, scrape_detail, delay)


def main() -> None:
    args = build_arg_parser(
        "Scrape sort-hvid.dk programme",
        "sort_hvid_events.json",
    ).parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    events = scrape(delay=args.delay)
    write_output(events, args.output, args.dry_run)


if __name__ == "__main__":
    main()
