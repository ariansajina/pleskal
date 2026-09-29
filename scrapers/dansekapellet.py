"""Scraper for Dansekapellet (Bispebjerg Torv 1), via teaterbilletter.dk.

Shows, performance times and content come from the teaterbilletter.dk API (see
``scrapers/teaterbilletter.py``).  The venue is registered there to Uppercut
Danseteater, which runs it, and events are published under the Uppercut
account, though visiting companies play there too.  Every genre is taken.
Dansekapellet's site has no show pages, so events keep their
teaterbilletter.dk links.

Wheelchair access is unconfirmed, so it isn't claimed.

Usage:
    uv run python scrapers/dansekapellet.py --dry-run
"""

from __future__ import annotations

from scrapers import teaterbilletter
from scrapers.teaterbilletter import TeaterbilletterVenue

VENUE = TeaterbilletterVenue(
    external_source="uppercut",
    venue_codes=("VN0000720",),
    venue_names={"VN0000720": "Dansekapellet"},
)
# There is no programme page to check against: the venue's listing lives on
# teaterbilletter.dk, which renders with JavaScript.
HOME_URL = "https://www.dansekapellet.dk/"


def scrape() -> list[dict]:
    """Scrape Dansekapellet's programme and return a list of event dicts."""
    return teaterbilletter.scrape(VENUE)


if __name__ == "__main__":
    teaterbilletter.run_cli(scrape, "dansekapellet")
