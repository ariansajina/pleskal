"""Scraper for Teater FÅR302 (https://www.faar302.dk/), via teaterbilletter.dk.

Shows, performance times, prices, images, descriptions and credits come from
the teaterbilletter.dk API (see ``scrapers/teaterbilletter.py``) for FÅR302's
own stage and the site-specific locations it registers as separate venues.
Every genre is taken.

FÅR302's front page lists each show as a ``div.forestilling`` card whose "Køb
billet" button carries the ticketing ``data-event_no``; that links each event
to its page on faar302.dk.  Only the front page is fetched: faar302.dk serves
a bot challenge to many requests for its show pages.

The theatre is not wheelchair accessible (stated on its /billetter/ page).

Usage:
    uv run python scrapers/faar302.py
    uv run python scrapers/faar302.py --output events.json
    uv run python scrapers/faar302.py --dry-run   # print JSON, don't write
"""

from __future__ import annotations

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


def scrape() -> list[dict]:
    """Scrape FÅR302's programme and return a list of event dicts."""
    return teaterbilletter.scrape(
        VENUE,
        venue_links=teaterbilletter.venue_page_links(
            PROGRAM_URL,
            card_selector="div.forestilling",
            link_selector='a.forteksten[href], a[href*="/forestilling/"]',
        ),
    )


if __name__ == "__main__":
    teaterbilletter.run_cli(scrape, "faar302")
