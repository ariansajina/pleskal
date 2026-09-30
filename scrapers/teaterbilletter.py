"""Shared scraping logic for venues that sell tickets through teaterbilletter.dk.

teaterbilletter.dk is the public front of Billetten, the ticketing system many
Copenhagen stages use.  Its site is backed by a public JSON listing,
``/api/events?venueCodes=<code>[,<code>…]``, that carries everything an event
record needs: title, teaser and description (plain text), credits, images
(served from tereba.dk), the venue's address, every scheduled performance, the
running time and the ticket price range.  So a venue on the system is scraped
from the API alone; a per-venue module only supplies a
:class:`TeaterbilletterVenue` config and, optionally, a ``venue_links`` hook
that looks the shows up on the venue's own programme page, so events link to
the venue's show pages rather than to teaterbilletter.dk.

Performance times in the API are **UTC** without an offset — a 20:00 show in
Copenhagen reads ``18:00:00`` in summer and ``19:00:00`` in winter — so they are
converted to Copenhagen time here.

Adding a venue:

1. Find its venue code(s) (``VN…``) in ``https://teaterbilletter.dk/api/venues``
   (a theatre may have several, e.g. a site-specific location).
2. Add ``scrapers/<venue>.py`` with a ``VENUE`` config and a ``scrape()`` that
   calls :func:`scrape` (see ``afukscene.py``).  If the venue's own programme
   page shows Billetten's "Køb billet" buttons (``data-event_no``), pass
   :func:`venue_page_links` so events link to the venue's show pages (see
   ``blaagaardteater.py``), and give the module a ``PROGRAM_URL`` for the
   scraper-health skill.
3. Register it in ``scrapers/registry.py`` (``TEATERBILLETTER_IMAGE_DOMAINS``)
   and add its publisher to ``scrapers/sources.json``.
"""

from __future__ import annotations

import datetime
import logging
import re
import time
import zoneinfo
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from events.limits import MAX_PRICE_NOTE_LENGTH
from scrapers.base import (
    HEADERS,
    build_arg_parser,
    get_soup,
    is_cancelled_title,
    make_session,
    write_output,
)

API_URL = "https://teaterbilletter.dk/api/events"
SITE_URL = "https://teaterbilletter.dk"
IMAGE_DOMAIN = "tereba.dk"
CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")
PAGE_SIZE = 30

# Genre filter for dance/performance-focused listings: the teaterbilletter.dk
# genres "Dans" and "Events" (its own site filter), plus shows whose category
# is dance, performance or new circus but whose genre tags miss that (new
# circus without tags, "Performance / Kropsteater" tagged as Drama).
DANCE_AND_EVENTS_GENRES = frozenset({"Dans", "Events"})
DANCE_AND_PERFORMANCE_CATEGORIES = frozenset(
    {"Dans og ballet", "Performance", "Nycirkus"}
)

# Scheduled performances closed to the public (e.g. booked by a school).
_CLOSED_SHOW_TYPE = "Lukket forestilling"
_WHITESPACE_RE = re.compile(r"\s+")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TeaterbilletterVenue:
    """Per-venue configuration for :func:`scrape`.

    ``venue_codes`` are Billetten venue codes (``VN…``); a theatre can have
    several (e.g. a site-specific location next to its own stage).
    ``venue_names`` overrides the API's venue name per code (the API writes
    e.g. "TEATER FÅR302" or "Dansekapellet, København").  ``genres`` and
    ``categories`` restrict the scrape to events tagged with one of those
    genres (``mappedCategoryNames``) or filed under one of those categories
    (``categoryName``); leave both as None to take every event.
    """

    external_source: str
    venue_codes: tuple[str, ...]
    venue_names: Mapping[str, str] = field(default_factory=dict)
    genres: frozenset[str] | None = None
    categories: frozenset[str] | None = None
    is_wheelchair_accessible: bool = False
    category: str = "performance"


# A venue_links hook gets the session and the (filtered) API events and returns
# the venue's show page per str(eventNo). A show it has no page for keeps its
# teaterbilletter.dk link; if it can't read the venue's site at all, it should
# raise rather than return nothing (see venue_page_links).
LinksHook = Callable[[requests.Session, list[dict]], dict[str, str]]


# ── API ───────────────────────────────────────────────────────────────────────


def fetch_events(session: requests.Session, venue_codes: tuple[str, ...]) -> list[dict]:
    """Return every teaterbilletter.dk event at *venue_codes*.

    Raises on HTTP or JSON errors: the API is the scraper's only source, so a
    failure must surface as a failed scrape rather than an empty programme.
    """
    events: list[dict] = []
    page = 1
    while True:
        resp = session.get(
            API_URL,
            params={
                "page": page,
                "pageSize": PAGE_SIZE,
                "venueCodes": ",".join(venue_codes),
            },
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        if "items" not in data:
            raise ValueError(f"Unexpected teaterbilletter.dk response: {data!r:.200}")
        events.extend(data["items"] or [])
        page_count = (data.get("pagination") or {}).get("pageCount") or 1
        if page >= page_count:
            return events
        page += 1


def matches_filter(event: dict, venue: TeaterbilletterVenue) -> bool:
    """Return True if *event* passes the venue's genre/category filter."""
    if venue.genres is None and venue.categories is None:
        return True
    genres = set(event.get("mappedCategoryNames") or [])
    if venue.genres and genres & venue.genres:
        return True
    return bool(venue.categories and event.get("categoryName") in venue.categories)


def _parse_utc(value: str) -> datetime.datetime | None:
    try:
        dt = datetime.datetime.fromisoformat(value)
    except TypeError, ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.astimezone(CPH_TZ)


def show_times(event: dict) -> list[datetime.datetime]:
    """Return the sorted, de-duplicated public performance times of *event*.

    ``scheduledShows`` (every performance, with its state and type) is used
    when present, dropping closed and non-active performances; otherwise
    ``shows`` / ``showDates`` (upcoming performances only).  Times are
    returned in Copenhagen time.
    """
    scheduled = event.get("scheduledShows")
    if scheduled:
        raw = [
            s.get("dateTime", "")
            for s in scheduled
            if s
            and s.get("state", "Active") == "Active"
            and s.get("type") != _CLOSED_SHOW_TYPE
        ]
    else:
        raw = [s.get("showTime", "") for s in event.get("shows") or [] if s] or list(
            event.get("showDates") or []
        )
    return sorted({dt for value in raw if (dt := _parse_utc(value)) is not None})


def price_note(event: dict) -> str:
    """Format the ticket price range, e.g. "40–165 kr."."""
    low = event.get("ticketPriceMin")
    high = event.get("ticketPriceMax")
    if not low and not high:
        return ""
    if low and high and low != high:
        note = f"{low:g}–{high:g} kr."
    else:
        note = f"{(low or high):g} kr."
    return note[:MAX_PRICE_NOTE_LENGTH]


def _paragraphs(text: str) -> list[str]:
    """Split API plain text into paragraphs (one per non-blank line)."""
    return [
        _WHITESPACE_RE.sub(" ", line).strip()
        for line in (text or "").splitlines()
        if line.strip()
    ]


# Credits list the crew before the cast, like the venues' own pages.
_CREDIT_ORDER = {"Production": 0, "Cast": 1}


def credits(event: dict) -> str:
    """Return the API's credits as markdown lines, e.g. "**Koreograf** Name".

    One line per role (names in the API's order, crew before cast), then the
    producing company when it isn't the venue's own organiser.
    """
    roles: dict[str, list[str]] = {}
    accreditations = sorted(
        (a for a in event.get("accreditations") or [] if a),
        key=lambda a: _CREDIT_ORDER.get(a.get("positionTypeName"), 2),
    )
    for credit in accreditations:
        role = _WHITESPACE_RE.sub(" ", str(credit.get("positionName") or "")).strip()
        name = _WHITESPACE_RE.sub(
            " ", f"{credit.get('firstName') or ''} {credit.get('lastName') or ''}"
        ).strip()
        if role and name and name not in roles.setdefault(role, []):
            roles[role].append(name)
    lines = [f"**{role}** {', '.join(names)}" for role, names in roles.items() if names]
    producer = event.get("producer") or {}
    organizer = event.get("organizer") or {}
    if producer.get("name") and producer.get("code") != organizer.get("code"):
        lines.append(f"**Produktion** {producer['name'].strip()}")
    return "  \n".join(lines)


def description(event: dict) -> str:
    """Return the teaser, description and credits as markdown paragraphs.

    The API separates paragraphs with single or double newlines, so every line
    becomes a paragraph.  Teaser paragraphs already in the description (venues
    often reuse the description's opening as teaser) are left out.  The credits
    (see :func:`credits`) end it as one paragraph of lines.
    """
    body = _paragraphs(event.get("description") or "")
    body_text = " ".join(body)
    lead = [p for p in _paragraphs(event.get("teaser") or "") if p not in body_text]
    credit_lines = credits(event)
    return "\n\n".join(lead + body + ([credit_lines] if credit_lines else []))


def image_url(event: dict) -> str:
    """Return the event's largest landscape image, else its largest image."""
    images = [i for i in event.get("images") or [] if i and i.get("url")]
    if not images:
        return ""
    landscape = [i for i in images if i.get("orientation") == "Landscape"]
    best = max(landscape or images, key=lambda i: i.get("width") or 0)
    return str(best["url"])


def event_page_url(event: dict) -> str:
    """Return the event's teaterbilletter.dk page."""
    exit_link = str(event.get("exitLinkUrl") or "").split("#", 1)[0]
    if exit_link:
        return exit_link
    return f"{SITE_URL}/forestillinger/{event.get('slug', '')}"


def venue_address(event: dict) -> str:
    """Format the API venue's street address, e.g. "Enghavevej 82B".

    Street only, like the other scrapers: geocoding appends the city itself,
    and Nominatim fails on some addresses when the postcode and district are
    in the query too.
    """
    venue = event.get("venue") or {}
    street = " ".join(
        str(part).strip()
        for part in (venue.get("street"), venue.get("number"))
        if part and str(part).strip()
    )
    return street + str(venue.get("letter") or "").strip()


def venue_name(event: dict, venue: TeaterbilletterVenue) -> str:
    api_venue = event.get("venue") or {}
    code = api_venue.get("code") or ""
    return venue.venue_names.get(code) or str(api_venue.get("name") or "").strip()


# ── Links to the venue's own show pages ───────────────────────────────────────────────


def ticket_links(
    soup: BeautifulSoup, base_url: str, card_selector: str, link_selector: str
) -> dict[str, str]:
    """Map ticket numbers to show pages on a venue's programme listing.

    Venues embed Billetten's ticket widget, whose "Køb billet" buttons carry the
    show's ``data-event_no`` (the API's ``eventNo``).  For every card matching
    *card_selector* that has such a button, the first *link_selector* match in
    the card is taken as the show's page.
    """
    links: dict[str, str] = {}
    for card in soup.select(card_selector):
        button = card.select_one("[data-event_no]")
        link = card.select_one(link_selector)
        if button is None or link is None or not link.get("href"):
            continue
        event_no = str(button["data-event_no"]).strip()
        if event_no and event_no not in links:
            links[event_no] = urljoin(base_url, str(link["href"]).strip())
    return links


class ListingUnavailable(Exception):
    """A venue's programme page couldn't be read (error or bot challenge)."""


def venue_page_links(
    listing_url: str,
    card_selector: str,
    link_selector: str,
    retry_delay: float = 10.0,
) -> LinksHook:
    """Return a hook linking events to their pages on the venue's own site.

    Reads the programme at *listing_url* (see :func:`ticket_links`); only this
    one page is fetched.  The content itself (description and credits) comes
    from the API, which has as much as the venues' show pages and isn't
    behind the bot challenge faar302.dk serves to some requests.

    If the programme can't be read — an HTTP error, or a page without any
    *card_selector* card, which is what that bot challenge looks like (status
    200) — it is retried once and then :class:`ListingUnavailable` is raised,
    failing the venue's scrape.  Falling back to teaterbilletter.dk links
    instead would switch every event's ``source_url`` for one run and back on
    the next, and scraped series are keyed on ``source_url``, so each switch
    would move the upcoming dates into another series.  A failed scrape leaves
    the imported events as they are.
    """

    def links(session: requests.Session, events: list[dict]) -> dict[str, str]:
        if not events:
            return {}
        for attempt in (1, 2):
            try:
                soup = get_soup(listing_url, session)
            except requests.RequestException as exc:
                problem = str(exc)
            else:
                if soup.select(card_selector):
                    found = ticket_links(
                        soup, listing_url, card_selector, link_selector
                    )
                    for event in events:
                        if str(event.get("eventNo")) not in found:
                            log.info(
                                "No page on %s for %r", listing_url, event.get("title")
                            )
                    return found
                title = soup.title.get_text(strip=True) if soup.title else ""
                problem = f"no {card_selector!r} cards (page title {title!r})"
            log.warning("Could not read %s (try %d): %s", listing_url, attempt, problem)
            if attempt == 1:
                time.sleep(retry_delay)
        raise ListingUnavailable(f"{listing_url}: {problem}")

    return links


# ── Record building ───────────────────────────────────────────────────────────


def build_records(
    event: dict,
    venue: TeaterbilletterVenue,
    source_url: str | None = None,
    now: datetime.datetime | None = None,
) -> list[dict]:
    """Build one pleskal record per upcoming public performance of *event*.

    Each record links to *source_url* (the venue's show page) when given, else
    to teaterbilletter.dk, and ends after the API's running time; when the API
    has none (``durationInMinutes`` 0) the end is left open.
    """
    if now is None:
        now = datetime.datetime.now(datetime.UTC)

    title = _WHITESPACE_RE.sub(" ", str(event.get("title") or "")).strip()
    if not title or is_cancelled_title(title):
        return []

    minutes = event.get("durationInMinutes") or 0
    duration = datetime.timedelta(minutes=minutes) if minutes > 0 else None
    base = {
        "title": title,
        "description": description(event),
        "venue_name": venue_name(event, venue),
        "venue_address": venue_address(event),
        "category": venue.category,
        "is_free": False,
        "is_wheelchair_accessible": venue.is_wheelchair_accessible,
        "price_note": price_note(event),
        "source_url": source_url or event_page_url(event),
        "external_source": venue.external_source,
        "image_url": image_url(event),
    }
    return [
        {
            **base,
            "start_datetime": t.isoformat(),
            "end_datetime": (t + duration).isoformat() if duration else None,
        }
        for t in show_times(event)
        if t >= now
    ]


# ── Scrape entry point ────────────────────────────────────────────────────────


def scrape(
    venue: TeaterbilletterVenue,
    venue_links: LinksHook | None = None,
    session: requests.Session | None = None,
) -> list[dict]:
    """Scrape *venue*'s teaterbilletter.dk programme into pleskal records."""
    session = session or make_session()
    events = fetch_events(session, venue.venue_codes)
    selected = [e for e in events if matches_filter(e, venue)]
    log.info(
        "%s: %d of %d teaterbilletter.dk events pass the filter",
        venue.external_source,
        len(selected),
        len(events),
    )

    links = venue_links(session, selected) if venue_links else {}
    records: list[dict] = []
    for event in selected:
        records.extend(
            build_records(event, venue, links.get(str(event.get("eventNo"))))
        )
    log.info("%s: %d event records", venue.external_source, len(records))
    return records


def run_cli(scrape_fn: Callable[[], list[dict]], name: str) -> None:
    """Command-line entry point shared by the per-venue modules."""
    args = build_arg_parser(
        f"Scrape {name} from teaterbilletter.dk",
        f"{name}_events.json",
        include_delay=False,
    ).parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    write_output(scrape_fn(), args.output, args.dry_run)
