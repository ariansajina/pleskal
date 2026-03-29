"""Scraper for https://kbhdanser.dk/en/

Fetches upcoming dance performance events and outputs a JSON array of event
dicts ready for ingestion into the pleskal database.

Each kbhdanser event may have multiple performance dates, possibly at different
venues.  The scraper flattens these into individual records — one per
performance date — so the standard base_import machinery can upsert them using
(source_url, start_datetime) as a unique key.

Usage:
    uv run python scrapers/kbhdanser.py
    uv run python scrapers/kbhdanser.py --output events.json
    uv run python scrapers/kbhdanser.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import contextlib
import datetime
import logging
import re
import time
import zoneinfo

import requests
from bs4 import BeautifulSoup, Tag

from scrapers.base import (
    build_arg_parser,
    get_crawl_delay,
    get_soup,
    make_session,
    write_output,
)

BASE_URL = "https://kbhdanser.dk"
HOME_URL = f"{BASE_URL}/en/"
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")
EXTERNAL_SOURCE = "kbhdanser"

# Hardcoded venue address lookup.  Keys are lowercase; values are
# (canonical display name, full address).  Matching is case-insensitive and
# supports partial substring matching.
VENUE_ADDRESSES: dict[str, tuple[str, str]] = {
    "østre gasværk teater": (
        "Østre Gasværk Teater",
        "Nyborggade 17, 2100 København Ø",
    ),
    "østre gasværk theatre": (
        "Østre Gasværk Teater",
        "Nyborggade 17, 2100 København Ø",
    ),
    "østre gasværk": (
        "Østre Gasværk Teater",
        "Nyborggade 17, 2100 København Ø",
    ),
    "gamle scene": (
        "Det Kongelige Teater – Gamle Scene",
        "Kongens Nytorv 9, 1017 København K",
    ),
    "musikhuset aarhus": (
        "Musikhuset Aarhus",
        "Thomas Jensens Allé 2, 8000 Aarhus C",
    ),
}

DANISH_MONTHS: dict[str, int] = {
    "januar": 1,
    "februar": 2,
    "marts": 3,
    "april": 4,
    "maj": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}

ENGLISH_MONTHS: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

log = logging.getLogger(__name__)


# ── Venue helpers ─────────────────────────────────────────────────────────────


def lookup_venue(raw_name: str) -> tuple[str, str | None]:
    """
    Return (canonical_name, address) for a venue name.

    Tries an exact match, then a substring match against the hardcoded table.
    Logs a warning and returns (raw_name, None) for unknown venues.
    """
    normalised = raw_name.strip().lower()
    if normalised in VENUE_ADDRESSES:
        display, address = VENUE_ADDRESSES[normalised]
        return display, address
    for key, (display, address) in VENUE_ADDRESSES.items():
        if key in normalised or normalised in key:
            return display, address
    log.warning("Unknown venue %r — address will be omitted", raw_name)
    return raw_name.strip(), None


# ── Date / time helpers ───────────────────────────────────────────────────────

# Danish: "21. maj 2026. kl. 19:30"
_DANISH_DATE_RE = re.compile(
    r"(\d{1,2})\.\s*"
    r"(januar|februar|marts|april|maj|juni|juli|august|september|oktober|november|december)"
    r"\s+(\d{4})\.?\s*(?:kl\.\s*(\d{1,2})[.:](\d{2}))?",
    re.IGNORECASE,
)

# English: "May 21, 2026 - 7:30PM"  or  "September 26th, 2026 – 20:00"
_ENGLISH_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August"
    r"|September|October|November|December)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"
    r"(?:\s*[-–]\s*(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?)?",
    re.IGNORECASE,
)


def _parse_danish_dates(
    text: str,
) -> list[tuple[datetime.date, datetime.time | None]]:
    results: list[tuple[datetime.date, datetime.time | None]] = []
    for m in _DANISH_DATE_RE.finditer(text):
        day = int(m.group(1))
        month = DANISH_MONTHS[m.group(2).lower()]
        year = int(m.group(3))
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            continue
        t: datetime.time | None = None
        if m.group(4) and m.group(5):
            with contextlib.suppress(ValueError):
                t = datetime.time(int(m.group(4)), int(m.group(5)))
        results.append((d, t))
    return results


def _parse_english_dates(
    text: str,
) -> list[tuple[datetime.date, datetime.time | None]]:
    results: list[tuple[datetime.date, datetime.time | None]] = []
    for m in _ENGLISH_DATE_RE.finditer(text):
        month = ENGLISH_MONTHS[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3))
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            continue
        t = None
        if m.group(4) and m.group(5):
            hour = int(m.group(4))
            minute = int(m.group(5))
            ampm = m.group(6) or ""
            if ampm.upper() == "PM" and hour < 12:
                hour += 12
            elif ampm.upper() == "AM" and hour == 12:
                hour = 0
            with contextlib.suppress(ValueError):
                t = datetime.time(hour, minute)
        results.append((d, t))
    return results


def parse_dates(text: str) -> list[tuple[datetime.date, datetime.time | None]]:
    """Return (date, time_or_None) pairs found in *text* (Danish or English)."""
    results = _parse_danish_dates(text)
    if not results:
        results = _parse_english_dates(text)
    return results


def make_dt(d: datetime.date, t: datetime.time | None) -> datetime.datetime:
    """Combine date + time in CPH timezone; returns UTC-aware datetime."""
    effective_t = t if t is not None else datetime.time(19, 0)
    return datetime.datetime(
        d.year,
        d.month,
        d.day,
        effective_t.hour,
        effective_t.minute,
        tzinfo=CPH_TZ,
    ).astimezone(datetime.UTC)


# ── Homepage scraping ─────────────────────────────────────────────────────────


def _real_img_src(tag: Tag) -> str:
    """Return the first non-SVG src from an <img> tag."""
    for img in tag.find_all("img"):
        src = str(img.get("src", ""))
        if src.startswith("https://"):
            return src
    return ""


def collect_event_cards(soup: BeautifulSoup) -> list[dict]:
    """
    Extract event card data from the kbhdanser homepage.

    Returns a list of dicts with keys: title, artists, detail_url, image_url.
    Only returns cards where the href looks like a direct event page
    (``/slug/`` or ``/slug``), not nav/footer links.
    """
    cards: list[dict] = []
    seen_urls: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        # Event card links are absolute URLs to /slug or /slug/ on the same domain
        if not href.startswith(BASE_URL + "/"):
            continue
        # Exclude /en/ pages (those are landing pages, not detail pages)
        path = href[len(BASE_URL) :]
        if path.startswith("/en/") or path == "/en":
            continue
        # Must contain an h1 (the event title inside the card)
        h1 = a.find("h1")
        if not h1:
            continue
        # Skip duplicates (same link may appear in carousel + card section)
        if href in seen_urls:
            continue

        title = h1.get_text(strip=True)
        if not title:
            continue

        h2 = a.find("h2")
        artists = h2.get_text(strip=True) if h2 else ""

        image_url = _real_img_src(a)

        seen_urls.add(href)
        cards.append(
            {
                "title": title,
                "artists": artists,
                "detail_url": href,
                "image_url": image_url,
            }
        )

    log.info("Found %d event cards on homepage", len(cards))
    return cards


# ── Detail page scraping ──────────────────────────────────────────────────────


def _find_english_url(soup: BeautifulSoup, detail_url: str) -> str | None:
    """
    Look for an 'EN' nav link on a Danish detail page.
    Returns the English URL, or None if not found.
    """
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).upper()
        if text == "EN":
            href = str(a["href"])
            if href.startswith(BASE_URL + "/en/"):
                return href
    return None


def _extract_description(soup: BeautifulSoup) -> str:
    """
    Extract the main description paragraphs from a detail page.

    Walks all <p> and accordion-title <div> tags in document order and stops
    once a <div class="e-n-accordion-item-title-text"> whose text contains
    "read more" is encountered — those accordion sections hold bios and
    credits, not the event description.

    Additional filters:
    - Skip very short paragraphs (< 40 chars).
    - Skip credit/role lines (short label: value patterns).
    - Skip lines with birth years (bio markers like "°1997, KOR").
    - Deduplicate identical paragraphs.
    """
    seen: set[str] = set()
    paragraphs: list[str] = []

    for tag in soup.find_all(["p", "div"]):
        if tag.name == "div" and "e-n-accordion-item-title-text" in (
            tag.get("class") or []
        ):
            if "read more" in tag.get_text(strip=True).lower():
                break
            continue

        if tag.name != "p":
            continue

        text = tag.get_text(" ", strip=True)
        if len(text) < 40:
            continue
        # Skip credit/role lines (short label: value patterns)
        if re.match(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?:\s+", text):
            continue
        # Skip lines with birth years (bio markers like "°1997, KOR")
        if re.search(r"°\d{4}", text):
            continue
        if text in seen:
            continue
        seen.add(text)
        paragraphs.append(text)

    return "\n\n".join(paragraphs)


def _extract_performances(soup: BeautifulSoup) -> list[dict]:
    """
    Extract performance blocks from a detail page.

    Each block contains: venue_name, venue_address, dates (list of {date, time}).

    Returns a flat list of performance dicts, one per date/time entry.
    """
    full_text = soup.get_text("\n")

    # Parse all dates from the page text
    date_time_pairs = parse_dates(full_text)
    today = datetime.date.today()
    # Only keep future dates
    date_time_pairs = [(d, t) for d, t in date_time_pairs if d >= today]

    if not date_time_pairs:
        return []

    performances: list[dict] = []

    # Split text into lines and scan for venue headers + associated dates
    lines = [line.strip() for line in full_text.split("\n") if line.strip()]

    # Build a structure: list of (venue_raw, [date_time_pairs])
    # by scanning through lines.
    venue_blocks: list[dict] = []
    current_venue: str | None = None
    current_dates: list[tuple[datetime.date, datetime.time | None]] = []

    def _is_venue_line(line: str) -> bool:
        """Heuristic: line matches a known venue or is ALL CAPS location."""
        lower = line.lower()
        for key in VENUE_ADDRESSES:
            if key in lower:
                return True
        # ALL CAPS lines of 5–60 chars that look like venue names
        return line.isupper() and 5 <= len(line) <= 60 and not re.search(r"\d", line)

    for line in lines:
        if _is_venue_line(line):
            # Save previous block if it has dates
            if current_venue and current_dates:
                venue_blocks.append({"venue": current_venue, "dates": current_dates})
            current_venue = line
            current_dates = []
            continue

        # Check if line contains a date
        pairs = _parse_danish_dates(line) or _parse_english_dates(line)
        if pairs:
            for d, t in pairs:
                if d >= today:
                    current_dates.append((d, t))

    # Flush last block
    if current_venue and current_dates:
        venue_blocks.append({"venue": current_venue, "dates": current_dates})

    # If we found venue blocks, use them; otherwise use all dates under a
    # single default venue.
    if venue_blocks:
        for block in venue_blocks:
            venue_display, venue_address = lookup_venue(block["venue"])
            for d, t in block["dates"]:
                performances.append(
                    {
                        "venue_name": venue_display,
                        "venue_address": venue_address or "",
                        "start_datetime": make_dt(d, t).isoformat(),
                    }
                )
    else:
        # Fallback: no venue blocks found — use all dates with no venue
        for d, t in date_time_pairs:
            performances.append(
                {
                    "venue_name": "",
                    "venue_address": "",
                    "start_datetime": make_dt(d, t).isoformat(),
                }
            )

    return performances


def _fetch_press_image(slug: str, session: requests.Session) -> str:
    """
    Fetch the first image URL from the pressemateriale page for *slug*.

    URL pattern: https://kbhdanser.dk/<slug>-pressemateriale/
    Returns an empty string if the page is unavailable or has no image.
    """
    press_url = f"{BASE_URL}/{slug}-pressemateriale/"
    try:
        press_soup = get_soup(press_url, session)
    except requests.HTTPError:
        return ""
    for a in press_soup.find_all("a", href=True):
        if a.get("download") is not None:
            return str(a["href"])
    return ""


def _slug_from_url(url: str) -> str:
    """Extract the event slug from a detail URL (Danish or English variant)."""
    path = url.rstrip("/").split("/")
    return path[-1] if path else ""


def scrape_detail(
    card: dict,
    session: requests.Session,
    delay: float = 1.0,
) -> list[dict]:
    """
    Fetch the detail page for one event card and return a flat list of
    event records (one per performance date).

    Prefers the English ``/en/<slug>/`` variant when available.
    """
    detail_url = card["detail_url"]
    try:
        soup = get_soup(detail_url, session)
    except requests.HTTPError as exc:
        log.warning("HTTP error fetching %s: %s", detail_url, exc)
        return []

    # Prefer English version
    en_url = _find_english_url(soup, detail_url)
    if en_url and en_url != detail_url:
        time.sleep(delay)
        try:
            soup = get_soup(en_url, session)
            detail_url = en_url
        except requests.HTTPError as exc:
            log.warning("HTTP error fetching EN page %s: %s", en_url, exc)
            # Fall back to the already-fetched Danish page

    # Title
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else card["title"]

    # Description
    description = _extract_description(soup)

    # Image — try the pressemateriale page first (highest quality),
    # fall back to a hero image on the detail page, then the card thumbnail.
    slug = _slug_from_url(detail_url)
    time.sleep(delay)
    image_url = _fetch_press_image(slug, session)
    if not image_url:
        hero_img = soup.find("img", src=re.compile(r"^https://"))
        if hero_img:
            src = str(hero_img.get("src", ""))
            if src.startswith("https://") and "kbhdanser.dk" in src:
                image_url = src
    if not image_url:
        image_url = card.get("image_url", "")

    # Performances
    performances = _extract_performances(soup)
    if not performances:
        log.info("No future performances found for %s — skipping", detail_url)
        return []

    records: list[dict] = []
    for perf in performances:
        records.append(
            {
                "title": title,
                "description": description,
                "start_datetime": perf["start_datetime"],
                "end_datetime": None,
                "venue_name": perf["venue_name"],
                "venue_address": perf["venue_address"],
                "category": "performance",
                "is_free": False,
                "is_wheelchair_accessible": False,
                "price_note": "",
                "source_url": detail_url,
                "external_source": EXTERNAL_SOURCE,
                "image_url": image_url,
            }
        )

    log.info("Scraped %d performance record(s) for '%s'", len(records), title)
    return records


# ── Main scrape entry point ───────────────────────────────────────────────────


def scrape(delay: float = 1.5) -> list[dict]:
    """
    Scrape kbhdanser.dk and return a list of upcoming event records.

    ``delay`` controls the sleep between page fetches (seconds).
    """
    session = make_session()

    crawl_delay = get_crawl_delay(BASE_URL)
    if crawl_delay is not None and crawl_delay > delay:
        log.info(
            "robots.txt Crawl-delay %.1fs overrides --delay %.1fs",
            crawl_delay,
            delay,
        )
        delay = crawl_delay

    try:
        home_soup = get_soup(HOME_URL, session)
    except requests.HTTPError as exc:
        log.error("Cannot fetch homepage %s: %s", HOME_URL, exc)
        return []

    cards = collect_event_cards(home_soup)
    if not cards:
        log.warning("No event cards found on homepage")
        return []

    all_events: list[dict] = []
    for i, card in enumerate(cards, 1):
        log.info("[%d/%d] Scraping detail: %s", i, len(cards), card["detail_url"])
        if i > 1:
            time.sleep(delay)
        events = scrape_detail(card, session, delay=delay)
        all_events.extend(events)

    log.info("Total upcoming event records: %d", len(all_events))
    return all_events


def main() -> None:
    args = build_arg_parser(
        "Scrape kbhdanser.dk upcoming dance events",
        "kbhdanser_events.json",
    ).parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    events = scrape(delay=args.delay)
    write_output(events, args.output, args.dry_run)


if __name__ == "__main__":
    main()
