"""Unit tests for scrapers/hautscene.py helper functions."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import MagicMock

import pytest
import requests
from bs4 import BeautifulSoup

from scrapers.hautscene import (
    _get_info_row_value,
    _next_page_url,
    collect_event_urls,
    combine_dt,
    parse_date,
    parse_time,
    scrape_detail,
)

CPH_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _mock_session(html: str) -> MagicMock:
    session = MagicMock()
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    session.get.return_value = resp
    return session


# ── parse_date ────────────────────────────────────────────────────────────────


def test_parse_date_standard():
    assert parse_date("24.3.26") == datetime.date(2026, 3, 24)


def test_parse_date_zero_padded():
    assert parse_date("01.03.26") == datetime.date(2026, 3, 1)


def test_parse_date_end_of_year():
    assert parse_date("31.12.27") == datetime.date(2027, 12, 31)


def test_parse_date_invalid_returns_none():
    assert parse_date("not-a-date") is None


def test_parse_date_empty_returns_none():
    assert parse_date("") is None


def test_parse_date_invalid_day_returns_none():
    assert parse_date("32.01.26") is None


# ── parse_time ────────────────────────────────────────────────────────────────


def test_parse_time_range():
    start, end = parse_time("15:00 - 18:00")
    assert start == datetime.time(15, 0)
    assert end == datetime.time(18, 0)


def test_parse_time_single():
    start, end = parse_time("19:30")
    assert start == datetime.time(19, 30)
    assert end is None


def test_parse_time_midnight():
    start, end = parse_time("00:00 - 01:00")
    assert start == datetime.time(0, 0)
    assert end == datetime.time(1, 0)


def test_parse_time_dot_separator():
    start, end = parse_time("15.00 - 17.00")
    assert start == datetime.time(15, 0)
    assert end == datetime.time(17, 0)


def test_parse_time_invalid_raises():
    with pytest.raises(ValueError):
        parse_time("not-a-time")


# ── combine_dt ────────────────────────────────────────────────────────────────


def test_combine_dt_returns_utc():
    date = datetime.date(2026, 6, 1)
    t = datetime.time(20, 0)
    result = combine_dt(date, t)
    assert result.tzinfo is datetime.UTC
    # 20:00 CPH (CEST = UTC+2) → 18:00 UTC
    assert result.hour == 18


def test_combine_dt_winter_time():
    # January: CET = UTC+1
    date = datetime.date(2026, 1, 15)
    t = datetime.time(20, 0)
    result = combine_dt(date, t)
    assert result.hour == 19  # 20:00 CET → 19:00 UTC


# ── _next_page_url ────────────────────────────────────────────────────────────


def test_next_page_url_finds_next():
    html = """
    <html><body>
      <a href="/en/calendar?events_page=2">Page 2</a>
      <a href="/en/calendar?events_page=3">Page 3</a>
    </body></html>
    """
    result = _next_page_url(_soup(html), "https://www.hautscene.dk/en/calendar")
    assert result is not None
    assert "events_page=3" in result


def test_next_page_url_no_links_returns_none():
    html = "<html><body><a href='/en/about/'>About</a></body></html>"
    result = _next_page_url(_soup(html), "https://www.hautscene.dk/en/calendar")
    assert result is None


def test_next_page_url_already_on_last_page_returns_none():
    # Current page is 3; only links to page 2 (lower) — should return None
    html = '<html><body><a href="/en/calendar?events_page=2">Page 2</a></body></html>'
    result = _next_page_url(_soup(html), "https://www.hautscene.dk/en/calendar?events_page=3")
    assert result is None


# ── _get_info_row_value ───────────────────────────────────────────────────────


def test_get_info_row_value_found():
    html = """
    <div class="event-info">
      <div class="info-row">
        <div class="row-title">Time</div>
        <div class="size-medium">15:00 - 18:00</div>
      </div>
    </div>
    """
    info_div = _soup(html).select_one("div.event-info")
    assert _get_info_row_value(info_div, "time") == "15:00 - 18:00"


def test_get_info_row_value_case_insensitive():
    html = """
    <div class="event-info">
      <div class="info-row">
        <div class="row-title">Place</div>
        <div class="size-medium">Copenhagen</div>
      </div>
    </div>
    """
    info_div = _soup(html).select_one("div.event-info")
    assert _get_info_row_value(info_div, "PLACE") == "Copenhagen"


def test_get_info_row_value_not_found_returns_empty():
    html = '<div class="event-info"></div>'
    info_div = _soup(html).select_one("div.event-info")
    assert _get_info_row_value(info_div, "time") == ""


# ── collect_event_urls ────────────────────────────────────────────────────────


def test_collect_event_urls_single_page():
    html = """
    <html><body>
      <div class="calendar-container">
        <div class="calendar-event-teaser">
          <a href="/en/events/my-show">My Show</a>
        </div>
        <div class="calendar-event-teaser">
          <a href="/en/events/another-event">Another</a>
        </div>
        <div class="calendar-event-teaser">
          <a href="/en/about/">Not an event</a>
        </div>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    urls = collect_event_urls(session)
    assert len(urls) == 2
    assert "https://www.hautscene.dk/en/events/my-show" in urls


def test_collect_event_urls_deduplicates():
    html = """
    <html><body>
      <div class="calendar-container">
        <div class="calendar-event-teaser"><a href="/en/events/same-show">A</a></div>
        <div class="calendar-event-teaser"><a href="/en/events/same-show">B</a></div>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    urls = collect_event_urls(session)
    assert len(urls) == 1


def test_collect_event_urls_http_error_breaks_loop():
    session = MagicMock()
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError("503")
    urls = collect_event_urls(session)
    assert urls == []


# ── scrape_detail ─────────────────────────────────────────────────────────────

_MINIMAL_EVENT_HTML = """
<html><body>
  <div class="section-tag">My Workshop</div>
  <div class="event-info">
    <div data-compare-dates="true" data-start="24.3.26" data-end="24.3.26"></div>
    <div class="info-row">
      <div class="row-title">Time</div>
      <div class="size-medium">15:00 - 17:00</div>
    </div>
  </div>
</body></html>
"""


def test_scrape_detail_returns_event():
    session = _mock_session(_MINIMAL_EVENT_HTML)
    result = scrape_detail("https://www.hautscene.dk/en/events/my-workshop", session)
    assert result is not None
    assert result["title"] == "My Workshop"
    assert result["external_source"] == "hautscene"
    assert result["is_wheelchair_accessible"] is False


def test_scrape_detail_http_error_returns_none():
    session = MagicMock()
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError("404")
    assert scrape_detail("https://www.hautscene.dk/en/events/x", session) is None


def test_scrape_detail_no_title_returns_none():
    html = """
    <html><body>
      <div class="event-info">
        <div data-compare-dates="true" data-start="24.3.26"></div>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    assert scrape_detail("https://www.hautscene.dk/en/events/x", session) is None


def test_scrape_detail_empty_title_returns_none():
    html = """
    <html><body>
      <div class="section-tag">   </div>
      <div class="event-info">
        <div data-compare-dates="true" data-start="24.3.26"></div>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    assert scrape_detail("https://www.hautscene.dk/en/events/x", session) is None


def test_scrape_detail_no_event_info_returns_none():
    html = "<html><body><div class='section-tag'>Title</div></body></html>"
    session = _mock_session(html)
    assert scrape_detail("https://www.hautscene.dk/en/events/x", session) is None


def test_scrape_detail_bad_date_returns_none():
    html = """
    <html><body>
      <div class="section-tag">My Event</div>
      <div class="event-info">
        <div data-compare-dates="true" data-start="not-a-date"></div>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    assert scrape_detail("https://www.hautscene.dk/en/events/x", session) is None


def test_scrape_detail_missing_date_elem_returns_none():
    html = """
    <html><body>
      <div class="section-tag">My Event</div>
      <div class="event-info"></div>
    </body></html>
    """
    session = _mock_session(html)
    assert scrape_detail("https://www.hautscene.dk/en/events/x", session) is None


def test_scrape_detail_no_time_falls_back_to_midnight():
    html = """
    <html><body>
      <div class="section-tag">Untimed Event</div>
      <div class="event-info">
        <div data-compare-dates="true" data-start="24.3.26"></div>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://www.hautscene.dk/en/events/x", session)
    assert result is not None
    dt = datetime.datetime.fromisoformat(result["start_datetime"])
    # Midnight CPH (UTC+1 in March) = 23:00 UTC previous day
    assert dt.minute == 0


def test_scrape_detail_bad_time_falls_back_to_midnight():
    html = """
    <html><body>
      <div class="section-tag">Bad Time Event</div>
      <div class="event-info">
        <div data-compare-dates="true" data-start="24.3.26"></div>
        <div class="info-row">
          <div class="row-title">Time</div>
          <div class="size-medium">not-a-time</div>
        </div>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://www.hautscene.dk/en/events/x", session)
    assert result is not None  # falls back gracefully


def test_scrape_detail_free_event():
    html = """
    <html><body>
      <div class="section-tag">Free Show</div>
      <div class="event-info">
        <div data-compare-dates="true" data-start="24.3.26"></div>
      </div>
      <div class="booking-info">
        <div class="w-richtext"><p>Free admission — no booking required.</p></div>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://www.hautscene.dk/en/events/free", session)
    assert result["is_free"] is True


def test_scrape_detail_paid_event():
    html = """
    <html><body>
      <div class="section-tag">Paid Show</div>
      <div class="event-info">
        <div data-compare-dates="true" data-start="24.3.26"></div>
      </div>
      <div class="booking-info">
        <div class="w-richtext"><p>Tickets: 150 DKK</p></div>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://www.hautscene.dk/en/events/paid", session)
    assert result["is_free"] is False
    assert "150 DKK" in result["price_note"]


def test_scrape_detail_category_from_tag():
    html = """
    <html><body>
      <div class="section-tag">Workshop</div>
      <div class="event-info">
        <div data-compare-dates="true" data-start="24.3.26"></div>
      </div>
      <div class="event-tags">
        <a class="link-button-tag" href="#">Workshop</a>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://www.hautscene.dk/en/events/ws", session)
    assert result["category"] == "workshop"


def test_scrape_detail_image_from_hero():
    html = """
    <html><body>
      <div class="section-tag">Show</div>
      <div class="event-info">
        <div data-compare-dates="true" data-start="24.3.26"></div>
      </div>
      <img class="hero-figure-image" src="https://example.com/hero.jpg">
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://www.hautscene.dk/en/events/show", session)
    assert result["image_url"] == "https://example.com/hero.jpg"


def test_scrape_detail_multi_day_event_uses_end_date():
    html = """
    <html><body>
      <div class="section-tag">Long Run</div>
      <div class="event-info">
        <div data-compare-dates="true" data-start="24.3.26" data-end="26.3.26"></div>
        <div class="info-row">
          <div class="row-title">Time</div>
          <div class="size-medium">20:00 - 22:00</div>
        </div>
      </div>
    </body></html>
    """
    session = _mock_session(html)
    result = scrape_detail("https://www.hautscene.dk/en/events/run", session)
    assert result is not None
    # end_datetime should be on 26 March, not 24
    end = datetime.datetime.fromisoformat(result["end_datetime"])
    end_cph = end.astimezone(CPH_TZ)
    assert end_cph.day == 26
