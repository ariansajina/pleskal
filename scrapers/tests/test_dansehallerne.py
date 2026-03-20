"""Unit tests for scrapers/dansehallerne.py helper functions."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import MagicMock

import requests
from bs4 import BeautifulSoup

from scrapers.dansehallerne import (
    collect_event_urls,
    map_category,
    parse_date_string,
    parse_description,
    parse_image_url,
    parse_meta_table,
    parse_venue_address,
    scrape_detail,
)

CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")


def _dt(year, month, day, hour, minute):
    return datetime.datetime(year, month, day, hour, minute, tzinfo=CPH_TZ).astimezone(
        datetime.UTC
    )


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# ── parse_date_string ─────────────────────────────────────────────────────────


def test_single_date():
    result = parse_date_string("1.5.2026, 18:00")
    assert result == [(_dt(2026, 5, 1, 18, 0), None)]


def test_day_range():
    result = parse_date_string("1.-3.5.2026, 18:00")
    assert result == [
        (_dt(2026, 5, 1, 18, 0), None),
        (_dt(2026, 5, 2, 18, 0), None),
        (_dt(2026, 5, 3, 18, 0), None),
    ]


def test_two_ranges():
    result = parse_date_string("1.–3.5 + 8.–10.5.2026, 18:00")
    assert len(result) == 6
    assert result[0] == (_dt(2026, 5, 1, 18, 0), None)
    assert result[2] == (_dt(2026, 5, 3, 18, 0), None)
    assert result[3] == (_dt(2026, 5, 8, 18, 0), None)
    assert result[5] == (_dt(2026, 5, 10, 18, 0), None)


def test_unicode_dash():
    result_unicode = parse_date_string("1.\u20133.5.2026, 18:00")
    result_hyphen = parse_date_string("1.-3.5.2026, 18:00")
    assert result_unicode == result_hyphen


def test_invalid_returns_empty():
    assert parse_date_string("not a date") == []


def test_missing_time_returns_empty():
    assert parse_date_string("1.5.2026") == []


def test_missing_year_returns_empty():
    assert parse_date_string("1.5, 18:00") == []


def test_segment_missing_month_returns_empty():
    # Segment has no trailing .month
    assert parse_date_string("15.2026, 18:00") == []


def test_unparseable_day_segment_returns_empty():
    # Day part is neither a single day nor a range
    assert parse_date_string("abc.5.2026, 18:00") == []


# ── parse_meta_table ──────────────────────────────────────────────────────────


def test_parse_meta_table_basic():
    html = """
    <section class="event-meta-infos">
      <div class="meta-info table">
        <div class="row">
          <div class="key">Title:</div>
          <div class="value">My Event</div>
        </div>
        <div class="row">
          <div class="key">Date</div>
          <div class="value">1.5.2026, 18:00</div>
        </div>
      </div>
    </section>
    """
    meta = parse_meta_table(_soup(html))
    assert meta["title"] == "My Event"
    assert meta["date"] == "1.5.2026, 18:00"


def test_parse_meta_table_skips_add_to_calendar():
    html = """
    <section class="event-meta-infos">
      <div class="meta-info table">
        <div class="row">
          <div class="key">Add to calendar</div>
          <div class="value">ICS</div>
        </div>
        <div class="row">
          <div class="key">Type</div>
          <div class="value">Workshop</div>
        </div>
      </div>
    </section>
    """
    meta = parse_meta_table(_soup(html))
    assert "add to calendar" not in meta
    assert meta["type"] == "Workshop"


def test_parse_meta_table_skips_rows_without_key_or_value():
    html = """
    <section class="event-meta-infos">
      <div class="meta-info table">
        <div class="row"><div class="key">Only key</div></div>
        <div class="row"><div class="value">Only value</div></div>
        <div class="row">
          <div class="key">Good</div>
          <div class="value">Row</div>
        </div>
      </div>
    </section>
    """
    meta = parse_meta_table(_soup(html))
    assert list(meta.keys()) == ["good"]


def test_parse_meta_table_empty():
    assert parse_meta_table(_soup("<html></html>")) == {}


# ── parse_description ─────────────────────────────────────────────────────────


def test_parse_description_returns_markdown():
    html = '<div id="event-entry-content"><p>Hello <strong>world</strong></p></div>'
    result = parse_description(_soup(html))
    assert "**world**" in result


def test_parse_description_missing_returns_empty():
    assert parse_description(_soup("<html></html>")) == ""


# ── parse_image_url ───────────────────────────────────────────────────────────


def test_parse_image_url_uses_srcset_largest():
    html = """
    <figure class="post-thumbnail">
      <img srcset="small.jpg 400w, large.jpg 1200w, medium.jpg 800w" src="fallback.jpg">
    </figure>
    """
    assert parse_image_url(_soup(html)) == "large.jpg"


def test_parse_image_url_falls_back_to_src():
    html = """
    <figure class="post-thumbnail">
      <img src="image.jpg">
    </figure>
    """
    assert parse_image_url(_soup(html)) == "image.jpg"


def test_parse_image_url_no_figure_returns_empty():
    assert parse_image_url(_soup("<html></html>")) == ""


def test_parse_image_url_figure_no_img_returns_empty():
    html = '<figure class="post-thumbnail"></figure>'
    assert parse_image_url(_soup(html)) == ""


def test_parse_image_url_invalid_srcset_falls_back_to_src():
    # srcset entries without width descriptor are skipped; falls back to src
    html = """
    <figure class="post-thumbnail">
      <img srcset="bad-entry" src="fallback.jpg">
    </figure>
    """
    assert parse_image_url(_soup(html)) == "fallback.jpg"


# ── map_category ──────────────────────────────────────────────────────────────


def test_map_category_known():
    assert map_category("Performance") == "performance"
    assert map_category("WORKSHOP") == "workshop"
    assert map_category("open practice") == "open_practice"
    assert map_category("ipaf performance") == "performance"


def test_map_category_unknown_defaults_to_other():
    assert map_category("unknown") == "other"
    assert map_category("") == "other"


# ── parse_venue_address ───────────────────────────────────────────────────────


def test_parse_venue_address_full():
    raw = "Dansehallerne, Franciska Clausens Plads 27, 1799 Copenhagen V View map Hide map"
    name, address = parse_venue_address(raw)
    assert name == "Dansehallerne"
    assert "Franciska Clausens Plads 27" in address
    assert "View map" not in address


def test_parse_venue_address_danish_city_name_normalised():
    raw = "Franciska Clausens Plads 27, 1799 København V"
    _, address = parse_venue_address(raw)
    assert "Copenhagen" in address
    assert "København" not in address


def test_parse_venue_address_no_street_uses_default():
    _, address = parse_venue_address("Studio 4")
    assert address == "Franciska Clausens Plads 27, 1799 Copenhagen V"


def test_parse_venue_address_always_returns_dansehallerne():
    name, _ = parse_venue_address("Blackboxen, Dansehallerne")
    assert name == "Dansehallerne"


# ── scrape_detail ─────────────────────────────────────────────────────────────

_MINIMAL_META_HTML = """
<html><body>
  <section class="event-meta-infos">
    <div class="meta-info table">
      <div class="row"><div class="key">Title</div><div class="value">Dance Show</div></div>
      <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 20:00</div></div>
      <div class="row"><div class="key">Venue</div><div class="value">Studio 4</div></div>
    </div>
  </section>
</body></html>
"""


def _mock_session(html: str) -> MagicMock:
    session = MagicMock()
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    session.get.return_value = resp
    return session


def test_scrape_detail_returns_records():
    session = _mock_session(_MINIMAL_META_HTML)
    results = scrape_detail(
        "https://dansehallerne.dk/en/public-program/performance/1/", session
    )
    assert len(results) == 1
    assert results[0]["title"] == "Dance Show"
    assert results[0]["external_source"] == "dansehallerne"
    assert results[0]["is_wheelchair_accessible"] is True


def test_scrape_detail_http_error_returns_empty():
    session = MagicMock()
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError("404")
    assert (
        scrape_detail("https://dansehallerne.dk/en/public-program/x/1/", session) == []
    )


def test_scrape_detail_no_meta_returns_empty():
    session = _mock_session("<html><body><p>No meta here</p></body></html>")
    assert (
        scrape_detail("https://dansehallerne.dk/en/public-program/x/1/", session) == []
    )


def test_scrape_detail_no_title_returns_empty():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 20:00</div></div>
        </div>
      </section>
    </body></html>
    """
    session = _mock_session(html)
    assert (
        scrape_detail("https://dansehallerne.dk/en/public-program/x/1/", session) == []
    )


def test_scrape_detail_no_date_returns_empty():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">Dance Show</div></div>
        </div>
      </section>
    </body></html>
    """
    session = _mock_session(html)
    assert (
        scrape_detail("https://dansehallerne.dk/en/public-program/x/1/", session) == []
    )


def test_scrape_detail_free_admission_in_description():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">Free Show</div></div>
          <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 20:00</div></div>
        </div>
      </section>
      <div id="event-entry-content"><p>Free admission to all events.</p></div>
    </body></html>
    """
    session = _mock_session(html)
    results = scrape_detail("https://dansehallerne.dk/en/public-program/x/1/", session)
    assert results[0]["is_free"] is True
    assert results[0]["price_note"] == "Free admission"


def test_scrape_detail_pay_what_you_can():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">Show</div></div>
          <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 20:00</div></div>
        </div>
      </section>
      <div id="event-entry-content"><p>Pay what you can at the door.</p></div>
    </body></html>
    """
    session = _mock_session(html)
    results = scrape_detail("https://dansehallerne.dk/en/public-program/x/1/", session)
    assert results[0]["is_free"] is False
    assert "sliding scale" in results[0]["price_note"]


def test_scrape_detail_ticket_button_means_not_free():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">Ticketed Show</div></div>
          <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 20:00</div></div>
        </div>
        <button class="basm_select">Buy tickets</button>
      </section>
    </body></html>
    """
    session = _mock_session(html)
    results = scrape_detail("https://dansehallerne.dk/en/public-program/x/1/", session)
    assert results[0]["is_free"] is False


def test_scrape_detail_ics_button_timestamps():
    import calendar

    # Use timestamps well in the future
    start_ts = calendar.timegm(datetime.date(2030, 6, 1).timetuple())
    end_ts = start_ts + 7200
    html = f"""
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">Show</div></div>
          <div class="row"><div class="key">Date</div><div class="value">1.6.2030, 20:00</div></div>
        </div>
      </section>
      <button class="js-download" data-start="{start_ts}" data-end="{end_ts}">ICS</button>
    </body></html>
    """
    session = _mock_session(html)
    results = scrape_detail("https://dansehallerne.dk/en/public-program/x/1/", session)
    assert len(results) == 1
    assert results[0]["end_datetime"] is not None


def test_scrape_detail_uses_artist_field_when_no_title():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Artist</div><div class="value">The Band</div></div>
          <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 20:00</div></div>
        </div>
      </section>
    </body></html>
    """
    session = _mock_session(html)
    results = scrape_detail("https://dansehallerne.dk/en/public-program/x/1/", session)
    assert results[0]["title"] == "The Band"


def test_scrape_detail_duration_sets_end_time():
    html = """
    <html><body>
      <section class="event-meta-infos">
        <div class="meta-info table">
          <div class="row"><div class="key">Title</div><div class="value">Show</div></div>
          <div class="row"><div class="key">Date</div><div class="value">1.6.2026, 20:00</div></div>
          <div class="row"><div class="key">Duration</div><div class="value">2 hours</div></div>
        </div>
      </section>
    </body></html>
    """
    session = _mock_session(html)
    results = scrape_detail("https://dansehallerne.dk/en/public-program/x/1/", session)
    assert results[0]["end_datetime"] is not None


# ── collect_event_urls ────────────────────────────────────────────────────────


def test_collect_event_urls_extracts_matching_hrefs():
    html = """
    <html><body>
      <a href="/en/public-program/performance/123/">Event 1</a>
      <a href="/en/public-program/workshop/456">Event 2</a>
      <a href="/en/about/">Not an event</a>
    </body></html>
    """
    session = _mock_session(html)
    urls = collect_event_urls(session)
    assert len(urls) == 2
    assert "https://dansehallerne.dk/en/public-program/performance/123/" in urls
    assert "https://dansehallerne.dk/en/public-program/workshop/456" in urls


def test_collect_event_urls_deduplicates():
    html = """
    <html><body>
      <a href="/en/public-program/performance/123/">First</a>
      <a href="/en/public-program/performance/123/">Duplicate</a>
    </body></html>
    """
    session = _mock_session(html)
    urls = collect_event_urls(session)
    assert len(urls) == 1
