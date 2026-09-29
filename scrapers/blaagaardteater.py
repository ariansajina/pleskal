"""Scraper for Blaagaard Teater (https://blaagaardteater.dk/), via teaterbilletter.dk.

Shows, performance times, prices and images come from the teaterbilletter.dk
API (see ``scrapers/teaterbilletter.py``).  Blaagaard is mostly a drama stage,
so only dance, performance and new-circus shows and events are taken (the
Dans/Events genres plus the matching categories).

The programme page (``/program``) lists each show as a ``div.teaser`` card
whose "Køb billet" button carries the ticketing ``data-event_no``; that links
each event to its page on blaagaardteater.dk, which gives the description: the
teaser, the text and the credit lists ("Medvirkende", "Skabt af", …).  When a
show page can't be read, the API's description and credits are used.

Step-free: its "Om os" page offers a ramp into both the foyer and the
auditorium (though there is no accessible toilet).

Usage:
    uv run python scrapers/blaagaardteater.py --dry-run
"""

from __future__ import annotations

from bs4 import BeautifulSoup

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


def parse_description(soup: BeautifulSoup) -> str:
    """Return a show page's teaser, description and credits as markdown."""
    info = soup.select_one(".entry-info")
    text = teaterbilletter.html_markdown(
        info.select_one(".description") if info else None
    )
    if info is None or not text:
        return ""
    teaser = info.select_one(".teaser")
    parts = [teaser.get_text(" ", strip=True)] if teaser else []
    parts.append(text)
    for block in info.select(".credit-list"):
        heading = block.select_one("h2")
        names = [li.get_text(" ", strip=True) for li in block.select("li")]
        names = [n for n in names if n]
        if heading and names:
            lines = [f"**{heading.get_text(' ', strip=True)}**", *names]
            parts.append("  \n".join(lines))
    return "\n\n".join(p for p in parts if p)


def scrape() -> list[dict]:
    """Scrape Blaagaard Teater's programme and return a list of event dicts."""
    return teaterbilletter.scrape(
        VENUE,
        enrich=teaterbilletter.listing_enricher(
            PROGRAM_URL,
            card_selector=".teaser-grid .teaser",
            link_selector="h2 a[href]",
            description_from_page=parse_description,
        ),
    )


if __name__ == "__main__":
    teaterbilletter.run_cli(scrape, "blaagaardteater")
