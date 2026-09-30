"""Unit tests for scrapers/faar302.py (the teaterbilletter.dk layer is covered
by test_teaterbilletter.py)."""

from __future__ import annotations

from unittest.mock import patch

from bs4 import BeautifulSoup

from scrapers import faar302
from scrapers.faar302 import scrape
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


def _links_kwargs() -> dict:
    with (
        patch("scrapers.faar302.teaterbilletter.venue_page_links") as links,
        patch("scrapers.faar302.teaterbilletter.scrape"),
    ):
        scrape()
    return {"url": links.call_args.args[0], **links.call_args.kwargs}


def test_front_page_cards_link_ticket_numbers():
    html = _card("gazed", "147686") + _card("skuret", "151582") + _card("gratis", None)
    kwargs = _links_kwargs()
    links = ticket_links(
        _soup(html), kwargs["url"], kwargs["card_selector"], kwargs["link_selector"]
    )
    assert kwargs["url"] == "https://www.faar302.dk/"
    assert links == {
        "147686": "https://www.faar302.dk/forestilling/gazed/",
        "151582": "https://www.faar302.dk/forestilling/skuret/",
    }


def test_takes_every_genre_at_both_venues():
    venue = faar302.VENUE
    assert venue.venue_codes == ("VN0000120", "VN0003980")
    assert venue.genres is None and venue.categories is None
    assert venue.venue_names["VN0000120"] == "Teater FÅR302"
    assert venue.is_wheelchair_accessible is False
