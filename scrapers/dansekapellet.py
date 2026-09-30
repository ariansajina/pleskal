"""Scraper for Dansekapellet (Bispebjerg Torv 1), via teaterbilletter.dk.

Shows, performance times and content come from the teaterbilletter.dk API (see
``scrapers/teaterbilletter.py``).  The venue is registered there to Uppercut
Danseteater, its resident company, but visiting companies play there too, so
events are published under a Dansekapellet account.  Every genre is taken.
Dansekapellet's site has no show pages, so events keep their
teaterbilletter.dk links.

Step-free: level access from the entrance to the ground floor (theatre hall,
halls 1-3, accessible toilet), a platform lift to the first floor and mobile
ramps for the dome hall's 14 cm step (godadgang.dk factsheet for Dansekapellet).

Usage:
    uv run python scrapers/dansekapellet.py --dry-run
"""

from __future__ import annotations

from scrapers import teaterbilletter
from scrapers.teaterbilletter import TeaterbilletterVenue

VENUE = TeaterbilletterVenue(
    external_source="dansekapellet",
    venue_codes=("VN0000720",),
    venue_names={"VN0000720": "Dansekapellet"},
    is_wheelchair_accessible=True,
)
# There is no programme page to check against: the venue's listing lives on
# teaterbilletter.dk, which renders with JavaScript.
HOME_URL = "https://www.dansekapellet.dk/"


def scrape() -> list[dict]:
    """Scrape Dansekapellet's programme and return a list of event dicts."""
    return teaterbilletter.scrape(VENUE)


if __name__ == "__main__":
    teaterbilletter.run_cli(scrape, "dansekapellet")
