"""Scraper for https://dansehallerne.dk/en/public-program/

Fetches all event listing URLs, visits each detail page, and outputs a JSON
array of event dicts ready for ingestion into the pleskal database.

Each detail page may have multiple dates (one ICS button per date), so a
single page can produce multiple output records.

Usage:
    uv run python scrapers/dansehallerne.py
    uv run python scrapers/dansehallerne.py --output events.json
    uv run python scrapers/dansehallerne.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import contextlib
import datetime
import logging
import re
import zoneinfo
from urllib.parse import urljoin

import markdownify
import requests
from bs4 import BeautifulSoup

from scrapers.base import (
    build_arg_parser,
    get_crawl_delay,
    get_soup,
    make_session,
    scrape_url_list,
    write_output,
)

BASE_URL = "https://dansehallerne.dk"
PROGRAM_URL = f"{BASE_URL}/en/public-program/"
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")

# Map dansehallerne type strings → pleskal EventCategory values
CATEGORY_MAP = {
    "performance": "performance",
    "ipaf performance": "performance",
    "talk": "talk",
    "workshop": "workshop",
    "open practice": "openpractice",
    "social": "social",
    "children": "other",
    "children & family": "other",
    "family": "other",
}

log = logging.getLogger(__name__)


# ── Listing page ──────────────────────────────────────────────────────────────


def collect_event_urls(session: requests.Session) -> list[str]:
    """Return all unique event detail URLs from the public programme listing."""
    soup = get_soup(PROGRAM_URL, session)
    seen: set[str] = set()
    urls: list[str] = []

    for a in soup.find_all("a", href=True):
        href = str(a.get("href", ""))
        url = urljoin(BASE_URL, href)
        # Only accept paths like /en/public-program/<type>/<id>/
        if url not in seen and re.search(r"/en/public-program/[^/]+/\d+/?$", url):
            seen.add(url)
            urls.append(url)

    log.info("Found %d event URLs on listing page", len(urls))
    return urls


# ── Date string parser ────────────────────────────────────────────────────────


def parse_date_string(
    date_str: str,
) -> list[tuple[datetime.datetime, datetime.datetime | None]]:
    """
    Parse a dansehallerne date string into a list of (start_dt, end_dt) pairs.

    Handles:
      - Single date:      "1.5.2026, 18:00"
      - Day range:        "1.–3.5.2026, 18:00"        → 1,2,3 May
      - Multiple ranges:  "1.–3.5 + 8.–10.5.2026, 18:00" → 1,2,3,8,9,10 May

    The time applies to every generated date.  End time is derived from the
    Duration meta field (handled by the caller), so end_dt is always None here.
    """
    # Normalise unicode dashes and whitespace
    date_str = date_str.replace("\u2013", "-").replace("\u2014", "-").strip()

    # Extract trailing year and time: "..., HH:MM" or "....YYYY, HH:MM"
    time_m = re.search(r",\s*(\d{2}):(\d{2})\s*$", date_str)
    if not time_m:
        return []
    hour, minute = int(time_m.group(1)), int(time_m.group(2))
    date_str = date_str[: time_m.start()].strip()

    # Extract year — may appear only in the last segment after a '+'
    year_m = re.search(r"\.(\d{4})$", date_str)
    if not year_m:
        return []
    year = int(year_m.group(1))
    date_str = date_str[: year_m.start()].strip()

    results: list[tuple[datetime.datetime, datetime.datetime | None]] = []

    # Split into range segments on ' + '
    for segment in re.split(r"\s*\+\s*", date_str):
        segment = segment.strip()

        # Each segment may end with an explicit month: "1.-3.5" or "8.-10.5"
        # or just days if month was already consumed: shouldn't happen here
        seg_month_m = re.search(r"\.(\d{1,2})$", segment)
        if not seg_month_m:
            return []
        month = int(seg_month_m.group(1))
        seg_days = segment[: seg_month_m.start()].strip()

        # Parse day or day range
        range_m = re.match(r"^(\d{1,2})\.-(\d{1,2})$", seg_days)
        single_m = re.match(r"^(\d{1,2})$", seg_days)

        if range_m:
            day_start, day_end = int(range_m.group(1)), int(range_m.group(2))
        elif single_m:
            day_start = day_end = int(single_m.group(1))
        else:
            return []

        for day in range(day_start, day_end + 1):
            try:
                dt = datetime.datetime(
                    year, month, day, hour, minute, tzinfo=CPH_TZ
                ).astimezone(datetime.UTC)
            except ValueError:
                continue
            results.append((dt, None))

    return results


# ── Detail page ───────────────────────────────────────────────────────────────


def parse_meta_table(soup: BeautifulSoup) -> dict[str, str]:
    """Extract key→value pairs from the .meta-info.table section."""
    meta: dict[str, str] = {}
    for row in soup.select("section.event-meta-infos .meta-info.table .row"):
        key_el = row.select_one(".key")
        val_el = row.select_one(".value")
        if not (key_el and val_el):
            continue
        key = key_el.get_text(strip=True).lower().rstrip(":")
        # Skip the "add to calendar" row — it mixes text from all ICS buttons
        if key == "add to calendar":
            continue
        val = val_el.get_text(" ", strip=True)
        meta[key] = val
    return meta


def parse_description(soup: BeautifulSoup) -> str:
    """Extract markdown description from #event-entry-content."""
    content_div = soup.select_one("#event-entry-content")
    if not content_div:
        return ""
    return markdownify.markdownify(str(content_div), heading_style="ATX").strip()


def parse_image_url(soup: BeautifulSoup) -> str:
    """Return the best available image URL from the post-thumbnail figure."""
    figure = soup.select_one("figure.post-thumbnail")
    if not figure:
        return ""
    img = figure.select_one("img")
    if not img:
        return ""
    # Prefer the largest srcset entry
    srcset = str(img.get("srcset", ""))
    if srcset:
        candidates: list[tuple[int, str]] = []
        for part in srcset.split(","):
            chunks = part.strip().split()
            if len(chunks) >= 2:
                with contextlib.suppress(ValueError):
                    candidates.append((int(chunks[1].rstrip("w")), chunks[0]))
        if candidates:
            return max(candidates, key=lambda x: x[0])[1]
    return str(img.get("src", ""))


def map_category(raw_type: str) -> str:
    return CATEGORY_MAP.get(raw_type.lower().strip(), "other")


def parse_venue_address(venue_raw: str) -> tuple[str, str]:
    """
    Return (venue_name, address) from the raw venue meta value.

    The venue field can look like:
      - "Dansehallerne, Franciska Clausens Plads 27, 1799 Copenhagen V View map Hide map"
      - "Studio 4"
      - "Blackboxen, Dansehallerne"

    We always want venue_name = "Dansehallerne" and a clean address.
    """
    # Strip trailing map-toggle text
    venue_raw = re.sub(
        r"\s*(View map|Hide map|View kort|Skjul kort)\s*", "", venue_raw
    ).strip()

    address = "Franciska Clausens Plads 27, 1799 Copenhagen V"

    # If the raw text contains a recognisable street address, extract it
    addr_match = re.search(
        r"Franciska Clausens Plads\s+\d+.*?(?=\s*(?:View|Hide|Vis|Skjul|$))",
        venue_raw,
    )
    if addr_match:
        address = addr_match.group(0).strip()

    # Normalise Danish city name to English spelling used in the app
    address = re.sub(r"København", "Copenhagen", address)

    return "Dansehallerne", address


def scrape_detail(url: str, session: requests.Session) -> list[dict]:
    """
    Scrape a single event detail page.

    Returns a list of event dicts — one per date (multi-date events have
    multiple ICS buttons).  Returns an empty list on parse errors.
    """
    try:
        soup = get_soup(url, session)
    except requests.HTTPError as exc:
        log.warning("HTTP error fetching %s: %s", url, exc)
        return []

    meta = parse_meta_table(soup)
    if not meta:
        log.warning("No meta table found at %s", url)
        return []

    description = parse_description(soup)
    image_url = parse_image_url(soup)
    raw_type = meta.get("type", "")
    category = map_category(raw_type)
    venue_name, address = parse_venue_address(meta.get("venue", ""))

    title = meta.get("title", "")
    artist = meta.get("artist", "")
    if title and artist:
        title = f"{title} by {artist}"
    elif not title:
        title = artist
    if not title:
        log.warning("No title found at %s", url)
        return []

    # Price detection — the site has no single "is_free" field.
    # Heuristic: check for free-admission language first (higher priority),
    # then pay-what-you-can, then ticket-button presence.
    price_note = ""
    full_text = description.lower()
    # "free admission" / "free entry" / "gratis" in first 600 chars (intro)
    if re.search(r"free admission|free entry|gratis|free of charge", full_text[:600]):
        price_note = "Free admission"
        is_free = True
    elif re.search(r"pay what you can|sliding scale", full_text[:600]):
        # Check that this isn't just a boilerplate footer note
        # by looking for it in the *first* 300 chars specifically
        price_note = "Pay what you can (sliding scale)"
        is_free = False
    else:
        # Fall back to ticket-button presence in the event-meta-infos section
        meta_section = soup.select_one("section.event-meta-infos")
        has_ticket_btn = bool(
            meta_section and meta_section.select_one("button.basm_select")
        )
        is_free = not has_ticket_btn

    # Build entries from ICS buttons where timestamps are present, then
    # fill any remaining dates from the meta table date string.  This handles
    # the case where the site only populates data-start on a subset of buttons.
    ics_entries: list[tuple[datetime.datetime, datetime.datetime | None]] = []
    for btn in soup.select("button.js-download[data-start]"):
        start_ts = btn.get("data-start")
        end_ts = btn.get("data-end")
        if not start_ts:
            continue
        start_dt = datetime.datetime.fromtimestamp(int(str(start_ts)), tz=datetime.UTC)
        end_dt = (
            datetime.datetime.fromtimestamp(int(str(end_ts)), tz=datetime.UTC)
            if end_ts
            else None
        )
        ics_entries.append((start_dt, end_dt))

    # Parse all dates from the meta table and use any not already covered
    date_str = meta.get("date", "")
    meta_entries = parse_date_string(date_str)
    if meta_entries:
        # Try to derive end from Duration for meta-derived entries
        duration_str = meta.get("duration", "")
        dur_m = re.match(r"(\d+)\s*hour", duration_str, re.IGNORECASE)
        delta = datetime.timedelta(hours=int(dur_m.group(1))) if dur_m else None

        ics_dates = {e[0].date() for e in ics_entries}
        for start_dt, _ in meta_entries:
            if start_dt.date() not in ics_dates:
                end_dt = start_dt + delta if delta else None
                ics_entries.append((start_dt, end_dt))

        ics_entries.sort(key=lambda e: e[0])

    if not ics_entries:
        log.warning("Cannot parse date %r at %s", date_str, url)
        return []

    results = []
    for start_dt, end_dt in ics_entries:
        results.append(
            {
                "title": title,
                "description": description,
                "start_datetime": start_dt.isoformat(),
                "end_datetime": end_dt.isoformat() if end_dt else None,
                "venue_name": venue_name,
                "venue_address": address,
                "category": category,
                "is_free": is_free,
                "is_wheelchair_accessible": True,
                "price_note": price_note,
                "source_url": url,
                "external_source": "dansehallerne",
                "image_url": image_url,
            }
        )

    return results


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
        "Scrape dansehallerne.dk public programme",
        "dansehallerne_events.json",
    ).parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    events = scrape(delay=args.delay)
    write_output(events, args.output, args.dry_run)


if __name__ == "__main__":
    main()
