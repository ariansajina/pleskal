"""Scraper for https://dansehallerne.dk/en/professionals/

Fetches all workshop listing URLs, visits each detail page, and outputs a JSON
array of event dicts ready for ingestion into the pleskal database.

All events from this endpoint are categorised as "workshop".  Each detail page
may have multiple dates (one ICS button per date), so a single page can produce
multiple output records.

Usage:
    uv run python scrapers/dansehallerne_workshops.py
    uv run python scrapers/dansehallerne_workshops.py --output workshops.json
    uv run python scrapers/dansehallerne_workshops.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import datetime
import logging
import re
from urllib.parse import urljoin

import requests

from scrapers.base import (
    build_arg_parser,
    get_crawl_delay,
    get_soup,
    make_session,
    scrape_url_list,
    write_output,
)
from scrapers.dansehallerne import (
    parse_date_string,
    parse_description,
    parse_image_url,
    parse_meta_table,
    parse_venue_address,
)

BASE_URL = "https://dansehallerne.dk"
WORKSHOPS_URL = f"{BASE_URL}/en/professionals/"

log = logging.getLogger(__name__)


# ── Listing page ──────────────────────────────────────────────────────────────


def collect_workshop_urls(session: requests.Session) -> list[str]:
    """Return all unique workshop detail URLs from the professionals listing."""
    soup = get_soup(WORKSHOPS_URL, session)
    seen: set[str] = set()
    urls: list[str] = []

    for a in soup.find_all("a", href=True):
        href = str(a.get("href", ""))
        url = urljoin(BASE_URL, href)
        # Only accept paths like /en/professionals/<type>/<id>/
        if url not in seen and re.search(r"/en/professionals/[^/]+/\d+/?$", url):
            seen.add(url)
            urls.append(url)

    log.info("Found %d workshop URLs on listing page", len(urls))
    return urls


# ── Detail page ───────────────────────────────────────────────────────────────


def scrape_detail(url: str, session: requests.Session) -> list[dict]:
    """
    Scrape a single workshop detail page.

    Returns a list of event dicts — one per date (multi-date workshops have
    multiple ICS buttons).  Returns an empty list on parse errors.

    Category is always "workshop" for this endpoint.
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

    # Price detection — same heuristic as the public programme scraper.
    price_note = ""
    full_text = description.lower()
    if re.search(r"free admission|free entry|gratis|free of charge", full_text[:600]):
        price_note = "Free admission"
        is_free = True
    elif re.search(r"pay what you can|sliding scale", full_text[:600]):
        price_note = "Pay what you can (sliding scale)"
        is_free = False
    else:
        meta_section = soup.select_one("section.event-meta-infos")
        has_ticket_btn = bool(
            meta_section and meta_section.select_one("button.basm_select")
        )
        is_free = not has_ticket_btn

    # Build entries from ICS buttons where timestamps are present, then
    # fill any remaining dates from the meta table date string.
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

    date_str = meta.get("date", "")
    meta_entries = parse_date_string(date_str)
    if meta_entries:
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

    # Workshops with multiple sessions are series. Single-session listings
    # don't get a series — they behave as a normal event.
    multi_session = len(ics_entries) > 1
    series_key = url if multi_session else ""

    results = []
    for start_dt, end_dt in ics_entries:
        record = {
            "title": title,
            "description": description,
            "start_datetime": start_dt.isoformat(),
            "end_datetime": end_dt.isoformat() if end_dt else None,
            "venue_name": venue_name,
            "venue_address": address,
            "category": "workshop",
            "is_free": is_free,
            "is_wheelchair_accessible": True,
            "price_note": price_note,
            "source_url": url,
            "external_source": "dansehallerne",
            "image_url": image_url,
        }
        if series_key:
            record["series_key"] = series_key
            record["series_title"] = title
            record["series_description"] = description
        results.append(record)

    return results


# ── Main ──────────────────────────────────────────────────────────────────────


def scrape(delay: float = 0.5) -> list[dict]:
    """Scrape all workshops and return a list of event dicts."""
    session = make_session()
    crawl_delay = get_crawl_delay(BASE_URL)
    if crawl_delay is not None and crawl_delay > delay:
        log.info(
            "robots.txt Crawl-delay %.1fs overrides --delay %.1fs", crawl_delay, delay
        )
        delay = crawl_delay
    urls = collect_workshop_urls(session)
    return scrape_url_list(urls, session, scrape_detail, delay)


def main() -> None:
    args = build_arg_parser(
        "Scrape dansehallerne.dk workshops (professionals programme)",
        "dansehallerne_workshops_events.json",
    ).parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    events = scrape(delay=args.delay)
    write_output(events, args.output, args.dry_run)


if __name__ == "__main__":
    main()
