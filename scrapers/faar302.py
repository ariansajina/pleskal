"""Scraper for https://www.faar302.dk/ (Teater FÅR302)

FÅR302 is a small WordPress site whose front page lists every show on the
current programme as a ``div.forestilling`` card: title, a Danish date range
("7.-10. Oktober 2026"), a cover image, a link to the show's detail page, and a
"Køb billet" button carrying the show's ticketing ``data-event_no``.  The
detail page adds the long description but, like the card, only the date range —
individual performance times live in the ticketing system.

Tickets are sold through Billetten, which also backs teaterbilletter.dk.  That
site exposes a public JSON listing (``/api/events?venueCodes=…``) whose
``eventNo`` matches the card's ``data-event_no`` and whose ``shows`` list gives
each performance's local start time, plus the ticket price range.  We join the
two: one record per performance when the show is on teaterbilletter.dk, and a
single record spanning the date range when it isn't (site-specific or far-off
shows are sometimes sold only through FÅR302's own ticket widget).

The theatre is not wheelchair accessible (stated on its /billetter/ page).

Usage:
    uv run python scrapers/faar302.py
    uv run python scrapers/faar302.py --output events.json
    uv run python scrapers/faar302.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import datetime
import logging
import re
import time
import zoneinfo

import markdownify
import requests
from bs4 import BeautifulSoup, Tag

from events.limits import MAX_PRICE_NOTE_LENGTH
from scrapers.base import (
    HEADERS,
    build_arg_parser,
    get_crawl_delay,
    get_soup,
    make_session,
    write_output,
)

BASE_URL = "https://www.faar302.dk"
# Billetten's teaterbilletter.dk listing, filtered to FÅR302's venue code.
TICKETS_API_URL = "https://teaterbilletter.dk/api/events"
VENUE_CODE = "VN0000120"
EXTERNAL_SOURCE = "faar302"
VENUE_NAME = "Teater FÅR302"
VENUE_ADDRESS = "Toldbodgade 6"
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")

_MONTHS = {
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

# "15. September - 2. Oktober 2026", "7.-10. Oktober 2026",
# "20. December 2026 - 5. Januar 2027" or a single "12. Marts 2027".
_DATE_RANGE_RE = re.compile(
    r"(?P<d1>\d{1,2})\.\s*(?:(?P<m1>[a-zæøå]+)\s*(?P<y1>\d{4})?)?\s*"
    r"(?:[-–]\s*(?P<d2>\d{1,2})\.\s*(?P<m2>[a-zæøå]+)\s*(?P<y2>\d{4}))?",
    re.IGNORECASE,
)
_BLANK_LINES_RE = re.compile(r"\n{3,}")

log = logging.getLogger(__name__)


# ── Front page ────────────────────────────────────────────────────────────────


def parse_listing(soup: BeautifulSoup) -> list[dict]:
    """Return one dict per show card on the front page.

    Each dict has ``url``, ``title``, ``date_text``, ``image_url`` and
    ``event_no`` (``""`` when the card has no ticket button).
    """
    shows: list[dict] = []
    seen: set[str] = set()
    for card in soup.select("div.forestilling"):
        link = card.select_one("a.forteksten[href]") or card.select_one("a[href]")
        title_el = card.select_one("h1")
        if link is None or title_el is None:
            continue
        url = str(link["href"]).strip()
        if "/forestilling/" not in url or url in seen:
            continue
        seen.add(url)

        date_el = card.select_one("h3")
        image_el = card.select_one("[data-src]")
        button = card.select_one("[data-event_no]")
        # Collapse editor artefacts (zero-width joiners, doubled spaces).
        title = re.sub(r"[\u200b-\u200d\ufeff]", "", title_el.get_text(" ", strip=True))
        shows.append(
            {
                "url": url,
                "title": re.sub(r"\s+", " ", title).strip(),
                "date_text": date_el.get_text(" ", strip=True) if date_el else "",
                "image_url": str(image_el["data-src"]).strip() if image_el else "",
                "event_no": str(button["data-event_no"]).strip() if button else "",
            }
        )
    return shows


def parse_date_range(text: str) -> tuple[datetime.date, datetime.date] | None:
    """Parse a FÅR302 Danish date range into (first_day, last_day).

    The month and year are only written once when both ends share them
    ("7.-10. Oktober 2026"), so the start inherits whatever it omits from the
    end.  Returns None when the text doesn't parse.
    """
    m = _DATE_RANGE_RE.search(text or "")
    if m is None:
        return None
    if m["d2"] is None:
        # Single date: needs its own month and year.
        if not (m["m1"] and m["y1"]):
            return None
        end_day, end_month, end_year = m["d1"], m["m1"], m["y1"]
    else:
        end_day, end_month, end_year = m["d2"], m["m2"], m["y2"]

    end_month_no = _MONTHS.get(end_month.lower())
    start_month_no = _MONTHS.get(m["m1"].lower()) if m["m1"] else end_month_no
    if end_month_no is None or start_month_no is None:
        return None
    start_year = int(m["y1"]) if m["y1"] else int(end_year)
    # "20. December - 5. Januar 2027": the start is in the previous year.
    if not m["y1"] and start_month_no > end_month_no:
        start_year -= 1

    try:
        start = datetime.date(start_year, start_month_no, int(m["d1"]))
        end = datetime.date(int(end_year), end_month_no, int(end_day))
    except ValueError:
        return None
    if end < start:
        return None
    return start, end


# ── Detail page ───────────────────────────────────────────────────────────────


# "Varighed ca. 35 min", "ca. 1 time og 45 minutter", "Duration 75 min."
_DURATION_LABEL_RE = re.compile(r"^(?:varighed|duration)\b:?\s*(.*)$", re.IGNORECASE)
_HOURS_RE = re.compile(r"(\d+)\s*(?:timer?|hours?)\b", re.IGNORECASE)
_MINUTES_RE = re.compile(r"(\d+)\s*(?:minutter|minutes?|min)\b", re.IGNORECASE)


def parse_duration(soup: BeautifulSoup) -> datetime.timedelta | None:
    """Return the running time stated on a detail page, if any.

    The label and value may share a line ("Varighed ca. 35 min") or the value
    may follow on the next one ("Varighed" / "75 minutter").
    """
    lines = [ln.strip() for ln in soup.get_text("\n").split("\n") if ln.strip()]
    for i, line in enumerate(lines):
        m = _DURATION_LABEL_RE.match(line)
        if m is None:
            continue
        value = m.group(1) or (lines[i + 1] if i + 1 < len(lines) else "")
        hours = _HOURS_RE.search(value)
        minutes = _MINUTES_RE.search(value)
        total = (int(hours.group(1)) * 60 if hours else 0) + (
            int(minutes.group(1)) if minutes else 0
        )
        if total:
            return datetime.timedelta(minutes=total)
    return None


def _is_blank_paragraph(el: Tag) -> bool:
    return el.name == "p" and not el.get_text(strip=True).replace("\xa0", "")


def parse_description(soup: BeautifulSoup) -> str:
    """Convert the detail page's ``div.textbox`` to markdown."""
    box = soup.select_one("div.textbox")
    if box is None:
        return ""
    for p in box.find_all("p"):
        if _is_blank_paragraph(p):
            p.decompose()
    md = markdownify.markdownify(str(box), heading_style="ATX")
    md = _BLANK_LINES_RE.sub("\n\n", md)
    return md.strip()


# ── Ticketing API ─────────────────────────────────────────────────────────────


def fetch_ticket_events(session: requests.Session) -> dict[str, dict]:
    """Return teaterbilletter.dk events at FÅR302, keyed by str(eventNo).

    Best-effort: on any failure an empty dict is returned, so every show falls
    back to a single date-range record instead of the whole scrape failing.
    """
    events: dict[str, dict] = {}
    page = 1
    try:
        while True:
            resp = session.get(
                TICKETS_API_URL,
                params={"page": page, "venueCodes": VENUE_CODE, "pageSize": 30},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("items") or []:
                if item.get("eventNo") is not None:
                    events[str(item["eventNo"])] = item
            page_count = (data.get("pagination") or {}).get("pageCount") or 1
            if page >= page_count:
                break
            page += 1
    except (requests.RequestException, ValueError) as exc:
        log.warning(
            "Could not fetch FÅR302 performances from %s: %s", TICKETS_API_URL, exc
        )
        return {}
    return events


def show_times(ticket_event: dict | None) -> list[datetime.datetime]:
    """Return the sorted, de-duplicated aware start times of a ticket event."""
    if not ticket_event:
        return []
    raw: list[str] = [
        s.get("showTime", "") for s in ticket_event.get("shows") or [] if s
    ] or list(ticket_event.get("showDates") or [])
    times: set[datetime.datetime] = set()
    for value in raw:
        try:
            dt = datetime.datetime.fromisoformat(value)
        except TypeError, ValueError:
            continue
        # The API gives Copenhagen wall-clock times without an offset.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CPH_TZ)
        times.add(dt)
    return sorted(times)


def price_note(ticket_event: dict | None) -> str:
    """Format the API's ticket price range, e.g. "40–165 kr."."""
    if not ticket_event:
        return ""
    low = ticket_event.get("ticketPriceMin")
    high = ticket_event.get("ticketPriceMax")
    if not low and not high:
        return ""
    if low and high and low != high:
        note = f"{low:g}–{high:g} kr."
    else:
        note = f"{(low or high):g} kr."
    return note[:MAX_PRICE_NOTE_LENGTH]


# ── Record building ───────────────────────────────────────────────────────────


def build_records(
    show: dict,
    description: str,
    ticket_event: dict | None,
    now: datetime.datetime | None = None,
    page_duration: datetime.timedelta | None = None,
) -> list[dict]:
    """Build the pleskal records for one show.

    One record per upcoming performance when the ticketing API lists times,
    each ending after the running time (the API's ``durationInMinutes``, or
    *page_duration* from the detail page when the API leaves it at 0);
    otherwise a single record spanning the card's date range (midnight on the
    first day to the end of the last), kept while the run hasn't ended.
    """
    if now is None:
        now = datetime.datetime.now(datetime.UTC)

    base = {
        "title": show["title"],
        "description": description,
        "venue_name": VENUE_NAME,
        "venue_address": VENUE_ADDRESS,
        "category": "performance",
        "is_free": False,
        "is_wheelchair_accessible": False,
        "price_note": price_note(ticket_event),
        "source_url": show["url"],
        "external_source": EXTERNAL_SOURCE,
        "image_url": show["image_url"],
    }

    times = show_times(ticket_event)
    if times:
        api_minutes = (ticket_event or {}).get("durationInMinutes") or 0
        duration = (
            datetime.timedelta(minutes=api_minutes)
            if api_minutes > 0
            else page_duration
        )
        return [
            {
                **base,
                "start_datetime": t.isoformat(),
                "end_datetime": (t + duration).isoformat() if duration else None,
            }
            for t in times
            if t >= now
        ]

    date_range = parse_date_range(show["date_text"])
    if date_range is None:
        log.warning("No performance times or date range for %s", show["url"])
        return []
    first, last = date_range
    start = datetime.datetime.combine(first, datetime.time(0, 0), tzinfo=CPH_TZ)
    end = datetime.datetime.combine(last, datetime.time(23, 59), tzinfo=CPH_TZ)
    if end < now:
        return []
    return [
        {
            **base,
            "start_datetime": start.isoformat(),
            "end_datetime": end.isoformat() if last > first else None,
        }
    ]


# ── Main scrape entry point ───────────────────────────────────────────────────


def scrape(delay: float = 0.5) -> list[dict]:
    """Scrape the FÅR302 programme and return a list of event dicts."""
    session = make_session()
    crawl_delay = get_crawl_delay(BASE_URL)
    if crawl_delay is not None and crawl_delay > delay:
        delay = crawl_delay

    shows = parse_listing(get_soup(f"{BASE_URL}/", session))
    log.info("Found %d shows on the front page", len(shows))
    ticket_events = fetch_ticket_events(session)

    records: list[dict] = []
    for i, show in enumerate(shows, 1):
        time.sleep(delay)
        log.info("[%d/%d] Scraping %s", i, len(shows), show["url"])
        try:
            detail = get_soup(show["url"], session)
        except requests.RequestException as exc:
            log.warning("Could not fetch %s: %s", show["url"], exc)
            continue
        # Read the running time before parse_description trims the page.
        duration = parse_duration(detail)
        records.extend(
            build_records(
                show,
                parse_description(detail),
                ticket_events.get(show["event_no"]),
                page_duration=duration,
            )
        )

    log.info("Scraped %d event records from %d shows", len(records), len(shows))
    return records


def main() -> None:
    args = build_arg_parser(
        "Scrape faar302.dk programme",
        "faar302_events.json",
    ).parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    records = scrape(delay=args.delay)
    write_output(records, args.output, args.dry_run)


if __name__ == "__main__":
    main()
