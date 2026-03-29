"""Unit tests for scrapers/kbhdanser.py helper functions."""

from __future__ import annotations

import datetime
import sys
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
    main,
    make_dt,
    parse_dates,
    scrape,
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
    perfs = _extract_performances(_soup(html))
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
    perfs = _extract_performances(_soup(html))
    assert perfs == []


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
    perfs = _extract_performances(_soup(html))
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
    resp_press = MagicMock()
    resp_press.text = "<html></html>"
    resp_press.raise_for_status.return_value = None
    # First call returns Danish, second call returns English, third returns empty press page
    session.get.side_effect = [resp_da, resp_en, resp_press]

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


@patch("scrapers.kbhdanser.datetime")
def test_scrape_detail_en_page_fetch_error_falls_back_to_danish(mock_dt):
    """When fetching the EN page raises HTTPError, fall back to the Danish page."""
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    danish_html = """
    <html><body>
      <a href="https://kbhdanser.dk/en/show/">EN</a>
      <h1>Show DA</h1>
      <p>ØSTRE GASVÆRK TEATER</p>
      <p>21. maj 2026. kl. 19:30</p>
    </body></html>
    """
    session = MagicMock()
    resp_ok = MagicMock()
    resp_ok.text = danish_html
    resp_ok.raise_for_status.return_value = None
    resp_err = MagicMock()
    resp_err.raise_for_status.side_effect = requests.HTTPError("503")
    resp_press = MagicMock()
    resp_press.text = "<html></html>"
    resp_press.raise_for_status.return_value = None
    # First call (Danish page) succeeds; second (EN page) fails; third (press page) succeeds
    session.get.side_effect = [resp_ok, resp_err, resp_press]

    card = {
        "title": "Show",
        "artists": "",
        "detail_url": "https://kbhdanser.dk/show/",
        "image_url": "",
    }
    records = scrape_detail(card, session, delay=0)
    # Should still return records using the successfully fetched Danish page
    assert len(records) >= 1
    assert records[0]["title"] == "Show DA"
    assert records[0]["source_url"] == "https://kbhdanser.dk/show/"


# ── lookup_venue (loop branch) ────────────────────────────────────────────────


def test_lookup_venue_loop_substring_match():
    """A name that's a substring of a known venue key hits the loop path."""
    name, address = lookup_venue("Gasværk")
    # "gasværk" is contained in the key "østre gasværk teater"
    assert address is not None
    assert "Nyborggade" in address


# ── Date parser edge cases (ValueError paths) ─────────────────────────────────


def test_parse_danish_date_invalid_day_skipped():
    """Day 32 matches the regex but fails datetime.date() — should be skipped."""
    results = _parse_danish_dates("32. maj 2026")
    assert results == []


def test_parse_english_date_invalid_day_skipped():
    """February 30th matches the regex but fails datetime.date() — skipped."""
    results = _parse_english_dates("February 30th, 2026")
    assert results == []


# ── collect_event_cards (extra branch coverage) ───────────────────────────────


def test_collect_event_cards_external_link_excluded():
    """Links to external domains are excluded."""
    html = """
    <html><body>
      <a href="https://external.com/show/"><h1>External Show</h1></a>
      <a href="https://kbhdanser.dk/local/"><h1>Local Show</h1></a>
    </body></html>
    """
    cards = collect_event_cards(_soup(html))
    titles = [c["title"] for c in cards]
    assert "External Show" not in titles
    assert "Local Show" in titles


def test_collect_event_cards_whitespace_only_h1_excluded():
    """An h1 containing only whitespace is treated as empty title and skipped."""
    html = """
    <html><body>
      <a href="https://kbhdanser.dk/show/"><h1>   </h1></a>
      <a href="https://kbhdanser.dk/valid/"><h1>Valid Show</h1></a>
    </body></html>
    """
    cards = collect_event_cards(_soup(html))
    urls = [c["detail_url"] for c in cards]
    assert "https://kbhdanser.dk/show/" not in urls
    assert "https://kbhdanser.dk/valid/" in urls


# ── _extract_description (credit-line skip) ───────────────────────────────────


def test_extract_description_skips_credit_role_lines():
    """Paragraphs matching 'Role: name' pattern (credits) are excluded."""
    html = """
    <html><body>
      <p>Direction: Some Director working on this amazing production of dance.</p>
      <p>Choreography: Another Person creating this beautiful movement piece.</p>
      <p>A captivating performance that explores the boundaries of contemporary dance.</p>
    </body></html>
    """
    desc = _extract_description(_soup(html))
    assert "Direction:" not in desc
    assert "Choreography:" not in desc
    assert "captivating performance" in desc


# ── _extract_performances (no-venue fallback) ────────────────────────────────


@patch("scrapers.kbhdanser.datetime")
def test_extract_performances_fallback_when_no_venue_blocks(mock_dt):
    """When no venue lines are found, all future dates are returned under empty venue."""
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    html = """
    <html><body>
      <h1>Mysterious Show</h1>
      <p>21. maj 2026. kl. 19:30</p>
      <p>22. maj 2026. kl. 19:30</p>
    </body></html>
    """
    perfs = _extract_performances(_soup(html))
    assert len(perfs) >= 2
    assert perfs[0]["venue_name"] == ""
    assert perfs[0]["venue_address"] == ""


@patch("scrapers.kbhdanser.datetime")
def test_extract_performances_fallback_single_date(mock_dt):
    """Fallback path with a single date returns one record."""
    mock_dt.date.today.return_value = _FIXED_TODAY
    mock_dt.date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)
    mock_dt.time.side_effect = lambda *a, **kw: datetime.time(*a, **kw)
    mock_dt.datetime.side_effect = lambda *a, **kw: datetime.datetime(*a, **kw)
    mock_dt.UTC = datetime.UTC

    html = """
    <html><body>
      <p>21. maj 2026. kl. 19:30</p>
    </body></html>
    """
    perfs = _extract_performances(_soup(html))
    assert len(perfs) == 1
    assert "start_datetime" in perfs[0]


# ── scrape() ─────────────────────────────────────────────────────────────────

_HOMEPAGE_WITH_CARDS = """
<html><body>
  <a href="https://kbhdanser.dk/chroniques/">
    <img src="https://kbhdanser.dk/wp-content/uploads/chroniques.webp">
    <h1>Chroniques</h1>
    <h2>Peeping Tom</h2>
  </a>
</body></html>
"""

_SAMPLE_RECORD = {
    "title": "Chroniques",
    "description": "A great show.",
    "start_datetime": "2026-05-21T17:30:00+00:00",
    "end_datetime": None,
    "venue_name": "Østre Gasværk Teater",
    "venue_address": "Nyborggade 17, 2100 København Ø",
    "category": "performance",
    "is_free": False,
    "is_wheelchair_accessible": False,
    "price_note": "",
    "source_url": "https://kbhdanser.dk/chroniques/",
    "external_source": "kbhdanser",
    "image_url": "https://kbhdanser.dk/wp-content/uploads/chroniques.webp",
}


def _make_scrape_mocks(home_html: str, detail_records: list[dict]):
    """Return (mock_session, mock_get_soup, mock_scrape_detail, mock_crawl_delay)."""
    mock_session = MagicMock()
    home_soup = BeautifulSoup(home_html, "lxml")

    def fake_get_soup(url, session):
        return home_soup

    return mock_session, fake_get_soup, detail_records


@patch("scrapers.kbhdanser.time")
@patch("scrapers.kbhdanser.scrape_detail")
@patch("scrapers.kbhdanser.get_soup")
@patch("scrapers.kbhdanser.get_crawl_delay", return_value=None)
@patch("scrapers.kbhdanser.make_session")
def test_scrape_returns_events(
    mock_make_session, mock_crawl_delay, mock_get_soup, mock_scrape_detail, mock_time
):
    mock_session = MagicMock()
    mock_make_session.return_value = mock_session
    mock_get_soup.return_value = BeautifulSoup(_HOMEPAGE_WITH_CARDS, "lxml")
    mock_scrape_detail.return_value = [_SAMPLE_RECORD]

    result = scrape(delay=0)

    assert len(result) == 1
    assert result[0]["title"] == "Chroniques"
    mock_scrape_detail.assert_called_once()


@patch("scrapers.kbhdanser.get_soup")
@patch("scrapers.kbhdanser.get_crawl_delay", return_value=None)
@patch("scrapers.kbhdanser.make_session")
def test_scrape_homepage_http_error_returns_empty(
    mock_make_session, mock_crawl_delay, mock_get_soup
):
    mock_make_session.return_value = MagicMock()
    mock_get_soup.side_effect = requests.HTTPError("500")

    result = scrape(delay=0)
    assert result == []


@patch("scrapers.kbhdanser.get_soup")
@patch("scrapers.kbhdanser.get_crawl_delay", return_value=None)
@patch("scrapers.kbhdanser.make_session")
def test_scrape_no_cards_returns_empty(
    mock_make_session, mock_crawl_delay, mock_get_soup
):
    mock_make_session.return_value = MagicMock()
    # Homepage has no event cards (no <a> with <h1>)
    mock_get_soup.return_value = BeautifulSoup(
        "<html><body><p>No events</p></body></html>", "lxml"
    )

    result = scrape(delay=0)
    assert result == []


@patch("scrapers.kbhdanser.time")
@patch("scrapers.kbhdanser.scrape_detail")
@patch("scrapers.kbhdanser.get_soup")
@patch("scrapers.kbhdanser.get_crawl_delay", return_value=2.0)
@patch("scrapers.kbhdanser.make_session")
def test_scrape_crawl_delay_overrides_default(
    mock_make_session, mock_crawl_delay, mock_get_soup, mock_scrape_detail, mock_time
):
    """robots.txt crawl-delay of 2.0s overrides the 0s default passed in."""
    mock_make_session.return_value = MagicMock()
    mock_get_soup.return_value = BeautifulSoup(_HOMEPAGE_WITH_CARDS, "lxml")
    mock_scrape_detail.return_value = [_SAMPLE_RECORD]

    scrape(delay=0)

    # scrape_detail should have been called with the larger delay
    _, kwargs = mock_scrape_detail.call_args
    assert kwargs.get("delay", 0) == 2.0 or mock_scrape_detail.call_args[0][2] == 2.0


@patch("scrapers.kbhdanser.time")
@patch("scrapers.kbhdanser.scrape_detail")
@patch("scrapers.kbhdanser.get_soup")
@patch("scrapers.kbhdanser.get_crawl_delay", return_value=None)
@patch("scrapers.kbhdanser.make_session")
def test_scrape_sleeps_between_cards(
    mock_make_session, mock_crawl_delay, mock_get_soup, mock_scrape_detail, mock_time
):
    """time.sleep is called between cards (not before the first)."""
    homepage_with_two_cards = """
    <html><body>
      <a href="https://kbhdanser.dk/show-one/"><h1>Show One</h1></a>
      <a href="https://kbhdanser.dk/show-two/"><h1>Show Two</h1></a>
    </body></html>
    """
    mock_make_session.return_value = MagicMock()
    mock_get_soup.return_value = BeautifulSoup(homepage_with_two_cards, "lxml")
    mock_scrape_detail.return_value = []

    scrape(delay=1.0)

    # sleep called exactly once (between the two cards)
    mock_time.sleep.assert_called_once_with(1.0)


# ── main() ────────────────────────────────────────────────────────────────────


@patch("scrapers.kbhdanser.write_output")
@patch("scrapers.kbhdanser.scrape", return_value=[_SAMPLE_RECORD])
def test_main_calls_scrape_and_write_output(mock_scrape, mock_write):
    with patch.object(sys, "argv", ["kbhdanser.py"]):
        main()

    mock_scrape.assert_called_once()
    mock_write.assert_called_once()
    events_arg, output_arg, dry_run_arg = mock_write.call_args[0]
    assert events_arg == [_SAMPLE_RECORD]
    assert dry_run_arg is False


@patch("scrapers.kbhdanser.write_output")
@patch("scrapers.kbhdanser.scrape", return_value=[])
def test_main_dry_run_flag(mock_scrape, mock_write):
    with patch.object(sys, "argv", ["kbhdanser.py", "--dry-run"]):
        main()

    _, _, dry_run_arg = mock_write.call_args[0]
    assert dry_run_arg is True
