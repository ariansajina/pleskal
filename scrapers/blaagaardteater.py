"""Scraper for Blaagaard Teater (https://blaagaardteater.dk/), via teaterbilletter.dk.

Shows, performance times, prices, images, descriptions and credits come from
the teaterbilletter.dk API (see ``scrapers/teaterbilletter.py``).  Blaagaard is
mostly a drama stage, so only dance, performance and new-circus shows and
events are taken (the Dans/Events genres plus the matching categories).

The programme page (``/program``) lists each show as a ``div.teaser`` card
whose "Køb billet" button carries the ticketing ``data-event_no``; that links
each event to its page on blaagaardteater.dk.

Step-free: its "Om os" page offers a ramp into both the foyer and the
auditorium (though there is no accessible toilet).

Usage:
    uv run python scrapers/blaagaardteater.py --dry-run
"""

from __future__ import annotations

from scrapers import teaterbilletter
from scrapers.teaterbilletter import TeaterbilletterVenue

PROGRAM_URL = "https://blaagaardteater.dk/program"

VENUE = TeaterbilletterVenue(
    external_source="blaagaardteater",
    venue_codes=("VN0000046",),
    venue_names={"VN0000046": "Blaagaard Teater"},
    genres=teaterbilletter.DANCE_AND_EVENTS_GENRES,
    categories=teaterbilletter.DANCE_AND_PERFORMANCE_CATEGORIES,
    is_wheelchair_accessible=True,
)


def scrape() -> list[dict]:
    """Scrape Blaagaard Teater's programme and return a list of event dicts."""
    return teaterbilletter.scrape(
        VENUE,
        venue_links=teaterbilletter.venue_page_links(
            PROGRAM_URL,
            card_selector=".teaser-grid .teaser",
            link_selector="h2 a[href]",
        ),
    )


if __name__ == "__main__":
    teaterbilletter.run_cli(scrape, "blaagaardteater")
