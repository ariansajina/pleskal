"""Tests for the thin teaterbilletter.dk venue scrapers: Blaagaard Teater,
AFUK Scene and Dansekapellet (FÅR302 has its own test module)."""

from __future__ import annotations

import importlib
from unittest.mock import patch

from bs4 import BeautifulSoup

from scrapers import afukscene, blaagaardteater, dansekapellet, teaterbilletter
from scrapers.registry import SOURCES
from scrapers.teaterbilletter import ticket_links

# Trimmed from https://blaagaardteater.dk/program.
BLAAGAARD_PROGRAM = """
<section class="teaser-grid">
  <div class="teaser" data-type="forestilling">
    <div class="teaser-thumb">
      <div class="teaser-buttons">
        <button class="button basm basm_select hover-glow" data-event_no="147563">Køb billet</button>
        <a class="button hover-glow" href="https://blaagaardteater.dk/program/hun-er-vred">Læs mere</a>
      </div>
    </div>
    <h2 class="heading--b"><a href="https://blaagaardteater.dk/program/hun-er-vred">HUN ER VRED/ARG/SINT</a></h2>
  </div>
  <div class="teaser" data-type="event">
    <div class="teaser-buttons">
      <a class="button hover-glow" href="https://blaagaardteater.dk/program/blaa-nabo">Læs mere</a>
    </div>
    <h2 class="heading--b"><a href="https://blaagaardteater.dk/program/blaa-nabo">BLAA NABO</a></h2>
  </div>
</section>
"""


def test_blaagaard_program_links_ticket_numbers():
    with (
        patch("scrapers.teaterbilletter.listing_enricher") as enricher,
        patch("scrapers.teaterbilletter.scrape"),
    ):
        blaagaardteater.scrape()
    url = enricher.call_args.args[0]
    kwargs = enricher.call_args.kwargs
    links = ticket_links(
        BeautifulSoup(BLAAGAARD_PROGRAM, "lxml"),
        url,
        kwargs["card_selector"],
        kwargs["link_selector"],
    )
    assert url == "https://blaagaardteater.dk/program"
    assert kwargs["description_from_page"] is blaagaardteater.parse_description
    assert links == {"147563": "https://blaagaardteater.dk/program/hun-er-vred"}


# Trimmed from https://blaagaardteater.dk/program/hun-er-vred.
BLAAGAARD_SHOW = """
<main class="scene" data-scene="programme-entry">
  <div class="entry-info">
    <div class="action-buttons"><button data-event_no="147563">Køb billet</button></div>
    <div class="date-info heading--s">forestilling<br>10.12.26 – 12.12.26</div>
    <div class="teaser lt">Et paradigmeskifte i fortællingen om adoption.</div>
    <div class="event-info-table"><table><tr><td>Pris</td><td>70 — 220,-</td></tr></table></div>
    <div class="description"><p><strong>HUN ER VRED/ARG/SINT</strong> er et scenisk vidnesbyrd.</p><p>Et co-produktion.</p></div>
    <div class="credit-list"><h2 class="heading--s">Medvirkende</h2>
      <ul class="table-style"><li>UMA FEED</li><li>DANIEL JEREMIAH PERSSON</li></ul></div>
    <div class="credit-list"><h2 class="heading--s">Skabt af</h2>
      <ul class="table-style"><li>Instruktør SAGA GÄRDE</li><li> </li></ul></div>
    <div class="credit-list"><h2 class="heading--s">Tom</h2><ul class="table-style"></ul></div>
  </div>
</main>
"""


def test_blaagaard_description_has_teaser_text_and_credits():
    text = blaagaardteater.parse_description(BeautifulSoup(BLAAGAARD_SHOW, "lxml"))
    assert text == (
        "Et paradigmeskifte i fortællingen om adoption.\n\n"
        "**HUN ER VRED/ARG/SINT** er et scenisk vidnesbyrd.\n\n"
        "Et co-produktion.\n\n"
        "**Medvirkende**  \nUMA FEED  \nDANIEL JEREMIAH PERSSON\n\n"
        "**Skabt af**  \nInstruktør SAGA GÄRDE"
    )


def test_blaagaard_page_without_description_is_empty():
    page = "<main><div class='entry-info'><div class='teaser'>Kun teaser</div></div></main>"
    assert blaagaardteater.parse_description(BeautifulSoup(page, "lxml")) == ""
    assert blaagaardteater.parse_description(BeautifulSoup("<p>x</p>", "lxml")) == ""


def test_blaagaard_takes_dance_and_events_only():
    venue = blaagaardteater.VENUE
    assert venue.genres == teaterbilletter.DANCE_AND_EVENTS_GENRES
    assert venue.categories == teaterbilletter.DANCE_AND_PERFORMANCE_CATEGORIES
    assert venue.is_wheelchair_accessible is True


def test_afuk_takes_dance_and_events_without_enrichment():
    with patch("scrapers.teaterbilletter.scrape", return_value=[]) as scrape:
        assert afukscene.scrape() == []
    scrape.assert_called_once_with(afukscene.VENUE)
    assert afukscene.VENUE.genres == teaterbilletter.DANCE_AND_EVENTS_GENRES
    assert (
        afukscene.VENUE.categories == teaterbilletter.DANCE_AND_PERFORMANCE_CATEGORIES
    )


def test_dansekapellet_takes_everything():
    with patch("scrapers.teaterbilletter.scrape", return_value=[]) as scrape:
        assert dansekapellet.scrape() == []
    scrape.assert_called_once_with(dansekapellet.VENUE)
    venue = dansekapellet.VENUE
    assert venue.genres is None and venue.categories is None
    assert venue.external_source == "dansekapellet"
    assert venue.venue_names == {"VN0000720": "Dansekapellet"}


def test_registry_matches_venue_configs():
    for name, module in [
        ("faar302", "scrapers.faar302"),
        ("blaagaardteater", "scrapers.blaagaardteater"),
        ("afukscene", "scrapers.afukscene"),
        ("dansekapellet", "scrapers.dansekapellet"),
    ]:
        source = SOURCES[name]
        venue = importlib.import_module(module).VENUE
        assert source.external_source == venue.external_source
        assert source.allowed_image_domains == frozenset({"tereba.dk"})
