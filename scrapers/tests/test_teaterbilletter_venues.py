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
    assert links == {"147563": "https://blaagaardteater.dk/program/hun-er-vred"}


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


def test_dansekapellet_takes_everything_under_uppercut():
    with patch("scrapers.teaterbilletter.scrape", return_value=[]) as scrape:
        assert dansekapellet.scrape() == []
    scrape.assert_called_once_with(dansekapellet.VENUE)
    venue = dansekapellet.VENUE
    assert venue.genres is None and venue.categories is None
    assert venue.external_source == "uppercut"
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
