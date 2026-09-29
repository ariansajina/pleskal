"""Unit tests for scrapers/faar302.py (the teaterbilletter.dk layer is covered
by test_teaterbilletter.py)."""

from __future__ import annotations

import datetime
from unittest.mock import patch

from bs4 import BeautifulSoup

from scrapers import faar302
from scrapers.faar302 import parse_duration, scrape
from scrapers.teaterbilletter import ticket_links


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _card(slug: str, event_no: str | None) -> str:
    button = (
        f'<a class="button basm basm_select" href="#" data-event_no="{event_no}">'
        "Køb billet</a>"
        if event_no
        else ""
    )
    return f"""
    <div class="forestilling">
      <a href="https://www.faar302.dk/forestilling/{slug}/">
        <div class="coverpic b-lazy" data-src="https://www.faar302.dk/{slug}.jpg"></div>
      </a>
      <div class="fortekst">
        {button}
        <a class="forteksten" href="https://www.faar302.dk/forestilling/{slug}/">
          <h3>7.-10. Oktober 2026</h3><h1>{slug}</h1>
        </a>
      </div>
    </div>
    """


def test_front_page_cards_link_ticket_numbers():
    html = _card("gazed", "147686") + _card("skuret", "151582") + _card("gratis", None)
    enrich_kwargs = _enricher_kwargs()
    links = ticket_links(
        _soup(html),
        faar302.PROGRAM_URL,
        enrich_kwargs["card_selector"],
        enrich_kwargs["link_selector"],
    )
    assert links == {
        "147686": "https://www.faar302.dk/forestilling/gazed/",
        "151582": "https://www.faar302.dk/forestilling/skuret/",
    }


def _enricher_kwargs() -> dict:
    with (
        patch("scrapers.faar302.teaterbilletter.listing_enricher") as enricher,
        patch("scrapers.faar302.teaterbilletter.scrape"),
    ):
        scrape(delay=0.25)
    return {"url": enricher.call_args.args[0], **enricher.call_args.kwargs}


def test_scrape_takes_every_genre_at_both_venues_and_enriches():
    kwargs = _enricher_kwargs()
    assert kwargs["url"] == "https://www.faar302.dk/"
    assert kwargs["duration_from_page"] is parse_duration
    assert kwargs["delay"] == 0.25
    venue = faar302.VENUE
    assert venue.venue_codes == ("VN0000120", "VN0003980")
    assert venue.genres is None and venue.categories is None
    assert venue.venue_names["VN0000120"] == "Teater FÅR302"
    assert venue.is_wheelchair_accessible is False


class TestParseDuration:
    def test_label_and_value_on_one_line(self):
        html = "<div><p>Varighed ca. 35 min</p></div>"
        assert parse_duration(_soup(html)) == datetime.timedelta(minutes=35)

    def test_value_on_next_line(self):
        html = "<div><strong>Varighed:</strong><br>ca. 1 time og 45 minutter</div>"
        assert parse_duration(_soup(html)) == datetime.timedelta(minutes=105)

    def test_english_label(self):
        html = "<p>Duration 75 min.</p>"
        assert parse_duration(_soup(html)) == datetime.timedelta(minutes=75)

    def test_label_without_value(self):
        assert parse_duration(_soup("<p>Varighed</p><p>kommer snart</p>")) is None

    def test_missing(self):
        assert parse_duration(_soup("<p>Om forestillingen</p>")) is None
