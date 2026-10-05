"""Scraper for https://kbhdanser.dk/en/

Fetches upcoming dance performance events and outputs a JSON array of event
dicts ready for ingestion into the pleskal database.

Each kbhdanser event may have multiple performance dates, possibly at different
venues.  The scraper flattens these into individual records — one per
performance date — so the standard base_import machinery can upsert them using
(source_url, start_datetime) as a unique key.

Wheelchair access is decided per performance, from its venue (see
WHEELCHAIR_ACCESSIBLE_VENUES); a venue that isn't listed there isn't claimed.

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
import urllib.parse
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
    # Republique's stages are listed as "Republique / Revolver" etc.; the more
    # specific key has to come first for the substring match.
    "republique / revolver": (
        "Republique – Revolver",
        "Østerfælled Torv 37, 2100 København Ø",
    ),
    "republique": (
        "Republique",
        "Østerfælled Torv 37, 2100 København Ø",
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

# Venues (by canonical display name above) with documented wheelchair access, from
# their own accessibility pages (and godadgang.dk where noted):
#   - Østre Gasværk Teater: wheelchair spaces on all three stages, accessible
#     toilet in the foyer; only the front row is step-free.
#   - Republique / Revolver: level entrance, hall and toilets on one floor,
#     wheelchair spaces and companion tickets on both stages.
#   - Gamle Scene: ramp and lift, two wheelchair spaces in the stalls (book ahead
#     via customer service); step-free to the stalls/1st floor on the left side.
#   - Musikhuset Aarhus: level access and wheelchair spaces in every hall
#     (godadgang.dk), accessible toilets on every floor.
WHEELCHAIR_ACCESSIBLE_VENUES = frozenset(
    {
        "Østre Gasværk Teater",
        "Republique",
        "Republique – Revolver",
        "Det Kongelige Teater – Gamle Scene",
        "Musikhuset Aarhus",
    }
)

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


def _strip_query(url: str) -> str:
    """Return *url* with query string and fragment removed."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parts._replace(query="", fragment=""))


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

# Danish: "21. maj 2026. kl. 19:30", "26. september 2026 – kl. 20:00"
_DANISH_DATE_RE = re.compile(
    r"(\d{1,2})\.\s*"
    r"(januar|februar|marts|april|maj|juni|juli|august|september|oktober|november|december)"
    r"\s+(\d{4})\.?[\s,\-–]*(?:kl\.\s*(\d{1,2})[.:](\d{2}))?",
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
    """Return (date, time_or_None) pairs found in *text* (Danish and English).

    Both languages are read: the English pages mix in Danish-formatted dates
    (a past premiere in a credits block, or a whole performance list), so
    reading English only when no Danish date exists loses every performance.
    """
    return _parse_danish_dates(text) + _parse_english_dates(text)


# The headline range above a performance list ("21.- 23. maj 2026",
# "May 21-24, 2026") restates the listed dates; read as a date it would add a
# phantom performance on the last day at the default time.
_DATE_RANGE_RE = re.compile(
    r"\d{1,2}\.?\s*[-–]\s*\d{1,2}\.\s*(?:"
    + "|".join(DANISH_MONTHS)
    + r")\b|(?:"
    + "|".join(ENGLISH_MONTHS)
    + r")\s+\d{1,2}\s*[-–]\s*\d{1,2}\b",
    re.IGNORECASE,
)
_DATE_ONLY_RES = (
    re.compile(
        r"\d{1,2}\.\s*(?:" + "|".join(DANISH_MONTHS) + r")\s+\d{4}\.?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:" + "|".join(ENGLISH_MONTHS) + r")\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}",
        re.IGNORECASE,
    ),
)
_TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})\s*(AM|PM)?", re.IGNORECASE)
# A press citation under a review quote: "Fjord Review · 15. juli 2020 · Standby".
_CITATION_SEPARATOR = "·"
# What may surround a date on a performance line besides times: "kl.", "og",
# dashes, and a short note like "EXTRA SHOW" or "Udsolgt". Anything longer is
# a sentence that happens to mention a date, not a performance.
_MAX_DATE_LINE_EXTRA = 30


def _parse_time_match(m: re.Match[str]) -> datetime.time | None:
    hour, minute = int(m.group(1)), int(m.group(2))
    ampm = (m.group(3) or "").upper()
    if ampm == "PM" and hour < 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0
    try:
        return datetime.time(hour, minute)
    except ValueError:
        return None


def parse_performance_line(
    line: str,
) -> list[tuple[datetime.date, datetime.time | None]]:
    """Return the performances listed on one line of a detail page.

    A performance line is a date plus its time(s): "September 26, 2026 –
    8:00 PM", "21. maj 2026 – kl. 19:30", "24. maj 2025. kl. 15:00 og 19:30"
    (two shows). Headline ranges, press citations and prose mentioning a date
    yield nothing.
    """
    if _DATE_RANGE_RE.search(line):
        return []
    matches = [m for regex in _DATE_ONLY_RES for m in regex.finditer(line)]
    if len(matches) != 1:
        return parse_dates(line) if len(matches) > 1 else []
    date_m = matches[0]
    if (
        _CITATION_SEPARATOR in line[: date_m.start()]
        and _CITATION_SEPARATOR in line[date_m.end() :]
    ):
        return []
    dates = parse_dates(date_m.group(0))
    if not dates:
        return []
    date = dates[0][0]
    rest = line[: date_m.start()] + " " + line[date_m.end() :]
    times = [t for t in map(_parse_time_match, _TIME_RE.finditer(rest)) if t]
    leftover = re.sub(r"\b(?:kl|og|and|at)\b", "", _TIME_RE.sub("", rest), flags=re.I)
    if len(re.sub(r"[\W_]+", "", leftover)) > _MAX_DATE_LINE_EXTRA:
        return []
    if not times:
        return [(date, None)]
    return [(date, t) for t in times]


_DURATION_LINE_RE = re.compile(r"^(?:duration|varighed)\s*:?\s*(.+)$", re.IGNORECASE)
_DURATION_LABEL_RE = re.compile(r"^(?:duration|varighed)\s*:?$", re.IGNORECASE)


def parse_duration(text: str) -> datetime.timedelta | None:
    """Return the running time from a "Duration: 1h15m" / "Varighed: 75 min" line.

    The value may also sit on the line after a bare "Duration:" label.
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    for i, line in enumerate(lines):
        if _DURATION_LABEL_RE.match(line):
            value = lines[i + 1].lower() if i + 1 < len(lines) else ""
        elif m := _DURATION_LINE_RE.match(line):
            value = m.group(1).lower()
        else:
            continue
        hours = re.search(r"(\d+)\s*(?:hours?|timer?|h|t)(?![a-zæøå])", value)
        minutes = re.search(r"(\d+)\s*(?:minutes?|minutter|min|m)(?![a-zæøå])", value)
        if hours or minutes:
            return datetime.timedelta(
                hours=int(hours.group(1)) if hours else 0,
                minutes=int(minutes.group(1)) if minutes else 0,
            )
    return None


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


# Uploads are served from One.com's CDN (usercontent.one/wp/kbhdanser.dk/...),
# not from kbhdanser.dk itself.
_UPLOAD_URL_RE = re.compile(
    r"^https://(?:(?:www\.)?kbhdanser\.dk|usercontent\.one/wp/kbhdanser\.dk)"
    r"/wp-content/uploads/",
)
_PHOTO_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|heic|heif)$", re.IGNORECASE)


def _is_photo_url(url: str) -> bool:
    """True for a kbhdanser upload in a raster format (not an SVG ornament)."""
    return bool(_UPLOAD_URL_RE.match(url)) and bool(
        _PHOTO_EXT_RE.search(urllib.parse.urlsplit(url).path)
    )


def _encode_url(url: str) -> str:
    """Percent-encode non-ASCII path characters ("©" in photo credits).

    The importer downloads with urllib, which rejects non-ASCII URLs.
    Already-encoded sequences are left alone.
    """
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        parts._replace(path=urllib.parse.quote(parts.path, safe="/%"))
    )


def _first_photo(tag: Tag) -> str:
    """Return the first photo URL among the ``<img>``/``<video>`` tags in *tag*.

    Lazy-loaded ``<img>`` tags carry an SVG placeholder in ``src`` and the real
    URL in ``data-lazy-src``; the header logo and section ornaments are SVGs
    and the tracking pixels are off-site, so only raster uploads count.
    """
    for el in tag.find_all(["img", "video"]):
        if el.name == "video":
            candidates = [el.get("poster")]
        else:
            candidates = [el.get("data-lazy-src"), el.get("src")]
        for candidate in candidates:
            url = str(candidate or "").strip()
            if _is_photo_url(url):
                return _encode_url(url)
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
        href = _strip_query(str(a["href"]))
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
        # Skip duplicates (same link may appear in carousel + card section,
        # with or without the trailing slash)
        if href.rstrip("/") in seen_urls:
            continue

        title = h1.get_text(strip=True)
        if not title:
            continue

        h2 = a.find("h2")
        artists = h2.get_text(strip=True) if h2 else ""

        image_url = _first_photo(a)

        seen_urls.add(href.rstrip("/"))
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
            href = _strip_query(str(a["href"]))
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


_NOT_A_VENUE_RE = re.compile(
    r"show|forestilling|premiere|ticket|billet|sold out|udsolgt|ekstra|extra",
    re.IGNORECASE,
)
# A review quote ("“The NDT dancers are phenomenal.”") above its citation.
_QUOTE_CHARS = "\"'“”„«»‘’"
# A credits entry naming where the work premiered ("WORLD PREMIERE" /
# "11. februar 2027," / "Amare, Den Haag, Holland"), not a show on sale here.
_PREMIERE_HEADING_RE = re.compile(r"premiere\b", re.IGNORECASE)


def _is_known_venue(line: str) -> bool:
    lower = line.lower()
    return any(key in lower for key in VENUE_ADDRESSES)


def _block_heading(lines: list[str], i: int) -> str:
    """Return the line heading the performance list starting at line *i*.

    That is the line just above the list, past a headline date range, joined
    with the line before it when a heading is split over two lines
    ("Republique /" + "Revolver"). Returns "" at the top of the page.
    """
    j = i - 1
    while j >= 0 and _DATE_RANGE_RE.search(lines[j]):
        j -= 1  # skip the headline range between venue and list
    if j < 0:
        return ""
    heading = lines[j]
    if j > 0 and lines[j - 1].endswith("/"):
        heading = f"{lines[j - 1]} {heading}"
    return heading


def _block_venue(heading: str, title: str) -> str | None:
    """Return *heading* if it names the venue of the performance list below it.

    Each list sits under its venue: "GAMLE SCENE", "Østre Gasværk Teater",
    "Republique / Revolver". Returns None when the heading isn't a venue (a
    label such as "ARTISTIC TEAM:", a note such as "EXTRA SHOW", a review
    quote, the page title), so the list keeps the venue of the one before it.
    """
    if not heading:
        return None
    if _is_known_venue(heading):
        return heading
    if (
        len(heading) <= 40
        and not re.search(r"\d", heading)
        and not heading.endswith((":", ".", "!", "?"))
        and not heading.startswith(tuple(_QUOTE_CHARS))
        and not _NOT_A_VENUE_RE.search(heading)
        and heading.casefold() != title.casefold()
    ):
        return heading
    return None


def _extract_performances(soup: BeautifulSoup) -> list[dict]:
    """
    Extract upcoming performances from a detail page.

    Returns a flat list of performance dicts (venue_name, venue_address,
    start_datetime, end_datetime), one per date/time entry. Pages render the
    performance list twice (desktop and mobile layouts); each start time is
    returned once, with the venue of its first occurrence. A date without a
    time under a premiere heading is a credits entry (where and when the work
    premiered, often abroad), not a performance.
    """
    full_text = soup.get_text("\n")
    lines = [line.strip() for line in full_text.split("\n") if line.strip()]
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""
    duration = parse_duration(full_text)
    today = datetime.date.today()

    performances: list[dict] = []
    seen: set[str] = set()
    current_venue: str | None = None
    in_block = False
    premiere_credit = False
    for i, line in enumerate(lines):
        pairs = parse_performance_line(line)
        if not pairs:
            in_block = False
            continue
        if not in_block:
            heading = _block_heading(lines, i)
            current_venue = _block_venue(heading, title) or current_venue
            premiere_credit = bool(_PREMIERE_HEADING_RE.search(heading))
            in_block = True
        if premiere_credit and all(t is None for _, t in pairs):
            continue
        for d, t in pairs:
            if d < today:
                continue
            start = make_dt(d, t)
            if start.isoformat() in seen:
                continue
            seen.add(start.isoformat())
            if current_venue:
                venue_display, venue_address = lookup_venue(current_venue)
            else:
                venue_display, venue_address = "", None
            end = start + duration if duration and t is not None else None
            performances.append(
                {
                    "venue_name": venue_display,
                    "venue_address": venue_address or "",
                    "start_datetime": start.isoformat(),
                    "end_datetime": end.isoformat() if end else None,
                }
            )

    return performances


def _extract_image(soup: BeautifulSoup) -> str:
    """Return the event's image URL from a detail page, or "".

    Uses the page's ``og:image`` (the event's featured image) when present,
    otherwise the first photo on the page.
    """
    og = soup.find("meta", property="og:image")
    if og:
        url = str(og.get("content", "")).strip()
        if _is_photo_url(url):
            return _encode_url(url)
    return _first_photo(soup)


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

    # Image — the detail page's own image, falling back to the card thumbnail.
    image_url = _extract_image(soup) or card.get("image_url", "")

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
                "end_datetime": perf["end_datetime"],
                "venue_name": perf["venue_name"],
                "venue_address": perf["venue_address"],
                "category": "performance",
                "is_free": False,
                "is_wheelchair_accessible": (
                    perf["venue_name"] in WHEELCHAIR_ACCESSIBLE_VENUES
                ),
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
