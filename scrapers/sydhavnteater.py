"""Scraper for https://sydhavnteater.dk/events/kalender

Uses the Craft CMS GraphQL API at https://cms.sydhavnteater.dk/api to fetch
all events, filters to upcoming only, and outputs a JSON array of event dicts
ready for ingestion into the pleskal database.

Date ranges are expanded into individual performances.  The "When" field from
the event's dataTable section is parsed to determine which days in the run
have performances and at what time(s); "Duration" gives the end time.  The
English columns are often left empty, so the Danish ones ("Spilletid",
"Varighed", "Sted") are the fallback.

Usage:
    uv run python scrapers/sydhavnteater.py
    uv run python scrapers/sydhavnteater.py --output events.json
    uv run python scrapers/sydhavnteater.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import datetime
import logging
import re
import zoneinfo

import markdownify

from scrapers.base import build_arg_parser, make_session, write_output

BASE_URL = "https://sydhavnteater.dk"
API_URL = "https://cms.sydhavnteater.dk/api"
EXTERNAL_SOURCE = "sydhavnteater"
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")

HEADERS = {
    "User-Agent": "pleskalScraper/1.0 (+https://pleskal.dk/about/)",
    "Content-Type": "application/json",
}

GRAPHQL_QUERY = """
{
  eventsEntries {
    ... on event_Entry {
      title
      slug
      uri
      dateFrom
      dateTo
      ticketLink
      text
      textEnglish
      stage { title }
      category { title }
      media { url }
      sections {
        ... on text_Entry {
          headlineEnglish
          text
          textEnglish
        }
        ... on dataTable_Entry {
          data {
            title
            text
            titleEnglish
            textEnglish
          }
        }
      }
    }
  }
}
"""

# The CMS only exposes a stage *name* (e.g. "Kapelscenen"), which isn't
# itself geocodable -- these physical addresses come from the venue's own
# "Find vej" (directions) page and let Event._build_geocode_query() resolve
# a stage to an actual pin instead of falling back to the theatre's default
# venue name. Keyed by stage name with whitespace stripped and lowercased,
# since the CMS and the directions page don't always agree on spacing (e.g.
# "Kapelscenen" vs. "Kapel scenen").
STAGE_ADDRESSES = {
    "kapelscenen": "Vestre Kirkegård",
    "annexscenen": "Borgbjergsvej 44",
    "foyerscenen": "Vestre Kirkegård",
    "kontor": "Wagnersvej 19",
}


def _stage_address(venue_name: str) -> str:
    """Look up the physical address for a stage/space name, if known."""
    normalized = re.sub(r"\s+", "", venue_name).lower()
    return STAGE_ADDRESSES.get(normalized, "")


# Map Craft CMS category titles → pleskal EventCategory values
CATEGORY_MAP = {
    "forestillinger": "performance",
    "forestilling": "performance",
    "aktiviteter": "other",
    "aktivitet": "other",
    "workshops": "workshop",
    "workshop": "workshop",
    "start": "other",
    "kin-festival": "other",
    "kin festival": "other",
}

# Weekday name → Python weekday number (Monday=0, Sunday=6)
_WEEKDAY_MAP = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
    # Danish, for the "Spilletid" fallback
    "man": 0,
    "mandag": 0,
    "tir": 1,
    "tirs": 1,
    "tirsdag": 1,
    "ons": 2,
    "onsdag": 2,
    "tor": 3,
    "tors": 3,
    "torsdag": 3,
    "fre": 4,
    "fredag": 4,
    "lør": 5,
    "lørdag": 5,
    "søn": 6,
    "søndag": 6,
}
_WEEKDAY_ALT = "|".join(sorted(_WEEKDAY_MAP, key=len, reverse=True))

log = logging.getLogger(__name__)


# ── API fetch ─────────────────────────────────────────────────────────────────


def fetch_events() -> list[dict]:
    """POST the GraphQL query and return the raw list of event dicts."""
    session = make_session()
    resp = session.post(
        API_URL,
        headers=HEADERS,
        json={"query": GRAPHQL_QUERY},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]["eventsEntries"]


# ── Filtering ─────────────────────────────────────────────────────────────────


def is_upcoming(event: dict) -> bool:
    """Return True if the event's dateTo is today or in the future."""
    date_to_str = event.get("dateTo") or event.get("dateFrom")
    if not date_to_str:
        return False
    try:
        date_to = datetime.datetime.fromisoformat(date_to_str).date()
    except ValueError:
        return False
    return date_to >= datetime.date.today()


# ── Field extraction ──────────────────────────────────────────────────────────


def parse_description(event: dict) -> str:
    """
    Extract the English description as markdown.

    Prefers the first non-empty textEnglish from sections[], falls back to
    the top-level textEnglish field, then to the Danish text in the same
    order (some events are only written up in Danish).  Skips dataTable
    sections (no textEnglish on those rows in the text_Entry sense).
    """
    for field in ("textEnglish", "text"):
        for section in event.get("sections") or []:
            html = (section or {}).get(field) or ""
            if html.strip():
                return markdownify.markdownify(html, heading_style="ATX").strip()
        html = event.get(field) or ""
        if html.strip():
            return markdownify.markdownify(html, heading_style="ATX").strip()
    return ""


def _extract_row(event: dict, english_title: str, danish_titles: set[str]) -> str:
    """Return a dataTable row's value: the English text, else the Danish one.

    The CMS keeps both languages on one row; editors often fill in only the
    Danish column ("Spilletid: kl. 20.00" with an empty English "When").
    Placeholders like "tba" count as empty.
    """
    for section in event.get("sections") or []:
        for row in (section or {}).get("data") or []:
            row = row or {}
            title_en = (row.get("titleEnglish") or "").strip().lower()
            title_da = (row.get("title") or "").strip().lower()
            if title_en != english_title and title_da not in danish_titles:
                continue
            for field in ("textEnglish", "text"):
                value = (row.get(field) or "").strip()
                if value and value.lower() not in {"tba", "tbc", "tba."}:
                    return value
    return ""


def _extract_when(event: dict) -> str:
    """Return the 'When' schedule string from the dataTable sections, or ''."""
    return _extract_row(event, "when", {"spilletid", "hvornår", "tidspunkt"})


def _extract_where(event: dict) -> str:
    """Return the 'Where' string from the dataTable sections, or ''."""
    return _extract_row(event, "where", {"sted", "hvor"})


def _extract_duration(event: dict) -> datetime.timedelta | None:
    """Return the running time from the 'Duration' row ("1 hour and 15 min.")."""
    value = _extract_row(event, "duration", {"varighed"}).lower()
    hours = re.search(r"(\d+)\s*(?:hours?|timer?|t)\b", value)
    minutes = re.search(r"(\d+)\s*(?:minutes?|minutter|min)\b", value)
    if not (hours or minutes):
        return None
    return datetime.timedelta(
        hours=int(hours.group(1)) if hours else 0,
        minutes=int(minutes.group(1)) if minutes else 0,
    )


def _parse_time(token: str) -> datetime.time | None:
    """
    Parse a time token like '20.00', '18:00', '4.00 pm', '4 pm' into a
    datetime.time.  Returns None on failure.
    """
    token = token.strip().lower()
    # Handle "4 pm" / "4:00 pm" / "4.00 pm"
    # "4:00 PM — 6:00 PM": the start's am/pm is what counts, not the token end
    am_pm_m = re.match(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)\b", token)
    if am_pm_m:
        hour = int(am_pm_m.group(1))
        minute = int(am_pm_m.group(2) or 0)
        if am_pm_m.group(3) == "pm" and hour != 12:
            hour += 12
        elif am_pm_m.group(3) == "am" and hour == 12:
            hour = 0
        try:
            return datetime.time(hour, minute)
        except ValueError:
            return None
    # Handle "20.00", "20:00", "20.00-22.00" (take first)
    m = re.match(r"(\d{1,2})[.:](\d{2})", token)
    if m:
        try:
            return datetime.time(int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    # Plain hour like "20"
    plain_m = re.match(r"^(\d{1,2})$", token)
    if plain_m:
        try:
            return datetime.time(int(plain_m.group(1)), 0)
        except ValueError:
            return None
    return None


def _parse_times_from_clause(clause: str) -> list[datetime.time]:
    """
    Extract all time values from a clause like 'at 16.00 & 18.00' or
    '19.30, 20.00 & 20.30'.
    """
    times: list[datetime.time] = []
    # Remove leading 'at', 'kl.', 'kl'.  Note: the trailing '.' in 'kl.' is
    # not itself a word character, so a trailing \b after \.? never actually
    # matches when the period is present (no word boundary between '.' and
    # the following space) — leaving a stray '.' that breaks time parsing.
    clause = re.sub(r"\b(?:at|kl)\.?", " ", clause, flags=re.IGNORECASE).strip()
    # Split on separators: &, ,, +, 'and'/'og', whitespace sequences
    tokens = re.split(r"[&,+]|\b(?:and|og)\b", clause, flags=re.IGNORECASE)
    for tok in tokens:
        t = _parse_time(tok.strip())
        if t is not None:
            times.append(t)
    return times


def parse_when(
    when_str: str,
) -> dict[int, list[datetime.time]] | None:
    """
    Parse the "When" schedule string and return a mapping of
    weekday → list[time] (Monday=0, Sunday=6).

    Returns None if the string cannot be parsed (caller falls back to
    midnight for every day in the run).

    Handles these patterns (non-exhaustively):
      "at 20.00"                           → all days: [20:00]
      "20.00"                              → all days: [20:00]
      "at 16.00 & 18.00"                  → all days: [16:00, 18:00]
      "Tue — Sat at 20.00"                → Tue-Sat: [20:00]
      "Tue, Thu & Fri at 20.00 — Wed at 17.00 — Sat at 16.00"
                                           → Tue/Thu/Fri: [20:00], Wed: [17:00], Sat: [16:00]
      "Tues-Fri at 18.00"                 → Tue-Fri: [18:00]
      "Every Tuesday at 15.00 — 17.00"   → all Tue: [15:00]  (17.00 is end time)
      "Wed - Thur at 19.30, 20.00 & 20.30" → Wed/Thu: [19:30, 20:00, 20:30]
      "Thur & Fri at 19.00 and Sat at 15.00" → Thu/Fri: [19:00], Sat: [15:00]
      "Tors & fre kl. 19.00 og lørdag kl. 15.00" (Danish, same)
      "Every Tuesday at 4:00 PM — 6:00 PM" → all Tue: [16:00]
    """
    if not when_str:
        return None

    # Normalise dashes and whitespace
    s = when_str.replace("\u2013", "—").replace("\u2014", "—").strip()

    # Remove "Every " prefix
    s = re.sub(r"\bEvery\b\s*", "", s, flags=re.IGNORECASE).strip()

    # If no weekday token found, treat as "all days at <time>"
    has_weekday = bool(re.search(rf"\b(?:{_WEEKDAY_ALT})\b", s, re.IGNORECASE))
    if not has_weekday:
        # Extract times
        times = _parse_times_from_clause(s)
        if not times:
            return None
        # Return wildcard: None key means "every day"
        return {-1: times}

    # Split the string into "clause segments" — each clause is a weekday spec
    # followed by a time spec.  Clauses are separated by " — " / " - " where the
    # next token is alphabetic (i.e. starts a new weekday group, not a time range).
    #
    # Complication: "Tue — Sat at 20.00" should be a RANGE, not two segments.
    # We detect this by checking whether the token after the separator looks like
    # a weekday AND the preceding token also looks like a lone weekday (no time).
    # We therefore split lazily: first re-join any "orphan weekday — weekday" pairs.
    #
    # "Thur & Fri at 19.00 and Sat at 15.00" also starts a new clause at an
    # "and"/"og" that follows a time; before a time ("Tue and Thu at 19.00")
    # it just lists days.
    s = re.sub(
        rf"(\d)(\s*(?:am|pm)?)\s+(?:and|og)\s+(?=(?:{_WEEKDAY_ALT})\b)",
        r"\1\2 — ",
        s,
        flags=re.IGNORECASE,
    )
    raw_segments = re.split(r"\s+[—–-]\s+(?=[A-Za-zæøåÆØÅ])", s)

    # Re-join consecutive segments where the first has no time (it's the range start)
    segments: list[str] = []
    i = 0
    while i < len(raw_segments):
        seg = raw_segments[i]
        # Check if this segment contains a digit (time component)
        if not re.search(r"\d", seg) and i + 1 < len(raw_segments):
            # This segment is pure weekday text — check if next segment starts
            # with a weekday too (range: "Tue — Sat at 20.00")
            next_seg = raw_segments[i + 1]
            next_first_word = re.match(r"(\w+)", next_seg)
            if next_first_word and next_first_word.group(1).lower() in _WEEKDAY_MAP:
                # Merge: "Tue — Sat at 20.00"
                segments.append(seg + " — " + next_seg)
                i += 2
                continue
        segments.append(seg)
        i += 1

    result: dict[int, list[datetime.time]] = {}

    for segment in segments:
        segment = segment.strip()

        # Separate the weekday part from the time part.
        # Split on first occurrence of 'at' or 'kl' followed by a time.
        time_split = re.split(
            r"\s+(?:at|kl\.?)\s*", segment, maxsplit=1, flags=re.IGNORECASE
        )
        if len(time_split) == 2:
            days_part, times_part = time_split
        else:
            # Format "Tue — Sat 20.00" without 'at' — find first time-like token
            m = re.search(r"(\d{1,2}[.:]\d{2})", segment)
            if m:
                days_part = segment[: m.start()].strip()
                times_part = segment[m.start() :].strip()
            else:
                continue

        times = _parse_times_from_clause(times_part)
        if not times:
            continue

        # Parse the days part — may be a range "Tue — Sat" or list "Tue, Thu & Fri"
        # First check for a range (two weekday names separated by — or -)
        range_m = re.match(
            r"^(\w+)\s*[—–-]\s*(\w+)$",
            days_part.strip(),
            re.IGNORECASE,
        )
        if range_m:
            start_name = range_m.group(1).lower()
            end_name = range_m.group(2).lower()
            start_wd = _WEEKDAY_MAP.get(start_name)
            end_wd = _WEEKDAY_MAP.get(end_name)
            if start_wd is not None and end_wd is not None:
                # Expand range, wrapping around week if needed
                wd = start_wd
                while True:
                    result.setdefault(wd, []).extend(times)
                    if wd == end_wd:
                        break
                    wd = (wd + 1) % 7
                continue

        # Otherwise parse as list: "Tue, Thu & Fri"
        day_tokens = re.split(r"[,&+]|\b(?:and|og)\b", days_part, flags=re.IGNORECASE)
        found_any = False
        for tok in day_tokens:
            tok = tok.strip().lower()
            wd = _WEEKDAY_MAP.get(tok)
            if wd is not None:
                result.setdefault(wd, []).extend(times)
                found_any = True

        if not found_any:
            log.debug("Could not parse weekday segment %r in %r", days_part, when_str)

    return {wd: sorted(set(times)) for wd, times in result.items()} or None


def _normalize_dt(iso_str: str) -> datetime.datetime:
    """
    Parse an ISO 8601 datetime string and normalise to midnight CPH.

    The API always returns 07:00 UTC (= 09:00 CPH) as a placeholder time.
    We treat all sydhavnteater events as all-day unless parse_when provides a
    specific time.
    """
    dt = datetime.datetime.fromisoformat(iso_str)
    return (
        dt.astimezone(CPH_TZ)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(datetime.UTC)
    )


def _dt_at_time(date: datetime.date, t: datetime.time) -> datetime.datetime:
    """Combine a date and a CPH wall-clock time into a UTC-aware datetime."""
    return datetime.datetime(
        date.year, date.month, date.day, t.hour, t.minute, tzinfo=CPH_TZ
    ).astimezone(datetime.UTC)


def build_records(event: dict) -> list[dict]:
    """
    Map a raw API event dict to a list of pleskal event record dicts — one per
    performance day.  Returns an empty list if essential fields are missing.

    Date ranges (dateFrom→dateTo) are expanded day by day.  The "When" field
    determines which weekdays have performances and at what time(s); a day
    with several shows (e.g. "at 16.00 & 18.00") gets one record per show.
    The "Duration" row, when present, sets each timed record's end.
    """
    # CMS titles carry editor artefacts: zero-width joiners and doubled spaces
    # ("Skæbnen  \u200d- en spøgelseshistorie i VR").
    title = re.sub(r"[\u200b-\u200d\ufeff]", "", event.get("title") or "")
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        log.warning("Skipping event with no title: %s", event.get("slug"))
        return []

    uri = event.get("uri") or ""
    source_url = f"{BASE_URL}/{uri}" if uri else ""
    if not source_url:
        log.warning("Skipping event with no URI: %s", title)
        return []

    date_from_str = event.get("dateFrom")
    if not date_from_str:
        log.warning("Skipping event with no dateFrom: %s", title)
        return []

    try:
        start_date = datetime.datetime.fromisoformat(date_from_str).date()
    except ValueError as exc:
        log.warning("Cannot parse dateFrom %r for %s: %s", date_from_str, title, exc)
        return []

    date_to_str = event.get("dateTo") or date_from_str
    try:
        end_date = datetime.datetime.fromisoformat(date_to_str).date()
    except ValueError:
        end_date = start_date

    if end_date < start_date:
        end_date = start_date

    stages = event.get("stage") or []
    venue_name = stages[0]["title"] if stages else "Sydhavn Teater"
    where_str = _extract_where(event)
    if where_str:
        venue_name = where_str
    venue_address = _stage_address(venue_name)

    categories = event.get("category") or []
    raw_category = categories[0]["title"].lower() if categories else ""
    category = CATEGORY_MAP.get(raw_category, "other")

    media = event.get("media") or []
    image_url = media[0]["url"] if media else ""

    ticket_link = event.get("ticketLink") or ""
    is_free = not bool(ticket_link)

    description = parse_description(event)

    when_str = _extract_when(event)
    schedule = parse_when(when_str)  # {weekday: [times]} or None
    duration = _extract_duration(event)

    records: list[dict] = []
    current = start_date
    while current <= end_date:
        wd = current.weekday()

        if schedule is None:
            # No schedule info — one record per day at midnight CPH
            times: list[datetime.time] = []
        elif -1 in schedule:
            # All-days wildcard
            times = schedule[-1]
        else:
            times = schedule.get(wd, [])
            if not times:
                current += datetime.timedelta(days=1)
                continue

        if times:
            slots = [
                (start_dt, start_dt + duration if duration else None)
                for start_dt in (_dt_at_time(current, t) for t in times)
            ]
        else:
            # Midnight fallback: an all-day placeholder, so no end time
            midnight = datetime.datetime(
                current.year,
                current.month,
                current.day,
                0,
                0,
                tzinfo=CPH_TZ,
            ).astimezone(datetime.UTC)
            slots = [(midnight, None)]

        for start_dt, end_dt in slots:
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
                    "price_note": "",
                    "source_url": source_url,
                    "external_source": EXTERNAL_SOURCE,
                    "image_url": image_url,
                }
            )

        current += datetime.timedelta(days=1)

    return records


# ── Main ──────────────────────────────────────────────────────────────────────


def scrape() -> list[dict]:
    """Fetch all events from the API, filter to upcoming, and return records."""
    raw_events = fetch_events()
    log.info("Fetched %d events from API", len(raw_events))

    upcoming = [e for e in raw_events if is_upcoming(e)]
    log.info("%d upcoming events after date filter", len(upcoming))

    records: list[dict] = []
    for event in upcoming:
        event_records = build_records(event)
        records.extend(event_records)
        if event_records:
            log.debug(
                "  %s → %d record(s)", event.get("title", "?"), len(event_records)
            )

    log.info("Built %d event records", len(records))
    return records


def main() -> None:
    args = build_arg_parser(
        "Scrape sydhavnteater.dk calendar",
        "sydhavnteater_events.json",
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
