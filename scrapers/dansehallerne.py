"""Scraper for https://dansehallerne.dk/en/public-program/

Fetches all event listing URLs, visits each detail page, and outputs a JSON
array of event dicts ready for ingestion into the Pleskal database.

Each detail page may have multiple dates (one ICS button per date), so a
single page can produce multiple output records.

Usage:
    uv run python scrapers/dansehallerne.py
    uv run python scrapers/dansehallerne.py --output events.json
    uv run python scrapers/dansehallerne.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import logging
import re
import time
import zoneinfo
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://dansehallerne.dk"
PROGRAM_URL = f"{BASE_URL}/en/public-program/"
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; PleskalScraper/1.0; +https://pleskal.dk)"),
    "Accept-Language": "en-US,en;q=0.9",
}

# Map dansehallerne type strings → Pleskal EventCategory values
CATEGORY_MAP = {
    "performance": "performance",
    "ipaf performance": "performance",
    "talk": "talk",
    "workshop": "workshop",
    "open practice": "open_practice",
    "social": "social",
    "children": "other",
    "children & family": "other",
    "family": "other",
}

log = logging.getLogger(__name__)


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


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
    """Extract plain-text description from #event-entry-content."""
    content_div = soup.select_one("#event-entry-content")
    if not content_div:
        return ""
    for br in content_div.find_all("br"):
        br.replace_with("\n")
    paragraphs = []
    for el in content_div.find_all(["p", "h2", "h3", "h4"]):
        text = el.get_text("\n", strip=True)
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs).strip()


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

    title = meta.get("title", "") or meta.get("artist", "")
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

    # Each ICS download button = one date/time slot
    ics_buttons = soup.select("button.js-download[data-start]")

    if not ics_buttons:
        # Fallback: parse date from meta table
        date_str = meta.get("date", "")
        m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4}),\s*(\d{2}):(\d{2})", date_str)
        if not m:
            log.warning("Cannot parse date %r at %s", date_str, url)
            return []
        day, month, year, hour, minute = (int(x) for x in m.groups())
        start_dt = datetime.datetime(
            year, month, day, hour, minute, tzinfo=CPH_TZ
        ).astimezone(datetime.UTC)
        # Try to derive end from Duration
        end_dt: datetime.datetime | None = None
        duration_str = meta.get("duration", "")
        dur_m = re.match(r"(\d+)\s*hour", duration_str, re.IGNORECASE)
        if dur_m:
            end_dt = start_dt + datetime.timedelta(hours=int(dur_m.group(1)))
        ics_entries = [(start_dt, end_dt)]
    else:
        ics_entries = []
        for btn in ics_buttons:
            start_ts = btn.get("data-start")
            end_ts = btn.get("data-end")
            if not start_ts:
                continue
            start_dt = datetime.datetime.fromtimestamp(
                int(str(start_ts)), tz=datetime.UTC
            )
            end_dt = (
                datetime.datetime.fromtimestamp(int(str(end_ts)), tz=datetime.UTC)
                if end_ts
                else None
            )
            ics_entries.append((start_dt, end_dt))

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
    session = requests.Session()
    urls = collect_event_urls(session)

    events: list[dict] = []
    for i, url in enumerate(urls, 1):
        log.info("[%d/%d] Scraping %s", i, len(urls), url)
        records = scrape_detail(url, session)
        events.extend(records)
        if i < len(urls):
            time.sleep(delay)

    log.info("Scraped %d event records from %d pages", len(events), len(urls))
    return events


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape dansehallerne.dk public programme"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="dansehallerne_events.json",
        help="Output JSON file path (default: dansehallerne_events.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print JSON to stdout instead of writing a file",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay in seconds between detail page requests (default: 0.5)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    events = scrape(delay=args.delay)

    output = json.dumps(events, indent=2, ensure_ascii=False)

    if args.dry_run:
        print(output)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Wrote {len(events)} events to {args.output}")


if __name__ == "__main__":
    main()
