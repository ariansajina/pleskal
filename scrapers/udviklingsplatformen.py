"""Scraper for the worksharings in https://www.udviklingsplatformen.dk/en/calendar

UP (Scenekunstens Udviklingsplatform) keeps a calendar of things happening in
the independent performing-arts field: open calls, deadlines, courses, and the
worksharings artists hold during or after a residency. Only the worksharings
are scraped.

The calendar page filters by category client-side: picking "Worksharing" in
its dropdown fetches ``/getCalendarEvents?category=worksharing`` (with an
``X-Requested-With: XMLHttpRequest`` header) and swaps the returned HTML
fragment into the list. We call that endpoint directly, under the ``/en/``
prefix for the English texts. It lists upcoming entries only (``from``/``to``
can't reach back past today), plus entries that started earlier and are still
running.

Each entry is a ``div.item`` with a ``data-id``, a date line, a type, a title
(``.sender``), "Read more at" links (the organiser's page) and an HTML body.
There is no time, venue, price or image:

- **Date:** "23. October", "28. February, 2027" (the year is only shown when it
  isn't the current one) or a range "08. December – 09. December". A range of
  up to a week yields one record per day; a longer one is listed on its first
  day.
- **Time:** taken from the body when it names one ("4:00 PM", "17:00",
  "kl. 17"), else a midnight placeholder without an end time (as sydhavnteater
  does for unscheduled days). UP's own worksharings give ranges, often as a
  programme of several slots ("1:00-1:45 p.m.: Worksharing in The Pit ...",
  "1:45-2:30 p.m.: ...", "13:00 - 13:45"), with the am/pm marker on the end
  only; the first time is the start and the last range's end the end.
- **Venue:** UP itself when the link stays on udviklingsplatformen.dk or the
  body names its address or rooms (its worksharings come out of the Tid i Rum
  / Time in Space residencies in The Pit and White Lab, Baldersgade 6), else
  the organiser link's label when it reads as a name ("Warehouse9"), else the
  organiser's domain.
- **Source URL:** the entry's anchor on UP's calendar (``#event-<id>``, which
  the page scrolls to and opens); the organiser's page is appended to the
  description.

UP mostly relays events hosted by venues pleskal already scrapes, with a
proper time and venue. An entry whose link points at one of those venues
(``COVERED_HOSTS``) is left out, so the same worksharing isn't listed twice.

Usage:
    uv run python scrapers/udviklingsplatformen.py
    uv run python scrapers/udviklingsplatformen.py --output events.json
    uv run python scrapers/udviklingsplatformen.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import datetime
import logging
import re
import zoneinfo
from urllib.parse import urlparse

import markdownify
from bs4 import BeautifulSoup, Tag

from events.limits import MAX_TITLE_LENGTH, MAX_VENUE_LENGTH
from scrapers.base import HEADERS, build_arg_parser, make_session, write_output

BASE_URL = "https://www.udviklingsplatformen.dk"
CALENDAR_URL = f"{BASE_URL}/en/calendar"
EVENTS_URL = f"{BASE_URL}/en/getCalendarEvents"
CATEGORY = "worksharing"
EXTERNAL_SOURCE = "udviklingsplatformen"
VENUE_NAME = "Udviklingsplatformen"
VENUE_ADDRESS = "Baldersgade 6, 2200 København N"
UP_HOST = "udviklingsplatformen.dk"
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")

# Sites of the venues other scrapers import (their sources.json websites).
# Kept in sync with the registry by a test.
COVERED_HOSTS = frozenset(
    {
        "afuk.dk",
        "blaagaardteater.dk",
        "dansehallerne.dk",
        "dansekapellet.dk",
        "faar302.dk",
        "hautscene.dk",
        "kbhdanser.dk",
        "sort-hvid.dk",
        "sydhavnteater.dk",
        "warehouse9.dk",
    }
)

# A range longer than this is a run (an exhibition, a residency), listed on
# its first day rather than as one record per day.
MAX_SPLIT_DAYS = 7

_MONTHS = {
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
# "23. October" or "28. February, 2027"
_DATE_RE = re.compile(r"(\d{1,2})\.\s*([A-Za-z]+)(?:,?\s*(\d{4}))?")

# Clock times in the body: "4:00 PM", "6 p.m.", "17:00", "kl. 17", "kl. 17.30".
# A bare "17.30" is not read as a time (it is as likely a date or a price).
_AMPM = r"([ap])\.?\s?m\b\.?"
_TIME_RES = (
    re.compile(rf"\b(1[0-2]|0?[1-9])(?:[:.]([0-5]\d))?\s*{_AMPM}", re.IGNORECASE),
    re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b"),
    re.compile(r"\bkl\.?\s*([01]?\d|2[0-3])(?:[.:]([0-5]\d))?\b", re.IGNORECASE),
)
# Time ranges: "1:30–3:00 p.m.", "1:45–2:30 PM", "13:00 - 13:45", "kl. 13-14".
# Only accepted with an am/pm marker, "kl." or colons on both sides, so date
# ranges ("14-21 August", "23.10-24.10") aren't read as times.
_RANGE_RE = re.compile(
    r"(?P<kl>\bkl\.?\s*)?\b(?P<h1>[01]?\d|2[0-3])(?:(?P<s1>[:.])(?P<m1>[0-5]\d))?"
    r"(?:\s*(?P<ap1>[ap])\.?\s?m\b\.?)?"
    r"\s*[-–—]\s*"
    r"(?P<h2>[01]?\d|2[0-3])(?:(?P<s2>[:.])(?P<m2>[0-5]\d))?"
    r"(?:\s*(?P<ap2>[ap])\.?\s?m\b\.?)?",
    re.IGNORECASE,
)

# Link labels that say nothing about who hosts the event.
_GENERIC_LABEL_RE = re.compile(
    r"\b(?:read|more|see|learn|here|info|information|link|apply|ticket|tickets|"
    r"sign|register|website|page|click|læs|mere|billet|billetter|tilmeld)\b",
    re.IGNORECASE,
)

_FREE_RE = re.compile(
    r"\b(?:free (?:admission|entry|entrance|of charge)"
    r"|(?:admission|entrance|entry)(?: is)?:? free"
    r"|(?:register|sign up|signup|tilmelding)(?: \w+)? for free"
    r"|gratis)\b",
    re.IGNORECASE,
)

# UP's own rooms and residency programme, named by its in-house worksharings.
_UP_VENUE_RE = re.compile(
    r"\b(?:Baldersgade|The Pit|White Lab|Tid i Rum|Time in Space)\b", re.IGNORECASE
)

log = logging.getLogger(__name__)


# ── Fetch ─────────────────────────────────────────────────────────────────────


def fetch_items() -> list[Tag]:
    """Fetch the calendar's worksharing entries as ``div.item`` tags."""
    session = make_session()
    resp = session.get(
        EVENTS_URL,
        params={"category": CATEGORY},
        headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
        timeout=20,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    return soup.select("div.item[data-id]")


# ── Field extraction ──────────────────────────────────────────────────────────


def _text(item: Tag, selector: str) -> str:
    el = item.select_one(selector)
    return " ".join(el.get_text(" ").split()) if el else ""


def _parse_date(text: str, today: datetime.date) -> datetime.date | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    month = _MONTHS.get(m.group(2).lower())
    if month is None:
        return None
    year = int(m.group(3)) if m.group(3) else today.year
    try:
        return datetime.date(year, month, int(m.group(1)))
    except ValueError:
        return None


def parse_dates(
    text: str, today: datetime.date
) -> tuple[datetime.date, datetime.date] | None:
    """Parse an entry's date line into a (first, last) day.

    A date without a year is in the current year; a range's end that would
    fall before its start (``"28. December – 03. January"``) is in the next.
    """
    parts = re.split(r"\s+[–—-]\s+", text, maxsplit=1)
    start = _parse_date(parts[0], today)
    if start is None:
        return None
    end = _parse_date(parts[1], today) if len(parts) > 1 else None
    if end is None:
        return start, start
    if end < start:
        end = end.replace(year=start.year)
        if end < start:
            end = end.replace(year=start.year + 1)
    return start, end


def _hour(hour: int, ampm: str | None) -> int:
    if not ampm:
        return hour
    return hour % 12 + (12 if ampm.lower() == "p" else 0)


def _parse_range(m: re.Match[str]) -> tuple[datetime.time, datetime.time] | None:
    ap1, ap2 = m.group("ap1"), m.group("ap2")
    colons = m.group("s1") == ":" and m.group("s2") == ":"
    if not (ap1 or ap2 or m.group("kl") or colons):
        return None
    h1, h2 = int(m.group("h1")), int(m.group("h2"))
    if (ap1 or ap2) and not (1 <= h1 <= 12 and 1 <= h2 <= 12):
        return None
    m1, m2 = int(m.group("m1") or 0), int(m.group("m2") or 0)
    end = datetime.time(_hour(h2, ap2 or ap1), m2)
    start = datetime.time(_hour(h1, ap1 or ap2), m1)
    if not ap1 and ap2 and start > end:
        # "11:30-1:00 p.m.": the marker belongs to the end only.
        start = datetime.time(_hour(h1, "a"), m1)
    return start, end


def parse_times(text: str) -> tuple[datetime.time | None, datetime.time | None]:
    """Return the (start, end) clock times *text* names.

    The start is the first time named; the end is the latest end of a time
    range after it (a programme of slots runs until its last one), or None.
    """
    # (position, rank, start, end): a range outranks the single times that
    # match inside it, and "4:00 PM" reads as am/pm before 24-hour time.
    found: list[tuple[int, int, datetime.time, datetime.time | None]] = []
    for m in _RANGE_RE.finditer(text):
        times = _parse_range(m)
        if times:
            found.append((m.start(), 0, *times))
    for rank, pattern in enumerate(_TIME_RES, 1):
        m = pattern.search(text)
        if not m:
            continue
        hour = int(m.group(1))
        if rank == 1:
            hour = _hour(hour, m.group(3))
        found.append((m.start(), rank, datetime.time(hour, int(m.group(2) or 0)), None))
    if not found:
        return None, None
    start = min(found)[2]
    ends = [end for *_, end in found if end is not None and end > start]
    return start, max(ends, default=None)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def is_covered(url: str) -> bool:
    """True when *url* is on a venue site another scraper imports."""
    host = _host(url)
    return any(host == h or host.endswith(f".{h}") for h in COVERED_HOSTS)


def determine_venue(label: str, url: str, body: str) -> tuple[str, str]:
    """Return (venue_name, venue_address) for an entry."""
    host = _host(url)
    if host == UP_HOST or _UP_VENUE_RE.search(body):
        return VENUE_NAME, VENUE_ADDRESS
    if label and "." not in label and not _GENERIC_LABEL_RE.search(label):
        return label[:MAX_VENUE_LENGTH], ""
    if host:
        return host[:MAX_VENUE_LENGTH], ""
    return VENUE_NAME, VENUE_ADDRESS


def build_records(item: Tag, today: datetime.date) -> list[dict]:
    """Build the records of one calendar entry (one per day of a short range)."""
    if CATEGORY not in _text(item, ".type").lower():
        return []
    title = _text(item, ".sender")[:MAX_TITLE_LENGTH]
    dates = parse_dates(_text(item, ".dates"), today)
    if not title or dates is None:
        log.warning("Skipping unparseable entry %s", item.get("data-id"))
        return []

    link = item.select_one(".links a[href]")
    link_url = str(link["href"]).strip() if link else ""
    link_label = " ".join(link.get_text(" ").split()) if link else ""
    if link_url and is_covered(link_url):
        log.info("Skipping %r: listed by the venue's own scraper", title)
        return []

    content = item.select_one(".content")
    body_text = content.get_text(" ") if content else ""
    description = (
        markdownify.markdownify(str(content), heading_style="ATX").strip()
        if content
        else ""
    )
    if link_url:
        description += f"\n\nMore information: [{link_label or link_url}]({link_url})"

    venue_name, venue_address = determine_venue(link_label, link_url, body_text)
    start_time, end_time = parse_times(body_text)
    first, last = dates
    days = (last - first).days + 1
    day_list = (
        [first + datetime.timedelta(days=n) for n in range(days)]
        if days <= MAX_SPLIT_DAYS
        else [first]
    )

    return [
        {
            "title": title,
            "description": description.strip(),
            "start_datetime": datetime.datetime.combine(
                day, start_time or datetime.time(0, 0), tzinfo=CPH_TZ
            ).isoformat(),
            "end_datetime": (
                datetime.datetime.combine(day, end_time, tzinfo=CPH_TZ).isoformat()
                if start_time and end_time
                else None
            ),
            "venue_name": venue_name,
            "venue_address": venue_address,
            "category": "worksharing",
            "is_free": bool(_FREE_RE.search(body_text)),
            # Not claimed: even UP's own rooms differ (The Pit has level
            # access, White Lab is up a flight of stairs with no lift).
            "is_wheelchair_accessible": False,
            "price_note": "",
            "source_url": f"{CALENDAR_URL}#event-{item['data-id']}",
            "image_url": "",
        }
        for day in day_list
        if day >= today
    ]


def scrape() -> list[dict]:
    """Fetch the calendar's worksharings and build upcoming records."""
    today = datetime.datetime.now(CPH_TZ).date()
    records: list[dict] = []
    for item in fetch_items():
        records.extend(build_records(item, today))
    log.info("Built %d worksharing records", len(records))
    return records


def main() -> None:
    args = build_arg_parser(
        "Scrape udviklingsplatformen.dk calendar (worksharings only)",
        "udviklingsplatformen_events.json",
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
