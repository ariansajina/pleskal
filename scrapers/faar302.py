"""Scraper for Teater FÅR302 (https://www.faar302.dk/), via teaterbilletter.dk.

Shows, performance times, prices and images come from the teaterbilletter.dk
API (see ``scrapers/teaterbilletter.py``) for FÅR302's own stage and the
site-specific locations it registers as separate venues.  Every genre is taken.

FÅR302's front page lists each show as a ``div.forestilling`` card whose "Køb
billet" button carries the ticketing ``data-event_no``; that links each event
to its page on faar302.dk, whose ``div.textbox`` gives the description: fuller
than the API's (Danish and English, full credits, practical notes).  Some shows
have no running time in the API, so it is read from the page ("Varighed ca. 35
min") instead.  When a show page can't be read (faar302.dk intermittently
serves a bot challenge), the API's description and credits are used.

The theatre is not wheelchair accessible (stated on its /billetter/ page).

Usage:
    uv run python scrapers/faar302.py
    uv run python scrapers/faar302.py --output events.json
    uv run python scrapers/faar302.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

import datetime
import re

from bs4 import BeautifulSoup

from scrapers import teaterbilletter
from scrapers.teaterbilletter import TeaterbilletterVenue

PROGRAM_URL = "https://www.faar302.dk/"

VENUE = TeaterbilletterVenue(
    external_source="faar302",
    # Toldbodgade 6, plus the site-specific SKURET location by Carlsberg Station.
    venue_codes=("VN0000120", "VN0003980"),
    venue_names={"VN0000120": "Teater FÅR302"},
    is_wheelchair_accessible=False,
)

# "Varighed ca. 35 min", "ca. 1 time og 45 minutter", "Duration 75 min."
_DURATION_LABEL_RE = re.compile(r"^(?:varighed|duration)\b:?\s*(.*)$", re.IGNORECASE)
_HOURS_RE = re.compile(r"(\d+)\s*(?:timer?|hours?)\b", re.IGNORECASE)
_MINUTES_RE = re.compile(r"(\d+)\s*(?:minutter|minutes?|min)\b", re.IGNORECASE)


def parse_duration(soup: BeautifulSoup) -> datetime.timedelta | None:
    """Return the running time stated on a show page, if any.

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


def parse_description(soup: BeautifulSoup) -> str:
    """Return a show page's ``div.textbox`` (description and credits) as markdown."""
    return teaterbilletter.html_markdown(soup.select_one("div.textbox"))


def scrape(delay: float = 0.5) -> list[dict]:
    """Scrape FÅR302's programme and return a list of event dicts."""
    return teaterbilletter.scrape(
        VENUE,
        enrich=teaterbilletter.listing_enricher(
            PROGRAM_URL,
            card_selector="div.forestilling",
            link_selector='a.forteksten[href], a[href*="/forestilling/"]',
            description_from_page=parse_description,
            duration_from_page=parse_duration,
            delay=delay,
        ),
    )


if __name__ == "__main__":
    teaterbilletter.run_cli(scrape, "faar302")
