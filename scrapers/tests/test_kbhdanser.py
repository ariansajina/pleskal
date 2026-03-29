"""Unit tests for scrapers/kbhdanser.py helper functions."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import MagicMock, patch

import requests
from bs4 import BeautifulSoup

from scrapers.kbhdanser import (
    _extract_description,
    _extract_performances,
    _find_english_url,
    _parse_danish_dates,
    _parse_english_dates,
    collect_event_cards,
    lookup_venue,
    make_dt,
    parse_dates,
    scrape_detail,
)

CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")
BASE_URL = "https://kbhdanser.dk"

# A fixed "today" used across tests so dates are reliably future/past
_FIXED_TODAY = datetime.date(2026, 3, 29)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _mock_session(html: str) -> MagicMock:
    session = MagicMock()
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    session.get.return_value = resp
    return session


# ── lookup_venue ──────────────────────────────────────────────────────────────


def test_lookup_venue_exact_match():
    name, address = lookup_venue("Østre Gasværk Teater")
    assert name == "Østre Gasværk Teater"
    assert address == "Nyborggade 17, 2100 København Ø"


def test_lookup_venue_uppercase_variant():
    name, address = lookup_venue("ØSTRE GASVÆRK THEATRE")
    assert name == "Østre Gasværk Teater"
    assert address is not None


def test_lookup_venue_gamle_scene():
    name, address = lookup_venue("GAMLE SCENE")
    assert "Gamle Scene" in name
    assert address is not None
    assert "Kongens Nytorv" in address


def test_lookup_venue_musikhuset():
    name, address = lookup_venue("Musikhuset Aarhus")
    assert name == "Musikhuset Aarhus"
    assert address is not None
    assert "Aarhus" in address


def test_lookup_venue_partial_match():
    # "Østre Gasværk" is a substring of a known key
    name, address = lookup_venue("Østre Gasværk")
    assert address is not None


def test_lookup_venue_unknown_returns_name_and_none(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="scrapers.kbhdanser"):
        name, address = lookup_venue("Ukendt Teater")
    assert name == "Ukendt Teater"
    assert address is None
    assert "Unknown venue" in caplog.text


# ── _parse_danish_dates ───────────────────────────────────────────────────────


def test_parse_danish_date_with_time():
    results = _parse_danish_dates("21. maj 2026. kl. 19:30")
    assert len(results) == 1
    d, t = results[0]
    assert d == datetime.date(2026, 5, 21)
    assert t == datetime.time(19, 30)


def test_parse_danish_date_dot_time_separator():
    results = _parse_danish_dates("21. maj 2026. kl. 19.30")
    assert len(results) == 1
    d, t = results[0]
    assert t == datetime.time(19, 30)


def test_parse_danish_date_without_time():
    results = _parse_danish_dates("23. september 2026")
    assert len(results) == 1
    d, t = results[0]
    assert d == datetime.date(2026, 9, 23)
    assert t is None


def test_parse_danish_date_multiple():
    text = "21. maj 2026. kl. 19:30\n22. maj 2026. kl. 19:30\n23. maj 2026. kl. 17:00"
    results = _parse_danish_dates(text)
    assert len(results) == 3
    assert results[0][0] == datetime.date(2026, 5, 21)
    assert results[2][1] == datetime.time(17, 0)


def test_parse_danish_date_case_insensitive():
    results = _parse_danish_dates("21. MAJ 2026")
    assert len(results) == 1


def test_parse_danish_date_all_months():
    months = [
        ("januar", 1),
        ("februar", 2),
        ("marts", 3),
        ("april", 4),
        ("maj", 5),
        ("juni", 6),
        ("juli", 7),
        ("august", 8),
        ("september", 9),
        ("oktober", 10),
        ("november", 11),
        ("december", 12),
    ]
    for name, num in months:
        results = _parse_danish_dates(f"15. {name} 2026")
        assert len(results) == 1, f"Failed for month: {name}"
        assert results[0][0].month == num


def test_parse_danish_date_no_match_returns_empty():
    assert _parse_danish_dates("no dates here") == []


# ── _parse_english_dates ──────────────────────────────────────────────────────


def test_parse_english_date_with_pm_time():
    results = _parse_english_dates("May 21, 2026 - 7:30PM")
    assert len(results) == 1
    d, t = results[0]
    assert d == datetime.date(2026, 5, 21)
    assert t == datetime.time(19, 30)


def test_parse_english_date_with_24h_time():
    results = _parse_english_dates("September 26th, 2026 – 20:00")
    assert len(results) == 1
    d, t = results[0]
    assert d == datetime.date(2026, 9, 26)
    assert t == datetime.time(20, 0)


def test_parse_english_date_ordinal_suffixes():
    for suffix in ["1st", "2nd", "3rd", "4th", "21st"]:
        day_num = int("".join(c for c in suffix if c.isdigit()))
        results = _parse_english_dates(f"May {suffix}, 2026 - 19:00")
        assert len(results) == 1
        assert results[0][0].day == day_num


def test_parse_english_date_am_time():
    results = _parse_english_dates("March 10, 2027 - 10:00AM")
    assert len(results) == 1
    d, t = results[0]
    assert t == datetime.time(10, 0)


def test_parse_english_date_12pm_noon():
    results = _parse_english_dates("June 1, 2026 - 12:00PM")
    assert len(results) == 1
    assert results[0][1] == datetime.time(12, 0)


def test_parse_english_date_12am_midnight():
    results = _parse_english_dates("June 1, 2026 - 12:00AM")
    assert len(results) == 1
    assert results[0][1] == datetime.time(0, 0)


def test_parse_english_date_no_time():
    results = _parse_english_dates("May 28th, 2026")
    assert len(results) == 1
    d, t = results[0]
    assert d == datetime.date(2026, 5, 28)
    assert t is None


def test_parse_english_date_no_match():
    assert _parse_english_dates("no dates here") == []


# ── parse_dates ───────────────────────────────────────────────────────────────


def test_parse_dates_prefers_danish():
    results = parse_dates("21. maj 2026. kl. 19:30")
    assert len(results) == 1
    assert results[0][0] == datetime.date(2026, 5, 21)


def test_parse_dates_falls_back_to_english():
    results = parse_dates("May 21, 2026 - 7:30PM")
    assert len(results) == 1
    assert results[0][0] == datetime.date(2026, 5, 21)


# ── make_dt ───────────────────────────────────────────────────────────────────


def test_make_dt_with_time_returns_utc():
    d = datetime.date(2026, 6, 1)
    t = datetime.time(20, 0)
    result = make_dt(d, t)
    assert result.tzinfo is datetime.UTC
    # 20:00 CEST (UTC+2) → 18:00 UTC
    assert result.hour == 18


def test_make_dt_winter_offset():
    d = datetime.date(2026, 1, 15)
    t = datetime.time(20, 0)
    result = make_dt(d, t)
    # 20:00 CET (UTC+1) → 19:00 UTC
    assert result.hour == 19


def test_make_dt_none_time_defaults_to_19():
    d = datetime.date(2026, 5, 21)
    result = make_dt(d, None)
    # 19:00 CEST (UTC+2) → 17:00 UTC
    assert result.hour == 17


# ── collect_event_cards ───────────────────────────────────────────────────────

_HOMEPAGE_HTML = """
<html><body>
  <nav>
    <a href="https://kbhdanser.dk/en/">Home</a>
    <a href="https://kbhdanser.dk/about/">About</a>
  </nav>
  <!-- Event cards: <a href="/slug/"> containing <h1> -->
  <a href="https://kbhdanser.dk/chroniques/">
    <img src="https://kbhdanser.dk/wp-content/uploads/chroniques.webp">
    <h1>Chroniques</h1>
    <h2>Peeping Tom / Gabriela Carrizo</h2>
    <p>ØSTRE GASVÆRK THEATRE</p>
    <p>21. – 23. maj 2026.</p>
  </a>
  <a href="https://kbhdanser.dk/afanador">
    <img src="data:image/svg+xml,...">
    <img src="https://kbhdanser.dk/wp-content/uploads/afanador.webp">
    <h1>AFANADOR</h1>
    <h2>Ballet Nacional de España</h2>
    <p>GAMLE SCENE</p>
  </a>
  <!-- No h1: should be excluded -->
  <a href="https://kbhdanser.dk/program/">
    <h2>Program</h2>
  </a>
  <!-- /en/ path: should be excluded -->
  <a href="https://kbhdanser.dk/en/chroniques/">
    <h1>Chroniques EN</h1>
  </a>
</body></html>
"""


def test_collect_event_cards_finds_cards():
    soup = _soup(_HOMEPAGE_HTML)
    cards = collect_event_cards(soup)
    titles = [c["title"] for c in cards]
    assert "Chroniques" in titles
    assert "AFANADOR" in titles


def test_collect_event_cards_excludes_no_h1():
    soup = _soup(_HOMEPAGE_HTML)
    cards = collect_event_cards(soup)
    urls = [c["detail_url"] for c in cards]
    assert "https://kbhdanser.dk/program/" not in urls


def test_collect_event_cards_excludes_en_path():
    soup = _soup(_HOMEPAGE_HTML)
    cards = collect_event_cards(soup)
    urls = [c["detail_url"] for c in cards]
    assert not any("/en/" in u for u in urls)


def test_collect_event_cards_deduplicates():
    html = """
    <html><body>
      <a href="https://kbhdanser.dk/show/"><h1>Show</h1></a>
      <a href="https://kbhdanser.dk/show/"><h1>Show</h1></a>
    </body></html>
    """
    cards = collect_event_cards(_soup(html))
    assert len(cards) == 1


def test_collect_event_cards_extracts_artists():
    soup = _soup(_HOMEPAGE_HTML)
    cards = collect_event_cards(soup)
    chrono = next(c for c in cards if c["title"] == "Chroniques")
    assert "Peeping Tom" in chrono["artists"]


def test_collect_event_cards_real_image_skips_svg_placeholder():
    soup = _soup(_HOMEPAGE_HTML)
    cards = collect_event_cards(soup)
    afanador = next(c for c in cards if c["title"] == "AFANADOR")
    assert afanador["image_url"].startswith("https://")
    assert "svg" not in afanador["image_url"]


# ── _find_english_url ─────────────────────────────────────────────────────────


def test_find_english_url_found():
    html = """
    <html><body>
      <nav>
        <a href="https://kbhdanser.dk/chroniques/">DA</a>
        <a href="https://kbhdanser.dk/en/chroniques/">EN</a>
      </nav>
    </body></html>
    """
    result = _find_english_url(_soup(html), "https://kbhdanser.dk/chroniques/")
    assert result == "https://kbhdanser.dk/en/chroniques/"


def test_find_english_url_not_found_returns_none():
    html = "<html><body><a href='https://kbhdanser.dk/da/'>DA</a></body></html>"
    result = _find_english_url(_soup(html), "https://kbhdanser.dk/chroniques/")
    assert result is None


def test_find_english_url_case_insensitive():
    html = """
    <html><body>
      <a href="https://kbhdanser.dk/en/show/">en</a>
    </body></html>
    """
    result = _find_english_url(_soup(html), "https://kbhdanser.dk/show/")
    assert result == "https://kbhdanser.dk/en/show/"


# ── _extract_description ─────────────────────────────────────────────────────


def test_extract_description_collects_paragraphs():
    html = """
    <html><body>
      <h1>My Show</h1>
      <p>This is a wonderful dance performance featuring amazing artists.</p>
      <p>The show explores themes of time, memory, and movement in space.</p>
    </body></html>
    """
    desc = _extract_description(_soup(html))
    assert "wonderful dance performance" in desc
    assert "time, memory" in desc


def test_extract_description_deduplicates():
    text = "This is a wonderful dance performance featuring amazing artists."
    html = f"""
    <html><body>
      <p>{text}</p>
      <p>{text}</p>
      <p>Something else entirely unique and different from everything above.</p>
    </body></html>
    """
    desc = _extract_description(_soup(html))
    assert desc.count(text) == 1


def test_extract_description_skips_short_paragraphs():
    html = """
    <html><body>
      <p>Short</p>
      <p>This is a longer paragraph that contains enough text to be included in the output.</p>
    </body></html>
    """
    desc = _extract_description(_soup(html))
    assert "Short" not in desc
    assert "longer paragraph" in desc


def test_extract_description_skips_bio_markers():
    html = """
    <html><body>
      <p>Choreographer (°1987, KOR) — internationally celebrated artist.</p>
      <p>A beautiful performance about the nature of human experience and memory.</p>
    </body></html>
    """
    desc = _extract_description(_soup(html))
    assert "°1987" not in desc
    assert "beautiful performance" in desc


def test_extract_description_empty_if_no_paragraphs():
    html = "<html><body><h1>Title</h1></body></html>"
    assert _extract_description(_soup(html)) == ""


# ── _extract_performances ─────────────────────────────────────────────────────


@patch("scrapers.kbhdanser.datetime")
def test_extract_performances_future_dates_included(mock_dt):
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    html = """
    <html><body>
      <p>ØSTRE GASVÆRK TEATER</p>
      <p>21. maj 2026. kl. 19:30</p>
      <p>22. maj 2026. kl. 19:30</p>
      <a href="https://billet.gasvaerket.dk/da/buyingflow/tickets/30755/">KØB BILLET</a>
    </body></html>
    """
    perfs = _extract_performances(_soup(html), "https://kbhdanser.dk/chroniques/")
    assert len(perfs) >= 2
    start_dates = [p["start_datetime"][:10] for p in perfs]
    assert "2026-05-21" in start_dates
    assert "2026-05-22" in start_dates


@patch("scrapers.kbhdanser.datetime")
def test_extract_performances_past_dates_excluded(mock_dt):
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    html = """
    <html><body>
      <p>ØSTRE GASVÆRK TEATER</p>
      <p>10. januar 2026. kl. 19:30</p>
      <p>11. januar 2026. kl. 19:30</p>
    </body></html>
    """
    perfs = _extract_performances(_soup(html), "https://kbhdanser.dk/broken-theater/")
    assert perfs == []


@patch("scrapers.kbhdanser.datetime")
def test_extract_performances_ticket_url_captured(mock_dt):
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    ticket_url = "https://billet.gasvaerket.dk/da/buyingflow/tickets/30755/"
    html = f"""
    <html><body>
      <p>ØSTRE GASVÆRK TEATER</p>
      <p>21. maj 2026. kl. 19:30</p>
      <a href="{ticket_url}">KØB BILLET</a>
    </body></html>
    """
    perfs = _extract_performances(_soup(html), "https://kbhdanser.dk/chroniques/")
    assert len(perfs) >= 1
    assert any(p["ticket_url"] == ticket_url for p in perfs)


@patch("scrapers.kbhdanser.datetime")
def test_extract_performances_price_note_set(mock_dt):
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    html = """
    <html><body>
      <p>GAMLE SCENE</p>
      <p>26. september 2026. kl. 20:00</p>
    </body></html>
    """
    perfs = _extract_performances(_soup(html), "https://kbhdanser.dk/afanador/")
    assert len(perfs) >= 1
    assert "See ticket link for pricing" in perfs[0]["price_note"]


@patch("scrapers.kbhdanser.datetime")
def test_extract_performances_venue_address_looked_up(mock_dt):
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    html = """
    <html><body>
      <p>Østre Gasværk Teater</p>
      <p>21. maj 2026. kl. 19:30</p>
    </body></html>
    """
    perfs = _extract_performances(_soup(html), "https://kbhdanser.dk/chroniques/")
    assert len(perfs) >= 1
    assert perfs[0]["venue_address"] == "Nyborggade 17, 2100 København Ø"


# ── scrape_detail ─────────────────────────────────────────────────────────────

_DETAIL_HTML = """
<html><body>
  <h1>Chroniques</h1>
  <p>After bringing audiences to their feet with Triptych in 2024, Peeping Tom returns with their latest work, conceived and directed by Gabriela Carrizo.</p>
  <p>Chroniques unfolds in a series of chronicles existing outside a linear narrative, allowing the audience to dive into the dark dimensions of time and space.</p>
  <p>ØSTRE GASVÆRK TEATER</p>
  <p>21. maj 2026. kl. 19:30</p>
  <p>22. maj 2026. kl. 19:30</p>
  <a href="https://billet.gasvaerket.dk/da/buyingflow/tickets/30755/">KØB BILLET</a>
  <img src="https://kbhdanser.dk/wp-content/uploads/chroniques-hero.webp">
</body></html>
"""


@patch("scrapers.kbhdanser.datetime")
def test_scrape_detail_returns_records(mock_dt):
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    card = {
        "title": "Chroniques",
        "artists": "Peeping Tom",
        "detail_url": "https://kbhdanser.dk/chroniques/",
        "image_url": "https://kbhdanser.dk/wp-content/uploads/chroniques.webp",
    }
    session = _mock_session(_DETAIL_HTML)

    records = scrape_detail(card, session)
    assert len(records) >= 1
    r = records[0]
    assert r["title"] == "Chroniques"
    assert r["external_source"] == "kbhdanser"
    assert r["category"] == "performance"
    assert r["is_free"] is False
    assert r["is_wheelchair_accessible"] is False
    assert r["source_url"] == "https://kbhdanser.dk/chroniques/"


@patch("scrapers.kbhdanser.datetime")
def test_scrape_detail_prefers_english_page(mock_dt):
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    danish_html = """
    <html><body>
      <a href="https://kbhdanser.dk/en/chroniques/">EN</a>
      <h1>Chroniques DA</h1>
      <p>ØSTRE GASVÆRK TEATER</p>
      <p>21. maj 2026. kl. 19:30</p>
    </body></html>
    """
    english_html = """
    <html><body>
      <h1>Chroniques EN</h1>
      <p>ØSTRE GASVÆRK TEATER</p>
      <p>21. maj 2026. kl. 19:30</p>
      <p>After bringing audiences to their feet with Triptych in 2024, Peeping Tom returns.</p>
    </body></html>
    """
    session = MagicMock()
    resp_da = MagicMock()
    resp_da.text = danish_html
    resp_da.raise_for_status.return_value = None
    resp_en = MagicMock()
    resp_en.text = english_html
    resp_en.raise_for_status.return_value = None
    # First call returns Danish, second call returns English
    session.get.side_effect = [resp_da, resp_en]

    card = {
        "title": "Chroniques",
        "artists": "",
        "detail_url": "https://kbhdanser.dk/chroniques/",
        "image_url": "",
    }
    records = scrape_detail(card, session, delay=0)
    assert len(records) >= 1
    # Should have used the English title
    assert records[0]["title"] == "Chroniques EN"
    # source_url should be the English page
    assert records[0]["source_url"] == "https://kbhdanser.dk/en/chroniques/"


@patch("scrapers.kbhdanser.datetime")
def test_scrape_detail_http_error_returns_empty(mock_dt):
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    session = MagicMock()
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError("404")
    card = {
        "title": "Show",
        "artists": "",
        "detail_url": "https://kbhdanser.dk/show/",
        "image_url": "",
    }
    assert scrape_detail(card, session) == []


@patch("scrapers.kbhdanser.datetime")
def test_scrape_detail_no_future_dates_returns_empty(mock_dt):
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    html = """
    <html><body>
      <h1>Past Show</h1>
      <p>ØSTRE GASVÆRK TEATER</p>
      <p>10. januar 2026. kl. 19:30</p>
    </body></html>
    """
    card = {
        "title": "Past Show",
        "artists": "",
        "detail_url": "https://kbhdanser.dk/past-show/",
        "image_url": "",
    }
    session = _mock_session(html)
    assert scrape_detail(card, session) == []


@patch("scrapers.kbhdanser.datetime")
def test_scrape_detail_uses_card_image_as_fallback(mock_dt):
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    html = """
    <html><body>
      <h1>Show</h1>
      <p>GAMLE SCENE</p>
      <p>26. september 2026. kl. 20:00</p>
    </body></html>
    """
    card = {
        "title": "Show",
        "artists": "",
        "detail_url": "https://kbhdanser.dk/show/",
        "image_url": "https://kbhdanser.dk/wp-content/uploads/card.webp",
    }
    session = _mock_session(html)
    records = scrape_detail(card, session)
    assert len(records) >= 1
    assert (
        records[0]["image_url"] == "https://kbhdanser.dk/wp-content/uploads/card.webp"
    )
