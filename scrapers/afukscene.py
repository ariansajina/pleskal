"""Scraper for AFUK Scene (Enghavevej 82 B), via teaterbilletter.dk.

Shows, performance times and content come from the teaterbilletter.dk API (see
``scrapers/teaterbilletter.py``); only dance, performance and new-circus shows
and events are taken (the Dans/Events genres plus the matching categories).
AFUK's own scene page links straight to teaterbilletter.dk, so events keep
their teaterbilletter.dk links.

Wheelchair access is unconfirmed, so it isn't claimed: afuk.dk's practical-info
page and godadgang.dk say nothing about the scene (last checked 2026-09).

Usage:
    uv run python scrapers/afukscene.py --dry-run
"""

from __future__ import annotations

from scrapers import teaterbilletter
from scrapers.teaterbilletter import TeaterbilletterVenue

PROGRAM_URL = "https://www.afuk.dk/scene/"

VENUE = TeaterbilletterVenue(
    external_source="afukscene",
    venue_codes=("VN0001294",),
    genres=teaterbilletter.DANCE_AND_EVENTS_GENRES,
    categories=teaterbilletter.DANCE_AND_PERFORMANCE_CATEGORIES,
)


def scrape() -> list[dict]:
    """Scrape AFUK Scene's programme and return a list of event dicts."""
    return teaterbilletter.scrape(VENUE)


if __name__ == "__main__":
    teaterbilletter.run_cli(scrape, "afukscene")
